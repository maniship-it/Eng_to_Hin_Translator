"""Shared test fixtures."""

from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import List, Sequence

import pytest

SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from entohin.translator import Backend, Options, Translator  # noqa: E402

PLACEHOLDER_RE = re.compile(r"^#\d+#$")


class FakeBackend(Backend):
    """A deterministic stand-in for the neural model.

    Every word becomes the Devanagari word "शब्द"; placeholders are echoed
    unchanged, which is what a well-behaved model does.  Specific inputs can
    be overridden to simulate failure modes.
    """

    def __init__(self, overrides=None, greedy_overrides=None):
        self.overrides = dict(overrides or {})
        self.greedy_overrides = dict(greedy_overrides or {})
        self.calls: List[List[str]] = []
        self.greedy_calls: List[List[str]] = []

    def translate(self, texts: Sequence[str], options: Options,
                  greedy: bool = False) -> List[str]:
        batch = list(texts)
        if greedy:
            self.greedy_calls.append(batch)
        else:
            self.calls.append(batch)
        table = self.greedy_overrides if greedy else self.overrides
        return [table.get(text, self._translate_one(text)) for text in batch]

    @staticmethod
    def _translate_one(text: str) -> str:
        words = []
        for word in text.split():
            words.append(word if PLACEHOLDER_RE.match(word) else "शब्द")
        return " ".join(words)

    @property
    def translated_texts(self) -> List[str]:
        return [text for batch in self.calls for text in batch]


@pytest.fixture
def fake_backend() -> FakeBackend:
    return FakeBackend()


@pytest.fixture
def translator(fake_backend: FakeBackend) -> Translator:
    return Translator(fake_backend, Options(max_batch_size=8))


@pytest.fixture(scope="session")
def ct2_model_dir(tmp_path_factory) -> Path:
    """Build a tiny real CTranslate2 model, or skip if it cannot be built."""
    pytest.importorskip("ctranslate2")
    pytest.importorskip("sentencepiece")

    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
    import make_test_model

    destination = tmp_path_factory.mktemp("model")
    try:
        return make_test_model.build(destination)
    except Exception as exc:  # pragma: no cover - depends on the local build
        pytest.skip("could not build a test CTranslate2 model: %s" % exc)
