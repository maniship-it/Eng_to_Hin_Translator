"""End-to-end GUI tests driven without a user.

These need Tkinter and a display.  On a headless Linux box run them under
``xvfb-run``; on Windows they run as-is.  They are skipped when neither is
available.

Modal dialogs and file pickers are replaced with recorders, so the test drives
the same code paths a user would without anything blocking.
"""

from __future__ import annotations

import time

import pytest

tkinter = pytest.importorskip("tkinter")

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def tk_available():
    try:
        root = tkinter.Tk()
    except tkinter.TclError as exc:  # no display
        pytest.skip("no display available for Tkinter: %s" % exc)
    root.destroy()
    return True


class DialogRecorder:
    """Stands in for tkinter.messagebox so nothing blocks."""

    def __init__(self):
        self.calls = []

    def showerror(self, title, message, **kwargs):
        self.calls.append(("error", title))

    def showinfo(self, title, message, **kwargs):
        self.calls.append(("info", title))

    def showwarning(self, title, message, **kwargs):
        self.calls.append(("warning", title))

    def askokcancel(self, title, message, **kwargs):
        self.calls.append(("ask", title))
        return True

    def titles(self):
        return [title for _, title in self.calls]


class FilePicker:
    """Stands in for tkinter.filedialog with pre-set answers."""

    def __init__(self):
        self.open_path = ""
        self.save_path = ""
        self.directory = ""

    def askopenfilename(self, **kwargs):
        return self.open_path

    def asksaveasfilename(self, **kwargs):
        return self.save_path

    def askdirectory(self, **kwargs):
        return self.directory


