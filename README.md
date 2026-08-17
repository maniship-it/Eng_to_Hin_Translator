# English → Hindi Translator

A desktop English-to-Hindi translator that runs **completely offline** on a
Windows PC. Neural machine translation, a Tkinter interface, and no network
access at any point after installation.

Built for the case where the translating PC has no internet at all: you prepare
a bundle once on a connected machine, carry it across on a USB stick, and
install from that bundle.

---

## Contents

- [How it works](#how-it-works)
- [Quick start (offline Windows PC)](#quick-start-offline-windows-pc)
- [Step 1 — build the bundle on an online PC](#step-1--build-the-bundle-on-an-online-pc)
- [Step 2 — install on the offline PC](#step-2--install-on-the-offline-pc)
- [Using the application](#using-the-application)
- [Command line](#command-line)
- [Standalone .exe (no Python on the target PC)](#standalone-exe-no-python-on-the-target-pc)
- [How correctness is protected](#how-correctness-is-protected)
- [Troubleshooting](#troubleshooting)
- [Project layout](#project-layout)
- [Development](#development)
- [Licences](#licences)

---

## How it works

| Piece | What it is | Size |
|---|---|---|
| Translation model | Argos Translate `en→hi`: a CTranslate2 transformer + SentencePiece vocabulary | ~100 MB |
| Inference engine | [CTranslate2](https://github.com/OpenNMT/CTranslate2) — CPU-only, no PyTorch | ~40 MB wheel |
| Tokenizer | [SentencePiece](https://github.com/google/sentencepiece) | ~1 MB wheel |
| Interface | Tkinter (ships with Python) | — |

There is no PyTorch, no `transformers`, and no server: the whole runtime is two
wheels plus the model. Translation happens in-process on the CPU.

**Everything must be gathered once on a machine with internet.** The model and
the Python wheels cannot be conjured on the offline PC. That is what
`tools/make_offline_bundle.py` is for.

---

## Quick start (offline Windows PC)

If someone has already handed you the bundle folder:

1. Copy the folder to the PC, e.g. `C:\EngToHin`
2. Double-click **`install.bat`**
3. Double-click **`run.bat`**

That is the whole installation. Nothing is downloaded.

---

## Step 1 — build the bundle on an online PC

On any machine with internet (Windows, Linux or macOS — the Windows wheels are
downloaded cross-platform):

```bash
git clone <this repository>
cd Eng_to_Hin_Translator

pip install -r requirements.txt
python tools/make_offline_bundle.py --python-version 311 --zip
```

This produces `dist/EngToHinTranslator-Offline/` (and a `.zip`) containing:

```
wheels/           every Python dependency as a .whl
models/en_hi/     the neural translation model
src/              the application
tools/ scripts/   helper scripts
install.bat  run.bat  check.bat  INSTALL.txt
```

Match `--python-version` to the Python you will install on the offline PC —
`311`, `312` and `313` all work. Copy the folder onto a USB stick.

> **If the offline PC has no Python at all**, also put the Python installer
> from [python.org/downloads/windows](https://www.python.org/downloads/windows/)
> on the same USB stick. Pick the 64-bit installer matching the
> `--python-version` you built for.

### Just the model

If you only need the model (you already have the dependencies):

```bash
python tools/fetch_model.py
```

It downloads the Argos `translate-en_hi` package, normalises it into
`models/en_hi/`, prints the SHA-256, and verifies it with a test translation.
If your network blocks the download, fetch the `.argosmodel` file in a browser
and point the script at it:

```bash
python tools/fetch_model.py --from-file translate-en_hi-1_1.argosmodel
```

---

## Step 2 — install on the offline PC

**Requirements:** Windows 10/11 64-bit, and 64-bit Python 3.11+ installed with
*"Add python.exe to PATH"* and *"tcl/tk and IDLE"* both ticked.

Run **`install.bat`**. It:

1. finds Python and checks that Tkinter is present,
2. creates a private virtual environment in `.venv`,
3. installs the bundled wheels with `pip install --no-index --find-links wheels`,
4. runs a self-check and prints a test translation.

Then run **`run.bat`** to start the app, or **`check.bat`** at any time to
re-verify the installation.

---

## Using the application

The window is split into an English pane (left) and a Hindi pane (right).

| Action | How |
|---|---|
| Translate | **Ctrl+Enter**, or the Translate button |
| Cancel a long run | **Esc**, or the Cancel button |
| Open a text file | **Ctrl+O** — byte-order marks are honoured, and UTF-8, UTF-16, UTF-32 and Windows-1252 are detected |
| Save the translation | **Ctrl+S** — written UTF-8 with a BOM so Notepad shows Hindi correctly |
| Save English and Hindi together | File → Save side-by-side (a `.tsv` that opens in Excel) |
| Copy the result | Edit → Copy translation |
| Resize the text | **Ctrl+plus** / **Ctrl+minus** |
| Change the Hindi font | Tools → Settings |
| Point at a model elsewhere | Tools → Choose model folder |

The document's shape is preserved: blank lines stay blank, indentation and
bullet or numbered list markers are kept, and lines that contain no letters
(`42`, `-----`) are passed through untouched. Translation runs on a background
thread with a live sentence counter, so a long document neither freezes the
window nor blocks cancellation.

Settings live in `%LOCALAPPDATA%\EngToHinTranslator\settings.json`.

---

## Command line

The same engine without the GUI:

```bat
rem verify the installation and print a test translation
.venv\Scripts\python.exe -m entohin --check

rem translate a file
.venv\Scripts\python.exe -m entohin --file input.txt --out hindi.txt

rem to standard output, with a bigger beam for slightly better output
.venv\Scripts\python.exe -m entohin --file input.txt --beam-size 6
```

`--model-dir` overrides where the model is found, as does the `ENTOHIN_MODEL_DIR`
environment variable.

---

## Standalone .exe (no Python on the target PC)

If you would rather not install Python on the offline machine, build a frozen
application on an **online Windows** PC:

```bat
scripts\build_windows_exe.bat
```

This produces `dist\EngToHinTranslator\` containing `EngToHinTranslator.exe`,
its dependencies and the model. Copy that whole folder to the offline PC and
double-click the `.exe` — there is nothing to install.

PyInstaller can only build a Windows executable *on* Windows, so this step
cannot be done from Linux or macOS.

---

## How correctness is protected

The request was "correct and errorless", and machine translation cannot promise
that on its own. What the app does promise is that it **never silently shows
you text it has reason to distrust** — where a check fails, the English is kept
and you are told which lines those were.

**Before translation**

- Text is split into sentences, because the model is trained on sentences and
  degrades on long inputs. The splitter knows about abbreviations (`Mr.`,
  `e.g.`, `U.S.A.`), decimals (`3.14`), initials (`J. R. R. Tolkien`), quotes
  and the Devanagari danda (`।`).
- Lines with no letters are never sent to the model, so it cannot hallucinate
  text for `42` or `-----`.
- URLs, email addresses, Windows paths, UNC paths, `` `code` ``, `{templates}`
  and `<tags>` are replaced with numeric placeholders so the model cannot
  corrupt them. A line consisting only of such a span is passed straight
  through.

**After translation, every sentence is checked**

- **Placeholders**: each must come back exactly once. A dropped or duplicated
  placeholder fails the check.
- **Script**: output for a substantial English input must contain Devanagari.
  This catches the model echoing English back, or emitting junk.
- **Degeneracy**: empty output, a word repeated five times in a row, a
  repeating multi-word cycle, or output six times longer than the source — all
  the ways beam search goes into a loop.
- **Retry integrity**: the retry decode sees the raw text, so anything that had
  been protected must still appear verbatim in its output. A URL the model
  rewrote fails the check rather than being published broken.

A sentence that fails any check is re-decoded greedily (different search, with
n-gram repetition blocking, on the unprotected text). If the retry also fails,
the **original English is kept** and the line is listed in a warning dialog and
in the run report. Content is never dropped and never replaced with something
the app cannot vouch for.

Decoding is deterministic — fixed beam, no sampling — so the same input always
gives the same output. Repeated sentences are cached, which matters on
documents with boilerplate.

### What this does not promise

It is a compact neural model, not a human translator. Expect good results on
ordinary prose and weaker results on idiom, poetry, dense legal or medical
terminology, and heavily context-dependent pronouns. Sentences are translated
independently, so context does not carry across sentence boundaries. **Have
important output reviewed by a Hindi speaker.**

---

## Troubleshooting

| Symptom | Fix |
|---|---|
| `Python was not found` | Install 64-bit Python from python.org with *"Add python.exe to PATH"* ticked. |
| `No module named tkinter` | Re-run the Python installer and enable *"tcl/tk and IDLE"*. |
| `No matching distribution found` | The wheels target a different Python version — see `bundle-info.txt`, and rebuild with `--python-version` to match. |
| `No translation model found` | Copy `models\en_hi` next to the app, or use Tools → Choose model folder. |
| Hindi shows as boxes `□□□` | Pick a Devanagari font in Tools → Settings. Windows ships with *Nirmala UI* and *Mangal*. |
| `DLL load failed` importing ctranslate2 | Install the Microsoft Visual C++ Redistributable (x64). Download it on the online PC and carry it across. |
| Saved file shows garbage in Notepad | Files are saved UTF-8 with a BOM. If you re-save, keep the encoding as UTF-8. |
| Translation is slow | Tools → Settings: lower the beam size to 1–2, raise the batch size, set CPU threads to your core count. |
| Lines came back in English | Those failed the safety checks; the warning dialog lists them. Try rephrasing shorter sentences. |

Run `check.bat` to get a full diagnostic report.

---

## Project layout

```
src/entohin/
    __main__.py      CLI entry point and --check diagnostics
    gui.py           Tkinter interface
    translator.py    engine: batching, caching, verification, fallbacks
    segmenter.py     sentence splitting and layout preservation
    placeholders.py  protecting URLs, paths and code from the model
    model.py         locating and loading the model
    textio.py        encoding detection for reading and writing text files
    config.py        persisted user settings
tools/
    fetch_model.py         download and install the model
    make_offline_bundle.py build the offline installation folder
    make_test_model.py     build a tiny random model for the test suite
scripts/
    install.bat  run.bat  check.bat  build_windows_exe.bat
tests/           202 tests
```

## Development

```bash
python -m venv .venv
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/python -m pytest            # full suite
.venv/bin/python -m pytest -m "not integration"   # skip model-loading tests
```

The test suite does not need the real model: `tools/make_test_model.py` builds a
structurally valid CTranslate2 model with random weights, so the whole pipeline
is exercised end to end. Because that model cannot produce Devanagari, it also
serves as a live check that the safety guards reject bad output.

## Licences

This application is MIT licensed (see `LICENSE`).

The translation model is the Argos Translate `translate-en_hi` package,
distributed separately and downloaded by `tools/fetch_model.py`; it is not
included in this repository. CTranslate2 is MIT licensed, SentencePiece is
Apache 2.0.
