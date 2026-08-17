"""Tkinter desktop front-end for the offline English-to-Hindi translator.

The model is loaded, and every translation runs, on a worker thread; the UI
thread only ever drains a queue, so the window stays responsive on long
documents and the user can cancel a run in progress.
"""

from __future__ import annotations

import queue
import threading
import time
import tkinter as tk
import traceback
from pathlib import Path
from tkinter import filedialog, font as tkfont, messagebox, ttk
from typing import Optional

from . import model as model_module
from .config import Settings
from .textio import read_text_file, write_text_file
from .translator import (
    Report,
    TranslationCancelled,
    Translator,
    build_translator,
)
from .version import __version__

APP_NAME = "English → Hindi Translator"

# Messages passed from the worker thread to the UI thread.
MSG_MODEL_READY = "model_ready"
MSG_MODEL_FAILED = "model_failed"
MSG_PROGRESS = "progress"
MSG_DONE = "done"
MSG_ERROR = "error"
MSG_CANCELLED = "cancelled"


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

        self.title(APP_NAME)
        self.geometry("1100x700")
        self.minsize(760, 480)
        self._set_icon()

        self._init_style()
        self._build_menu()
        self._build_toolbar()
        self._build_panes()
        self._build_statusbar()
        self._bind_keys()

        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.after(50, self._drain_queue)
        self._load_model_async()

    # -- construction --------------------------------------------------

    def _set_icon(self) -> None:
        # A tiny embedded icon avoids shipping a binary asset.
        try:
            icon = tk.PhotoImage(width=16, height=16)
            icon.put("#1f6feb", to=(0, 0, 16, 16))
            icon.put("#ffffff", to=(3, 3, 13, 6))
            icon.put("#ffffff", to=(6, 6, 10, 13))
            self.iconphoto(True, icon)
            self._icon = icon  # keep a reference
        except tk.TclError:
            pass

    def _init_style(self) -> None:
        self.style = ttk.Style(self)
        for theme in ("vista", "winnative", "clam", "default"):
            if theme in self.style.theme_names():
                try:
                    self.style.theme_use(theme)
                    break
                except tk.TclError:
                    continue
        self.style.configure("Heading.TLabel", font=("Segoe UI", 10, "bold"))
        self.style.configure("Status.TLabel", padding=(6, 2))
        self.style.configure("Accent.TButton", font=("Segoe UI", 9, "bold"))

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
        view_menu.add_checkbutton(label="Wrap lines", variable=self._wrap_var(),
                                  command=self._apply_wrap)
        view_menu.add_checkbutton(label="Synchronised scrolling",
                                  variable=self._sync_scroll)
        menubar.add_cascade(label="View", menu=view_menu)

        tools_menu = tk.Menu(menubar, tearoff=0)
        tools_menu.add_command(label="Settings…", command=self.open_settings)
        tools_menu.add_command(label="Choose model folder…",
                               command=self.choose_model_folder)
        tools_menu.add_command(label="Reload model", command=self._load_model_async)
        menubar.add_cascade(label="Tools", menu=tools_menu)

        help_menu = tk.Menu(menubar, tearoff=0)
        help_menu.add_command(label="Where is my model?", command=self.show_model_help)
        help_menu.add_command(label="About", command=self.show_about)
        menubar.add_cascade(label="Help", menu=help_menu)

        self.config(menu=menubar)

    def _wrap_var(self) -> tk.BooleanVar:
        if not hasattr(self, "_wrap_variable"):
            self._wrap_variable = tk.BooleanVar(value=self.settings.wrap_text)
        return self._wrap_variable

    def _build_toolbar(self) -> None:
        bar = ttk.Frame(self, padding=(8, 6))
        bar.pack(side=tk.TOP, fill=tk.X)

        self.translate_button = ttk.Button(
            bar, text="Translate  (Ctrl+Enter)", style="Accent.TButton",
            command=self.translate, state=tk.DISABLED,
        )
        self.translate_button.pack(side=tk.LEFT)

        self.cancel_button = ttk.Button(
            bar, text="Cancel", command=self.cancel, state=tk.DISABLED
        )
        self.cancel_button.pack(side=tk.LEFT, padx=(6, 0))

        ttk.Separator(bar, orient=tk.VERTICAL).pack(
            side=tk.LEFT, fill=tk.Y, padx=10, pady=2
        )

        ttk.Button(bar, text="Open file", command=self.open_file).pack(side=tk.LEFT)
        ttk.Button(bar, text="Save translation", command=self.save_translation).pack(
            side=tk.LEFT, padx=(6, 0)
        )
        ttk.Button(bar, text="Copy result", command=self.copy_output).pack(
            side=tk.LEFT, padx=(6, 0)
        )
        ttk.Button(bar, text="Clear", command=self.clear_all).pack(
            side=tk.LEFT, padx=(6, 0)
        )

        self.progress = ttk.Progressbar(bar, mode="determinate", length=180)
        self.progress.pack(side=tk.RIGHT)
        self.progress_label = ttk.Label(bar, text="")
        self.progress_label.pack(side=tk.RIGHT, padx=(0, 8))

    def _build_panes(self) -> None:
        container = ttk.Panedwindow(self, orient=tk.HORIZONTAL)
        container.pack(fill=tk.BOTH, expand=True, padx=8, pady=(0, 6))

        source_frame = ttk.Frame(container)
        target_frame = ttk.Frame(container)
        container.add(source_frame, weight=1)
        container.add(target_frame, weight=1)

        base_size = self.settings.font_size
        self.source_font = tkfont.Font(family="Consolas", size=base_size)
        self.target_font = tkfont.Font(
            family=self.settings.hindi_font_family or "Nirmala UI", size=base_size + 1
        )
        # Fall back if the configured Devanagari font is not installed.
        if self.target_font.actual("family").lower() not in {
            (self.settings.hindi_font_family or "").lower()
        }:
            for family in ("Nirmala UI", "Mangal", "Noto Sans Devanagari",
                           "Kokila", "Utsaah", "FreeSans"):
                if family in tkfont.families(self):
                    self.target_font.configure(family=family)
                    break

        header = ttk.Frame(source_frame)
        header.pack(fill=tk.X)
        ttk.Label(header, text="English (source)", style="Heading.TLabel").pack(
            side=tk.LEFT, pady=(0, 4)
        )
        self.source_counts = ttk.Label(header, text="")
        self.source_counts.pack(side=tk.RIGHT)

        self.source_text = self._make_text(source_frame, self.source_font)
        self.source_text.bind("<<Modified>>", self._on_source_modified)

        header2 = ttk.Frame(target_frame)
        header2.pack(fill=tk.X)
        ttk.Label(header2, text="Hindi (translation)", style="Heading.TLabel").pack(
            side=tk.LEFT, pady=(0, 4)
        )
        self.target_counts = ttk.Label(header2, text="")
        self.target_counts.pack(side=tk.RIGHT)

        self.target_text = self._make_text(target_frame, self.target_font)
        self.target_text.configure(background="#fbfbfd")

        self._apply_wrap()

    def _make_text(self, parent: ttk.Frame, font: tkfont.Font) -> tk.Text:
        frame = ttk.Frame(parent)
        frame.pack(fill=tk.BOTH, expand=True)

        text = tk.Text(
            frame, wrap=tk.WORD, undo=True, font=font, relief=tk.FLAT,
            borderwidth=1, highlightthickness=1, highlightbackground="#c8c8d0",
            highlightcolor="#1f6feb", padx=8, pady=6, spacing1=1, spacing3=3,
            insertwidth=2, tabs="1c",
        )
        yscroll = ttk.Scrollbar(frame, orient=tk.VERTICAL)
        xscroll = ttk.Scrollbar(frame, orient=tk.HORIZONTAL)

        yscroll.configure(command=lambda *args: self._scroll_y(text, *args))
        xscroll.configure(command=text.xview)
        text.configure(
            yscrollcommand=lambda first, last: self._on_text_scrolled(
                text, yscroll, first, last
            ),
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

    def _build_statusbar(self) -> None:
        bar = ttk.Frame(self, relief=tk.GROOVE)
        bar.pack(side=tk.BOTTOM, fill=tk.X)
        self.status = ttk.Label(bar, text="Starting…", style="Status.TLabel",
                                anchor=tk.W)
        self.status.pack(side=tk.LEFT, fill=tk.X, expand=True)
        self.model_label = ttk.Label(bar, text="", style="Status.TLabel")
        self.model_label.pack(side=tk.RIGHT)

    def _bind_keys(self) -> None:
        self.bind("<Control-Return>", lambda e: self.translate())
        self.bind("<Control-o>", lambda e: (self.open_file(), "break")[1])
        self.bind("<Control-s>", lambda e: (self.save_translation(), "break")[1])
        self.bind("<Control-q>", lambda e: self._on_close())
        self.bind("<Control-plus>", lambda e: self.adjust_font(1))
        self.bind("<Control-equal>", lambda e: self.adjust_font(1))
        self.bind("<Control-minus>", lambda e: self.adjust_font(-1))
        self.bind("<Escape>", lambda e: self.cancel())

    # -- scrolling -----------------------------------------------------

    def _scroll_y(self, text: tk.Text, *args) -> None:
        text.yview(*args)
        if self._sync_scroll.get():
            other = self._other_text(text)
            other.yview_moveto(text.yview()[0])

    def _on_text_scrolled(self, text: tk.Text, scrollbar: ttk.Scrollbar,
                          first: str, last: str) -> None:
        scrollbar.set(first, last)

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
            except Exception as exc:  # surfaced to the user verbatim
                self.queue.put((MSG_MODEL_FAILED, exc, traceback.format_exc()))

        self.worker = threading.Thread(target=work, daemon=True)
        self.worker.start()

    def choose_model_folder(self) -> None:
        directory = filedialog.askdirectory(
            title="Select the folder containing the en→hi model"
        )
        if not directory:
            return
        if not model_module.is_model_dir(Path(directory)):
            messagebox.showerror(
                APP_NAME,
                "That folder does not contain a CTranslate2 model.\n\n"
                "Pick the folder that holds 'model.bin' (or its parent, which "
                "also holds sentencepiece.model).",
            )
            return
        self.settings.model_dir = directory
        self.settings.save()
        self._load_model_async()

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
                    text, progress=progress, cancel=cancel_event
                )
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
            filetypes=[
                ("Text files", "*.txt *.md *.csv *.log *.srt"),
                ("All files", "*.*"),
            ],
        )
        if not path:
            return
        content = read_text_file(Path(path))
        if content is None:
            messagebox.showerror(
                APP_NAME,
                "Could not read that file as text.\n\n"
                "Save it as UTF-8 plain text and try again.",
            )
            return
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
            rows.append("%s\t%s" % (english.replace("\t", " "), hindi.replace("\t", " ")))
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
        size = max(8, min(30, self.source_font.cget("size") + delta))
        self.source_font.configure(size=size)
        self.target_font.configure(size=size + 1)
        self.settings.font_size = size
        self.settings.save()

    def _apply_wrap(self) -> None:
        wrap = tk.WORD if self._wrap_var().get() else tk.NONE
        self.source_text.configure(wrap=wrap)
        self.target_text.configure(wrap=wrap)
        self.settings.wrap_text = self._wrap_var().get()
        self.settings.save()

    # -- dialogs -------------------------------------------------------

    def open_settings(self) -> None:
        SettingsDialog(self)

    def show_model_help(self) -> None:
        searched = "\n".join(
            "    %s" % path
            for path in model_module.candidate_model_dirs(
                [Path(self.settings.model_dir)] if self.settings.model_dir else None
            )
        )
        messagebox.showinfo(
            "Where is my model?",
            "This app translates entirely offline using a local neural model.\n\n"
            "Expected layout:\n"
            "    models\\en_hi\\model\\model.bin\n"
            "    models\\en_hi\\sentencepiece.model\n\n"
            "Searched in:\n%s\n\n"
            "If the model is somewhere else, use Tools → Choose model folder.\n"
            "To download it on an internet-connected PC, run:\n"
            "    python tools\\fetch_model.py" % searched,
        )

    def show_about(self) -> None:
        messagebox.showinfo(
            "About " + APP_NAME,
            "%s\nVersion %s\n\n"
            "Offline neural machine translation, English to Hindi.\n"
            "Runs entirely on this PC — no internet connection is used.\n\n"
            "Engine: CTranslate2 + SentencePiece\n"
            "Model: Argos Translate en→hi (CC0 / MIT components)"
            % (APP_NAME, __version__),
        )

    # -- queue / state -------------------------------------------------

    def _drain_queue(self) -> None:
        try:
            while True:
                message = self.queue.get_nowait()
                self._handle_message(message)
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
            self._set_busy(False, "Model ready — type or open a file, then press Translate.")
            self.translate_button.configure(state=tk.NORMAL)
            compute = getattr(translator.backend, "compute_type", "?")
            self.model_label.configure(text="Model: %s (%s)" % (directory.name, compute))

        elif kind == MSG_MODEL_FAILED:
            _, exc, detail = message
            self.translator = None
            self._set_busy(False, "Model not loaded.")
            self.translate_button.configure(state=tk.DISABLED)
            self.model_label.configure(text="Model: not loaded")
            messagebox.showerror(
                "Translation model not available",
                "%s\n\nUse Tools → Choose model folder if it is stored elsewhere."
                % exc,
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
            self.progress.configure(value=0)
            self.progress_label.configure(text="")

        elif kind == MSG_ERROR:
            _, exc, detail = message
            self._set_busy(False, "Translation failed.")
            messagebox.showerror(
                APP_NAME, "The translation failed:\n\n%s: %s" % (type(exc).__name__, exc)
            )

    def _summary(self, report: Report) -> str:
        elapsed = time.monotonic() - self._started_at
        parts = [
            "Translated %d sentence%s in %.1fs"
            % (report.translated, "" if report.translated == 1 else "s", elapsed)
        ]
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
            state=tk.DISABLED if busy or self.translator is None else tk.NORMAL
        )
        self.cancel_button.configure(state=tk.NORMAL if busy else tk.DISABLED)
        self.configure(cursor="watch" if busy else "")
        if not busy:
            self.progress.configure(value=0)
            self.progress_label.configure(text="")

    def _on_source_modified(self, event: tk.Event) -> None:
        self.source_text.edit_modified(False)
        self._update_counts()

    def _update_counts(self) -> None:
        source = self.source_text.get("1.0", "end-1c")
        target = self.target_text.get("1.0", "end-1c")
        self.source_counts.configure(text=_counts(source))
        self.target_counts.configure(text=_counts(target))

    def _text_event(self, event_name: str) -> None:
        widget = self.focus_get()
        if isinstance(widget, tk.Text):
            widget.event_generate(event_name)

    def _on_close(self) -> None:
        if self._busy and self.cancel_event is not None:
            if not messagebox.askokcancel(
                APP_NAME, "A translation is still running. Quit anyway?"
            ):
                return
            self.cancel_event.set()
        self.settings.save()
        if self.translator is not None:
            self.translator.close()
        self.destroy()


