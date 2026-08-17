"""Build a self-contained folder that installs on an offline Windows PC.

Run this ONCE on a machine with internet access (any OS -- the Windows wheels
are downloaded cross-platform).  It produces::

    dist/EngToHinTranslator-Offline/
        wheels/               every Python dependency as a .whl
        models/en_hi/         the neural translation model
        models/dictionary/    the English-Hindi dictionary database
        src/                  the application
        tools/  scripts/ helper scripts, install.bat, run.bat
        requirements.txt README.md INSTALL.txt

Copy that folder (or the .zip it can produce) to the offline PC and run
``install.bat``.  Nothing in the install step touches the network.

Usage::

    python tools/make_offline_bundle.py
    python tools/make_offline_bundle.py --python-version 312 --zip
    python tools/make_offline_bundle.py --skip-model   # wheels only
    python tools/make_offline_bundle.py --skip-dictionary
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = PROJECT_ROOT / "dist" / "EngToHinTranslator-Offline"

#: Copied verbatim into the bundle.
SOURCE_ITEMS = [
    "src",
    "tools",
    "scripts",
    "tests",
    "data",
    "requirements.txt",
    "requirements-dev.txt",
    "pyproject.toml",
    "README.md",
    "LICENSE",
]


def _human(size: float) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return "%.1f %s" % (size, unit)
        size /= 1024
    return "%.1f GB" % size


def _directory_size(path: Path) -> int:
    return sum(f.stat().st_size for f in path.rglob("*") if f.is_file())


def download_wheels(output: Path, python_version: str, platform: str,
                    requirements: Path) -> None:
    """Fetch every dependency as a Windows wheel."""
    output.mkdir(parents=True, exist_ok=True)
    command = [
        sys.executable, "-m", "pip", "download",
        "--requirement", str(requirements),
        "--dest", str(output),
        "--only-binary", ":all:",
        "--platform", platform,
        "--python-version", python_version,
    ]
    print("Downloading %s wheels for Python %s…" % (platform, python_version))
    result = subprocess.run(command)
    if result.returncode != 0:
        raise SystemExit(
            "pip download failed (exit %d).\n\n"
            "If a package has no wheel for %s / Python %s, try a different "
            "--python-version (311, 312 and 313 are well supported)."
            % (result.returncode, platform, python_version)
        )

    # pip also needs to be installable offline for `pip install --no-index`
    # to work on a bare Python; grab it plus setuptools/wheel.
    print("Downloading pip, setuptools and wheel…")
    subprocess.run(
        [
            sys.executable, "-m", "pip", "download", "pip", "setuptools", "wheel",
            "--dest", str(output), "--only-binary", ":all:",
            "--platform", platform, "--python-version", python_version,
        ],
        check=False,
    )

    wheels = sorted(output.glob("*.whl"))
    print("  %d wheels, %s" % (len(wheels), _human(_directory_size(output))))
    for wheel in wheels:
        print("    %s" % wheel.name)


def fetch_model(destination: Path, archive: str = "") -> None:
    """Download and install the translation model into the bundle."""
    sys.path.insert(0, str(PROJECT_ROOT / "tools"))
    import fetch_model as fetcher  # noqa: E402  (path set above)

    argv = ["--dest", str(destination), "--no-verify"]
    if archive:
        argv += ["--from-file", archive]
    code = fetcher.main(argv)
    if code != 0:
        raise SystemExit("Fetching the model failed.")


def build_dictionary(destination: Path) -> None:
    """Compile the English-Hindi dictionary straight into the bundle."""
    sys.path.insert(0, str(PROJECT_ROOT / "tools"))
    import build_dictionary as builder  # noqa: E402  (path set above)

    code = builder.main(["--dest", str(destination)])
    if code != 0:
        raise SystemExit("Building the dictionary failed.")


def copy_sources(output: Path) -> None:
    print("Copying application files…")
    for item in SOURCE_ITEMS:
        source = PROJECT_ROOT / item
        if not source.exists():
            continue
        target = output / item
        if source.is_dir():
            if target.exists():
                shutil.rmtree(target)
            shutil.copytree(
                source, target,
                ignore=shutil.ignore_patterns("__pycache__", "*.pyc", ".pytest_cache"),
            )
        else:
            shutil.copy2(source, target)
        print("  %s" % item)


INSTALL_TXT = """\
English to Hindi Translator - offline installation
==================================================

This folder installs and runs with NO internet connection.

WHAT YOU NEED ON THE OFFLINE PC
-------------------------------
  * Windows 10 or 11, 64-bit
  * Python {pyver_dotted} (64-bit) from python.org
      - During setup tick "Add python.exe to PATH"
      - Keep "tcl/tk and IDLE" ticked (this provides the window toolkit)
    If the offline PC has no Python, copy the python installer .exe onto the
    same USB stick from python.org/downloads/windows and run it first.

