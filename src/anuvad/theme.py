"""The visual design system: one palette, applied to every ttk widget.

Tkinter gives you grey boxes unless you tell it otherwise, so every colour,
font and widget style the application uses is defined here and applied once at
start-up. Screens then ask for a token (``palette.accent``) or a named style
(``"Accent.TButton"``) rather than inventing colours of their own.

Two complete palettes are provided — a light one and a dark one — and the user
can switch between them at any time.
"""

from __future__ import annotations

from dataclasses import dataclass
from tkinter import font as tkfont, ttk
from typing import Dict


@dataclass(frozen=True)
class Palette:
    """Every colour the interface uses, named by role rather than by hue."""

    name: str

    # Surfaces, from furthest back to closest.
    canvas: str          # the window behind everything
    surface: str         # cards and panels
    surface_alt: str     # inset areas: text boxes, lists
    sidebar: str         # the navigation rail
    sidebar_active: str  # the selected item in the rail

    # Text.
    text: str            # primary reading colour
    text_muted: str      # captions, hints, secondary detail
    text_inverse: str    # text on an accent-filled surface

    # Lines.
    border: str
    border_soft: str

    # Brand and meaning.
    accent: str          # primary action
    accent_hover: str
    accent_soft: str     # tinted background for accent chips
    marigold: str        # secondary highlight, used for Hindi
    marigold_soft: str
    success: str
    warning: str
    danger: str
    danger_soft: str

    @property
    def is_dark(self) -> bool:
        return self.name == "dark"


LIGHT = Palette(
    name="light",
    canvas="#eef1f6",
    surface="#ffffff",
    surface_alt="#f7f9fc",
    sidebar="#1b2c52",
    sidebar_active="#2f4b8c",
    text="#16233f",
    text_muted="#5f6a80",
    text_inverse="#ffffff",
    border="#d3dae6",
    border_soft="#e6ebf2",
    accent="#2f4b8c",
    accent_hover="#253d75",
    accent_soft="#e6ecf8",
    marigold="#a4680f",
    marigold_soft="#fbf1de",
    success="#1e7a45",
    warning="#9a6a09",
    danger="#a43521",
    danger_soft="#fbeae6",
)

DARK = Palette(
    name="dark",
    canvas="#10151f",
    surface="#182031",
    surface_alt="#1e2739",
    sidebar="#0c1220",
    sidebar_active="#24365e",
    text="#e8edf7",
    text_muted="#94a1b8",
    text_inverse="#0c1220",
    border="#2c3648",
    border_soft="#222b3c",
    accent="#6f96e8",
    accent_hover="#88a9ee",
    accent_soft="#1d2942",
    marigold="#e0ab5b",
    marigold_soft="#2a2317",
    success="#5cc189",
    warning="#e0b355",
    danger="#ef937f",
    danger_soft="#2e1d19",
)

PALETTES: Dict[str, Palette] = {"light": LIGHT, "dark": DARK}

#: Font families tried in order; the first installed one wins.
UI_FAMILIES = ("Segoe UI Variable Text", "Segoe UI", "Noto Sans", "DejaVu Sans")
MONO_FAMILIES = ("Cascadia Mono", "Consolas", "DejaVu Sans Mono", "Courier New")
DEVANAGARI_FAMILIES = ("Nirmala UI", "Noto Sans Devanagari", "Mangal",
                       "Utsaah", "Aparajita")


def pick_family(root, candidates, fallback: str = "TkDefaultFont") -> str:
    """The first font family from ``candidates`` that is actually installed."""
    try:
        available = {name.lower() for name in tkfont.families(root)}
    except Exception:  # pragma: no cover - depends on the Tk build
        return candidates[0] if candidates else fallback
    for family in candidates:
        if family.lower() in available:
            return family
    return candidates[0] if candidates else fallback


