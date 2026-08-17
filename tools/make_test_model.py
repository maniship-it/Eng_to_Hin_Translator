"""Build a tiny, randomly-initialised model for testing the plumbing.

The real en→hi model has to be downloaded, which the test suite cannot do.
This builds a structurally valid CTranslate2 model plus a real SentencePiece
vocabulary so the full pipeline -- tokenise, decode, restore placeholders,
reassemble the document -- can be exercised end to end.

The translations it produces are meaningless.  It verifies wiring, not quality.

Usage::

    python tools/make_test_model.py --dest build/test-model
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path

CORPUS = """\
The quick brown fox jumps over the lazy dog.
Good morning, how are you today?
This is a test sentence for the translator.
Please open the file and read the first line.
He said that the meeting will start at nine o'clock.
Water freezes at zero degrees Celsius.
She bought two books and a notebook from the shop.
The train to the city leaves every thirty minutes.
Children were playing in the park yesterday evening.
Write your name and address on the form.
"""


def build_sentencepiece(dest: Path, vocab_size: int = 96) -> Path:
    """Train a small SentencePiece model on the sample corpus."""
    import sentencepiece as spm

    with tempfile.TemporaryDirectory() as tmp:
        corpus_path = Path(tmp) / "corpus.txt"
        corpus_path.write_text(CORPUS, encoding="utf-8")
        prefix = Path(tmp) / "sp"
        spm.SentencePieceTrainer.Train(
            input=str(corpus_path),
            model_prefix=str(prefix),
            vocab_size=vocab_size,
            model_type="unigram",
            character_coverage=1.0,
            # CTranslate2 expects <unk>, <s> and </s> to exist in the vocabulary.
            unk_id=0,
            bos_id=1,
            eos_id=2,
            pad_id=-1,
        )
        target = dest / "sentencepiece.model"
        target.write_bytes((prefix.with_suffix(".model")).read_bytes())
    return target


def build_ct2_model(dest: Path, vocabulary, d_model: int = 32,
                    ffn_dim: int = 64, num_heads: int = 4) -> Path:
    """Create a valid CTranslate2 transformer with small random weights."""
    import numpy as np
    import ctranslate2.specs as specs

    rng = np.random.default_rng(1234)

    def weights(*shape) -> "np.ndarray":
        # Small values keep the decoder from saturating immediately.
        return (rng.standard_normal(shape) * 0.02).astype(np.float32)

    def ones(size: int) -> "np.ndarray":
        return np.ones(size, dtype=np.float32)

    def zeros(*shape) -> "np.ndarray":
        return np.zeros(shape, dtype=np.float32)

    spec = specs.TransformerSpec.from_config(num_layers=1, num_heads=num_heads)
    vocab_size = len(vocabulary)

    def fill_layer_norm(norm) -> None:
        norm.gamma = ones(d_model)
        norm.beta = zeros(d_model)

    def fill_ffn(ffn) -> None:
        fill_layer_norm(ffn.layer_norm)
        ffn.linear_0.weight = weights(ffn_dim, d_model)
        ffn.linear_0.bias = zeros(ffn_dim)
        ffn.linear_1.weight = weights(d_model, ffn_dim)
        ffn.linear_1.bias = zeros(d_model)

    def fill_attention(attention, projections) -> None:
        fill_layer_norm(attention.layer_norm)
        for index, out_dim in enumerate(projections):
            attention.linear[index].weight = weights(out_dim, d_model)
            attention.linear[index].bias = zeros(out_dim)

    encoder = spec.encoder
    encoder.embeddings[0].weight = weights(vocab_size, d_model)
    fill_layer_norm(encoder.layer_norm)
    for layer in encoder.layer:
        fill_attention(layer.self_attention, (3 * d_model, d_model))
        fill_ffn(layer.ffn)

    decoder = spec.decoder
    decoder.embeddings.weight = weights(vocab_size, d_model)
    fill_layer_norm(decoder.layer_norm)
    decoder.projection.weight = weights(vocab_size, d_model)
    decoder.projection.bias = zeros(vocab_size)
    for layer in decoder.layer:
        fill_attention(layer.self_attention, (3 * d_model, d_model))
        # Cross-attention splits into queries, then keys+values, then output.
        fill_attention(layer.attention, (d_model, 2 * d_model, d_model))
        fill_ffn(layer.ffn)

    spec.register_source_vocabulary(list(vocabulary))
    spec.register_target_vocabulary(list(vocabulary))

    # A converter would normally do this; validate() also boxes the raw arrays
    # into the variable objects that the serialiser expects.
    spec.validate()
    spec.optimize(quantization="float32")

    target = dest / "model"
    target.mkdir(parents=True, exist_ok=True)
    spec.save(str(target))
    return target


def vocabulary_from_sentencepiece(path: Path):
    import sentencepiece

    processor = sentencepiece.SentencePieceProcessor()
    processor.Load(str(path))
    return [processor.IdToPiece(i) for i in range(processor.GetPieceSize())]


def build(dest: Path) -> Path:
    dest.mkdir(parents=True, exist_ok=True)
    spm_path = build_sentencepiece(dest)
    vocabulary = vocabulary_from_sentencepiece(spm_path)
    build_ct2_model(dest, vocabulary)
    (dest / "metadata.json").write_text(
        json.dumps(
            {
                "name": "test model (random weights)",
                "source": "en",
                "target": "hi",
                "target_prefix_token": None,
                "note": "Structurally valid, semantically meaningless.",
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    return dest


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dest", default="build/test-model")
    args = parser.parse_args(argv)
    dest = build(Path(args.dest).resolve())
    print("Test model written to %s" % dest)
    return 0


if __name__ == "__main__":
    sys.exit(main())
