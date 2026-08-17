"""User settings, persisted as JSON next to the user's data directory."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, fields
from pathlib import Path
from typing import Any, Dict

from .model import user_data_dir

SETTINGS_FILENAME = "settings.json"


@dataclass
class Settings:
    """Everything the GUI lets the user change, plus where the model lives."""

    model_dir: str = ""
    dictionary_path: str = ""
    beam_size: int = 4
    max_batch_size: int = 16
    compute_type: str = "int8"
    intra_threads: int = 0
    protect_entities: bool = True
    font_size: int = 12
    hindi_font_family: str = "Nirmala UI"
    wrap_text: bool = True
    shown_quick_start: bool = False
    theme: str = "light"
    speech_rate: int = 0
    speech_voice: str = ""
    last_directory: str = ""

    @classmethod
    def path(cls) -> Path:
        return user_data_dir() / SETTINGS_FILENAME

    @classmethod
    def load(cls) -> "Settings":
        """Read settings from disk, ignoring anything unreadable or unknown."""
        path = cls.path()
        try:
            raw: Dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return cls()
        if not isinstance(raw, dict):
            return cls()

        known = {f.name: f for f in fields(cls)}
        values: Dict[str, Any] = {}
        for key, value in raw.items():
            field = known.get(key)
            if field is None:
                continue
            try:
                if field.type is int or field.type == "int":
                    values[key] = int(value)
                elif field.type is bool or field.type == "bool":
                    values[key] = bool(value)
                else:
                    values[key] = str(value)
            except (TypeError, ValueError):
                continue
        return cls(**values)

    def save(self) -> None:
        """Write settings to disk; failures are non-fatal."""
        path = self.path()
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(
                json.dumps(asdict(self), indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
        except OSError:
            pass

    def to_options(self):
        """Build translator :class:`~anuvad.translator.Options` from these."""
        from .translator import Options

        return Options(
            beam_size=max(1, min(10, self.beam_size)),
            max_batch_size=max(1, min(128, self.max_batch_size)),
            compute_type=self.compute_type or "int8",
            intra_threads=max(0, self.intra_threads),
            protect_entities=self.protect_entities,
        )
