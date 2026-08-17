"""The translation engine: sentence-at-a-time English to Hindi, offline.

The engine is deliberately conservative.  Anything it cannot translate with
confidence is passed through unchanged rather than guessed at, and every
translation is checked for the two failure modes neural MT actually exhibits
in production -- dropped placeholders and degenerate repetition loops -- with
a fallback decode when a check fails.
"""

from __future__ import annotations

import re
import threading
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Callable, List, Optional, Sequence

from . import placeholders, segmenter
from .model import ModelPaths, pick_compute_type, resolve_model

ProgressCallback = Callable[[int, int], None]

_WHITESPACE_SPLIT_RE = re.compile(r"^(\s*)(.*?)(\s*)$", re.DOTALL)


class TranslationCancelled(RuntimeError):
    """Raised when a caller cancels an in-flight translation."""


@dataclass
class Options:
    """Decoding and performance settings."""

    beam_size: int = 4
    max_batch_size: int = 16
    repetition_penalty: float = 1.1
    no_repeat_ngram_size: int = 0
    length_penalty: float = 1.0
    #: Decoding budget is proportional to input length, within these bounds.
    max_decoding_length: int = 384
    length_ratio: float = 3.0
    compute_type: str = "int8"
    device: str = "cpu"
    inter_threads: int = 1
    intra_threads: int = 0  # 0 lets CTranslate2 choose
    cache_size: int = 4096
    protect_entities: bool = True
    #: Reject output containing no Devanagari -- the model has either echoed
    #: the English back or produced junk.  Disable only when experimenting
    #: with a model that writes Hindi in Latin script.
    expect_devanagari: bool = True


@dataclass
class Report:
    """What happened during a translation run."""

    segments: int = 0
    translated: int = 0
    cached: int = 0
    passthrough: int = 0
    retried: int = 0
    failed: int = 0
    warnings: List[str] = field(default_factory=list)


class Backend:
    """Minimal interface the engine needs from a translation model."""

    def translate(self, texts: Sequence[str], options: Options,
                  greedy: bool = False) -> List[str]:
        raise NotImplementedError

    def close(self) -> None:  # pragma: no cover - trivial
        pass


class CTranslate2Backend(Backend):
    """CTranslate2 + SentencePiece, loaded from a local directory."""

    def __init__(self, paths: ModelPaths, options: Optional[Options] = None):
        import ctranslate2
        import sentencepiece

        options = options or Options()
        self.paths = paths
        self.compute_type = pick_compute_type(options.compute_type, options.device)

        self._translator = ctranslate2.Translator(
            str(paths.ct2_dir),
            device=options.device,
            compute_type=self.compute_type,
            inter_threads=max(1, options.inter_threads),
            intra_threads=max(0, options.intra_threads),
        )
        self._source_sp = sentencepiece.SentencePieceProcessor()
        self._source_sp.Load(str(paths.source_spm))
        if paths.target_spm == paths.source_spm:
            self._target_sp = self._source_sp
        else:
            self._target_sp = sentencepiece.SentencePieceProcessor()
            self._target_sp.Load(str(paths.target_spm))

        prefix = paths.target_prefix_token
        self._target_prefix = [prefix] if prefix else None

    @classmethod
    def from_dir(cls, model_dir, options: Optional[Options] = None) -> "CTranslate2Backend":
        return cls(resolve_model(model_dir), options)

    def translate(self, texts: Sequence[str], options: Options,
                  greedy: bool = False) -> List[str]:
        if not texts:
            return []

        batch = [self._source_sp.Encode(text, out_type=str) for text in texts]
        longest = max((len(tokens) for tokens in batch), default=1)
        max_decoding_length = min(
            options.max_decoding_length,
            max(32, int(longest * options.length_ratio) + 16),
        )

        prefix = None
        if self._target_prefix is not None:
            prefix = [list(self._target_prefix) for _ in batch]

        results = self._translator.translate_batch(
            batch,
            target_prefix=prefix,
            max_batch_size=options.max_batch_size,
            beam_size=1 if greedy else max(1, options.beam_size),
            length_penalty=options.length_penalty,
            repetition_penalty=options.repetition_penalty if greedy else 1.0,
            no_repeat_ngram_size=3 if greedy else options.no_repeat_ngram_size,
            max_decoding_length=max_decoding_length,
            replace_unknowns=True,
        )

        out: List[str] = []
        for result in results:
            tokens = list(result.hypotheses[0])
            if self._target_prefix and tokens[:len(self._target_prefix)] == self._target_prefix:
                tokens = tokens[len(self._target_prefix):]
            out.append(self._target_sp.Decode(tokens))
        return out

    def close(self) -> None:
        translator = getattr(self, "_translator", None)
        if translator is not None:
            try:
                translator.unload_model()
            except Exception:  # pragma: no cover - best effort
                pass


