"""The Anuvad Plus desktop window.

The model is loaded, and every translation runs, on a worker thread; the UI
thread only ever drains a queue, so the window stays responsive on long
documents and the user can cancel a run in progress.

Layout is a navigation rail on the left and a stack of pages on the right.
The pages live in a Notebook whose own tab strip is hidden — the rail selects
them — which keeps page switching simple while letting the rail carry the
larger, friendlier targets.
"""

from __future__ import annotations

import queue
import threading
import time
import tkinter as tk
import traceback
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import List, Optional

from . import model as model_module
from .config import Settings
from .gui_dictionary import DictionaryPanel
from .runtime import is_missing_msvc_runtime, msvc_runtime_message
from .textio import read_text_file, write_text_file
from .theme import Theme
from .translator import (
    Report,
    TranslationCancelled,
    Translator,
    build_translator,
)
from .version import __version__

APP_NAME = "Anuvad Plus"
APP_TITLE = "Anuvad Plus — English ⇄ Hindi"
APP_TAGLINE = "अनुवाद प्लस"
APP_SUBTITLE = "Translator · Dictionary · Government glossary"

# Messages passed from the worker thread to the UI thread.
MSG_MODEL_READY = "model_ready"
MSG_MODEL_FAILED = "model_failed"
MSG_PROGRESS = "progress"
MSG_DONE = "done"
MSG_ERROR = "error"
MSG_CANCELLED = "cancelled"

PAGE_TRANSLATE = 0
PAGE_DICTIONARY = 1

QUICK_START = [
    ("Translate some text",
     "Type or paste English on the left, then press Translate (or Ctrl+Enter). "
     "The Hindi appears on the right."),
    ("Translate a whole file",
     "File → Open text file loads a document. Blank lines, indentation and "
     "numbered lists are kept exactly as they were."),
    ("Save your work",
     "File → Save translation writes a .txt file. Save side-by-side writes "
     "English and Hindi in two columns, ready for Excel."),
    ("Look up a word, either way",
     "Open the Dictionary (Ctrl+D) and type English or Hindi — it searches "
     "in whichever direction you type. Double-click any word to look it up."),
    ("Hear how a word sounds",
     "Every English word shows its pronunciation. Press Speak to hear it, "
     "using the voice built into Windows."),
    ("Government terminology",
     "The Glossary lists official administrative terms with meanings and "
     "examples in both languages."),
]

TIPS = [
    "Tip: double-click any word to look it up in the Dictionary.",
    "Tip: press Ctrl+Enter to translate, Esc to cancel a long run.",
    "Tip: the Dictionary searches both ways — type English or type हिंदी.",
    "Tip: misspelled a word? The Dictionary suggests what you probably meant.",
    "Tip: press Speak in the Dictionary to hear an English word aloud.",
    "Tip: File → Save side-by-side gives you English and Hindi in two columns.",
    "Tip: everything runs on this PC — nothing is sent over the internet.",
]


class Tooltip:
    """A small hover label, so every control explains itself."""

    def __init__(self, widget: tk.Widget, text: str, theme: Optional[Theme] = None):
        self.widget = widget
        self.text = text
        self.theme = theme
        self.window: Optional[tk.Toplevel] = None
        widget.bind("<Enter>", self._show, add="+")
        widget.bind("<Leave>", self._hide, add="+")
        widget.bind("<ButtonPress>", self._hide, add="+")

    def _show(self, event=None) -> None:
        if self.window is not None or not self.text:
            return
        try:
            x = self.widget.winfo_rootx() + 14
            y = self.widget.winfo_rooty() + self.widget.winfo_height() + 8
        except tk.TclError:
            return
        self.window = tk.Toplevel(self.widget)
        self.window.wm_overrideredirect(True)
        self.window.wm_geometry("+%d+%d" % (x, y))
        background = "#0c1220" if self.theme is None else self.theme.palette.sidebar
        tk.Label(
            self.window, text=self.text, justify=tk.LEFT, background=background,
            foreground="#ffffff", relief=tk.FLAT, borderwidth=0,
            font=("Segoe UI", 9), padx=10, pady=6, wraplength=320,
        ).pack()

    def _hide(self, event=None) -> None:
        if self.window is not None:
            self.window.destroy()
            self.window = None


class NavItem(tk.Frame):
    """One entry in the navigation rail."""

    def __init__(self, parent, theme: Theme, icon: str, label: str, command):
        colours = theme.palette
        super().__init__(parent, background=colours.sidebar, cursor="hand2")
        self.theme = theme
        self.command = command
        self.selected = False

        self.icon = tk.Label(self, text=icon, background=colours.sidebar,
                             foreground="#ffffff", font=(theme.ui_family,
                                                        theme.base_size + 3))
        self.icon.pack(side=tk.LEFT, padx=(16, 10), pady=11)
        self.text = tk.Label(self, text=label, background=colours.sidebar,
                             foreground="#c6d2e8",
                             font=(theme.ui_family, theme.base_size))
        self.text.pack(side=tk.LEFT, pady=11)

        for widget in (self, self.icon, self.text):
            widget.bind("<Button-1>", lambda e: self.command())
            widget.bind("<Enter>", self._hover)
            widget.bind("<Leave>", self._unhover)

    def _paint(self, background: str, foreground: str) -> None:
        for widget in (self, self.icon, self.text):
            try:
                widget.configure(background=background)
            except tk.TclError:
                return
        self.icon.configure(foreground=foreground)
        self.text.configure(foreground=foreground)

    def _hover(self, event=None) -> None:
        if not self.selected:
            self._paint(self.theme.palette.sidebar_active, "#ffffff")

    def _unhover(self, event=None) -> None:
        if not self.selected:
            self._paint(self.theme.palette.sidebar, "#c6d2e8")

    def set_selected(self, selected: bool) -> None:
        self.selected = selected
        if selected:
            self._paint(self.theme.palette.sidebar_active, "#ffffff")
        else:
            self._paint(self.theme.palette.sidebar, "#c6d2e8")

    def restyle(self, theme: Theme) -> None:
        self.theme = theme
        self.set_selected(self.selected)