INSTALL
-------
  1. Copy this whole folder to the offline PC, for example C:\\EngToHin
  2. Double-click  install.bat
     It creates a private virtual environment and installs the bundled
     wheels from the wheels\\ folder. Nothing is downloaded.

RUN
---
  Double-click  run.bat

  Or, to translate a file from the command line:
      .venv\\Scripts\\python.exe -m entohin --file input.txt --out hindi.txt

CHECK THE INSTALL
-----------------
  Double-click  check.bat   (prints a report and a test translation)

TROUBLESHOOTING
---------------
  "Python was not found"
      Python is not installed or not on PATH. Re-run the Python installer
      and tick "Add python.exe to PATH".

  "No matching distribution found"
      The wheels were built for Python {pyver_dotted}. Install that version,
      or rebuild the bundle on an online PC with:
          python tools\\make_offline_bundle.py --python-version <version>

  Hindi shows as boxes
      Install or select a Devanagari font (Tools -> Settings -> Hindi font).
      Windows ships with "Nirmala UI" and "Mangal".

  "No translation model found"
      The models\\en_hi folder is missing. Copy it from this bundle into the
      installation folder, or use Tools -> Choose model folder in the app.

  "No dictionary database found"
      The models\\dictionary folder is missing. The translator still works;
      only the Dictionary tab needs it. Copy the folder across, or use
      Dictionary -> Choose dictionary file in the app.

USING THE DICTIONARY
--------------------
  Open the Dictionary tab, or press Ctrl+D. You can also double-click any
  word in the translation panes to look it up.

  It gives Hindi meanings, part of speech, English and Hindi definitions,
  synonyms and antonyms, and example sentences - plus a glossary of central
  government administrative terms in both languages.
"""


def write_bundle_docs(output: Path, python_version: str) -> None:
    dotted = "%s.%s" % (python_version[0], python_version[1:])
    (output / "INSTALL.txt").write_text(
        INSTALL_TXT.format(pyver_dotted=dotted), encoding="utf-8", newline="\r\n"
    )
    # Record what the bundle targets so install.bat can warn on a mismatch.
    (output / "bundle-info.txt").write_text(
        "python_version=%s\n" % dotted, encoding="utf-8", newline="\r\n"
    )
    print("  INSTALL.txt")


def copy_bat_files(output: Path) -> None:
    for name in ("install.bat", "run.bat", "check.bat"):
        source = PROJECT_ROOT / "scripts" / name
        if source.exists():
            shutil.copy2(source, output / name)
            print("  %s" % name)


def make_zip(output: Path) -> Path:
    print("Creating zip archive…")
    archive = shutil.make_archive(str(output), "zip", root_dir=output.parent,
                                  base_dir=output.name)
    return Path(archive)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT),
                        help="Bundle folder to create (default: %s)" % DEFAULT_OUTPUT)
    parser.add_argument("--python-version", default="311",
                        help="Target Python on the offline PC: 311, 312 or 313.")
    parser.add_argument("--platform", default="win_amd64",
                        help="Target platform tag (default: win_amd64).")
    parser.add_argument("--skip-model", action="store_true",
                        help="Do not download the model (wheels and code only).")
    parser.add_argument("--skip-wheels", action="store_true",
                        help="Do not download wheels (model and code only).")
    parser.add_argument("--skip-dictionary", action="store_true",
                        help="Do not build the dictionary database.")
    parser.add_argument("--model-archive", default="",
                        help="Use an already-downloaded .argosmodel file.")
    parser.add_argument("--zip", action="store_true",
                        help="Also produce a .zip of the bundle.")
    args = parser.parse_args(argv)

    output = Path(args.output).expanduser().resolve()
    output.mkdir(parents=True, exist_ok=True)
    print("Building offline bundle in %s\n" % output)

    if not args.skip_wheels:
        download_wheels(
            output / "wheels", args.python_version, args.platform,
            PROJECT_ROOT / "requirements.txt",
        )
        print()

    if not args.skip_model:
        fetch_model(output / "models" / "en_hi", args.model_archive)
        print()

    if not args.skip_dictionary:
        build_dictionary(output / "models" / "dictionary" / "dictionary.sqlite")
        print()

    copy_sources(output)
    copy_bat_files(output)
    write_bundle_docs(output, args.python_version)

    total = _directory_size(output)
    print("\nBundle ready: %s (%s)" % (output, _human(total)))

    if args.zip:
        archive = make_zip(output)
        print("Zip: %s (%s)" % (archive, _human(archive.stat().st_size)))

    print(
        "\nCopy the folder to the offline PC and run install.bat, then run.bat."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
