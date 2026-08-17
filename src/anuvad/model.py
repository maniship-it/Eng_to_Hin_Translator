"""Locating and loading the offline English-to-Hindi translation model.

The model is a CTranslate2 directory plus a SentencePiece vocabulary.  Both
come from the Argos Translate ``translate-en_hi`` package, which
``tools/fetch_model.py`` unpacks into the layout described in
:func:`discover_model_dir`.  Nothing here touches the network.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Sequence

MODEL_ENV_VAR = "ANUVAD_MODEL_DIR"

#: Name of the folder a model is expected to live in, relative to a search root.
MODEL_DIR_NAME = os.path.join("models", "en_hi")


class ModelNotFoundError(RuntimeError):
    """Raised when no usable model directory can be located."""


class ModelLoadError(RuntimeError):
    """Raised when a model directory exists but cannot be loaded."""


def app_root() -> Path:
    """Root of the installed application (parent of ``src``, or the exe dir)."""
    import sys

    if getattr(sys, "frozen", False):  # PyInstaller bundle
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[2]


def user_data_dir() -> Path:
    """Per-user directory for settings and side-loaded models."""
    if os.name == "nt":
        base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    else:
        base = os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share")
    return Path(base) / "AnuvadPlus"


def candidate_model_dirs(extra: Optional[Sequence[Path]] = None) -> List[Path]:
    """Every directory that may hold the model, in search order."""
    candidates: List[Path] = []
    if extra:
        candidates.extend(Path(p) for p in extra)
    env_value = os.environ.get(MODEL_ENV_VAR)
    if env_value:
        candidates.append(Path(env_value))
    candidates.append(app_root() / MODEL_DIR_NAME)
    candidates.append(user_data_dir() / MODEL_DIR_NAME)
    return candidates


def _find_ct2_dir(root: Path) -> Optional[Path]:
    """Find the CTranslate2 directory (the one holding ``model.bin``)."""
    if (root / "model.bin").is_file():
        return root
    for path in sorted(root.rglob("model.bin")):
        return path.parent
    return None


def _find_sentencepiece(root: Path, prefer: Sequence[str]) -> Optional[Path]:
    """Find a SentencePiece model file, honouring preferred names first."""
    for name in prefer:
        direct = root / name
        if direct.is_file():
            return direct
    matches = sorted(root.rglob("*.model"))
    # Exclude anything inside the CTranslate2 directory.
    matches = [m for m in matches if not (m.parent / "model.bin").is_file()]
    for name in prefer:
        for match in matches:
            if match.name == name:
                return match
    return matches[0] if matches else None


@dataclass
class ModelPaths:
    """Resolved on-disk locations for one translation direction."""

    root: Path
    ct2_dir: Path
    source_spm: Path
    target_spm: Path
    metadata: dict

    @property
    def target_prefix_token(self) -> Optional[str]:
        """Language token some multi-target models require (usually absent)."""
        value = self.metadata.get("target_prefix_token")
        return str(value) if value else None


def is_model_dir(path: Path) -> bool:
    """Cheap check for whether ``path`` looks like a usable model directory."""
    try:
        return path.is_dir() and _find_ct2_dir(path) is not None
    except OSError:
        return False


def resolve_model(path: Path) -> ModelPaths:
    """Resolve the concrete file layout inside a model directory."""
    path = Path(path)
    if not path.is_dir():
        raise ModelNotFoundError("Model directory does not exist: %s" % path)

    ct2_dir = _find_ct2_dir(path)
    if ct2_dir is None:
        raise ModelLoadError(
            "No CTranslate2 model (model.bin) found under: %s" % path
        )

    source_spm = _find_sentencepiece(
        path, ("source.spm.model", "sentencepiece.model", "spm.model", "sp_model.model")
    )
    if source_spm is None:
        raise ModelLoadError("No SentencePiece (.model) file found under: %s" % path)

    target_spm = _find_sentencepiece(
        path, ("target.spm.model", "sentencepiece.model", "spm.model", "sp_model.model")
    )
    if target_spm is None:
        target_spm = source_spm

    metadata: dict = {}
    for name in ("metadata.json", "model.json"):
        meta_path = path / name
        if meta_path.is_file():
            try:
                metadata = json.loads(meta_path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                metadata = {}
            break

    return ModelPaths(
        root=path,
        ct2_dir=ct2_dir,
        source_spm=source_spm,
        target_spm=target_spm,
        metadata=metadata if isinstance(metadata, dict) else {},
    )


def discover_model_dir(extra: Optional[Sequence[Path]] = None) -> Path:
    """Return the first directory on the search path that holds a model.

    Layout expected under the returned directory::

        models/en_hi/
            model/               CTranslate2 model (contains model.bin)
            sentencepiece.model  SentencePiece vocabulary
            metadata.json        optional, written by tools/fetch_model.py
    """
    tried: List[Path] = []
    for candidate in candidate_model_dirs(extra):
        tried.append(candidate)
        if is_model_dir(candidate):
            return candidate
    raise ModelNotFoundError(
        "No translation model found. Looked in:\n  "
        + "\n  ".join(str(p) for p in tried)
        + "\n\nRun tools/fetch_model.py on a machine with internet access, or "
        "copy the models folder from the offline bundle next to the "
        "application."
    )


def supported_compute_types(device: str = "cpu") -> List[str]:
    """Compute types this CTranslate2 build supports on ``device``."""
    import ctranslate2

    try:
        return sorted(ctranslate2.get_supported_compute_types(device))
    except Exception:  # pragma: no cover - depends on the local build
        return ["default"]


def pick_compute_type(requested: str, device: str = "cpu") -> str:
    """Choose a compute type, falling back when the request is unavailable."""
    supported = supported_compute_types(device)
    if requested in supported:
        return requested
    for fallback in ("int8_float32", "int8", "float32", "default"):
        if fallback in supported:
            return fallback
    return "default"