def _split_whitespace(text: str):
    match = _WHITESPACE_SPLIT_RE.match(text)
    assert match is not None  # the pattern matches any string
    return match.group(1), match.group(2), match.group(3)


_DEVANAGARI_RE = re.compile(r"[ऀ-ॿ]")
_LETTER_RE = re.compile(r"[A-Za-z]")


def has_devanagari(text: str) -> bool:
    """True if ``text`` contains at least one Devanagari character."""
    return bool(_DEVANAGARI_RE.search(text))


def looks_untranslated(source: str, output: str) -> bool:
    """True if a substantial English input produced no Hindi at all.

    Short inputs are exempt: a model may legitimately leave "OK" or an
    acronym in Latin script.
    """
    if len(_LETTER_RE.findall(source)) < 4:
        return False
    return not has_devanagari(output)


def is_degenerate(source: str, output: str) -> bool:
    """Detect the repetition loops beam search occasionally falls into."""
    if not output.strip():
        return True

    words = output.split()
    if len(words) >= 6:
        # The same word over and over.
        unique_ratio = len(set(words)) / len(words)
        if unique_ratio < 0.25:
            return True
        # The same word repeated consecutively many times.
        run = 1
        for previous, current in zip(words, words[1:]):
            run = run + 1 if current == previous else 1
            if run >= 5:
                return True
        # A repeating multi-word cycle ("A B A B A B ...").
        for size in (2, 3, 4):
            if len(words) >= size * 4:
                window = words[:size]
                repeats = 1
                index = size
                while index + size <= len(words) and words[index:index + size] == window:
                    repeats += 1
                    index += size
                if repeats >= 4:
                    return True

    # Wildly longer than the source is a runaway decode.
    if len(output) > 40 and len(output) > 6 * max(len(source), 1):
        return True
    return False


