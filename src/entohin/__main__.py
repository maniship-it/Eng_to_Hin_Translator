"""Entry point: ``python -m entohin`` starts the GUI, or translates a file.

Examples::

    python -m entohin                       # start the desktop app
    python -m entohin --file input.txt      # translate a file to stdout
    python -m entohin --file in.txt -o out.txt
    python -m entohin --check               # verify the offline install
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="entohin",
        description="Offline English to Hindi translator.",
    )
    parser.add_argument("--file", "-f", help="Translate this text file instead of "
                                             "starting the GUI.")
    parser.add_argument("--out", "-o", help="Write the translation here "
                                            "(default: standard output).")
    parser.add_argument("--model-dir", help="Folder containing the en→hi model.")
    parser.add_argument("--beam-size", type=int, default=4,
                        help="Beam size; higher is slower but slightly better.")
    parser.add_argument("--batch-size", type=int, default=16,
                        help="Sentences translated per batch.")
    parser.add_argument("--define", "-d", metavar="WORD",
                        help="Print the dictionary entry for a word and exit.")
    parser.add_argument("--admin-glossary", action="store_true",
                        help="List the government administrative glossary.")
    parser.add_argument("--dictionary", help="Path to the dictionary database.")
    parser.add_argument("--check", action="store_true",
                        help="Check that the model and dependencies are usable.")
    parser.add_argument("--version", action="store_true", help="Print the version.")
    return parser


def _check(model_dir: str = "", dictionary_path: str = "") -> int:
    """Verify dependencies and the model, printing a readable report."""
    from .version import __version__

    print("English → Hindi Translator %s" % __version__)
    print("Python %s" % sys.version.split()[0])

    ok = True
    for name in ("ctranslate2", "sentencepiece"):
        try:
            module = __import__(name)
            version = getattr(module, "__version__", "installed")
            print("  [ok]   %s %s" % (name, version))
        except ImportError as exc:
            ok = False
            print("  [FAIL] %s is missing (%s)" % (name, exc))

    try:
        import tkinter  # noqa: F401
        print("  [ok]   tkinter")
    except ImportError:
        ok = False
        print("  [FAIL] tkinter is missing — reinstall Python with the "
              "'tcl/tk and IDLE' option enabled.")

    from . import model as model_module

    try:
        directory = model_module.discover_model_dir(
            [Path(model_dir)] if model_dir else None
        )
        paths = model_module.resolve_model(directory)
        print("  [ok]   model: %s" % directory)
        print("         ctranslate2 dir : %s" % paths.ct2_dir)
        print("         sentencepiece   : %s" % paths.source_spm)
    except Exception as exc:
        ok = False
        print("  [FAIL] %s" % exc)
        return 1 if not ok else 0

    if ok:
        try:
            from .translator import build_translator

            translator = build_translator(directory)
            result = translator.translate_text("This is a test. How are you?")
            print("  [ok]   test translation: %s" % result.text.replace("\n", " "))
            translator.close()
        except Exception as exc:
            ok = False
            print("  [FAIL] translation failed: %s: %s" % (type(exc).__name__, exc))

    # The dictionary is optional: the translator works without it.
    from .dictionary import Dictionary

    try:
        with Dictionary.open(
            extra=[Path(dictionary_path)] if dictionary_path else None
        ) as dictionary:
            meta = dictionary.meta()
            print("  [ok]   dictionary: %s" % dictionary.path)
            print("         %s head words, %s administrative terms"
                  % (meta.get("entries", "?"), meta.get("admin_terms", "?")))
    except Exception as exc:
        print("  [warn] dictionary not available: %s"
              % str(exc).splitlines()[0])
        print("         The translator works without it; build it with "
              "tools/build_dictionary.py")

    print("\n%s" % ("All checks passed." if ok else "Some checks failed — see above."))
    return 0 if ok else 1


def _open_dictionary(dictionary_path: str = ""):
    from .dictionary import Dictionary

    return Dictionary.open(extra=[Path(dictionary_path)] if dictionary_path else None)


def _print_entry(entry) -> None:
    """Print one dictionary entry as plain text."""
    from .dictionary import pos_label

    print(entry.word)
    print("=" * max(len(entry.word), 8))
    if entry.matched_form:
        print("(shown for %r)" % entry.matched_form)
    if entry.hindi_meanings:
        print("Hindi   : %s" % ", ".join(entry.hindi_meanings[:12]))
    if entry.parts_of_speech:
        print("Parts of speech: %s"
              % ", ".join(pos_label(p) for p in entry.parts_of_speech))

    for sense in entry.administrative_senses:
        print("\n[Government administrative term%s]"
              % (" — %s" % sense.category if sense.category else ""))
        if sense.hindi:
            print("  हिंदी   : %s" % ", ".join(sense.hindi))
        if sense.definition_en:
            print("  Meaning : %s" % sense.definition_en)
        if sense.definition_hi:
            print("  अर्थ    : %s" % sense.definition_hi)
        for example in sense.examples_en:
            print("  Example : %s" % example)
        for example in sense.examples_hi:
            print("  उदाहरण  : %s" % example)

    grouped: dict = {}
    for sense in entry.senses:
        if sense.is_administrative:
            continue
        grouped.setdefault(sense.pos or "other", []).append(sense)

    for pos, senses in grouped.items():
        print("\n%s" % pos_label(pos))
        for number, sense in enumerate(senses, start=1):
            parts = []
            if sense.hindi:
                parts.append(", ".join(sense.hindi))
            if sense.definition_en:
                parts.append(sense.definition_en)
            if not parts:
                continue
            print("  %d. %s" % (number, " — ".join(parts)))
            for example in sense.examples_en[:2]:
                print("       e.g. %s" % example)

    if entry.synonyms:
        print("\nSynonyms: %s" % ", ".join(entry.synonyms[:25]))
    if entry.antonyms:
        print("Antonyms: %s" % ", ".join(entry.antonyms[:25]))


def _define(word: str, dictionary_path: str = "") -> int:
    """Print the dictionary entry for ``word``."""
    from .dictionary import DictionaryError, DictionaryNotFoundError

    try:
        dictionary = _open_dictionary(dictionary_path)
    except (DictionaryNotFoundError, DictionaryError) as exc:
        print(exc, file=sys.stderr)
        return 2

    with dictionary:
        entries = dictionary.search(word)
        if not entries:
            print("Not found: %s" % word, file=sys.stderr)
            suggestions = dictionary.suggest(word, limit=10)
            if suggestions:
                print("Did you mean: %s" % ", ".join(suggestions), file=sys.stderr)
            return 1
        for index, entry in enumerate(entries[:5]):
            if index:
                print()
            _print_entry(entry)
    return 0


def _list_admin_glossary(dictionary_path: str = "") -> int:
    """Print the curated administrative glossary as a table."""
    from .dictionary import DictionaryError, DictionaryNotFoundError

    try:
        dictionary = _open_dictionary(dictionary_path)
    except (DictionaryNotFoundError, DictionaryError) as exc:
        print(exc, file=sys.stderr)
        return 2

    with dictionary:
        entries = dictionary.administrative_terms()
        if not entries:
            print("The dictionary contains no administrative glossary.",
                  file=sys.stderr)
            return 1
        for entry in entries:
            for sense in entry.administrative_senses:
                print("%-42s %-34s %s"
                      % (entry.word, ", ".join(sense.hindi), sense.category))
        print("\n%d administrative term(s)." % len(entries), file=sys.stderr)
    return 0


def _translate_file(args: argparse.Namespace) -> int:
    from .textio import read_text_file, write_text_file
    from .translator import Options, build_translator

    source = Path(args.file)
    text = read_text_file(source)
    if text is None:
        print("Could not read %s as text." % source, file=sys.stderr)
        return 2

    options = Options(
        beam_size=max(1, args.beam_size), max_batch_size=max(1, args.batch_size)
    )
    translator = build_translator(args.model_dir, options)

    last = [-1]

    def progress(done: int, total: int) -> None:
        if total and done != last[0]:
            last[0] = done
            print("\r  %d / %d sentences" % (done, total), end="", file=sys.stderr)

    result = translator.translate_text(text, progress=progress)
    print("", file=sys.stderr)
    translator.close()

    if args.out:
        write_text_file(Path(args.out), result.text)
        print("Wrote %s" % args.out, file=sys.stderr)
    else:
        sys.stdout.write(result.text)

    report = result.report
    print(
        "Segments: %d · translated %d · cached %d · retried %d · kept English %d"
        % (report.segments, report.translated, report.cached, report.retried,
           report.failed),
        file=sys.stderr,
    )
    return 0


def main(argv=None) -> int:
    args = _build_parser().parse_args(argv)

    if args.version:
        from .version import __version__

        print(__version__)
        return 0

    if args.check:
        return _check(args.model_dir or "", args.dictionary or "")

    if args.define:
        return _define(args.define, args.dictionary or "")

    if args.admin_glossary:
        return _list_admin_glossary(args.dictionary or "")

    if args.file:
        return _translate_file(args)

    from .gui import main as gui_main

    return gui_main()


if __name__ == "__main__":
    sys.exit(main())