class Theme:
    """Holds the active palette and the fonts, and styles the widgets."""

    def __init__(self, root, mode: str = "light", base_size: int = 11,
                 devanagari_family: str = ""):
        self.root = root
        self.palette = PALETTES.get(mode, LIGHT)
        self.style = ttk.Style(root)

        self.ui_family = pick_family(root, UI_FAMILIES)
        self.mono_family = pick_family(root, MONO_FAMILIES)
        self.devanagari_family = devanagari_family or pick_family(
            root, DEVANAGARI_FAMILIES)

        self.base_size = base_size
        self.body = tkfont.Font(family=self.ui_family, size=base_size)
        self.body_bold = tkfont.Font(family=self.ui_family, size=base_size,
                                     weight="bold")
        self.small = tkfont.Font(family=self.ui_family, size=base_size - 2)
        self.small_bold = tkfont.Font(family=self.ui_family, size=base_size - 2,
                                      weight="bold")
        self.heading = tkfont.Font(family=self.ui_family, size=base_size + 3,
                                   weight="bold")
        self.display = tkfont.Font(family=self.ui_family, size=base_size + 12,
                                   weight="bold")
        self.mono = tkfont.Font(family=self.mono_family, size=base_size - 1)
        self.editor = tkfont.Font(family=self.mono_family, size=base_size + 1)
        self.hindi = tkfont.Font(family=self.devanagari_family, size=base_size + 3)
        self.hindi_big = tkfont.Font(family=self.devanagari_family,
                                     size=base_size + 7)
        self.hindi_editor = tkfont.Font(family=self.devanagari_family,
                                        size=base_size + 3)

        self.apply()

    # -- switching -----------------------------------------------------

    def set_mode(self, mode: str) -> None:
        self.palette = PALETTES.get(mode, LIGHT)
        self.apply()

    def toggle_mode(self) -> str:
        self.set_mode("light" if self.palette.is_dark else "dark")
        return self.palette.name

    def set_base_size(self, size: int) -> None:
        self.base_size = max(8, min(22, size))
        self.body.configure(size=self.base_size)
        self.body_bold.configure(size=self.base_size)
        self.small.configure(size=max(7, self.base_size - 2))
        self.small_bold.configure(size=max(7, self.base_size - 2))
        self.heading.configure(size=self.base_size + 3)
        self.display.configure(size=self.base_size + 12)
        self.mono.configure(size=max(7, self.base_size - 1))
        self.editor.configure(size=self.base_size + 1)
        self.hindi.configure(size=self.base_size + 3)
        self.hindi_big.configure(size=self.base_size + 7)
        self.hindi_editor.configure(size=self.base_size + 3)

    def set_devanagari_family(self, family: str) -> None:
        if not family:
            return
        self.devanagari_family = family
        for font in (self.hindi, self.hindi_big, self.hindi_editor):
            font.configure(family=family)

    # -- styling -------------------------------------------------------

    def apply(self) -> None:
        """Push the palette into every ttk style the application uses."""
        colours = self.palette
        style = self.style

        for candidate in ("clam", "alt", "default"):
            if candidate in style.theme_names():
                try:
                    style.theme_use(candidate)
                    break
                except Exception:  # pragma: no cover
                    continue

        try:
            self.root.configure(background=colours.canvas)
        except Exception:  # pragma: no cover
            pass

        style.configure(".", background=colours.canvas, foreground=colours.text,
                        font=self.body, borderwidth=0, focuscolor=colours.accent)

        style.configure("TFrame", background=colours.canvas)
        style.configure("Card.TFrame", background=colours.surface,
                        relief="flat", borderwidth=1)
        style.configure("Inset.TFrame", background=colours.surface_alt)
        style.configure("Sidebar.TFrame", background=colours.sidebar)

        style.configure("TLabel", background=colours.canvas,
                        foreground=colours.text, font=self.body)
        style.configure("Card.TLabel", background=colours.surface,
                        foreground=colours.text)
        style.configure("Muted.TLabel", background=colours.canvas,
                        foreground=colours.text_muted, font=self.small)
        style.configure("CardMuted.TLabel", background=colours.surface,
                        foreground=colours.text_muted, font=self.small)
        style.configure("Heading.TLabel", background=colours.canvas,
                        foreground=colours.text, font=self.heading)
        style.configure("CardHeading.TLabel", background=colours.surface,
                        foreground=colours.text, font=self.heading)
        style.configure("Eyebrow.TLabel", background=colours.canvas,
                        foreground=colours.text_muted, font=self.small_bold)
        style.configure("Status.TLabel", background=colours.surface,
                        foreground=colours.text_muted, font=self.small,
                        padding=(12, 6))

        # Buttons -------------------------------------------------------
        style.configure("TButton", background=colours.surface,
                        foreground=colours.text, font=self.body,
                        padding=(14, 8), relief="flat", borderwidth=1)
        style.map("TButton",
                  background=[("active", colours.surface_alt),
                              ("disabled", colours.surface)],
                  foreground=[("disabled", colours.text_muted)],
                  bordercolor=[("!disabled", colours.border)])

        style.configure("Accent.TButton", background=colours.accent,
                        foreground=colours.text_inverse, font=self.body_bold,
                        padding=(20, 10), relief="flat", borderwidth=0)
        style.map("Accent.TButton",
                  background=[("active", colours.accent_hover),
                              ("disabled", colours.border)],
                  foreground=[("disabled", colours.text_muted)])

        style.configure("Ghost.TButton", background=colours.surface,
                        foreground=colours.accent, font=self.body,
                        padding=(12, 7), relief="flat", borderwidth=0)
        style.map("Ghost.TButton",
                  background=[("active", colours.accent_soft)],
                  foreground=[("disabled", colours.text_muted)])

        style.configure("Chip.TButton", background=colours.accent_soft,
                        foreground=colours.accent, font=self.small,
                        padding=(10, 4), relief="flat", borderwidth=0)
        style.map("Chip.TButton", background=[("active", colours.accent)],
                  foreground=[("active", colours.text_inverse)])

        style.configure("Speak.TButton", background=colours.marigold_soft,
                        foreground=colours.marigold, font=self.small_bold,
                        padding=(12, 6), relief="flat", borderwidth=0)
        style.map("Speak.TButton", background=[("active", colours.marigold)],
                  foreground=[("active", colours.text_inverse)])

        # Inputs --------------------------------------------------------
        style.configure("TEntry", fieldbackground=colours.surface_alt,
                        foreground=colours.text, insertcolor=colours.text,
                        bordercolor=colours.border, lightcolor=colours.border,
                        darkcolor=colours.border, padding=8, relief="flat")
        style.map("TEntry", bordercolor=[("focus", colours.accent)])

        style.configure("Search.TEntry", fieldbackground=colours.surface,
                        foreground=colours.text, insertcolor=colours.text,
                        padding=10)

        style.configure("TCombobox", fieldbackground=colours.surface_alt,
                        background=colours.surface_alt, foreground=colours.text,
                        arrowcolor=colours.text_muted,
                        bordercolor=colours.border, padding=6, relief="flat")
        style.map("TCombobox", fieldbackground=[("readonly", colours.surface_alt)],
                  bordercolor=[("focus", colours.accent)])

        style.configure("TSpinbox", fieldbackground=colours.surface_alt,
                        foreground=colours.text, arrowcolor=colours.text_muted,
                        bordercolor=colours.border, padding=6, relief="flat")

        style.configure("TCheckbutton", background=colours.canvas,
                        foreground=colours.text, font=self.body,
                        focuscolor=colours.accent)
        style.map("TCheckbutton", background=[("active", colours.canvas)])
        style.configure("Card.TCheckbutton", background=colours.surface,
                        foreground=colours.text)
        style.map("Card.TCheckbutton", background=[("active", colours.surface)])

        # Structure -----------------------------------------------------
        style.configure("TSeparator", background=colours.border)
        style.configure("TPanedwindow", background=colours.canvas)
        style.configure("Sash", sashthickness=8, gripcount=0)

        style.configure("TProgressbar", background=colours.accent,
                        troughcolor=colours.surface_alt, borderwidth=0,
                        thickness=6)

        style.configure("Vertical.TScrollbar", background=colours.border_soft,
                        troughcolor=colours.surface_alt, borderwidth=0,
                        arrowcolor=colours.text_muted, relief="flat",
                        arrowsize=12)
        style.map("Vertical.TScrollbar",
                  background=[("active", colours.border)])
        style.configure("Horizontal.TScrollbar", background=colours.border_soft,
                        troughcolor=colours.surface_alt, borderwidth=0,
                        arrowcolor=colours.text_muted, relief="flat",
                        arrowsize=12)

        # The notebook is the page container, but the sidebar drives it, so
        # its own tab strip is hidden.
        style.layout("Tabless.TNotebook.Tab", [])
        style.configure("Tabless.TNotebook", background=colours.canvas,
                        borderwidth=0, tabmargins=0)

    # -- helpers for plain Tk widgets ----------------------------------

    def text_widget_options(self, inset: bool = True) -> dict:
        """Colours for a ``tk.Text``, which ttk cannot style."""
        colours = self.palette
        return {
            "background": colours.surface_alt if inset else colours.surface,
            "foreground": colours.text,
            "insertbackground": colours.text,
            "selectbackground": colours.accent,
            "selectforeground": colours.text_inverse,
            "highlightthickness": 1,
            "highlightbackground": colours.border,
            "highlightcolor": colours.accent,
            "borderwidth": 0,
            "relief": "flat",
        }

    def listbox_options(self) -> dict:
        colours = self.palette
        return {
            "background": colours.surface_alt,
            "foreground": colours.text,
            "selectbackground": colours.accent,
            "selectforeground": colours.text_inverse,
            "highlightthickness": 1,
            "highlightbackground": colours.border,
            "borderwidth": 0,
            "relief": "flat",
            "activestyle": "none",
        }
