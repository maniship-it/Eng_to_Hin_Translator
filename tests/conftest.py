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


def _sense(pos, definition="", examples=(), synonyms=(), antonyms=()):
    return {
        "pos": pos,
        "definition_en": definition,
        "examples_en": list(examples),
        "synonyms": list(synonyms),
        "antonyms": list(antonyms),
    }


#: A small stand-in for WordNet, covering the words the tests look up.
TEST_WORDNET = {
    "government": [_sense(
        "noun", "the organization that is the governing authority of a political unit",
        ["the government reduced taxes"], ["authorities", "regime"],
    )],
    "run": [
        _sense("verb", "move fast by using one's feet", ["don't run--you'll be out of breath"],
               ["scat", "dash"]),
        _sense("noun", "a score in baseball made by a runner touching all four bases"),
    ],
    "happy": [_sense(
        "adjective", "enjoying or showing or marked by joy or pleasure",
        ["a happy smile", "spent many happy days on the beach"],
        ["felicitous", "glad"], ["unhappy"],
    )],
    "study": [_sense("verb", "consider in detail and subject to an analysis",
                     ["study the terms of the contract"], ["analyze", "examine"])],
    "mouse": [_sense("noun", "any of numerous small rodents")],
    "walk": [_sense("verb", "use one's feet to advance", ["walk, don't run!"])],
    "carry": [_sense("verb", "move while supporting")],
    "notification": [_sense("noun", "a request for payment")],
}

TEST_EXCEPTIONS = {"ran": "run", "mice": "mouse", "ate": "eat"}

#: A small stand-in for the FreeDict English-Hindi dictionary.
TEST_FREEDICT = {
    "government": [{"pos": "noun", "hindi": ["सरकार"],
                    "examples_en": ["The government has announced a new scheme."]}],
    "run": [{"pos": "verb", "hindi": ["दौड़ना"],
             "examples_en": ["He can run very fast."]}],
    "happy": [{"pos": "adjective", "hindi": ["सुखी", "प्रसन्न"],
               "examples_en": ["She was happy with the result."]}],
    "study": [{"pos": "verb", "hindi": ["अध्ययन करना"], "examples_en": []}],
    "mouse": [{"pos": "noun", "hindi": ["चूहा"], "examples_en": []}],
    "sanction": [{"pos": "noun", "hindi": ["मंज़ूरी"],
                  "examples_en": ["Without my sanction he signed the letter."]}],
}


@pytest.fixture(scope="session")
def dictionary_path(tmp_path_factory) -> Path:
    """Build a small dictionary database with the real builder."""
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
    import build_dictionary

    admin = build_dictionary.load_admin_glossary(
        Path(__file__).resolve().parents[1] / "data" / "admin_glossary.tsv"
    )
    destination = tmp_path_factory.mktemp("dictionary") / "dictionary.sqlite"
    build_dictionary.build_database(
        destination, TEST_WORDNET, TEST_EXCEPTIONS, TEST_FREEDICT, admin
    )
    return destination


@pytest.fixture
def dictionary(dictionary_path):
    from entohin.dictionary import Dictionary

    instance = Dictionary.open(dictionary_path)
    yield instance
    instance.close()


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