class TranslatorApp(tk.Tk):
    def __init__(self, settings: Optional[Settings] = None):
        super().__init__()

        self.settings = settings or Settings.load()
        self.queue: "queue.Queue[tuple]" = queue.Queue()
        self.translator: Optional[Translator] = None
        self.model_dir: Optional[Path] = None
        self.cancel_event: Optional[threading.Event] = None
        self.worker: Optional[threading.Thread] = None
        self._busy = False
        self._sync_scroll = tk.BooleanVar(value=True)
        self._started_at = 0.0
        self._tip_job: Optional[str] = None
        self.nav_items: List[NavItem] = []

        self.title(APP_TITLE)
        self.geometry("1240x790")
        self.minsize(940, 600)
        self._set_icon()

        self.theme = Theme(
            self,
            mode=self.settings.theme if self.settings.theme in ("light", "dark")
            else "light",
            base_size=self.settings.font_size,
            devanagari_family=self.settings.hindi_font_family,
        )
        # Kept for compatibility with the rest of the app and the tests.
        self.source_font = self.theme.editor
        self.target_font = self.theme.hindi_editor

        self._build_menu()
        self._build_header()
        self._build_body()
        self._build_statusbar()
        self._bind_keys()

        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.after(50, self._drain_queue)
        self._load_model_async()
        self.after(400, self._maybe_show_quick_start)

    # -- construction --------------------------------------------------

    def _set_icon(self) -> None:
        try:
            icon = tk.PhotoImage(width=16, height=16)
            icon.put("#2f4b8c", to=(0, 0, 16, 16))
            icon.put("#e0ab5b", to=(3, 3, 13, 6))
            icon.put("#ffffff", to=(3, 8, 13, 11))
            self.iconphoto(True, icon)
            self._icon = icon  # keep a reference alive
        except tk.TclError:
            pass

    def _build_menu(self) -> None:
        menubar = tk.Menu(self)

        file_menu = tk.Menu(menubar, tearoff=0)
        file_menu.add_command(label="Open text file…", accelerator="Ctrl+O",
                              command=self.open_file)
        file_menu.add_command(label="Save translation…", accelerator="Ctrl+S",
                              command=self.save_translation)
        file_menu.add_command(label="Save side-by-side…",
                              command=self.save_side_by_side)
        file_menu.add_separator()
        file_menu.add_command(label="Exit", accelerator="Ctrl+Q",
                              command=self._on_close)
        menubar.add_cascade(label="File", menu=file_menu)

        edit_menu = tk.Menu(menubar, tearoff=0)
        edit_menu.add_command(label="Cut", accelerator="Ctrl+X",
                              command=lambda: self._text_event("<<Cut>>"))
        edit_menu.add_command(label="Copy", accelerator="Ctrl+C",
                              command=lambda: self._text_event("<<Copy>>"))
        edit_menu.add_command(label="Paste", accelerator="Ctrl+V",
                              command=lambda: self._text_event("<<Paste>>"))
        edit_menu.add_separator()
        edit_menu.add_command(label="Copy translation", command=self.copy_output)
        edit_menu.add_command(label="Clear both panes", command=self.clear_all)
        menubar.add_cascade(label="Edit", menu=edit_menu)

        view_menu = tk.Menu(menubar, tearoff=0)
        view_menu.add_command(label="Larger text", accelerator="Ctrl++",
                              command=lambda: self.adjust_font(1))
        view_menu.add_command(label="Smaller text", accelerator="Ctrl+-",
                              command=lambda: self.adjust_font(-1))
        view_menu.add_separator()
        view_menu.add_command(label="Switch to dark / light theme",
                              accelerator="Ctrl+T", command=self.toggle_theme)
        view_menu.add_checkbutton(label="Wrap lines", variable=self._wrap_var(),
                                  command=self._apply_wrap)
        view_menu.add_checkbutton(label="Synchronised scrolling",
                                  variable=self._sync_scroll)
        menubar.add_cascade(label="View", menu=view_menu)

        dictionary_menu = tk.Menu(menubar, tearoff=0)
        dictionary_menu.add_command(label="Open dictionary", accelerator="Ctrl+D",
                                    command=self.show_dictionary)
        dictionary_menu.add_command(
            label="Look up selected word",
            command=lambda: self.lookup_selection(self._focused_text()),
        )
        dictionary_menu.add_separator()
        dictionary_menu.add_command(label="Government glossary",
                                    command=self.show_administrative_glossary)
        dictionary_menu.add_command(label="Choose dictionary file…",
                                    command=self.choose_dictionary_file)
        menubar.add_cascade(label="Dictionary", menu=dictionary_menu)

        tools_menu = tk.Menu(menubar, tearoff=0)
        tools_menu.add_command(label="Settings…", command=self.open_settings)
        tools_menu.add_command(label="Choose model folder…",
                               command=self.choose_model_folder)
        tools_menu.add_command(label="Reload model", command=self._load_model_async)
        menubar.add_cascade(label="Tools", menu=tools_menu)

        help_menu = tk.Menu(menubar, tearoff=0)
        help_menu.add_command(label="Quick start", accelerator="F1",
                              command=self.show_quick_start)
        help_menu.add_separator()
        help_menu.add_command(label="Where is my model?", command=self.show_model_help)
        help_menu.add_command(label="About", command=self.show_about)
        menubar.add_cascade(label="Help", menu=help_menu)

        self.config(menu=menubar)

    def _wrap_var(self) -> tk.BooleanVar:
        if not hasattr(self, "_wrap_variable"):
            self._wrap_variable = tk.BooleanVar(value=self.settings.wrap_text)
        return self._wrap_variable

    def _build_header(self) -> None:
        colours = self.theme.palette
        self.header = tk.Frame(self, background=colours.sidebar)
        self.header.pack(side=tk.TOP, fill=tk.X)

        inner = tk.Frame(self.header, background=colours.sidebar, padx=18, pady=12)
        inner.pack(fill=tk.X)
        self._header_inner = inner

        self.brand = tk.Label(inner, text="अ", background=colours.marigold,
                              foreground="#1b2c52",
                              font=(self.theme.devanagari_family,
                                    self.theme.base_size + 6, "bold"),
                              width=2, pady=2)
        self.brand.pack(side=tk.LEFT, padx=(0, 12))

        titles = tk.Frame(inner, background=colours.sidebar)
        titles.pack(side=tk.LEFT)
        self.brand_name = tk.Label(titles, text=APP_NAME,
                                   background=colours.sidebar, foreground="#ffffff",
                                   font=(self.theme.ui_family,
                                         self.theme.base_size + 6, "bold"))
        self.brand_name.pack(anchor=tk.W)
        self.brand_sub = tk.Label(titles, text=APP_SUBTITLE,
                                  background=colours.sidebar, foreground="#93a5c6",
                                  font=(self.theme.ui_family,
                                        self.theme.base_size - 2))
        self.brand_sub.pack(anchor=tk.W)

        self.offline_badge = tk.Label(
            inner, text="  ● Offline  ", background=colours.sidebar,
            foreground="#7fd7a3", font=(self.theme.ui_family,
                                        self.theme.base_size - 2, "bold"))
        self.offline_badge.pack(side=tk.RIGHT)

        self.theme_button = tk.Label(
            inner, text="  ☾  ", background=colours.sidebar, foreground="#c6d2e8",
            font=(self.theme.ui_family, self.theme.base_size + 2), cursor="hand2")
        self.theme_button.pack(side=tk.RIGHT, padx=(0, 14))
        self.theme_button.bind("<Button-1>", lambda e: self.toggle_theme())
        Tooltip(self.theme_button, "Switch between light and dark.  Ctrl+T",
                self.theme)

    def _build_body(self) -> None:
        colours = self.theme.palette
        body = ttk.Frame(self)
        body.pack(fill=tk.BOTH, expand=True)

        # Navigation rail ------------------------------------------------
        self.sidebar = tk.Frame(body, background=colours.sidebar, width=196)
        self.sidebar.pack(side=tk.LEFT, fill=tk.Y)
        self.sidebar.pack_propagate(False)

        for icon, label, command in (
            ("⇄", "Translate", lambda: self.show_page(PAGE_TRANSLATE)),
            ("⌕", "Dictionary", self.show_dictionary),
            ("▤", "Glossary", self.show_administrative_glossary),
        ):
            item = NavItem(self.sidebar, self.theme, icon, label, command)
            item.pack(fill=tk.X)
            self.nav_items.append(item)

        self.sidebar_footer = tk.Label(
            self.sidebar, text="v%s" % __version__, background=colours.sidebar,
            foreground="#5f7099", font=(self.theme.ui_family,
                                        self.theme.base_size - 3))
        self.sidebar_footer.pack(side=tk.BOTTOM, pady=12)

        # Pages ----------------------------------------------------------
        self.notebook = ttk.Notebook(body, style="Tabless.TNotebook")
        self.notebook.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        self.translate_page = ttk.Frame(self.notebook, padding=(16, 14))
        self.notebook.add(self.translate_page, text="Translate")
        self._build_translate_page(self.translate_page)

        self.dictionary_panel = DictionaryPanel(self.notebook, self.settings,
                                                self.theme)
        self.notebook.add(self.dictionary_panel, text="Dictionary")
        self.notebook.bind("<<NotebookTabChanged>>", self._on_tab_changed)

        self.show_page(PAGE_TRANSLATE)

    def _build_translate_page(self, parent: ttk.Frame) -> None:
        # Action bar -----------------------------------------------------
        bar = ttk.Frame(parent)
        bar.pack(fill=tk.X, pady=(0, 12))

        self.translate_button = ttk.Button(
            bar, text="Translate  ▸", style="Accent.TButton",
            command=self.translate, state=tk.DISABLED,
        )
        self.translate_button.pack(side=tk.LEFT)

        self.cancel_button = ttk.Button(bar, text="Cancel", command=self.cancel,
                                        state=tk.DISABLED)
        self.cancel_button.pack(side=tk.LEFT, padx=(8, 0))

        ttk.Separator(bar, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y,
                                                    padx=14, pady=4)

        open_button = ttk.Button(bar, text="Open file", command=self.open_file)
        open_button.pack(side=tk.LEFT)
        save_button = ttk.Button(bar, text="Save", command=self.save_translation)
        save_button.pack(side=tk.LEFT, padx=(8, 0))
        copy_button = ttk.Button(bar, text="Copy", command=self.copy_output)
        copy_button.pack(side=tk.LEFT, padx=(8, 0))
        clear_button = ttk.Button(bar, text="Clear", command=self.clear_all)
        clear_button.pack(side=tk.LEFT, padx=(8, 0))

        self.progress = ttk.Progressbar(bar, mode="determinate", length=170)
        self.progress.pack(side=tk.RIGHT, pady=6)
        self.progress_label = ttk.Label(bar, text="", style="Muted.TLabel")
        self.progress_label.pack(side=tk.RIGHT, padx=(0, 10))

        Tooltip(self.translate_button,
                "Translate the English text into Hindi.  Ctrl+Enter", self.theme)
        Tooltip(self.cancel_button, "Stop a translation that is running.  Esc",
                self.theme)
        Tooltip(open_button, "Open an English text file.  Ctrl+O", self.theme)
        Tooltip(save_button, "Save the Hindi translation.  Ctrl+S", self.theme)
        Tooltip(copy_button, "Copy the Hindi to the clipboard.", self.theme)
        Tooltip(clear_button, "Empty both panes.", self.theme)

        # Hint line ------------------------------------------------------
        self.tip_label = ttk.Label(parent, text=TIPS[0], style="Muted.TLabel")
        self.tip_label.pack(fill=tk.X, pady=(0, 10))
        self._tip_index = 0
        self._rotate_tip()

        # Editors --------------------------------------------------------
        panes = ttk.Panedwindow(parent, orient=tk.HORIZONTAL)
        panes.pack(fill=tk.BOTH, expand=True)

        source_card = ttk.Frame(panes, style="Card.TFrame", padding=12)
        target_card = ttk.Frame(panes, style="Card.TFrame", padding=12)
        panes.add(source_card, weight=1)
        panes.add(target_card, weight=1)

        self.source_counts = self._card_header(source_card, "English", "source")
        self.source_text = self._make_text(source_card, self.source_font)
        self.source_text.bind("<<Modified>>", self._on_source_modified)

        self.target_counts = self._card_header(target_card, "हिंदी  Hindi", "target")
        self.target_text = self._make_text(target_card, self.target_font)

        self._apply_wrap()

    def _card_header(self, parent: ttk.Frame, title: str, role: str) -> ttk.Label:
        header = ttk.Frame(parent, style="Card.TFrame")
        header.pack(fill=tk.X, pady=(0, 8))
        ttk.Label(header, text=title, style="CardHeading.TLabel").pack(side=tk.LEFT)
        counts = ttk.Label(header, text="", style="CardMuted.TLabel")
        counts.pack(side=tk.RIGHT)
        return counts

    def _make_text(self, parent: ttk.Frame, font) -> tk.Text:
        frame = ttk.Frame(parent, style="Card.TFrame")
        frame.pack(fill=tk.BOTH, expand=True)

        text = tk.Text(frame, wrap=tk.WORD, undo=True, font=font, padx=12,
                       pady=10, spacing1=2, spacing3=4, insertwidth=2, tabs="1c",
                       **self.theme.text_widget_options())
        yscroll = ttk.Scrollbar(frame, orient=tk.VERTICAL)
        xscroll = ttk.Scrollbar(frame, orient=tk.HORIZONTAL)

        yscroll.configure(command=lambda *args: self._scroll_y(text, *args))
        xscroll.configure(command=text.xview)
        text.configure(
            yscrollcommand=lambda first, last: yscroll.set(first, last),
            xscrollcommand=xscroll.set,
        )

        yscroll.pack(side=tk.RIGHT, fill=tk.Y)
        xscroll.pack(side=tk.BOTTOM, fill=tk.X)
        text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        text.bind("<MouseWheel>", self._on_mousewheel)
        text.bind("<Button-4>", self._on_mousewheel)
        text.bind("<Button-5>", self._on_mousewheel)
        self._attach_context_menu(text)
        return text

    def _attach_context_menu(self, text: tk.Text) -> None:
        menu = tk.Menu(text, tearoff=0)
        menu.add_command(label="Look up in dictionary",
                         command=lambda: self.lookup_selection(text))
        menu.add_separator()
        menu.add_command(label="Cut", command=lambda: text.event_generate("<<Cut>>"))
        menu.add_command(label="Copy", command=lambda: text.event_generate("<<Copy>>"))
        menu.add_command(label="Paste", command=lambda: text.event_generate("<<Paste>>"))
        menu.add_separator()
        menu.add_command(label="Select all",
                         command=lambda: text.tag_add(tk.SEL, "1.0", tk.END))

        def popup(event: tk.Event) -> None:
            try:
                menu.tk_popup(event.x_root, event.y_root)
            finally:
                menu.grab_release()

        text.bind("<Button-3>", popup)
        text.bind("<Double-Button-1>", lambda e: self._on_double_click(e, text))

    def _build_statusbar(self) -> None:
        colours = self.theme.palette
        self.statusbar = tk.Frame(self, background=colours.surface, height=30)
        self.statusbar.pack(side=tk.BOTTOM, fill=tk.X)
        self.status = ttk.Label(self.statusbar, text="Starting…",
                                style="Status.TLabel", anchor=tk.W)
        self.status.pack(side=tk.LEFT, fill=tk.X, expand=True)
        self.model_label = ttk.Label(self.statusbar, text="",
                                     style="Status.TLabel")
        self.model_label.pack(side=tk.RIGHT)

    def _bind_keys(self) -> None:
        self.bind("<Control-Return>", lambda e: self.translate())
        self.bind("<Control-o>", lambda e: (self.open_file(), "break")[1])
        self.bind("<Control-s>", lambda e: (self.save_translation(), "break")[1])
        self.bind("<Control-q>", lambda e: self._on_close())
        self.bind("<Control-d>", lambda e: (self.show_dictionary(), "break")[1])
        self.bind("<Control-t>", lambda e: (self.toggle_theme(), "break")[1])
        self.bind("<Control-plus>", lambda e: self.adjust_font(1))
        self.bind("<Control-equal>", lambda e: self.adjust_font(1))
        self.bind("<Control-minus>", lambda e: self.adjust_font(-1))
        self.bind("<Escape>", lambda e: self.cancel())
        self.bind("<F1>", lambda e: self.show_quick_start())

    # -- pages ---------------------------------------------------------

    def show_page(self, index: int) -> None:
        self.notebook.select(index)
        for position, item in enumerate(self.nav_items):
            item.set_selected(position == index
                              or (index == PAGE_DICTIONARY and position == 2
                                  and getattr(self, "_glossary_mode", False)))
        if index < len(self.nav_items):
            for position, item in enumerate(self.nav_items):
                item.set_selected(position == index)

    def _on_tab_changed(self, event: tk.Event) -> None:
        try:
            current = self.notebook.index(self.notebook.select())
        except (tk.TclError, KeyError):
            return
        if current == PAGE_DICTIONARY:
            self.dictionary_panel.ensure_loaded()

    def show_dictionary(self) -> None:
        self._glossary_mode = False
        self.show_page(PAGE_DICTIONARY)
        self.nav_items[1].set_selected(True)
        self.dictionary_panel.ensure_loaded()
        self.dictionary_panel.focus_search()

    def show_administrative_glossary(self) -> None:
        self._glossary_mode = True
        self.show_page(PAGE_DICTIONARY)
        for position, item in enumerate(self.nav_items):
            item.set_selected(position == 2)
        if self.dictionary_panel.ensure_loaded():
            self.dictionary_panel.browse_administrative()

    # -- theme ---------------------------------------------------------

    def toggle_theme(self) -> str:
        mode = self.theme.toggle_mode()
        self.settings.theme = mode
        self.settings.save()
        self._restyle()
        self.status.configure(text="Switched to the %s theme." % mode)
        return mode

    def _restyle(self) -> None:
        """Repaint the plain Tk widgets that ttk styling cannot reach."""
        colours = self.theme.palette
        for widget in (self.header, self._header_inner, self.sidebar):
            widget.configure(background=colours.sidebar)
        for label in (self.brand_name, self.brand_sub, self.offline_badge,
                      self.theme_button, self.sidebar_footer):
            label.configure(background=colours.sidebar)
        self.brand.configure(background=colours.marigold)
        self.brand_sub.configure(foreground="#93a5c6")
        self.theme_button.configure(
            text="  ☀  " if colours.is_dark else "  ☾  ", foreground="#c6d2e8")
        self.statusbar.configure(background=colours.surface)
        for item in self.nav_items:
            item.restyle(self.theme)
        for text in (self.source_text, self.target_text):
            text.configure(**self.theme.text_widget_options())
        self.dictionary_panel.restyle()

    # -- scrolling -----------------------------------------------------

    def _scroll_y(self, text: tk.Text, *args) -> None:
        text.yview(*args)
        if self._sync_scroll.get():
            self._other_text(text).yview_moveto(text.yview()[0])

    def _on_mousewheel(self, event: tk.Event) -> str:
        widget = event.widget
        if event.num == 4:
            delta = -3
        elif event.num == 5:
            delta = 3
        else:
            delta = -1 * int(event.delta / 40) if event.delta else 0
        widget.yview_scroll(delta, "units")
        if self._sync_scroll.get():
            self._other_text(widget).yview_moveto(widget.yview()[0])
        return "break"

    def _other_text(self, text: tk.Text) -> tk.Text:
        return self.target_text if text is self.source_text else self.source_text

    # -- dictionary bridge ---------------------------------------------

    def _on_double_click(self, event: tk.Event, text: tk.Text) -> None:
        self.after_idle(lambda: self.lookup_selection(text, quiet=True))

    def word_at_cursor(self, text: tk.Text) -> str:
        try:
            if text.tag_ranges(tk.SEL):
                return text.get(tk.SEL_FIRST, tk.SEL_LAST).strip()
        except tk.TclError:
            pass
        try:
            return text.get("insert wordstart", "insert wordend").strip()
        except tk.TclError:
            return ""

    def lookup_selection(self, text: tk.Text, quiet: bool = False) -> None:
        word = self.word_at_cursor(text)
        if not word or not any(character.isalpha() for character in word):
            if not quiet:
                self.status.configure(text="Select a word to look up.")
            return
        self.show_dictionary()
        self.dictionary_panel.lookup_word(word)

    def _focused_text(self) -> tk.Text:
        widget = self.focus_get()
        return widget if isinstance(widget, tk.Text) else self.source_text

    # -- model ---------------------------------------------------------

    def _load_model_async(self) -> None:
        if self._busy:
            messagebox.showinfo(APP_NAME, "Please wait for the current job to finish.")
            return
        self._set_busy(True, "Loading translation model…")
        self.model_label.configure(text="Model: loading…")

        extra = [Path(self.settings.model_dir)] if self.settings.model_dir else None
        options = self.settings.to_options()

        def work() -> None:
            try:
                directory = model_module.discover_model_dir(extra)
                translator = build_translator(directory, options)
                self.queue.put((MSG_MODEL_READY, translator, directory))
            except Exception as exc:
                self.queue.put((MSG_MODEL_FAILED, exc, traceback.format_exc()))

        self.worker = threading.Thread(target=work, daemon=True)
        self.worker.start()

    def choose_model_folder(self) -> None:
        directory = filedialog.askdirectory(
            title="Select the folder containing the en→hi model")
        if not directory:
            return
        if not model_module.is_model_dir(Path(directory)):
            messagebox.showerror(
                APP_NAME,
                "That folder does not contain a translation model.\n\n"
                "Pick the folder that holds 'model.bin' (or its parent, which "
                "also holds sentencepiece.model).",
            )
            return
        self.settings.model_dir = directory
        self.settings.save()
        self._load_model_async()

    def choose_dictionary_file(self) -> None:
        path = filedialog.askopenfilename(
            title="Select the dictionary database",
            filetypes=[("Dictionary database", "*.sqlite *.db"), ("All files", "*.*")],
        )
        if not path:
            return
        self.settings.dictionary_path = path
        self.settings.save()
        self.dictionary_panel.close()
        self.dictionary_panel.load_error = ""
        if self.dictionary_panel.ensure_loaded():
            self.show_dictionary()
            self.status.configure(text="Dictionary loaded from %s" % Path(path).name)

    # -- actions -------------------------------------------------------

    def translate(self) -> None:
        if self._busy:
            return
        if self.translator is None:
            self.show_model_help()
            return

        text = self.source_text.get("1.0", "end-1c")
        if not text.strip():
            self.status.configure(text="Nothing to translate — type or open a file.")
            return

        self.show_page(PAGE_TRANSLATE)
        self.cancel_event = threading.Event()
        cancel_event = self.cancel_event
        translator = self.translator
        self._started_at = time.monotonic()
        self._set_busy(True, "Translating…")
        self.progress.configure(value=0, maximum=100)

        def progress(done: int, total: int) -> None:
            self.queue.put((MSG_PROGRESS, done, total))

        def work() -> None:
            try:
                result = translator.translate_text(
                    text, progress=progress, cancel=cancel_event)
                self.queue.put((MSG_DONE, result.text, result.report))
            except TranslationCancelled:
                self.queue.put((MSG_CANCELLED,))
            except Exception as exc:
                self.queue.put((MSG_ERROR, exc, traceback.format_exc()))

        self.worker = threading.Thread(target=work, daemon=True)
        self.worker.start()

    def cancel(self) -> None:
        if self.cancel_event is not None and self._busy:
            self.cancel_event.set()
            self.status.configure(text="Cancelling…")

    def open_file(self) -> None:
        path = filedialog.askopenfilename(
            title="Open an English text file",
            initialdir=self.settings.last_directory or None,
            filetypes=[("Text files", "*.txt *.md *.csv *.log *.srt"),
                       ("All files", "*.*")],
        )
        if not path:
            return
        content = read_text_file(Path(path))
        if content is None:
            messagebox.showerror(
                APP_NAME,
                "Could not read that file as text.\n\n"
                "Save it as plain text and try again.",
            )
            return
        self.show_page(PAGE_TRANSLATE)
        self.source_text.delete("1.0", tk.END)
        self.source_text.insert("1.0", content)
        self.settings.last_directory = str(Path(path).parent)
        self.settings.save()
        self._update_counts()
        self.status.configure(text="Opened %s" % Path(path).name)

    def save_translation(self) -> None:
        content = self.target_text.get("1.0", "end-1c")
        if not content.strip():
            messagebox.showinfo(APP_NAME, "There is no translation to save yet.")
            return
        self._save_content(content, "hindi-translation.txt")

    def save_side_by_side(self) -> None:
        source_lines = self.source_text.get("1.0", "end-1c").split("\n")
        target_lines = self.target_text.get("1.0", "end-1c").split("\n")
        if not any(line.strip() for line in target_lines):
            messagebox.showinfo(APP_NAME, "There is no translation to save yet.")
            return
        rows = ["English\tHindi"]
        for index in range(max(len(source_lines), len(target_lines))):
            english = source_lines[index] if index < len(source_lines) else ""
            hindi = target_lines[index] if index < len(target_lines) else ""
            rows.append("%s\t%s" % (english.replace("\t", " "),
                                    hindi.replace("\t", " ")))
        self._save_content("\n".join(rows), "translation-side-by-side.tsv")

    def _save_content(self, content: str, default_name: str) -> None:
        path = filedialog.asksaveasfilename(
            title="Save as",
            defaultextension=Path(default_name).suffix,
            initialfile=default_name,
            initialdir=self.settings.last_directory or None,
            filetypes=[("Text files", "*.txt"), ("Tab separated", "*.tsv"),
                       ("All files", "*.*")],
        )
        if not path:
            return
        try:
            write_text_file(Path(path), content)
        except OSError as exc:
            messagebox.showerror(APP_NAME, "Could not save the file:\n\n%s" % exc)
            return
        self.settings.last_directory = str(Path(path).parent)
        self.settings.save()
        self.status.configure(text="Saved %s" % Path(path).name)

    def copy_output(self) -> None:
        content = self.target_text.get("1.0", "end-1c")
        if not content.strip():
            return
        self.clipboard_clear()
        self.clipboard_append(content)
        self.status.configure(text="Translation copied to the clipboard.")

    def clear_all(self) -> None:
        self.source_text.delete("1.0", tk.END)
        self.target_text.delete("1.0", tk.END)
        self._update_counts()
        self.status.configure(text="Cleared.")

    def adjust_font(self, delta: int) -> None:
        size = max(8, min(22, self.theme.base_size + delta))
        self.theme.set_base_size(size)
        self.settings.font_size = size
        self.settings.save()
        self.dictionary_panel.refresh_fonts()

    def _apply_wrap(self) -> None:
        wrap = tk.WORD if self._wrap_var().get() else tk.NONE
        self.source_text.configure(wrap=wrap)
        self.target_text.configure(wrap=wrap)
        self.settings.wrap_text = self._wrap_var().get()
        self.settings.save()

    def _rotate_tip(self) -> None:
        self._tip_index = (self._tip_index + 1) % len(TIPS)
        try:
            self.tip_label.configure(text=TIPS[self._tip_index])
        except tk.TclError:
            return
        self._tip_job = self.after(15000, self._rotate_tip)

    # -- dialogs -------------------------------------------------------

    def open_settings(self) -> None:
        SettingsDialog(self)

    def show_quick_start(self) -> None:
        QuickStartDialog(self)

    def _maybe_show_quick_start(self) -> None:
        if not self.settings.shown_quick_start:
            self.settings.shown_quick_start = True
            self.settings.save()
            self.show_quick_start()

    def show_model_help(self) -> None:
        searched = "\n".join(
            "    %s" % path
            for path in model_module.candidate_model_dirs(
                [Path(self.settings.model_dir)] if self.settings.model_dir else None)
        )
        messagebox.showinfo(
            "Where is my model?",
            "Anuvad Plus translates entirely offline using a local model.\n\n"
            "Expected layout:\n"
            "    models\\en_hi\\model\\model.bin\n"
            "    models\\en_hi\\sentencepiece.model\n\n"
            "Searched in:\n%s\n\n"
            "If the model is somewhere else, use Tools → Choose model folder."
            % searched,
        )

    def show_about(self) -> None:
        messagebox.showinfo(
            "About " + APP_NAME,
            "%s\nVersion %s\n\n"
            "Offline English to Hindi translation, a bilingual dictionary\n"
            "with pronunciation, and a government administrative glossary.\n"
            "Everything runs on this PC — no internet connection is used.\n\n"
            "Engine: CTranslate2 + SentencePiece\n"
            "Model: Argos Translate en→hi\n"
            "Dictionary: WordNet 3.0, FreeDict eng-hin (GPL-2.0+),\n"
            "CMU Pronouncing Dictionary, and this project's glossary"
            % (APP_TITLE, __version__),
        )

    # -- queue / state -------------------------------------------------

    def _drain_queue(self) -> None:
        try:
            while True:
                self._handle_message(self.queue.get_nowait())
        except queue.Empty:
            pass
        finally:
            self.after(50, self._drain_queue)

    def _handle_message(self, message: tuple) -> None:
        kind = message[0]

        if kind == MSG_MODEL_READY:
            _, translator, directory = message
            if self.translator is not None:
                self.translator.close()
            self.translator = translator
            self.model_dir = directory
            self._set_busy(False, "Ready — type or open a file, then press Translate.")
            self.translate_button.configure(state=tk.NORMAL)
            compute = getattr(translator.backend, "compute_type", "?")
            self.model_label.configure(text="Model: %s (%s)"
                                            % (directory.name, compute))

        elif kind == MSG_MODEL_FAILED:
            _, exc, detail = message
            self.translator = None
            self._set_busy(False, "Model not loaded.")
            self.translate_button.configure(state=tk.DISABLED)
            self.model_label.configure(text="Model: not loaded")
            if is_missing_msvc_runtime(exc):
                messagebox.showerror("One component is missing",
                                     msvc_runtime_message(exc))
            else:
                messagebox.showerror(
                    "Translation model not available",
                    "%s\n\nUse Tools → Choose model folder if it is stored "
                    "elsewhere." % exc,
                )

        elif kind == MSG_PROGRESS:
            _, done, total = message
            if total:
                self.progress.configure(maximum=total, value=done)
                self.progress_label.configure(text="%d / %d sentences" % (done, total))
            else:
                self.progress.configure(value=0)
                self.progress_label.configure(text="")

        elif kind == MSG_DONE:
            _, text, report = message
            self.target_text.delete("1.0", tk.END)
            self.target_text.insert("1.0", text)
            self.target_text.yview_moveto(self.source_text.yview()[0])
            self._set_busy(False, self._summary(report))
            self._update_counts()
            if report.warnings:
                self._show_warnings(report)

        elif kind == MSG_CANCELLED:
            self._set_busy(False, "Cancelled.")

        elif kind == MSG_ERROR:
            _, exc, detail = message
            self._set_busy(False, "Translation failed.")
            messagebox.showerror(
                APP_NAME, "The translation failed:\n\n%s: %s"
                          % (type(exc).__name__, exc))

    def _summary(self, report: Report) -> str:
        elapsed = time.monotonic() - self._started_at
        parts = ["Translated %d sentence%s in %.1fs"
                 % (report.translated, "" if report.translated == 1 else "s",
                    elapsed)]
        if report.cached:
            parts.append("%d from cache" % report.cached)
        if report.retried:
            parts.append("%d retried" % report.retried)
        if report.failed:
            parts.append("%d kept in English" % report.failed)
        return " · ".join(parts) + "."

    def _show_warnings(self, report: Report) -> None:
        preview = "\n".join("• " + line for line in report.warnings[:12])
        if len(report.warnings) > 12:
            preview += "\n… and %d more." % (len(report.warnings) - 12)
        messagebox.showwarning(
            "Some lines were left in English",
            "%d line(s) could not be translated confidently, so the original "
            "English was kept to avoid producing wrong text:\n\n%s"
            % (report.failed, preview),
        )

    def _set_busy(self, busy: bool, status: str) -> None:
        self._busy = busy
        self.status.configure(text=status)
        self.translate_button.configure(
            state=tk.DISABLED if busy or self.translator is None else tk.NORMAL)
        self.cancel_button.configure(state=tk.NORMAL if busy else tk.DISABLED)
        self.configure(cursor="watch" if busy else "")
        if not busy:
            self.progress.configure(value=0)
            self.progress_label.configure(text="")

    def _on_source_modified(self, event: tk.Event) -> None:
        self.source_text.edit_modified(False)
        self._update_counts()

    def _update_counts(self) -> None:
        self.source_counts.configure(
            text=_counts(self.source_text.get("1.0", "end-1c")))
        self.target_counts.configure(
            text=_counts(self.target_text.get("1.0", "end-1c")))

    def _text_event(self, event_name: str) -> None:
        widget = self.focus_get()
        if isinstance(widget, tk.Text):
            widget.event_generate(event_name)

    def _on_close(self) -> None:
        if self._busy and self.cancel_event is not None:
            if not messagebox.askokcancel(
                    APP_NAME, "A translation is still running. Quit anyway?"):
                return
            self.cancel_event.set()
        self.settings.save()
        if self._tip_job is not None:
            try:
                self.after_cancel(self._tip_job)
            except tk.TclError:
                pass
        if self.translator is not None:
            self.translator.close()
        self.dictionary_panel.close()
        self.destroy()


