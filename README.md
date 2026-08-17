# Anuvad Plus — English ⇄ Hindi

**अनुवाद प्लस** — an offline translator, bilingual dictionary and government
terminology glossary for Windows. Neural machine translation, English
pronunciation with audio, and no network access ever.

Built for a PC with no internet: build one `.exe` installer on a connected
machine, carry it across, double-click. **The offline PC needs nothing at all
— not even Python.**

> **Installing it?** → **[INSTALLATION.md](INSTALLATION.md)**

| | |
|---|---|
| **Translate** | English → Hindi, whole documents, layout preserved |
| **Dictionary** | ~150,000 words, both directions, English ⇄ हिंदी |
| **Pronunciation** | IPA, plain respelling, syllables, and *Speak* aloud |
| **Similar words** | "did you mean" for typos, plus clickable synonyms |
| **Glossary** | 177 government administrative terms, bilingual |
| **Offline** | no network code in the application at all |

## Contents

- [How it works](#how-it-works)
- [Install it](#install-it)
- [The translator](#the-translator)
- [The dictionary](#the-dictionary)
- [How correctness is protected](#how-correctness-is-protected)
- [Command line](#command-line)
- [Troubleshooting](#troubleshooting)
- [Project layout](#project-layout)
- [Development](#development)
- [Licences](#licences)

---

## How it works

| Piece | What it is | Size |
|---|---|---|
| Translation model | Argos Translate `en→hi`: a CTranslate2 transformer + SentencePiece vocabulary | ~100 MB |
| Inference engine | [CTranslate2](https://github.com/OpenNMT/CTranslate2) — CPU-only, no PyTorch | ~40 MB |
| Dictionary | WordNet 3.0 + FreeDict eng-hin + CMU Pronouncing Dictionary + the government glossary, compiled to SQLite | ~56 MB |
| Speech | the Windows speech engine, via PowerShell | — |
| Interface | Tkinter, themed light and dark | — |

There is no PyTorch, no `transformers`, and no server: the runtime is two
compiled libraries plus data files. Translation happens in-process on the CPU.

**Everything is gathered once on a machine with internet.** The offline PC only
ever receives finished files.

---

## Install it

**On a Windows PC with internet**, once:

```bat
git clone https://github.com/maniship-it/Eng_to_Hin_Translator.git
cd Eng_to_Hin_Translator
scripts\Build Installer.bat
```

That one script installs the build dependencies, downloads the model and the
dictionary sources, compiles the database, draws the icon, freezes the app with
PyInstaller and packages it with [Inno Setup](https://jrsoftware.org/isdl.php).
It produces:

```
dist\AnuvadPlusSetup.exe    single-file installer, ~180 MB
dist\AnuvadPlus\            the same thing as a portable folder
```

**On the offline PC**: copy `AnuvadPlusSetup.exe` across and double-click it.
No Python, no dependencies, no administrator rights — the installer defaults to
a per-user install. If the machine lacks Microsoft's C++ runtime, the installer
silently supplies it from a copy inside itself.

Prefer nothing installed at all? Copy the `dist\AnuvadPlus` folder and run
`AnuvadPlus.exe` from inside it.

Full walkthrough, including what to do when something goes wrong:
**[INSTALLATION.md](INSTALLATION.md)**.

### Without Inno Setup

If you skip Inno Setup you still get the portable folder. There is also a
no-install bundle aimed at PCs that already have Python:

```bash
python tools/make_offline_bundle.py --zip
```

It unpacks every dependency into `lib/`, so `Start Anuvad Plus.bat` runs the app
with only Python 3.13 present. Useful when you cannot copy an `.exe` onto the
target machine.

---

## The translator

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
| Open the dictionary | **Ctrl+D**, or the Dictionary tab |
| Look up a word you can see | Double-click it in either pane, or right-click → Look up |

The document's shape is preserved: blank lines stay blank, indentation and
bullet or numbered list markers are kept, and lines that contain no letters
(`42`, `-----`) are passed through untouched. Translation runs on a background
thread with a live sentence counter, so a long document neither freezes the
window nor blocks cancellation.

Settings live in `%LOCALAPPDATA%\AnuvadPlus\settings.json`.

---

## The dictionary

Press **Ctrl+D**, or double-click any word in either translation pane. Backed by
a local SQLite database of about 150,000 head words — no network, 3–8 ms per
lookup.

### Both directions

Type `sanction` or type `मंज़ूरी`. Anuvad Plus detects the script and searches
that way; the label above the box shows which direction is live. Autocomplete
follows suit, offering Devanagari words when you type Devanagari.

Hindi spelling variants are folded together for matching, so `मंज़ूरी` and
`मंजूरी` reach the same entry, as do chandrabindu/anusvara variants and text
carrying invisible zero-width joiners. What is *displayed* is always the
original spelling.

### Pronunciation

English entries carry, from the CMU Pronouncing Dictionary:

| | |
|---|---|
| IPA | `/ˈɡʌ.vɚ.mənt/` |
| Respelling | `GUH-vur-muhnt` |
| Syllables | `3` |
| **🔊 Speak** | says the word using the voice built into Windows |

Speech goes through the Windows speech engine via PowerShell, so it needs
nothing installed. Off Windows, the written forms still work and the app says
why the audio does not.

ARPAbet carries no syllable boundaries, so they are derived with a
maximal-onset syllabifier before the IPA and respelling are rendered.

### Similar words

- **Did you mean** — misspell something and the closest head words appear as
  clickable chips: `governmnet` → *government, governmental, governance*.
  Candidates come from a few cheap prefix buckets rather than the whole
  dictionary, so a failed lookup still answers in tens of milliseconds.
- **Related** — every entry offers its synonyms and antonyms as chips; click one
  to jump straight to it.

### For a word it gives

- **Hindi meanings**, most authoritative first
- **Part of speech**, labelled in both languages (`noun / संज्ञा`)
- **Definitions** — English for every sense; Hindi as well for government terms
- **Thesaurus** — synonyms (पर्यायवाची) and antonyms (विलोम)
- **Examples** — real sentences showing the word in use

Inflected forms resolve to their base word, so `running`, `ran`, `mice`,
`studies` and `happiest` all find the right entry — irregular forms come from
WordNet's own exception lists rather than guesswork.

### Government administrative terminology

`data/admin_glossary.tsv` is a curated glossary of **177 central government
administrative terms**, written for this project. Every term carries the English
and Hindi headword, a definition in **both** languages, and an example sentence
in **both** languages, across 15 categories:

| | | |
|---|---|---|
| designation | organisation | service matters |
| noting and drafting | finance and accounts | procurement |
| legislative | parliamentary | meetings |
| vigilance and discipline | right to information | grievances |
| official language | classification | general administration |

Administrative senses always sort above general ones, so `sanction` leads with
the government meaning (मंजूरी, स्वीकृति) rather than the everyday one.

The dictionary is **optional**: if the database is missing, its page says so and
the translator carries on working.

---

## Command line

The same engine without the GUI:

```bat
rem verify the installation and print a test translation
.venv\Scripts\python.exe -m anuvad --check

rem translate a file
.venv\Scripts\python.exe -m anuvad --file input.txt --out hindi.txt

rem to standard output, with a bigger beam for slightly better output
.venv\Scripts\python.exe -m anuvad --file input.txt --beam-size 6

rem dictionary lookup, in either language
AnuvadPlus.exe --define sanction
AnuvadPlus.exe --define अधिसूचना

rem look it up and say it aloud
AnuvadPlus.exe --define government --speak

rem print the whole government glossary
AnuvadPlus.exe --admin-glossary
```

`--model-dir` overrides where the model is found, as does the `ANUVAD_MODEL_DIR`
environment variable. `--dictionary` and `ANUVAD_DICTIONARY` do the same for
the dictionary database.

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
| "Windows protected your PC" on the installer | SmartScreen warns about any unsigned installer. **More info** → **Run anyway**. |
| `DLL load failed` / "One component is missing" | The PC lacks Microsoft's C++ runtime. The installer supplies it automatically; with the portable folder, run `vc_redist.x64.exe` once. |
| `No translation model found` | Copy `models\en_hi` next to `AnuvadPlus.exe`, or use Tools → Choose model folder. |
| Dictionary page says "not available" | Copy `models\dictionary` across, or use Dictionary → Choose dictionary file. The translator is unaffected. |
| Hindi shows as boxes `□□□` | Pick a Devanagari font in Tools → Settings. Windows ships with *Nirmala UI* and *Mangal*. |
| **Speak** does nothing | Speech goes through PowerShell. If policy blocks it, the written pronunciation still works; the status line explains. |
| A word is not in the dictionary | Try its base form. ~150,000 head words, ~36,000 with a pronunciation — every common word, but not every rare one. |
| Saved file shows garbage in Notepad | Files are saved UTF-8 with a BOM. If you re-save, keep the encoding as UTF-8. |
| Translation is slow | Tools → Settings: beam size 1–2, batch size 32, CPU threads = core count. |
| Lines came back in English | Those failed the safety checks; the warning dialog lists them. Try shorter sentences. |
| `Python was not found` (building) | Only the *build* PC needs Python. Install 3.13 with *"Add python.exe to PATH"* ticked. |

Run `AnuvadPlus.exe --check` for a full diagnostic report.

---

## Project layout

```
src/anuvad/
    __main__.py       command line: translate, define, glossary, --check
    gui.py            the window: navigation rail, pages, dialogs
    gui_dictionary.py the dictionary page
    theme.py          the design system: palettes, fonts, widget styles
    translator.py     engine: batching, caching, verification, fallbacks
    segmenter.py      sentence splitting and layout preservation
    placeholders.py   protecting URLs, paths and code from the model
    dictionary.py     lookup, lemmatisation, both directions, fuzzy matching
    pronunciation.py  ARPAbet → IPA, respelling, syllables
    hindi.py          Devanagari folding so spelling variants match
    speech.py         the Windows speech bridge
    model.py          locating and loading the model
    textio.py         encoding detection for reading and writing text
    config.py         persisted user settings
    runtime.py        dependency checks and the C++ runtime message
data/
    admin_glossary.tsv   177 curated government administrative terms
tools/
    fetch_model.py         download and install the model
    build_dictionary.py    compile the dictionary database
    make_icon.py           draw the application icon
    make_offline_bundle.py build the no-install bundle
    make_test_model.py     build a tiny random model for the test suite
installer/
    anuvad_plus.iss   Inno Setup script → AnuvadPlusSetup.exe
    anuvad.ico        generated icon
scripts/
    Build Installer.bat   one command: model → dictionary → exe → installer
    Start Anuvad Plus.bat  Check Anuvad Plus.bat  AnuvadPlus.py
    frozen_entry.py        PyInstaller entry point
anuvad_plus.spec      PyInstaller recipe
tests/                415 tests
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

The GUI tests drive the real window headlessly; on Linux run them under
`xvfb-run`. `pytest -m "not integration"` skips everything that loads a model or
opens a window.

## Licences

This application is MIT licensed (see `LICENSE`), and so is the administrative
glossary in `data/admin_glossary.tsv`, which was written for this project.

Everything downloaded by the build tools keeps its own licence and is **not**
included in this repository:

| Component | Source | Licence |
|---|---|---|
| Translation model | Argos Translate `translate-en_hi` | CC0 / MIT components |
| Definitions, thesaurus, examples | Princeton WordNet 3.0 | WordNet 3.0 licence (BSD-like) |
| Pronunciations | CMU Pronouncing Dictionary | BSD-2-Clause |
| English-Hindi meanings | FreeDict `eng-hin`, from the IIIT Hyderabad dictionary | **GPL-2.0-or-later** |
| Inference engine | CTranslate2 | MIT |
| Tokenizer | SentencePiece | Apache 2.0 |
| Installer | Inno Setup (build tool only) | Inno Setup licence |

Note the **GPL-2.0-or-later** on the FreeDict data. Using it yourself is
unrestricted. If you redistribute the built `dictionary.sqlite` to others,
that database contains GPL data and the GPL's terms apply to it — attribute
the source and pass the same freedoms on. The application code is separate
work and stays MIT; the database is aggregated data, not linked code. If you
would rather ship no GPL data at all, build with `--skip-freedict`: you keep
WordNet and the administrative glossary, and lose the general Hindi meanings.
