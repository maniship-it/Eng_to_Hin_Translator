"""Anuvad Plus launcher — run the application straight from this folder.

Nothing is installed. The bundle carries its libraries in ``lib`` and the
application in ``src``; this script puts both on the import path and starts
Anuvad Plus. It only needs Python itself.

    python AnuvadPlus.py            start the window
    python AnuvadPlus.py --check    check the installation
    python AnuvadPlus.py --help     every command line option
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent


def _prepare_path() -> None:
    """Put the bundled libraries and the application on sys.path."""
    for name in ("lib", "src"):
        folder = BASE / name
        if folder.is_dir() and str(folder) not in sys.path:
            sys.path.insert(0, str(folder))

    # Windows needs DLL directories declared explicitly since Python 3.8.
    if os.name == "nt" and hasattr(os, "add_dll_directory"):
        for folder in (BASE / "lib").glob("*"):
            if folder.is_dir():
                try:
                    os.add_dll_directory(str(folder))
                except (OSError, AttributeError):
                    pass


def _report(title: str, message: str) -> None:
    """Show a problem in a dialog when possible, on the console otherwise."""
    print("%s\n\n%s" % (title, message))
    try:
        import tkinter as tk
        from tkinter import messagebox

        root = tk.Tk()
        root.withdraw()
        messagebox.showerror(title, message)
        root.destroy()
    except Exception:
        try:
            input("\nPress Enter to close this window.")
        except (EOFError, KeyboardInterrupt):
            pass


def main() -> int:
    _prepare_path()

    try:
        from anuvad.__main__ import main as app_main
    except ImportError as exc:
        _report(
            "Anuvad Plus cannot start",
            "The application files could not be loaded.\n\n"
            "Make sure the whole Anuvad Plus folder was copied, including the 'src' "
            "and 'lib' folders.\n\nTechnical detail: %s" % exc,
        )
        return 2

    try:
        return app_main()
    except ImportError as exc:
        try:
            from anuvad.runtime import is_missing_msvc_runtime, msvc_runtime_message
        except ImportError:
            _report("Anuvad Plus cannot start", str(exc))
            return 2
        if is_missing_msvc_runtime(exc):
            _report("One component is missing", msvc_runtime_message(exc))
            return 3
        _report("Anuvad Plus cannot start", str(exc))
        return 2


if __name__ == "__main__":
    sys.exit(main())