class Translator:
    """Translates English text to Hindi, preserving document structure."""

    def __init__(self, backend: Backend, options: Optional[Options] = None):
        self.backend = backend
        self.options = options or Options()
        self._cache: "OrderedDict[str, str]" = OrderedDict()
        self._lock = threading.Lock()

    # -- cache ---------------------------------------------------------

    def _cache_get(self, key: str) -> Optional[str]:
        with self._lock:
            if key in self._cache:
                self._cache.move_to_end(key)
                return self._cache[key]
        return None

    def _cache_put(self, key: str, value: str) -> None:
        with self._lock:
            self._cache[key] = value
            self._cache.move_to_end(key)
            while len(self._cache) > self.options.cache_size:
                self._cache.popitem(last=False)

    def clear_cache(self) -> None:
        with self._lock:
            self._cache.clear()

    # -- public API ----------------------------------------------------

    def translate_text(
        self,
        text: str,
        progress: Optional[ProgressCallback] = None,
        cancel: Optional[threading.Event] = None,
    ) -> "TranslationResult":
        """Translate a whole document, preserving lines, markers and spacing."""
        doc = segmenter.parse(text)
        report = Report(segments=len(doc.segments))

        if not doc.segments:
            if progress:
                progress(0, 0)
            return TranslationResult(text=doc.render(), report=report)

        # Prepare each segment: strip surrounding whitespace, protect entities.
        prepared: List[_Prepared] = []
        for segment in doc.segments:
            leading, core, trailing = _split_whitespace(segment.text)
            protected = (
                placeholders.protect(core)
                if self.options.protect_entities
                else placeholders.Protected(text=core, values=[])
            )
            prepared.append(
                _Prepared(
                    leading=leading,
                    trailing=trailing,
                    source=core,
                    protected=protected,
                )
            )

        # Work out which unique strings actually need the model.
        pending: "OrderedDict[str, List[int]]" = OrderedDict()
        for index, item in enumerate(prepared):
            if item.protected.is_placeholder_only:
                item.output = item.source
                report.passthrough += 1
                continue
            cached = self._cache_get(item.protected.text)
            if cached is not None:
                item.raw_output = cached
                report.cached += 1
                continue
            pending.setdefault(item.protected.text, []).append(index)

        total = len(pending)
        done = 0
        if progress:
            progress(0, total)

        for batch in segmenter.iter_batches(list(pending.keys()), self.options.max_batch_size):
            if cancel is not None and cancel.is_set():
                raise TranslationCancelled("Translation cancelled")
            outputs = self.backend.translate(batch, self.options)
            for source, output in zip(batch, outputs):
                self._cache_put(source, output)
                for index in pending[source]:
                    prepared[index].raw_output = output
            done += len(batch)
            if progress:
                progress(min(done, total), total)

        # Verify each result, retrying the ones that look wrong.
        retry_indices: List[int] = []
        for index, item in enumerate(prepared):
            if item.output is not None or item.raw_output is None:
                continue
            restored, ok = placeholders.restore(
                item.raw_output, item.protected.values
            )
            if ok and self._is_good(item.source, item.raw_output, restored):
                item.output = restored
                report.translated += 1
            else:
                retry_indices.append(index)

        if retry_indices:
            if cancel is not None and cancel.is_set():
                raise TranslationCancelled("Translation cancelled")
            report.retried += len(retry_indices)
            # Retry greedily on the *unprotected* source: this recovers both
            # from lost placeholders and from beam-search repetition loops.
            sources = [prepared[i].source for i in retry_indices]
            outputs = self.backend.translate(sources, self.options, greedy=True)
            for index, output in zip(retry_indices, outputs):
                item = prepared[index]
                # The retry saw the raw text, so anything that was protected
                # must still be present verbatim -- otherwise the model has
                # rewritten a URL or a path and the result cannot be trusted.
                intact = all(value in output for value in item.protected.values)
                if not intact or not self._is_good(item.source, output, output):
                    # Keep the source text: losing content is worse than
                    # leaving a line untranslated, and it is visible to a user.
                    item.output = item.source
                    report.failed += 1
                    report.warnings.append(
                        "Could not translate reliably, kept English: %s"
                        % _abbreviate(item.source)
                    )
                else:
                    item.output = output.strip()
                    report.translated += 1

        for item in prepared:
            if item.output is None:
                # Nothing produced a result: keep the English so no content
                # silently disappears from the document.
                item.output = item.source
                report.failed += 1

        for segment, item in zip(doc.segments, prepared):
            segment.translated = item.leading + (item.output or "") + item.trailing

        if progress:
            progress(total, total)
        return TranslationResult(text=doc.render(), report=report)

    def translate_lines(self, lines: Sequence[str]) -> List[str]:
        """Convenience wrapper: translate a list of lines, one per output."""
        result = self.translate_text("\n".join(lines))
        return result.text.split("\n")

    def _is_good(self, source: str, raw_output: str, restored: str) -> bool:
        """Whether a model output is safe to show the user.

        ``raw_output`` still carries placeholders, so it is the right text to
        test for script; ``restored`` is what the user would actually see.
        """
        if is_degenerate(source, restored):
            return False
        if self.options.expect_devanagari and looks_untranslated(source, raw_output):
            return False
        return True

    def close(self) -> None:
        self.backend.close()


@dataclass
class _Prepared:
    leading: str
    trailing: str
    source: str
    protected: placeholders.Protected
    raw_output: Optional[str] = None
    output: Optional[str] = None


@dataclass
class TranslationResult:
    text: str
    report: Report


def _abbreviate(text: str, limit: int = 60) -> str:
    text = " ".join(text.split())
    return text if len(text) <= limit else text[:limit - 1] + "…"


def build_translator(model_dir=None, options: Optional[Options] = None) -> Translator:
    """Load the model and return a ready-to-use :class:`Translator`."""
    from .model import discover_model_dir

    options = options or Options()
    directory = model_dir or discover_model_dir()
    backend = CTranslate2Backend.from_dir(directory, options)
    return Translator(backend, options)
