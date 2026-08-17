"""Download and install the offline English-to-Hindi translation model.

Run this once on a machine that HAS internet access.  The extracted model is
written to ``models/en_hi`` inside the project, which is where the application
looks for it, and the whole folder can then be copied to an offline PC.

Usage::

    python tools/fetch_model.py                     # download and install
    python tools/fetch_model.py --from-file pkg.argosmodel
    python tools/fetch_model.py --dest D:\\models\\en_hi
    python tools/fetch_model.py --keep-archive      # keep the .argosmodel

The model is the Argos Translate ``translate-en_hi`` package: a CTranslate2
model plus a SentencePiece vocabulary, wrapped in a zip archive.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
import tempfile
import zipfile
from pathlib import Path
from typing import Iterable, List, Optional
from urllib.error import URLError
from urllib.request import Request, urlopen

PACKAGE_NAME = "translate-en_hi-1_1.argosmodel"

#: Mirrors, tried in order.  All serve the same Argos package.
MIRRORS: List[str] = [
    "https://argos-net.com/v1/" + PACKAGE_NAME,
    "https://data.argosopentech.com/argospm/v1/" + PACKAGE_NAME,
    "https://data.argosopentech.com/argospm/" + PACKAGE_NAME,
]

#: Where the app looks for the model by default.
DEFAULT_DEST = Path(__file__).resolve().parents[1] / "models" / "en_hi"

CHUNK = 256 * 1024


def _human(size: float) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return "%.1f %s" % (size, unit)
        size /= 1024
    return "%.1f GB" % size


def download(urls: Iterable[str], destination: Path) -> Path:
    """Download the first URL that works, showing progress."""
    errors: List[str] = []
    for url in urls:
        print("Downloading %s" % url)
        try:
            request = Request(url, headers={"User-Agent": "AnuvadPlus/1.0"})
            with urlopen(request, timeout=60) as response:
                total = int(response.headers.get("Content-Length") or 0)
                downloaded = 0
                with open(destination, "wb") as handle:
                    while True:
                        chunk = response.read(CHUNK)
                        if not chunk:
                            break
                        handle.write(chunk)
                        downloaded += len(chunk)
                        if total:
                            print(
                                "\r  %s / %s (%d%%)"
                                % (_human(downloaded), _human(total),
                                   downloaded * 100 // total),
                                end="",
                            )
                        else:
                            print("\r  %s" % _human(downloaded), end="")
                print()
            if destination.stat().st_size < 1024:
                raise ValueError("downloaded file is suspiciously small")
            return destination
        except (URLError, OSError, ValueError) as exc:
            print("  failed: %s" % exc)
            errors.append("%s -> %s" % (url, exc))
            continue

    raise SystemExit(
        "Could not download the model from any mirror:\n  "
        + "\n  ".join(errors)
        + "\n\nDownload %s manually in a browser and re-run with:\n"
        "    python tools/fetch_model.py --from-file <path to the file>"
        % PACKAGE_NAME
    )


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(CHUNK), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _safe_extract(archive: zipfile.ZipFile, target: Path) -> None:
    """Extract a zip, refusing entries that escape the target directory."""
    target = target.resolve()
    for member in archive.infolist():
        destination = (target / member.filename).resolve()
        if not str(destination).startswith(str(target)):
            raise SystemExit("Refusing to extract unsafe path: %s" % member.filename)
    archive.extractall(target)


def _find_one(root: Path, filename: str) -> Optional[Path]:
    if (root / filename).is_file():
        return root / filename
    for path in sorted(root.rglob(filename)):
        return path
    return None


def install(archive_path: Path, dest: Path) -> Path:
    """Extract the package and normalise it into the layout the app expects."""
    with tempfile.TemporaryDirectory() as tmp:
        staging = Path(tmp) / "extracted"
        staging.mkdir()
        print("Extracting %s" % archive_path.name)
        try:
            with zipfile.ZipFile(archive_path) as archive:
                _safe_extract(archive, staging)
        except zipfile.BadZipFile:
            raise SystemExit(
                "%s is not a valid .argosmodel archive (it may be a partial "
                "download or an HTML error page). Delete it and try again."
                % archive_path
            )

        model_bin = _find_one(staging, "model.bin")
        if model_bin is None:
            raise SystemExit("The archive does not contain a CTranslate2 model.bin.")
        ct2_source = model_bin.parent

        spm_source = None
        for name in ("sentencepiece.model", "spm.model", "sp_model.model",
                     "source.spm.model"):
            spm_source = _find_one(staging, name)
            if spm_source is not None:
                break
        if spm_source is None:
            candidates = [
                p for p in sorted(staging.rglob("*.model"))
                if not (p.parent / "model.bin").is_file()
            ]
            spm_source = candidates[0] if candidates else None
        if spm_source is None:
            raise SystemExit("The archive does not contain a SentencePiece model.")

        if dest.exists():
            print("Replacing existing model at %s" % dest)
            shutil.rmtree(dest)
        dest.mkdir(parents=True, exist_ok=True)

        shutil.copytree(ct2_source, dest / "model")
        shutil.copy2(spm_source, dest / "sentencepiece.model")

        # Carry across the package's own metadata if it has any, for reference.
        source_metadata = {}
        original = _find_one(staging, "metadata.json")
        if original is not None:
            try:
                source_metadata = json.loads(original.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                source_metadata = {}

        metadata = {
            "name": "English → Hindi",
            "source": "en",
            "target": "hi",
            "package": PACKAGE_NAME,
            "engine": "ctranslate2",
            # Set this only if a multi-target model needs a language token.
            "target_prefix_token": None,
            "source_package_metadata": source_metadata,
        }
        (dest / "metadata.json").write_text(
            json.dumps(metadata, indent=2, ensure_ascii=False), encoding="utf-8"
        )

    return dest


def verify(dest: Path) -> bool:
    """Load the installed model and run one sentence through it."""
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
    try:
        from anuvad.translator import build_translator
    except ImportError as exc:
        print("\nInstalled to %s" % dest)
        print("Could not import the app to verify (%s)." % exc)
        print("Install the dependencies first:  pip install -r requirements.txt")
        return False

    print("\nVerifying the model with a test sentence…")
    try:
        translator = build_translator(dest)
        result = translator.translate_text("Good morning. How are you today?")
        translator.close()
    except Exception as exc:
        print("Verification FAILED: %s: %s" % (type(exc).__name__, exc))
        return False

    print("  English : Good morning. How are you today?")
    print("  Hindi   : %s" % result.text)
    return True


def directory_size(path: Path) -> int:
    return sum(f.stat().st_size for f in path.rglob("*") if f.is_file())


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dest", default=str(DEFAULT_DEST),
                        help="Where to install the model (default: %s)" % DEFAULT_DEST)
    parser.add_argument("--from-file",
                        help="Install from an already-downloaded .argosmodel file.")
    parser.add_argument("--url", action="append",
                        help="Download from this URL instead of the built-in mirrors.")
    parser.add_argument("--sha256",
                        help="Expected SHA-256 of the archive; aborts on mismatch.")
    parser.add_argument("--keep-archive", action="store_true",
                        help="Keep the downloaded .argosmodel next to --dest.")
    parser.add_argument("--no-verify", action="store_true",
                        help="Skip the post-install test translation.")
    args = parser.parse_args(argv)

    dest = Path(args.dest).expanduser().resolve()

    with tempfile.TemporaryDirectory() as tmp:
        if args.from_file:
            archive = Path(args.from_file).expanduser().resolve()
            if not archive.is_file():
                raise SystemExit("No such file: %s" % archive)
        else:
            archive = download(args.url or MIRRORS, Path(tmp) / PACKAGE_NAME)

        digest = sha256(archive)
        print("SHA-256: %s" % digest)
        if args.sha256 and digest.lower() != args.sha256.lower():
            raise SystemExit(
                "Checksum mismatch!\n  expected %s\n  got      %s"
                % (args.sha256, digest)
            )

        install(archive, dest)

        if args.keep_archive and not args.from_file:
            kept = dest.parent / PACKAGE_NAME
            shutil.copy2(archive, kept)
            print("Kept the archive at %s" % kept)

    print("\nInstalled the model to %s (%s)" % (dest, _human(directory_size(dest))))

    if args.no_verify:
        return 0
    return 0 if verify(dest) else 1


if __name__ == "__main__":
    sys.exit(main())