class QuickStartDialog(tk.Toplevel):
    """A short walkthrough, shown on first run and from Help."""

    def __init__(self, app: TranslatorApp):
        super().__init__(app)
        self.app = app
        colours = app.theme.palette
        self.title("Quick start — " + APP_NAME)
        self.transient(app)
        self.resizable(False, False)
        self.configure(background=colours.surface)

        banner = tk.Frame(self, background=colours.sidebar, padx=22, pady=16)
        banner.pack(fill=tk.X)
        tk.Label(banner, text="Welcome to Anuvad Plus", background=colours.sidebar,
                 foreground="#ffffff",
                 font=(app.theme.ui_family, app.theme.base_size + 5,
                       "bold")).pack(anchor=tk.W)
        tk.Label(banner, text="Offline translation, dictionary and pronunciation.",
                 background=colours.sidebar, foreground="#9fb2d4",
                 font=(app.theme.ui_family, app.theme.base_size - 1)).pack(anchor=tk.W)

        body = tk.Frame(self, background=colours.surface, padx=22, pady=16)
        body.pack(fill=tk.BOTH, expand=True)

        for number, (title, text) in enumerate(QUICK_START, start=1):
            row = tk.Frame(body, background=colours.surface)
            row.pack(fill=tk.X, pady=(0, 11))
            tk.Label(row, text=str(number), background=colours.accent,
                     foreground=colours.text_inverse,
                     font=(app.theme.ui_family, app.theme.base_size - 1, "bold"),
                     width=3, pady=1).pack(side=tk.LEFT, anchor=tk.N)
            column = tk.Frame(row, background=colours.surface)
            column.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(12, 0))
            tk.Label(column, text=title, background=colours.surface,
                     foreground=colours.text, anchor=tk.W,
                     font=(app.theme.ui_family, app.theme.base_size,
                           "bold")).pack(fill=tk.X)
            tk.Label(column, text=text, background=colours.surface,
                     foreground=colours.text_muted, justify=tk.LEFT,
                     wraplength=440, anchor=tk.W,
                     font=(app.theme.ui_family,
                           app.theme.base_size - 1)).pack(fill=tk.X)

        footer = tk.Frame(self, background=colours.surface)
        footer.pack(fill=tk.X, padx=22, pady=(0, 18))
        ttk.Button(footer, text="Start using Anuvad Plus", style="Accent.TButton",
                   command=self.destroy).pack(side=tk.RIGHT)
        tk.Label(footer, text="Press F1 any time to see this again.",
                 background=colours.surface, foreground=colours.text_muted,
                 font=(app.theme.ui_family,
                       app.theme.base_size - 2)).pack(side=tk.LEFT)

        self.bind("<Escape>", lambda e: self.destroy())
        self.bind("<Return>", lambda e: self.destroy())
        self.update_idletasks()
        x = app.winfo_rootx() + (app.winfo_width() - self.winfo_width()) // 2
        y = app.winfo_rooty() + 50
        self.geometry("+%d+%d" % (max(x, 0), max(y, 0)))


