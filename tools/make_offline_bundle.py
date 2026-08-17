"""Build a self-contained folder that installs on an offline Windows PC.

Run this ONCE on a machine with internet access (any OS -- the Windows wheels
are downloaded cross-platform).  It produces::

    dist/AnuvadPlus-Offline/
        lib/                  every dependency, already unpacked
        models/en_hi/         the neural translation model
        models/dictionary/    the English-Hindi dictionary database
        src/                  the application
        Start Anuvad Plus.bat        double-click to run -- no install step
        Check Anuvad Plus.bat        confirms everything is in place
        vc_redist.x64.exe     Microsoft C++ runtime, only if the PC lacks it
        INSTALL.txt README.md

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
import zipfile
from pathlib import Path
from urllib.error import URLError
from urllib.request import Request, urlopen

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from anuvad.runtime import VC_REDIST_FILENAME, VC_REDIST_URL  # noqa: E402

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = PROJECT_ROOT / "dist" / "AnuvadPlus-Offline"

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
    "INSTALLATION.md",
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


def unpack_wheels(wheel_dir: Path, lib_dir: Path) -> None:
    """Unpack every wheel into ``lib`` so the app runs with no install step.

    A wheel is a zip whose contents go straight onto ``sys.path``; for these
    packages nothing else is needed.  Doing it here rather than on the target
    PC means the offline machine needs no pip, no virtual environment and no
    administrator rights -- only Python itself.
    """
    if lib_dir.exists():
        shutil.rmtree(lib_dir)
    lib_dir.mkdir(parents=True, exist_ok=True)

    wheels = sorted(wheel_dir.glob("*.whl"))
    if not wheels:
        raise SystemExit("No wheels found in %s" % wheel_dir)

    print("Unpacking %d wheels into lib/ …" % len(wheels))
    skipped = {"pip", "setuptools", "wheel"}
    for wheel in wheels:
        name = wheel.name.split("-")[0].lower().replace("_", "-")
        if name in skipped:
            # Only needed to install things; nothing is installed.
            continue
        with zipfile.ZipFile(wheel) as archive:
            for member in archive.infolist():
                target = (lib_dir / member.filename).resolve()
                if not str(target).startswith(str(lib_dir.resolve())):
                    raise SystemExit("Unsafe path in %s: %s"
                                     % (wheel.name, member.filename))
            archive.extractall(lib_dir)
        print("  %s" % wheel.name)

    print("  lib/ is %s" % _human(_directory_size(lib_dir)))


def fetch_vc_redist(destination: Path) -> bool:
    """Download Microsoft's C++ runtime installer into the bundle.

    CTranslate2 needs MSVCP140.dll and VCRUNTIME140_1.dll, which Python does
    not provide.  Most Windows PCs already have them; carrying the official
    installer means a machine that does not can be fixed without internet.
    """
    destination.parent.mkdir(parents=True, exist_ok=True)
    print("Downloading the Microsoft C++ runtime (%s) …" % VC_REDIST_URL)
    try:
        request = Request(VC_REDIST_URL, headers={"User-Agent": "AnuvadPlus/1.0"})
        with urlopen(request, timeout=120) as response:
            data = response.read()
        if len(data) < 1_000_000:
            raise ValueError("file is too small to be the real installer")
        destination.write_bytes(data)
    except (URLError, OSError, ValueError) as exc:
        print("  [warn] could not download it: %s" % exc)
        print("  The bundle will still work on any PC that already has the")
        print("  runtime (most do). To add it later, download")
        print("    %s" % VC_REDIST_URL)
        print("  and place it at %s" % destination)
        return False
    print("  saved %s (%s)" % (destination.name, _human(len(data))))
    return True


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
==============================================================
  Anuvad Plus - English to Hindi Translator
  Offline installation guide
==============================================================

Anuvad Plus runs entirely on this PC. It never uses the internet.


WHAT YOU NEED
-------------
  Windows 10 or 11, 64-bit, and Python {pyver_dotted} (64-bit).
  Nothing else. There is no setup program and nothing gets installed.


STEP 1 - INSTALL PYTHON (only once, only if it is missing)
----------------------------------------------------------
  To check, press the Windows key, type "python" and see if it appears.

  If not, run the Python {pyver_dotted} installer from the USB stick
  (or download it from python.org/downloads/windows).

  On the first screen of the installer:

      [x] Add python.exe to PATH     <-- TICK THIS BOX

  then click "Install Now" and keep the "tcl/tk and IDLE" option
  ticked when offered. That option provides the window toolkit.


STEP 2 - COPY THE FOLDER
------------------------
  Copy this whole Anuvad Plus folder to the PC, for example to:

      C:\\AnuvadPlus

  Keep the folder together. Everything it needs is inside it.


STEP 3 - START IT
-----------------
  Double-click:   Start Anuvad Plus.bat

  That is all. The window opens in a few seconds.

  To put it on the desktop: right-click "Start Anuvad Plus.bat",
  choose "Send to" then "Desktop (create shortcut)".


IF SOMETHING IS WRONG
---------------------
  Double-click "Check Anuvad Plus.bat". It prints a report saying exactly
  what is missing and what to do about it.


  "Python was not found"
      Python is not installed, or "Add python.exe to PATH" was not
      ticked during setup. Re-run the Python installer and tick it.

  "One component is missing" / "DLL load failed"
      This PC does not have the Microsoft C++ runtime. Double-click
      vc_redist.x64.exe in this folder, accept the prompt, then start
      Anuvad Plus again. It is a free Microsoft component and takes a minute.
      Most PCs already have it, so you will probably never see this.

  Hindi shows as boxes
      Tools > Settings, and choose a Devanagari font such as
      "Nirmala UI" or "Mangal". Both come with Windows.

  "No translation model found"
      The models folder did not get copied. Copy it again from the
      USB stick into the Anuvad Plus folder.


USING Anuvad Plus
----------
  Translate      Type or paste English on the left, press the blue
                 Translate button (or Ctrl+Enter).
  A whole file   File > Open text file.
  Save           File > Save translation, or Save side-by-side for
                 English and Hindi in two columns.
  Dictionary     Press Ctrl+D, or double-click any word to look it up.
                 Meanings, synonyms, antonyms and examples.
  Glossary       Dictionary > Administrative glossary - official
                 government terms in English and Hindi.

  Press F1 inside the app for the quick start guide.


WHAT IS IN THIS FOLDER
----------------------
  Start Anuvad Plus.bat        double-click this to run Anuvad Plus
  Check Anuvad Plus.bat        checks the installation and reports problems
  AnuvadPlus.py               the launcher that Start Anuvad Plus.bat calls
  lib\\                 the libraries Anuvad Plus needs, ready to use
  src\\                 the application itself
  models\\en_hi\\        the translation model
  models\\dictionary\\   the dictionary database
  data\\                the government terminology glossary
  vc_redist.x64.exe     Microsoft C++ runtime, only if the PC needs it
  README.md             full documentation
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
    for name in ("Start Anuvad Plus.bat", "Check Anuvad Plus.bat", "AnuvadPlus.py"):
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
    parser.add_argument("--python-version", default="313",
                        help="Target Python on the offline PC (default 313).")
    parser.add_argument("--platform", default="win_amd64",
                        help="Target platform tag (default: win_amd64).")
    parser.add_argument("--skip-model", action="store_true",
                        help="Do not download the model (wheels and code only).")
    parser.add_argument("--skip-wheels", action="store_true",
                        help="Do not download wheels (model and code only).")
    parser.add_argument("--skip-dictionary", action="store_true",
                        help="Do not build the dictionary database.")
    parser.add_argument("--skip-runtime", action="store_true",
                        help="Do not include the Microsoft C++ runtime installer.")
    parser.add_argument("--keep-wheels", action="store_true",
                        help="Keep the downloaded .whl files beside lib/.")
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
        unpack_wheels(output / "wheels", output / "lib")
        if not args.keep_wheels:
            shutil.rmtree(output / "wheels")
        print()

    if not args.skip_runtime:
        fetch_vc_redist(output / VC_REDIST_FILENAME)
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
        "\nCopy this folder to the offline PC and double-click 'Start Anuvad Plus.bat'."
        "\nNothing needs to be installed there except Python itself."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
