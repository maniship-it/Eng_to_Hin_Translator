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
def app(tk_available, ct2_model_dir, monkeypatch):
    from entohin import gui as gui_module
    from entohin.config import Settings

    dialogs = DialogRecorder()
    picker = FilePicker()
    monkeypatch.setattr(gui_module, "messagebox", dialogs)
    monkeypatch.setattr(gui_module, "filedialog", picker)
    # Never write to the real user settings file during tests.
    monkeypatch.setattr(Settings, "save", lambda self: None)

    settings = Settings()
    settings.model_dir = str(ct2_model_dir)

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
        from entohin.gui import SettingsDialog

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
        from entohin.gui import SettingsDialog

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