class SettingsDialog(tk.Toplevel):
    """Quality, performance and appearance settings."""

    def __init__(self, app: TranslatorApp):
        super().__init__(app)
        self.app = app
        colours = app.theme.palette
        self.title("Settings")
        self.transient(app)
        self.resizable(False, False)
        self.grab_set()
        self.configure(background=colours.canvas)

        settings = app.settings
        self.beam = tk.IntVar(value=settings.beam_size)
        self.batch = tk.IntVar(value=settings.max_batch_size)
        self.compute = tk.StringVar(value=settings.compute_type)
        self.threads = tk.IntVar(value=settings.intra_threads)
        self.protect = tk.BooleanVar(value=settings.protect_entities)
        self.hindi_font = tk.StringVar(value=app.theme.devanagari_family)
        self.speech_rate = tk.IntVar(value=settings.speech_rate)

        body = ttk.Frame(self, padding=18)
        body.pack(fill=tk.BOTH, expand=True)

        row = 0
        ttk.Label(body, text="Translation quality",
                  style="Heading.TLabel").grid(row=row, column=0, columnspan=2,
                                               sticky=tk.W, pady=(0, 8))
        row += 1
        ttk.Label(body, text="Beam size (higher = better, slower):").grid(
            row=row, column=0, sticky=tk.W, pady=4)
        ttk.Spinbox(body, from_=1, to=10, textvariable=self.beam, width=6).grid(
            row=row, column=1, sticky=tk.W)
        row += 1
        ttk.Checkbutton(
            body, text="Protect URLs, emails, paths and code from translation",
            variable=self.protect).grid(row=row, column=0, columnspan=2,
                                        sticky=tk.W, pady=4)

        row += 1
        ttk.Separator(body, orient=tk.HORIZONTAL).grid(
            row=row, column=0, columnspan=2, sticky=tk.EW, pady=12)
        row += 1
        ttk.Label(body, text="Performance", style="Heading.TLabel").grid(
            row=row, column=0, columnspan=2, sticky=tk.W, pady=(0, 8))
        row += 1
        ttk.Label(body, text="Sentences per batch:").grid(row=row, column=0,
                                                          sticky=tk.W, pady=4)
        ttk.Spinbox(body, from_=1, to=128, textvariable=self.batch, width=6).grid(
            row=row, column=1, sticky=tk.W)
        row += 1
        ttk.Label(body, text="CPU threads (0 = automatic):").grid(
            row=row, column=0, sticky=tk.W, pady=4)
        ttk.Spinbox(body, from_=0, to=64, textvariable=self.threads, width=6).grid(
            row=row, column=1, sticky=tk.W)
        row += 1
        ttk.Label(body, text="Compute type:").grid(row=row, column=0,
                                                   sticky=tk.W, pady=4)
        values = model_module.supported_compute_types("cpu") or ["int8"]
        ttk.Combobox(body, textvariable=self.compute, values=values, width=16,
                     state="readonly").grid(row=row, column=1, sticky=tk.W)

        row += 1
        ttk.Separator(body, orient=tk.HORIZONTAL).grid(
            row=row, column=0, columnspan=2, sticky=tk.EW, pady=12)
        row += 1
        ttk.Label(body, text="Appearance and speech",
                  style="Heading.TLabel").grid(row=row, column=0, columnspan=2,
                                               sticky=tk.W, pady=(0, 8))
        row += 1
        ttk.Label(body, text="Hindi font:").grid(row=row, column=0, sticky=tk.W,
                                                 pady=4)
        from tkinter import font as tkfont

        families = sorted(
            f for f in tkfont.families(app)
            if any(key in f.lower() for key in ("nirmala", "mangal", "devanagari",
                                                "kokila", "utsaah", "aparajita",
                                                "sans")))
        ttk.Combobox(body, textvariable=self.hindi_font,
                     values=families or ["Nirmala UI"], width=24).grid(
            row=row, column=1, sticky=tk.W)
        row += 1
        ttk.Label(body, text="Speaking speed (-10 slow … 10 fast):").grid(
            row=row, column=0, sticky=tk.W, pady=4)
        ttk.Spinbox(body, from_=-10, to=10, textvariable=self.speech_rate,
                    width=6).grid(row=row, column=1, sticky=tk.W)

        row += 1
        ttk.Label(body,
                  text="Quality and performance changes take effect after the "
                       "model reloads.",
                  style="Muted.TLabel", wraplength=380).grid(
            row=row, column=0, columnspan=2, sticky=tk.W, pady=(14, 0))

        buttons = ttk.Frame(self, padding=(18, 0, 18, 18))
        buttons.pack(fill=tk.X)
        ttk.Button(buttons, text="Cancel", command=self.destroy).pack(side=tk.RIGHT)
        ttk.Button(buttons, text="Save", style="Accent.TButton",
                   command=self._save).pack(side=tk.RIGHT, padx=(0, 8))

        self.bind("<Escape>", lambda e: self.destroy())
        self.update_idletasks()
        self._centre_on_parent()

    def _centre_on_parent(self) -> None:
        parent = self.app
        x = parent.winfo_rootx() + (parent.winfo_width() - self.winfo_width()) // 2
        y = parent.winfo_rooty() + (parent.winfo_height() - self.winfo_height()) // 3
        self.geometry("+%d+%d" % (max(x, 0), max(y, 0)))

    def _save(self) -> None:
        settings = self.app.settings
        needs_reload = (
            settings.beam_size != self.beam.get()
            or settings.max_batch_size != self.batch.get()
            or settings.compute_type != self.compute.get()
            or settings.intra_threads != self.threads.get()
            or settings.protect_entities != self.protect.get()
        )
        settings.beam_size = self.beam.get()
        settings.max_batch_size = self.batch.get()
        settings.compute_type = self.compute.get()
        settings.intra_threads = self.threads.get()
        settings.protect_entities = self.protect.get()
        settings.hindi_font_family = self.hindi_font.get()
        settings.speech_rate = self.speech_rate.get()
        settings.save()

        self.app.theme.set_devanagari_family(settings.hindi_font_family)
        self.app.dictionary_panel.refresh_fonts()
        self.destroy()
        if needs_reload and self.app.translator is not None:
            self.app._load_model_async()


def _counts(text: str) -> str:
    if not text.strip():
        return ""
    lines = text.count("\n") + 1
    words = len(text.split())
    return "%d lines · %d words · %d chars" % (lines, words, len(text))


def main() -> int:
    app = TranslatorApp()
    app.mainloop()
    return 0