def pump(app, predicate, timeout: float = 90.0) -> bool:
    """Run the Tk event loop until ``predicate`` holds or time runs out."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        app.update()
        if predicate():
            return True
        time.sleep(0.02)
    return False


@pytest.fixture
def app(tk_available, ct2_model_dir, dictionary_path, monkeypatch):
    from setu import gui as gui_module
    from setu.config import Settings

    dialogs = DialogRecorder()
    picker = FilePicker()
    monkeypatch.setattr(gui_module, "messagebox", dialogs)
    monkeypatch.setattr(gui_module, "filedialog", picker)
    # Never write to the real user settings file during tests.
    monkeypatch.setattr(Settings, "save", lambda self: None)

    settings = Settings()
    settings.model_dir = str(ct2_model_dir)
    settings.dictionary_path = str(dictionary_path)
    # The first-run walkthrough is exercised by its own test, not every test.
    settings.shown_quick_start = True

    instance = gui_module.TranslatorApp(settings)
    instance.dialogs = dialogs
    instance.picker = picker

    assert pump(instance, lambda: instance.translator is not None), "model never loaded"
    yield instance

    try:
        if instance.translator is not None:
            instance.translator.close()
        instance.destroy()
    except tkinter.TclError:
        pass


SAMPLE = (
    "Hello there. This is a test.\n"
    "\n"
    "  - Visit https://example.com/a_b today.\n"
    "42\n"
)


def _translate(app, text=SAMPLE):
    app.source_text.delete("1.0", tkinter.END)
    app.source_text.insert("1.0", text)
    app.update()
    app.translate()
    assert pump(app, lambda: not app._busy), "translation never finished"
    return app.target_text.get("1.0", "end-1c")


class TestStartup:
    def test_model_loads_and_enables_translation(self, app):
        assert app.translator is not None
        assert str(app.translate_button.cget("state")) == "normal"
        assert "Model:" in app.model_label.cget("text")

    def test_counts_update_as_text_is_typed(self, app):
        app.source_text.insert("1.0", "Two words")
        app.update()
        assert "2 words" in app.source_counts.cget("text")


class TestTranslating:
    def test_layout_is_preserved(self, app):
        output = _translate(app)
        lines = output.split("\n")
        assert len(lines) == len(SAMPLE.split("\n"))
        assert lines[1] == ""
        assert lines[2].startswith("  - ")
        assert lines[3] == "42"

    def test_urls_survive(self, app):
        assert "https://example.com/a_b" in _translate(app)

    def test_status_bar_reports_the_run(self, app):
        _translate(app)
        assert app.status.cget("text")

    def test_empty_input_is_refused_politely(self, app):
        app.source_text.delete("1.0", tkinter.END)
        app.translate()
        app.update()
        assert "Nothing to translate" in app.status.cget("text")

    def test_untranslatable_output_warns_instead_of_guessing(self, app):
        # The test model has random weights, so every sentence must fail the
        # safety checks and be left in English, with a warning.
        output = _translate(app)
        assert "Hello there." in output
        assert "warning" in [kind for kind, _ in app.dialogs.calls]


class TestFiles:
    def test_open_reads_the_file(self, app, tmp_path):
        path = tmp_path / "input.txt"
        path.write_text(SAMPLE, encoding="utf-8")
        app.picker.open_path = str(path)
        app.open_file()
        app.update()
        assert "Hello there." in app.source_text.get("1.0", "end-1c")

    def test_open_handles_utf16(self, app, tmp_path):
        path = tmp_path / "input16.txt"
        path.write_text("Hello there.", encoding="utf-16")
        app.picker.open_path = str(path)
        app.open_file()
        app.update()
        assert "Hello there." in app.source_text.get("1.0", "end-1c")

    def test_save_writes_utf8_with_bom(self, app, tmp_path):
        _translate(app)
        destination = tmp_path / "out.txt"
        app.picker.save_path = str(destination)
        app.save_translation()
        app.update()
        assert destination.read_bytes().startswith(b"\xef\xbb\xbf")

    def test_save_side_by_side_produces_a_table(self, app, tmp_path):
        _translate(app)
        destination = tmp_path / "out.tsv"
        app.picker.save_path = str(destination)
        app.save_side_by_side()
        app.update()
        content = destination.read_text(encoding="utf-8-sig")
        assert content.startswith("English\tHindi")
        assert len(content.splitlines()) == len(SAMPLE.split("\n")) + 1

    def test_saving_without_a_translation_is_refused(self, app, tmp_path):
        app.target_text.delete("1.0", tkinter.END)
        app.picker.save_path = str(tmp_path / "unused.txt")
        app.save_translation()
        assert "info" in [kind for kind, _ in app.dialogs.calls]
        assert not (tmp_path / "unused.txt").exists()


class TestViewActions:
    def test_font_size_changes(self, app):
        before = app.source_font.cget("size")
        app.adjust_font(1)
        assert app.source_font.cget("size") == before + 1
        app.adjust_font(-1)
        assert app.source_font.cget("size") == before

    def test_wrap_toggle(self, app):
        app._wrap_var().set(False)
        app._apply_wrap()
        assert str(app.source_text.cget("wrap")) == "none"
        app._wrap_var().set(True)
        app._apply_wrap()
        assert str(app.source_text.cget("wrap")) == "word"

    def test_clear_empties_both_panes(self, app):
        _translate(app)
        app.clear_all()
        app.update()
        assert app.source_text.get("1.0", "end-1c") == ""
        assert app.target_text.get("1.0", "end-1c") == ""

    def test_copy_puts_the_translation_on_the_clipboard(self, app):
        output = _translate(app)
        app.copy_output()
        app.update()
        assert app.clipboard_get() == output

    def test_help_dialogs_open(self, app):
        app.show_about()
        app.show_model_help()
        assert any("About" in title for title in app.dialogs.titles())
        assert any("model" in title for title in app.dialogs.titles())


class TestSettingsDialog:
    def test_saving_settings_applies_them(self, app):
        from setu.gui import SettingsDialog

        dialog = SettingsDialog(app)
        app.update()
        dialog.beam.set(2)
        dialog.protect.set(False)
        dialog._save()
        app.update()

        assert app.settings.beam_size == 2
        assert app.settings.protect_entities is False
        # Changing quality settings reloads the model in the background.
        assert pump(app, lambda: not app._busy)

    def test_cancelling_changes_nothing(self, app):
        from setu.gui import SettingsDialog

        before = app.settings.beam_size
        dialog = SettingsDialog(app)
        app.update()
        dialog.beam.set(9)
        dialog.destroy()
        app.update()
        assert app.settings.beam_size == before


class TestModelFolder:
    def test_choosing_a_valid_folder_reloads(self, app, ct2_model_dir):
        app.picker.directory = str(ct2_model_dir)
        app.choose_model_folder()
        assert pump(app, lambda: not app._busy)
        assert app.translator is not None

    def test_choosing_a_folder_without_a_model_is_rejected(self, app, tmp_path):
        app.picker.directory = str(tmp_path)
        app.choose_model_folder()
        app.update()
        assert "error" in [kind for kind, _ in app.dialogs.calls]


class TestDictionaryTab:
    def test_dictionary_loads_on_demand(self, app):
        app.show_dictionary()
        app.update()
        assert app.dictionary_panel.dictionary is not None

    def test_lookup_shows_hindi_and_definition(self, app):
        app.show_dictionary()
        app.dictionary_panel.search("government")
        app.update()
        shown = app.dictionary_panel.view.get("1.0", "end-1c")
        assert "government" in shown
        assert "सरकार" in shown
        assert "governing authority" in shown

    def test_lookup_shows_thesaurus(self, app):
        app.show_dictionary()
        app.dictionary_panel.search("happy")
        app.update()
        shown = app.dictionary_panel.view.get("1.0", "end-1c")
        assert "synonyms" in shown
        assert "antonyms" in shown
        assert "unhappy" in shown

    def test_lookup_shows_examples(self, app):
        app.show_dictionary()
        app.dictionary_panel.search("happy")
        app.update()
        assert "a happy smile" in app.dictionary_panel.view.get("1.0", "end-1c")

    def test_inflected_form_is_reported(self, app):
        app.show_dictionary()
        app.dictionary_panel.search("governments")
        app.update()
        assert "governments" in app.dictionary_panel.view.get("1.0", "end-1c")

    def test_hindi_query_searches_in_reverse(self, app):
        app.show_dictionary()
        app.dictionary_panel.search("सरकार")
        app.update()
        assert "government" in app.dictionary_panel.view.get("1.0", "end-1c")

    def test_unknown_word_offers_suggestions(self, app):
        app.show_dictionary()
        app.dictionary_panel.search("governmen")
        app.update()
        shown = app.dictionary_panel.view.get("1.0", "end-1c")
        assert "No exact match" in shown or "government" in shown
        assert app.dictionary_panel.results.size() > 0

    def test_missing_word_says_so(self, app):
        app.show_dictionary()
        app.dictionary_panel.search("zzzznotaword")
        app.update()
        assert "Not found" in app.dictionary_panel.view.get("1.0", "end-1c")

    def test_administrative_glossary_can_be_browsed(self, app):
        app.show_administrative_glossary()
        app.update()
        assert app.dictionary_panel.results.size() >= 150
        shown = app.dictionary_panel.view.get("1.0", "end-1c")
        assert "administrative term" in shown

    def test_administrative_entry_shows_both_languages(self, app):
        app.show_dictionary()
        app.dictionary_panel.search("Joint Secretary")
        app.update()
        shown = app.dictionary_panel.view.get("1.0", "end-1c")
        assert "संयुक्त सचिव" in shown
        assert "A senior officer heading a wing" in shown
        assert "मंत्रालय के किसी स्कंध" in shown
        assert "The proposal requires the approval" in shown
        assert "प्रस्ताव के लिए संयुक्त सचिव" in shown

    def test_glossary_filters_by_category(self, app):
        app.show_administrative_glossary()
        app.update()
        everything = app.dictionary_panel.results.size()
        app.dictionary_panel.category.set("designation")
        app.dictionary_panel.browse_administrative()
        app.update()
        filtered = app.dictionary_panel.results.size()
        assert 0 < filtered < everything

    def test_selecting_a_result_shows_it(self, app):
        app.show_dictionary()
        app.dictionary_panel.search("govern")
        app.update()
        panel = app.dictionary_panel
        if panel.results.size() > 1:
            panel.results.selection_clear(0, tkinter.END)
            panel.results.selection_set(1)
            panel._on_result_selected(None)
            app.update()
        assert panel.view.get("1.0", "end-1c").strip()

    def test_lookup_from_the_translator_pane(self, app):
        app.source_text.delete("1.0", tkinter.END)
        app.source_text.insert("1.0", "The government announced it.")
        app.source_text.tag_add(tkinter.SEL, "1.4", "1.14")
        app.update()
        app.lookup_selection(app.source_text)
        app.update()
        assert app.notebook.nametowidget(app.notebook.select()) is app.dictionary_panel
        assert "सरकार" in app.dictionary_panel.view.get("1.0", "end-1c")

    def test_word_at_cursor_uses_the_selection(self, app):
        app.source_text.delete("1.0", tkinter.END)
        app.source_text.insert("1.0", "hello world")
        app.source_text.tag_add(tkinter.SEL, "1.0", "1.5")
        assert app.word_at_cursor(app.source_text) == "hello"

    def test_lookup_of_a_non_word_is_ignored(self, app):
        app.source_text.delete("1.0", tkinter.END)
        app.source_text.insert("1.0", "12345")
        app.source_text.tag_add(tkinter.SEL, "1.0", "1.5")
        app.lookup_selection(app.source_text)
        app.update()
        assert "Select a word" in app.status.cget("text")

    def test_font_changes_reach_the_dictionary(self, app):
        before = app.dictionary_panel.body_font.cget("size")
        app.adjust_font(2)
        app.update()
        assert app.dictionary_panel.body_font.cget("size") == before + 2

    def test_missing_dictionary_is_reported_in_the_panel(self, app, tmp_path,
                                                         monkeypatch):
        app.dictionary_panel.close()
        app.settings.dictionary_path = str(tmp_path / "absent.sqlite")
        monkeypatch.setenv("SETU_DICTIONARY", str(tmp_path / "absent.sqlite"))
        monkeypatch.setattr("setu.dictionary.app_root", lambda: tmp_path)
        monkeypatch.setattr("setu.dictionary.user_data_dir", lambda: tmp_path)
        assert not app.dictionary_panel.ensure_loaded()
        app.update()
        shown = app.dictionary_panel.view.get("1.0", "end-1c")
        assert "not available" in shown.lower()
        # The translator itself must keep working.
        assert app.translator is not None


class TestFirstRunAndChrome:
    """The parts a brand-new user meets before anything else."""

    def test_quick_start_dialog_opens_and_closes(self, app):
        from setu.gui import QUICK_START, QuickStartDialog

        dialog = QuickStartDialog(app)
        app.update()
        assert dialog.winfo_exists()
        assert len(QUICK_START) >= 5
        dialog.destroy()
        app.update()

    def test_quick_start_shows_automatically_on_first_run(self, app):
        from setu.gui import QuickStartDialog

        app.settings.shown_quick_start = False
        app._maybe_show_quick_start()
        app.update()
        opened = [w for w in app.winfo_children()
                  if isinstance(w, QuickStartDialog)]
        assert opened, "the walkthrough should open on first run"
        # And it must not reappear on every start.
        assert app.settings.shown_quick_start is True
        for dialog in opened:
            dialog.destroy()
        app.update()

    def test_quick_start_does_not_reopen_once_seen(self, app):
        from setu.gui import QuickStartDialog

        app.settings.shown_quick_start = True
        app._maybe_show_quick_start()
        app.update()
        assert not [w for w in app.winfo_children()
                    if isinstance(w, QuickStartDialog)]

    def test_window_title_and_tip_bar(self, app):
        assert "SETU" in app.title()
        assert app.tip_label.cget("text").startswith("Tip:")

    def test_tips_rotate(self, app):
        from setu.gui import TIPS

        first = app.tip_label.cget("text")
        app._rotate_tip()
        app.update()
        assert app.tip_label.cget("text") != first or len(TIPS) == 1

    def test_tooltip_appears_and_disappears(self, app):
        from setu.gui import Tooltip

        tooltip = Tooltip(app.translate_button, "Translate the text")
        tooltip._show()
        app.update()
        assert tooltip.window is not None
        tooltip._hide()
        app.update()
        assert tooltip.window is None

    def test_tooltip_with_no_text_does_nothing(self, app):
        from setu.gui import Tooltip

        tooltip = Tooltip(app.translate_button, "")
        tooltip._show()
        assert tooltip.window is None
