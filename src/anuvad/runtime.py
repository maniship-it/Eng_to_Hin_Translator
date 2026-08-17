"""Checks for the things Anuvad Plus needs from the machine it runs on.

The one dependency that is not carried in the bundle is Microsoft's C++
runtime.  CTranslate2 links against ``MSVCP140.dll`` and
``VCRUNTIME140_1.dll``, and the Python installer does not provide them --
Python itself ships only ``vcruntime140.dll``.  Most Windows machines already
have the full runtime because countless applications install it, but a freshly
imaged PC may not, and the failure it produces ("DLL load failed while
importing _ext") tells the user nothing useful.

This module turns that into a plain instruction.
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

#: Name of the installer carried in the offline bundle.
VC_REDIST_FILENAME = "vc_redist.x64.exe"

#: Where Microsoft publishes it, for anyone rebuilding the bundle.
VC_REDIST_URL = "https://aka.ms/vs/17/release/vc_redist.x64.exe"

_MISSING_RUNTIME_MARKERS = (
    "dll load failed",
    "msvcp140",
    "vcruntime140",
)


@dataclass
class CheckResult:
    """The outcome of one dependency check."""

    name: str
    ok: bool
    detail: str = ""
    remedy: str = ""


def is_missing_msvc_runtime(exc: BaseException) -> bool:
    """True if ``exc`` looks like the missing Microsoft C++ runtime."""
    if os.name != "nt":
        return False
    if not isinstance(exc, ImportError):
        return False
    message = str(exc).lower()
    return any(marker in message for marker in _MISSING_RUNTIME_MARKERS)


def find_vc_redist(start: Optional[Path] = None) -> Optional[Path]:
    """Locate the bundled ``vc_redist.x64.exe``, if it travelled with us."""
    roots: List[Path] = []
    if start is not None:
        roots.append(Path(start))
    roots.append(Path(sys.argv[0]).resolve().parent if sys.argv[0] else Path.cwd())
    try:
        from .model import app_root

        roots.append(app_root())
    except Exception:  # pragma: no cover - defensive
        pass
    roots.append(Path.cwd())

    seen = set()
    for root in roots:
        for candidate in (root / VC_REDIST_FILENAME,
                          root / "runtime" / VC_REDIST_FILENAME,
                          root.parent / VC_REDIST_FILENAME):
            key = str(candidate)
            if key in seen:
                continue
            seen.add(key)
            try:
                if candidate.is_file():
                    return candidate
            except OSError:
                continue
    return None


def msvc_runtime_message(exc: Optional[BaseException] = None) -> str:
    """A message a non-technical user can act on."""
    installer = find_vc_redist()
    lines = [
        "This PC is missing the Microsoft Visual C++ runtime, which the "
        "translation engine needs.",
        "",
        "It is a one-time, one-minute fix:",
    ]
    if installer is not None:
        lines += [
            "",
            "    1. Open this folder:  %s" % installer.parent,
            "    2. Double-click       %s" % installer.name,
            "    3. Accept the prompt, then start Anuvad Plus again.",
            "",
            "No internet connection is needed — the installer is already here.",
        ]
    else:
        lines += [
            "",
            "    1. On a PC with internet, download:",
            "         %s" % VC_REDIST_URL,
            "    2. Copy that file to this PC and run it.",
            "    3. Start Anuvad Plus again.",
            "",
            "It is a free, standard Microsoft component. If you rebuild the "
            "offline bundle it will be included automatically.",
        ]
    if exc is not None:
        lines += ["", "Technical detail: %s" % exc]
    return "\n".join(lines)


def check_dependencies() -> List[CheckResult]:
    """Check everything the application needs in order to start."""
    results: List[CheckResult] = []

    results.append(CheckResult(
        "Python",
        sys.version_info >= (3, 9),
        detail="%d.%d.%d" % sys.version_info[:3],
        remedy="Install 64-bit Python 3.13 from python.org.",
    ))

    try:
        import tkinter  # noqa: F401

        results.append(CheckResult("tkinter (window toolkit)", True,
                                   detail="available"))
    except ImportError as exc:
        results.append(CheckResult(
            "tkinter (window toolkit)", False, detail=str(exc),
            remedy="Re-run the Python installer and tick 'tcl/tk and IDLE'.",
        ))

    for name in ("ctranslate2", "sentencepiece"):
        try:
            module = __import__(name)
            results.append(CheckResult(
                name, True, detail=getattr(module, "__version__", "installed")
            ))
        except ImportError as exc:
            if is_missing_msvc_runtime(exc):
                results.append(CheckResult(
                    name, False, detail="missing Microsoft C++ runtime",
                    remedy=msvc_runtime_message(exc),
                ))
            else:
                results.append(CheckResult(
                    name, False, detail=str(exc),
                    remedy="The lib folder is missing or incomplete. Re-copy "
                           "the Anuvad Plus folder from the USB stick.",
                ))

    return results