class SettingsDialog(tk.Toplevel):
    """Quality and performance settings, applied by reloading the model."""

    def __init__(self, app: TranslatorApp):
        super().__init__(app)
        self.app = app
        self.title("Settings")
        self.transient(app)
        self.resizable(False, False)
        self.grab_set()

        settings = app.settings
        self.beam = tk.IntVar(value=settings.beam_size)
        self.batch = tk.IntVar(value=settings.max_batch_size)
        self.compute = tk.StringVar(value=settings.compute_type)
        self.threads = tk.IntVar(value=settings.intra_threads)
        self.protect = tk.BooleanVar(value=settings.protect_entities)
        self.hindi_font = tk.StringVar(value=settings.hindi_font_family)

        body = ttk.Frame(self, padding=14)
        body.pack(fill=tk.BOTH, expand=True)

        row = 0
        ttk.Label(body, text="Translation quality", style="Heading.TLabel").grid(
            row=row, column=0, columnspan=2, sticky=tk.W, pady=(0, 6)
        )
        row += 1
        ttk.Label(body, text="Beam size (higher = better, slower):").grid(
            row=row, column=0, sticky=tk.W, pady=3
        )
        ttk.Spinbox(body, from_=1, to=10, textvariable=self.beam, width=6).grid(
            row=row, column=1, sticky=tk.W
        )
        row += 1
        ttk.Checkbutton(
            body,
            text="Protect URLs, emails, paths and code from translation",
            variable=self.protect,
        ).grid(row=row, column=0, columnspan=2, sticky=tk.W, pady=3)

        row += 1
        ttk.Separator(body, orient=tk.HORIZONTAL).grid(
            row=row, column=0, columnspan=2, sticky=tk.EW, pady=10
        )
        row += 1
        ttk.Label(body, text="Performance", style="Heading.TLabel").grid(
            row=row, column=0, columnspan=2, sticky=tk.W, pady=(0, 6)
        )
        row += 1
        ttk.Label(body, text="Sentences per batch:").grid(
            row=row, column=0, sticky=tk.W, pady=3
        )
        ttk.Spinbox(body, from_=1, to=128, textvariable=self.batch, width=6).grid(
            row=row, column=1, sticky=tk.W
        )
        row += 1
        ttk.Label(body, text="CPU threads (0 = automatic):").grid(
            row=row, column=0, sticky=tk.W, pady=3
        )
        ttk.Spinbox(body, from_=0, to=64, textvariable=self.threads, width=6).grid(
            row=row, column=1, sticky=tk.W
        )
        row += 1
        ttk.Label(body, text="Compute type:").grid(row=row, column=0, sticky=tk.W, pady=3)
        values = model_module.supported_compute_types("cpu") or ["int8"]
        ttk.Combobox(
            body, textvariable=self.compute, values=values, width=16, state="readonly"
        ).grid(row=row, column=1, sticky=tk.W)

        row += 1
        ttk.Separator(body, orient=tk.HORIZONTAL).grid(
            row=row, column=0, columnspan=2, sticky=tk.EW, pady=10
        )
        row += 1
        ttk.Label(body, text="Hindi font:").grid(row=row, column=0, sticky=tk.W, pady=3)
        families = sorted(
            f for f in tkfont.families(app)
            if any(k in f.lower() for k in ("nirmala", "mangal", "devanagari",
                                            "kokila", "utsaah", "aparajita", "sans"))
        )
        ttk.Combobox(
            body, textvariable=self.hindi_font, values=families or ["Nirmala UI"],
            width=24,
        ).grid(row=row, column=1, sticky=tk.W)

        row += 1
        ttk.Label(
            body,
            text="Quality and performance changes take effect after the model reloads.",
            foreground="#555555", wraplength=380,
        ).grid(row=row, column=0, columnspan=2, sticky=tk.W, pady=(12, 0))

        buttons = ttk.Frame(self, padding=(14, 0, 14, 14))
        buttons.pack(fill=tk.X)
        ttk.Button(buttons, text="Cancel", command=self.destroy).pack(side=tk.RIGHT)
        ttk.Button(buttons, text="Save", command=self._save).pack(
            side=tk.RIGHT, padx=(0, 6)
        )

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
        settings.save()

        self.app.target_font.configure(family=settings.hindi_font_family)
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
