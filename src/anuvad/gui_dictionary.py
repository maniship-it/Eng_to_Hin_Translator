"""The dictionary page: meanings both ways, pronunciation, and the glossary.

Lookups hit a local SQLite file and come back in a few milliseconds, so this
panel queries on the UI thread. Only speech is moved to a worker, because it
takes as long as the word takes to say.
"""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import List, Optional

from . import speech
from .dictionary import (
    Dictionary,
    DictionaryError,
    DictionaryNotFoundError,
    Entry,
    Sense,
    pos_label,
)
from .theme import Theme

#: How long to wait after the last keystroke before refreshing suggestions.
SUGGEST_DELAY_MS = 160

DIRECTION_LABELS = {
    "en-hi": "English → हिंदी",
    "hi-en": "हिंदी → English",
}


class ChipBar(ttk.Frame):
    """A row of clickable word chips — suggestions and related words."""

    def __init__(self, parent, theme: Theme, on_click):
        super().__init__(parent, style="Card.TFrame")
        self.theme = theme
        self.on_click = on_click
        self.caption = ttk.Label(self, text="", style="CardMuted.TLabel")
        self.buttons: List[ttk.Button] = []

    def show(self, caption: str, words: List[str]) -> None:
        self.clear()
        if not words:
            self.pack_forget()
            return
        self.caption.configure(text=caption)
        self.caption.pack(side=tk.LEFT, padx=(0, 8))
        for word in words:
            button = ttk.Button(self, text=word, style="Chip.TButton",
                                command=lambda w=word: self.on_click(w))
            button.pack(side=tk.LEFT, padx=(0, 6))
            self.buttons.append(button)
        self.pack(fill=tk.X, pady=(0, 8))

    def clear(self) -> None:
        for button in self.buttons:
            button.destroy()
        self.buttons = []
        self.caption.pack_forget()


