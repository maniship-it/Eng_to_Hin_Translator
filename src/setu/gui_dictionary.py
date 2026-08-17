"""The dictionary tab: word meanings, thesaurus and the administrative glossary.

Lookups run against a local SQLite database and return in well under a
millisecond, so this panel queries on the UI thread.  Typing is debounced so
the suggestion list is not rebuilt on every keystroke.
"""

from __future__ import annotations

import tkinter as tk
from tkinter import font as tkfont, ttk
from typing import List, Optional

from .dictionary import (
    Dictionary,
    DictionaryError,
    DictionaryNotFoundError,
    Entry,
    Sense,
    pos_label,
)

#: How long to wait after the last keystroke before refreshing suggestions.
SUGGEST_DELAY_MS = 160

class DictionaryPanel(ttk.Frame):
    """Search box, result list and a formatted view of one dictionary entry."""

    def __init__(self, parent, settings, hindi_family: str = "Nirmala UI",
                 base_size: int = 11):
        super().__init__(parent, padding=(8, 8))

        self.settings = settings
        self.dictionary: Optional[Dictionary] = None
        self.load_error: str = ""
        self._suggest_job: Optional[str] = None
        self._entries: List[Entry] = []
        self._browsing_admin = False

        self.body_font = tkfont.Font(family="Segoe UI", size=base_size)
        self.bold_font = tkfont.Font(family="Segoe UI", size=base_size, weight="bold")
        self.head_font = tkfont.Font(family="Segoe UI", size=base_size + 7,
                                     weight="bold")
        self.hindi_font = tkfont.Font(family=hindi_family, size=base_size + 3)
        self.hindi_small_font = tkfont.Font(family=hindi_family, size=base_size + 1)
        self.italic_font = tkfont.Font(family="Segoe UI", size=base_size,
                                       slant="italic")

        self._build()

    # -- construction --------------------------------------------------

    def _build(self) -> None:
        search_bar = ttk.Frame(self)
        search_bar.pack(fill=tk.X, pady=(0, 8))

        ttk.Label(search_bar, text="Word:", style="Heading.TLabel").pack(side=tk.LEFT)

        self.query = tk.StringVar()
        self.search_entry = ttk.Entry(search_bar, textvariable=self.query, width=30)
        self.search_entry.pack(side=tk.LEFT, padx=(6, 6))
        self.search_entry.bind("<KeyRelease>", self._on_typed)
        self.search_entry.bind("<Return>", lambda e: self.search())
        self.search_entry.bind("<Down>", self._focus_results)

        ttk.Button(search_bar, text="Search", command=self.search).pack(side=tk.LEFT)
        ttk.Button(search_bar, text="Administrative glossary",
                   command=self.browse_administrative).pack(side=tk.LEFT, padx=(12, 0))

        self.category = tk.StringVar()
        self.category_box = ttk.Combobox(
            search_bar, textvariable=self.category, width=22, state="readonly"
        )
        self.category_box.pack(side=tk.LEFT, padx=(6, 0))
        self.category_box.bind("<<ComboboxSelected>>",
                               lambda e: self.browse_administrative())

        ttk.Label(
            search_bar,
            text="Type English or Hindi (हिंदी) — both directions work.",
            foreground="#666666",
        ).pack(side=tk.RIGHT)

        panes = ttk.Panedwindow(self, orient=tk.HORIZONTAL)
        panes.pack(fill=tk.BOTH, expand=True)

        left = ttk.Frame(panes)
        right = ttk.Frame(panes)
        panes.add(left, weight=1)
        panes.add(right, weight=3)

        ttk.Label(left, text="Matches", style="Heading.TLabel").pack(anchor=tk.W)
        list_frame = ttk.Frame(left)
        list_frame.pack(fill=tk.BOTH, expand=True, pady=(4, 0))
        self.results = tk.Listbox(
            list_frame, activestyle="none", exportselection=False,
            font=self.body_font, borderwidth=1, relief=tk.FLAT,
            highlightthickness=1, highlightbackground="#c8c8d0",
        )
        scroll = ttk.Scrollbar(list_frame, orient=tk.VERTICAL,
                               command=self.results.yview)
        self.results.configure(yscrollcommand=scroll.set)
        scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self.results.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.results.bind("<<ListboxSelect>>", self._on_result_selected)
        self.results.bind("<Return>", self._on_result_selected)

        ttk.Label(right, text="Meaning", style="Heading.TLabel").pack(anchor=tk.W)
        view_frame = ttk.Frame(right)
        view_frame.pack(fill=tk.BOTH, expand=True, pady=(4, 0))
        self.view = tk.Text(
            view_frame, wrap=tk.WORD, font=self.body_font, relief=tk.FLAT,
            borderwidth=1, highlightthickness=1, highlightbackground="#c8c8d0",
            padx=12, pady=10, spacing1=1, spacing3=4, cursor="arrow",
            background="#fbfbfd",
        )
        view_scroll = ttk.Scrollbar(view_frame, orient=tk.VERTICAL,
                                    command=self.view.yview)
        self.view.configure(yscrollcommand=view_scroll.set)
        view_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self.view.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self._configure_tags()
        self.view.configure(state=tk.DISABLED)

        self.status = ttk.Label(self, text="", foreground="#555555")
        self.status.pack(fill=tk.X, pady=(6, 0))

    def _configure_tags(self) -> None:
        self.view.tag_configure("headword", font=self.head_font, foreground="#12203a",
                                spacing3=2)
        self.view.tag_configure("inflection", font=self.italic_font,
                                foreground="#666666", spacing3=8)
        self.view.tag_configure("hindi", font=self.hindi_font, foreground="#0b5d1e",
                                spacing3=8)
        self.view.tag_configure("hindi_body", font=self.hindi_small_font,
                                foreground="#1c1c1c", lmargin1=24, lmargin2=24)
        self.view.tag_configure("section", font=self.bold_font, foreground="#1f6feb",
                                spacing1=12, spacing3=4)
        self.view.tag_configure("admin", font=self.bold_font, foreground="#8a4b00",
                                spacing1=12, spacing3=4)
        self.view.tag_configure("label", font=self.bold_font, foreground="#444444",
                                lmargin1=24, lmargin2=24)
        self.view.tag_configure("body", lmargin1=24, lmargin2=24)
        self.view.tag_configure("example", font=self.italic_font,
                                foreground="#3a3a3a", lmargin1=40, lmargin2=40)
        self.view.tag_configure("hindi_example", font=self.hindi_small_font,
                                foreground="#3a3a3a", lmargin1=40, lmargin2=40)
        self.view.tag_configure("muted", foreground="#777777")

    # -- dictionary lifecycle ------------------------------------------

    def ensure_loaded(self) -> bool:
        """Open the dictionary on first use; report failure in the panel."""
        if self.dictionary is not None:
            return True
        extra = [self.settings.dictionary_path] if self.settings.dictionary_path else None
        try:
            self.dictionary = Dictionary.open(extra=extra)
        except (DictionaryNotFoundError, DictionaryError) as exc:
            self.load_error = str(exc)
            self._render_message(
                "Dictionary not available",
                str(exc)
                + "\n\nThe translator itself is unaffected — only this tab needs "
                  "the dictionary database.",
            )
            self.status.configure(text="Dictionary not loaded.")
            return False

        meta = self.dictionary.meta()
        self.status.configure(text="%s head words · %s administrative terms · %s"
                              % (meta.get("entries", "?"),
                                 meta.get("admin_terms", "?"),
                                 self.dictionary.path.name))
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
        if self._suggest_job is not None:
            self.after_cancel(self._suggest_job)
        self._suggest_job = self.after(SUGGEST_DELAY_MS, self._refresh_suggestions)

    def _refresh_suggestions(self) -> None:
        self._suggest_job = None
        if not self.ensure_loaded():
            return
        text = self.query.get().strip()
        if len(text) < 2:
            return
        assert self.dictionary is not None
        matches = self.dictionary.suggest(text, limit=60)
        if matches:
            self._browsing_admin = False
            self._fill_results(matches)

    def _fill_results(self, words: List[str]) -> None:
        self.results.delete(0, tk.END)
        for word in words:
            self.results.insert(tk.END, word)

    def search(self, word: str = "") -> None:
        """Look up ``word`` (or the search box contents) and show the result."""
        if not self.ensure_loaded():
            return
        assert self.dictionary is not None

        query = (word or self.query.get()).strip()
        if not query:
            return
        if word:
            self.query.set(word)

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

        suggestions = self.dictionary.suggest(query, limit=40)
        if suggestions:
            self._fill_results(suggestions)
            self._render_message(
                "No exact match for “%s”" % query,
                "Did you mean one of the words listed on the left?",
            )
        else:
            self._fill_results([])
            self._render_message(
                "Not found: “%s”" % query,
                "This word is not in the dictionary. Try the base form of the "
                "word, or check the spelling.",
            )

    def lookup_word(self, word: str) -> None:
        """Entry point used by the translator tab's context menu."""
        self.search(word)
        self.search_entry.focus_set()
        self.search_entry.selection_range(0, tk.END)

    def browse_administrative(self) -> None:
        """List the curated administrative glossary, optionally by category."""
        if not self.ensure_loaded():
            return
        assert self.dictionary is not None

        entries = self.dictionary.administrative_terms()
        category = self.category.get()
        if category and not category.startswith("("):
            entries = [
                entry for entry in entries
                if any(sense.category == category
                       for sense in entry.administrative_senses)
            ]

        self._entries = entries
        self._browsing_admin = True
        self._fill_results([entry.word for entry in entries])
        if entries:
            self.results.selection_clear(0, tk.END)
            self.results.selection_set(0)
            self._render_entry(entries[0])
        self.status.configure(
            text="%d administrative term(s)%s"
            % (len(entries), "" if category.startswith("(") else " in %s" % category)
        )

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
        word = self.results.get(index)
        if not self.ensure_loaded():
            return
        assert self.dictionary is not None
        entry = self.dictionary.lookup(word)
        if entry is not None:
            self._render_entry(entry)

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
        self.view.configure(state=tk.NORMAL)
        self.view.delete("1.0", tk.END)

        self._write(entry.word + "\n", "headword")
        if entry.matched_form:
            self._write("shown for “%s”\n" % entry.matched_form, "inflection")

        hindi = entry.hindi_meanings
        if hindi:
            self._write(", ".join(hindi[:10]) + "\n", "hindi")

        parts = entry.parts_of_speech
        if parts:
            self._write("Parts of speech: " + ", ".join(pos_label(p) for p in parts)
                        + "\n", "muted")

        for sense in entry.administrative_senses:
            self._render_admin_sense(sense)

        remaining = [s for s in entry.senses if not s.is_administrative]
        self._render_general_senses(remaining)

        synonyms = entry.synonyms
        antonyms = entry.antonyms
        if synonyms:
            self._write("\nThesaurus — synonyms / पर्यायवाची\n", "section")
            self._write(", ".join(synonyms[:40]) + "\n", "body")
        if antonyms:
            self._write("\nThesaurus — antonyms / विलोम\n", "section")
            self._write(", ".join(antonyms[:40]) + "\n", "body")

        self.view.configure(state=tk.DISABLED)
        self.view.yview_moveto(0)

    def _render_admin_sense(self, sense: Sense) -> None:
        heading = "■ Government administrative term"
        if sense.category:
            heading += " — %s" % sense.category
        self._write("\n" + heading + "\n", "admin")

        if sense.hindi:
            self._write("Hindi / हिंदी: ", "label")
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

    # -- appearance ----------------------------------------------------

    def apply_fonts(self, hindi_family: str, base_size: int) -> None:
        """Follow the font settings chosen for the translator panes."""
        self.body_font.configure(size=base_size)
        self.bold_font.configure(size=base_size)
        self.italic_font.configure(size=base_size)
        self.head_font.configure(size=base_size + 7)
        self.hindi_font.configure(family=hindi_family, size=base_size + 3)
        self.hindi_small_font.configure(family=hindi_family, size=base_size + 1)
