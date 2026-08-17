"""Speak a word aloud, offline, with nothing extra installed.

Windows ships a speech engine (SAPI) and the .NET ``System.Speech`` assembly,
both reachable from PowerShell, which is present on every Windows 10 and 11
machine. Anuvad Plus drives that rather than bundling a speech library, so
the "no dependencies" promise holds.

Nothing here ever raises: if speech is unavailable the caller is told so and
the application carries on silently.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import threading
from dataclasses import dataclass
from typing import Optional

#: Guard against a runaway PowerShell process.
TIMEOUT_SECONDS = 20

#: Rate accepted by SAPI, -10 (slowest) to 10 (fastest).
MIN_RATE, MAX_RATE = -10, 10


@dataclass
class SpeechResult:
    """What happened when speech was attempted."""

    ok: bool
    message: str = ""


def _powershell() -> Optional[str]:
    for name in ("powershell.exe", "powershell", "pwsh"):
        found = shutil.which(name)
        if found:
            return found
    return None


def is_available() -> bool:
    """True if this machine can speak."""
    return os.name == "nt" and _powershell() is not None


def unavailable_reason() -> str:
    """Why speech is not available, phrased for a user."""
    if os.name != "nt":
        return ("Speaking words aloud uses the Windows speech engine, so it "
                "only works on Windows.")
    if _powershell() is None:
        return ("Windows PowerShell was not found, so the speech engine "
                "cannot be reached.")
    return ""


def _escape(text: str) -> str:
    """Quote text for a PowerShell single-quoted string."""
    return text.replace("'", "''")


def build_command(text: str, rate: int = 0, voice: str = "") -> list:
    """The PowerShell command used to speak ``text``.

    Kept separate from running it so the construction can be tested on any
    platform.
    """
    rate = max(MIN_RATE, min(MAX_RATE, int(rate)))
    script = [
        "Add-Type -AssemblyName System.Speech;",
        "$s = New-Object System.Speech.Synthesis.SpeechSynthesizer;",
        "$s.Rate = %d;" % rate,
    ]
    if voice:
        # A missing voice must not abort the whole command.
        script.append("try { $s.SelectVoice('%s') } catch {};" % _escape(voice))
    script.append("$s.Speak('%s');" % _escape(text))
    script.append("$s.Dispose();")

    return [
        _powershell() or "powershell.exe",
        "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
        "-Command", " ".join(script),
    ]


def speak(text: str, rate: int = 0, voice: str = "") -> SpeechResult:
    """Speak ``text`` and wait for it to finish."""
    cleaned = (text or "").strip()
    if not cleaned:
        return SpeechResult(False, "There is nothing to speak.")
    if not is_available():
        return SpeechResult(False, unavailable_reason())

    try:
        completed = subprocess.run(
            build_command(cleaned, rate=rate, voice=voice),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            timeout=TIMEOUT_SECONDS,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except subprocess.TimeoutExpired:
        return SpeechResult(False, "The speech engine did not respond in time.")
    except OSError as exc:
        return SpeechResult(False, "Could not start the speech engine: %s" % exc)

    if completed.returncode != 0:
        detail = (completed.stderr or b"").decode("utf-8", "replace").strip()
        return SpeechResult(
            False,
            "The speech engine reported a problem." + (" %s" % detail if detail else ""),
        )
    return SpeechResult(True)


def speak_async(text: str, rate: int = 0, voice: str = "",
                done=None) -> threading.Thread:
    """Speak without blocking the interface.

    ``done`` is called with the :class:`SpeechResult` on the worker thread;
    a Tk caller should marshal back to the UI thread itself.
    """

    def work() -> None:
        result = speak(text, rate=rate, voice=voice)
        if done is not None:
            done(result)

    thread = threading.Thread(target=work, daemon=True)
    thread.start()
    return thread