class DictionaryPanel(ttk.Frame):
    """Search box, result list, and a formatted view of one entry."""

    def __init__(self, parent, settings, theme: Theme):
        super().__init__(parent, padding=(16, 14))

        self.settings = settings
        self.theme = theme
        self.dictionary: Optional[Dictionary] = None
        self.load_error: str = ""
        self._suggest_job: Optional[str] = None
        self._entries: List[Entry] = []
        self._browsing_admin = False
        self._current: Optional[Entry] = None

        self._build()

    # -- construction --------------------------------------------------

    def _build(self) -> None:
        # Search card ----------------------------------------------------
        search_card = ttk.Frame(self, style="Card.TFrame", padding=14)
        search_card.pack(fill=tk.X)

        top = ttk.Frame(search_card, style="Card.TFrame")
        top.pack(fill=tk.X)

        ttk.Label(top, text="Look up", style="CardHeading.TLabel").pack(side=tk.LEFT)

        self.direction_label = ttk.Label(top, text=DIRECTION_LABELS["en-hi"],
                                         style="CardMuted.TLabel")
        self.direction_label.pack(side=tk.RIGHT)

        entry_row = ttk.Frame(search_card, style="Card.TFrame")
        entry_row.pack(fill=tk.X, pady=(10, 0))

        self.query = tk.StringVar()
        self.search_entry = ttk.Entry(entry_row, textvariable=self.query,
                                      font=self.theme.body, width=34)
        self.search_entry.pack(side=tk.LEFT, ipady=3)
        self.search_entry.bind("<KeyRelease>", self._on_typed)
        self.search_entry.bind("<Return>", lambda e: self.search())
        self.search_entry.bind("<Down>", self._focus_results)

        ttk.Button(entry_row, text="Search", style="Accent.TButton",
                   command=self.search).pack(side=tk.LEFT, padx=(8, 0))
        ttk.Button(entry_row, text="Government glossary", style="Ghost.TButton",
                   command=self.browse_administrative).pack(side=tk.LEFT,
                                                            padx=(14, 0))

        self.category = tk.StringVar()
        self.category_box = ttk.Combobox(entry_row, textvariable=self.category,
                                         width=22, state="readonly")
        self.category_box.pack(side=tk.LEFT, padx=(8, 0))
        self.category_box.bind("<<ComboboxSelected>>",
                               lambda e: self.browse_administrative())

        ttk.Label(search_card,
                  text="Type English or हिंदी — Anuvad Plus searches whichever "
                       "way you are typing.",
                  style="CardMuted.TLabel").pack(anchor=tk.W, pady=(8, 0))

        # Results --------------------------------------------------------
        panes = ttk.Panedwindow(self, orient=tk.HORIZONTAL)
        panes.pack(fill=tk.BOTH, expand=True, pady=(14, 0))

        left = ttk.Frame(panes, style="Card.TFrame", padding=12)
        right = ttk.Frame(panes, style="Card.TFrame", padding=12)
        panes.add(left, weight=1)
        panes.add(right, weight=3)

        ttk.Label(left, text="Matches", style="CardHeading.TLabel").pack(anchor=tk.W)
        list_frame = ttk.Frame(left, style="Card.TFrame")
        list_frame.pack(fill=tk.BOTH, expand=True, pady=(8, 0))
        self.results = tk.Listbox(list_frame, exportselection=False,
                                  font=self.theme.body,
                                  **self.theme.listbox_options())
        scroll = ttk.Scrollbar(list_frame, orient=tk.VERTICAL,
                               command=self.results.yview)
        self.results.configure(yscrollcommand=scroll.set)
        scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self.results.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.results.bind("<<ListboxSelect>>", self._on_result_selected)
        self.results.bind("<Return>", self._on_result_selected)

        # Entry view -----------------------------------------------------
        head = ttk.Frame(right, style="Card.TFrame")
        head.pack(fill=tk.X)
        ttk.Label(head, text="Meaning", style="CardHeading.TLabel").pack(side=tk.LEFT)

        self.speak_button = ttk.Button(head, text="🔊  Speak", style="Speak.TButton",
                                       command=self.speak_current)
        self.pronunciation_label = ttk.Label(head, text="",
                                             style="CardMuted.TLabel")
        self.pronunciation_label.pack(side=tk.RIGHT, padx=(0, 10))

        self.suggestions = ChipBar(right, self.theme, self._chip_clicked)
        self.related = ChipBar(right, self.theme, self._chip_clicked)

        view_frame = ttk.Frame(right, style="Card.TFrame")
        view_frame.pack(fill=tk.BOTH, expand=True, pady=(8, 0))
        self.view = tk.Text(view_frame, wrap=tk.WORD, font=self.theme.body,
                            padx=14, pady=12, spacing1=2, spacing3=5,
                            cursor="arrow", **self.theme.text_widget_options())
        view_scroll = ttk.Scrollbar(view_frame, orient=tk.VERTICAL,
                                    command=self.view.yview)
        self.view.configure(yscrollcommand=view_scroll.set)
        view_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self.view.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self._configure_tags()
        self.view.configure(state=tk.DISABLED)

        self.status = ttk.Label(self, text="", style="Muted.TLabel")
        self.status.pack(fill=tk.X, pady=(10, 0))

    def _configure_tags(self) -> None:
        colours = self.theme.palette
        self.view.tag_configure("headword", font=self.theme.display,
                                foreground=colours.text, spacing3=2)
        self.view.tag_configure("inflection", font=self.theme.small,
                                foreground=colours.text_muted, spacing3=8)
        self.view.tag_configure("hindi", font=self.theme.hindi_big,
                                foreground=colours.marigold, spacing3=8)
        self.view.tag_configure("hindi_body", font=self.theme.hindi,
                                foreground=colours.text, lmargin1=26, lmargin2=26)
        self.view.tag_configure("phonetic", font=self.theme.mono,
                                foreground=colours.accent, spacing3=6)
        self.view.tag_configure("section", font=self.theme.body_bold,
                                foreground=colours.accent, spacing1=14, spacing3=4)
        self.view.tag_configure("admin", font=self.theme.body_bold,
                                foreground=colours.marigold, spacing1=14,
                                spacing3=4)
        self.view.tag_configure("label", font=self.theme.small_bold,
                                foreground=colours.text_muted, lmargin1=26,
                                lmargin2=26)
        self.view.tag_configure("body", foreground=colours.text, lmargin1=26,
                                lmargin2=26)
        self.view.tag_configure("example", font=self.theme.small,
                                foreground=colours.text_muted, lmargin1=42,
                                lmargin2=42)
        self.view.tag_configure("hindi_example", font=self.theme.hindi,
                                foreground=colours.text_muted, lmargin1=42,
                                lmargin2=42)
        self.view.tag_configure("muted", foreground=colours.text_muted,
                                font=self.theme.small)

    # -- appearance ----------------------------------------------------

    def restyle(self) -> None:
        """Repaint the plain Tk widgets after a theme change."""
        self.view.configure(**self.theme.text_widget_options())
        self.results.configure(**self.theme.listbox_options())
        self._configure_tags()
        if self._current is not None:
            self._render_entry(self._current)

    def refresh_fonts(self) -> None:
        self.view.configure(font=self.theme.body)
        self.results.configure(font=self.theme.body)
        self._configure_tags()
        if self._current is not None:
            self._render_entry(self._current)

    def focus_search(self) -> None:
        self.search_entry.focus_set()
        self.search_entry.selection_range(0, tk.END)

    # -- dictionary lifecycle ------------------------------------------

    def ensure_loaded(self) -> bool:
        if self.dictionary is not None:
            return True
        extra = [self.settings.dictionary_path] if self.settings.dictionary_path \
            else None
        try:
            self.dictionary = Dictionary.open(extra=extra)
        except (DictionaryNotFoundError, DictionaryError) as exc:
            self.load_error = str(exc)
            self._render_message(
                "Dictionary not available",
                str(exc) + "\n\nThe translator itself is unaffected — only this "
                           "page needs the dictionary database.",
            )
            self.status.configure(text="Dictionary not loaded.")
            return False

        meta = self.dictionary.meta()
        self.status.configure(
            text="%s words · %s pronunciations · %s government terms"
                 % (meta.get("entries", "?"), meta.get("pronunciations", "?"),
                    meta.get("admin_terms", "?")))
        categories = ["(all categories)"] + self.dictionary.administrative_categories()
        self.category_box.configure(values=categories)
        if not self.category.get():
            self.category.set(categories[0])
        return True

    def close(self) -> None:
        if self.dictionary is not None:
            self.dictionary.close()
            self.dictionary = None

    # -- searching -----------------------------------------------------

    def _on_typed(self, event: tk.Event) -> None:
        if event.keysym in ("Up", "Down", "Return", "Escape", "Tab"):
            return
        self._update_direction()
        if self._suggest_job is not None:
            self.after_cancel(self._suggest_job)
        self._suggest_job = self.after(SUGGEST_DELAY_MS, self._refresh_suggestions)

    def _update_direction(self) -> None:
        if self.dictionary is None:
            return
        direction = self.dictionary.detect_direction(self.query.get())
        self.direction_label.configure(text=DIRECTION_LABELS[direction])

    def _refresh_suggestions(self) -> None:
        self._suggest_job = None
        if not self.ensure_loaded():
            return
        text = self.query.get().strip()
        if len(text) < 2:
            return
        assert self.dictionary is not None
        matches = self.dictionary.suggest_either(text, limit=60)
        if matches:
            self._browsing_admin = False
            self._fill_results(matches)

    def _fill_results(self, words: List[str]) -> None:
        self.results.delete(0, tk.END)
        for word in words:
            self.results.insert(tk.END, word)

    def search(self, word: str = "") -> None:
        """Look up a word and show it, in whichever direction it is written."""
        if not self.ensure_loaded():
            return
        assert self.dictionary is not None

        query = (word or self.query.get()).strip()
        if not query:
            return
        if word:
            self.query.set(word)
        self._update_direction()

        entries = self.dictionary.search(query, limit=40)
        if entries:
            self._entries = entries
            self._browsing_admin = False
            self._fill_results([entry.word for entry in entries])
            self.results.selection_clear(0, tk.END)
            self.results.selection_set(0)
            self._render_entry(entries[0])
            self.status.configure(text="")
            return

        # Nothing matched: offer the closest spellings, then any prefix match.
        similar = self.dictionary.similar_words(query, limit=8)
        suggestions = self.dictionary.suggest_either(query, limit=40)
        self._fill_results(suggestions or similar)
        self._current = None
        self.speak_button.pack_forget()
        self.pronunciation_label.configure(text="")
        self.related.show("", [])

        if similar:
            self.suggestions.show("Did you mean:", similar)
            self._render_message(
                "No entry for “%s”" % query,
                "The closest words are shown above — click one to look it up.",
            )
        else:
            self.suggestions.show("", [])
            self._render_message(
                "Not found: “%s”" % query,
                "This word is not in the dictionary. Try the base form of the "
                "word, or check the spelling.",
            )

    def lookup_word(self, word: str) -> None:
        """Entry point used by the translator page."""
        self.search(word)
        self.focus_search()

    def _chip_clicked(self, word: str) -> None:
        self.search(word)

    def browse_administrative(self) -> None:
        if not self.ensure_loaded():
            return
        assert self.dictionary is not None

        entries = self.dictionary.administrative_terms()
        category = self.category.get()
        if category and not category.startswith("("):
            entries = [e for e in entries
                       if any(s.category == category
                              for s in e.administrative_senses)]

        self._entries = entries
        self._browsing_admin = True
        self._fill_results([entry.word for entry in entries])
        if entries:
            self.results.selection_clear(0, tk.END)
            self.results.selection_set(0)
            self._render_entry(entries[0])
        self.status.configure(
            text="%d government term(s)%s"
                 % (len(entries),
                    "" if category.startswith("(") else " in %s" % category))

    def _focus_results(self, event: tk.Event) -> str:
        if self.results.size():
            self.results.focus_set()
            self.results.selection_clear(0, tk.END)
            self.results.selection_set(0)
            self._on_result_selected(event)
        return "break"

    def _on_result_selected(self, event: tk.Event) -> None:
        selection = self.results.curselection()
        if not selection:
            return
        index = selection[0]
        if self._entries and index < len(self._entries) and self._browsing_admin:
            self._render_entry(self._entries[index])
            return
        if not self.ensure_loaded():
            return
        assert self.dictionary is not None
        word = self.results.get(index)
        entries = self.dictionary.search(word, limit=1)
        if entries:
            self._render_entry(entries[0])

    # -- speech --------------------------------------------------------

    def speak_current(self) -> None:
        """Say the current head word aloud using the Windows voice."""
        if self._current is None:
            return
        word = self._current.word
        if not speech.is_available():
            self.status.configure(text=speech.unavailable_reason())
            return

        self.speak_button.configure(state=tk.DISABLED)
        self.status.configure(text="Speaking “%s”…" % word)

        def finished(result: speech.SpeechResult) -> None:
            self.after(0, lambda: self._speech_finished(result))

        speech.speak_async(word, rate=getattr(self.settings, "speech_rate", 0),
                           voice=getattr(self.settings, "speech_voice", ""),
                           done=finished)

    def _speech_finished(self, result: speech.SpeechResult) -> None:
        try:
            self.speak_button.configure(state=tk.NORMAL)
            self.status.configure(text="" if result.ok else result.message)
        except tk.TclError:
            pass  # the window closed while speaking

    # -- rendering -----------------------------------------------------

    def _write(self, text: str, *tags: str) -> None:
        self.view.insert(tk.END, text, tags if tags else ())

    def _render_message(self, title: str, body: str) -> None:
        self.view.configure(state=tk.NORMAL)
        self.view.delete("1.0", tk.END)
        self._write(title + "\n", "headword")
        self._write(body + "\n", "body")
        self.view.configure(state=tk.DISABLED)

    def _render_entry(self, entry: Entry) -> None:
        self._current = entry
        self.view.configure(state=tk.NORMAL)
        self.view.delete("1.0", tk.END)

        self._write(entry.word + "\n", "headword")
        if entry.matched_form:
            self._write("shown for “%s”\n" % entry.matched_form, "inflection")

        # Pronunciation, in the header and in the body.
        spoken = entry.pronunciation
        if entry.has_pronunciation:
            pieces = []
            if spoken.ipa:
                pieces.append("/%s/" % spoken.ipa)
            if spoken.respelling:
                pieces.append(spoken.respelling)
            self._write("  ".join(pieces) + "\n", "phonetic")
            self.pronunciation_label.configure(
                text="/%s/" % spoken.ipa if spoken.ipa else "")
            self.speak_button.pack(side=tk.RIGHT)
        else:
            self.pronunciation_label.configure(text="")
            self.speak_button.pack_forget()

        hindi_meanings = entry.hindi_meanings
        if hindi_meanings:
            self._write(", ".join(hindi_meanings[:10]) + "\n", "hindi")

        parts = entry.parts_of_speech
        if parts:
            self._write("Parts of speech: "
                        + ", ".join(pos_label(p) for p in parts) + "\n", "muted")
        if entry.has_pronunciation and spoken.syllable_count:
            self._write("Syllables: %d\n" % spoken.syllable_count, "muted")

        for sense in entry.administrative_senses:
            self._render_admin_sense(sense)
        self._render_general_senses(
            [s for s in entry.senses if not s.is_administrative])

        synonyms, antonyms = entry.synonyms, entry.antonyms
        if synonyms:
            self._write("\nSynonyms · पर्यायवाची\n", "section")
            self._write(", ".join(synonyms[:40]) + "\n", "body")
        if antonyms:
            self._write("\nAntonyms · विलोम\n", "section")
            self._write(", ".join(antonyms[:40]) + "\n", "body")

        self.view.configure(state=tk.DISABLED)
        self.view.yview_moveto(0)

        # Chips: spelling neighbours are irrelevant on a hit, related words
        # are what the reader wants next.
        self.suggestions.show("", [])
        if self.dictionary is not None:
            self.related.show("Related:", self.dictionary.related_words(entry, 10))

    def _render_admin_sense(self, sense: Sense) -> None:
        heading = "■ Government administrative term"
        if sense.category:
            heading += " — %s" % sense.category
        self._write("\n" + heading + "\n", "admin")

        if sense.hindi:
            self._write("Hindi · हिंदी: ", "label")
            self._write(", ".join(sense.hindi) + "\n", "hindi_body")
        if sense.definition_en:
            self._write("Meaning: ", "label")
            self._write(sense.definition_en + "\n", "body")
        if sense.definition_hi:
            self._write("अर्थ: ", "label")
            self._write(sense.definition_hi + "\n", "hindi_body")
        for example in sense.examples_en:
            self._write("Example:  " + example + "\n", "example")
        for example in sense.examples_hi:
            self._write("उदाहरण:  " + example + "\n", "hindi_example")

    def _render_general_senses(self, senses: List[Sense]) -> None:
        grouped: "dict[str, List[Sense]]" = {}
        for sense in senses:
            grouped.setdefault(sense.pos or "other", []).append(sense)

        for pos, group in grouped.items():
            self._write("\n%s\n" % pos_label(pos), "section")
            number = 0
            for sense in group:
                number += 1
                if sense.hindi:
                    self._write("%d. " % number, "label")
                    self._write(", ".join(sense.hindi) + "\n", "hindi_body")
                    if sense.definition_en:
                        self._write(sense.definition_en + "\n", "body")
                elif sense.definition_en:
                    self._write("%d. " % number, "label")
                    self._write(sense.definition_en + "\n", "body")
                else:
                    number -= 1

                if sense.definition_hi:
                    self._write(sense.definition_hi + "\n", "hindi_body")
                for example in sense.examples_en[:3]:
                    self._write("“%s”\n" % example, "example")
                for example in sense.examples_hi[:3]:
                    self._write("“%s”\n" % example, "hindi_example")
