# Anuvad Plus — Installation Guide

**Anuvad Plus** (अनुवाद प्लस) is an offline English ⇄ Hindi translator with a
bilingual dictionary, English pronunciation, and a government administrative
glossary. It runs entirely on your PC and never uses the internet.

There are two halves:

- **[Part A](#part-a--build-the-installer)** — done **once**, on a Windows PC
  **with** internet. Produces a single `AnuvadPlusSetup.exe`.
- **[Part B](#part-b--install-on-the-offline-pc)** — run that one file on the
  offline PC. Nothing else is needed there. **Not even Python.**

---

## Part A — build the installer

Do this on a Windows PC with an internet connection.

### A1. Install the two build tools

| Tool | Where | Why |
|---|---|---|
| **Python 3.13 (64-bit)** | [python.org/downloads/windows](https://www.python.org/downloads/windows/) | to build the application. Tick **Add python.exe to PATH**. |
| **Inno Setup 6** | [jrsoftware.org/isdl.php](https://jrsoftware.org/isdl.php) | to wrap it into a single installer. |

Inno Setup is optional. Without it you still get a portable folder — see
[Portable, no installer](#portable-no-installer) below.

### A2. Get the project

```bat
git clone https://github.com/maniship-it/Eng_to_Hin_Translator.git
cd Eng_to_Hin_Translator
```

### A3. Run one script

Double-click **`scripts\Build Installer.bat`**, or run it from a prompt.

It installs the build dependencies, downloads the translation model and the
dictionary sources, compiles the dictionary, draws the icon, freezes the
application with PyInstaller, fetches Microsoft's C++ runtime, and packages
everything with Inno Setup.

Expect **10–15 minutes** and about **400 MB** downloaded. The result:

```
dist\AnuvadPlusSetup.exe        the installer  (~180 MB)
dist\AnuvadPlus\                the same thing as a portable folder
```

### A4. Copy it across

Put `AnuvadPlusSetup.exe` on a USB stick. That single file is everything.

---

## Part B — install on the offline PC

1. Copy `AnuvadPlusSetup.exe` onto the PC.
2. Double-click it.
3. Click through the wizard. It offers a desktop shortcut.
4. Anuvad Plus starts.

That is the whole installation. **No Python, no separate downloads, no
internet, and no administrator rights** — the installer defaults to a per-user
install under your own profile. If you want it available to everyone on the PC
and you have admin rights, choose that option in the wizard.

If the PC happens to be missing Microsoft's C++ runtime, the installer spots
that and installs it silently, from a copy inside itself. You will not be asked
anything.

### Portable, no installer

If you would rather not install anything at all, copy the whole
`dist\AnuvadPlus` folder to the PC and run `AnuvadPlus.exe` from inside it. It
is fully self-contained. To remove it, delete the folder.

---

## Using Anuvad Plus

Press **F1** inside the app at any time for the quick start.

### Translating

| I want to… | Do this |
|---|---|
| Translate some text | Type on the left, press **Translate** or **Ctrl+Enter** |
| Translate a whole file | **File → Open text file**, then Translate |
| Save the Hindi | **File → Save translation** (**Ctrl+S**) |
| Get both languages side by side | **File → Save side-by-side** — opens in Excel |
| Stop a long translation | **Esc** |

Blank lines, indentation, bullets and numbering are preserved, so a formatted
document comes back with the same shape. Where Anuvad Plus is unsure of a
translation it **keeps the English** and tells you which lines those were,
rather than showing you something it cannot vouch for.

### The dictionary

Press **Ctrl+D**, or double-click any word in either pane.

- **Both directions.** Type `sanction` or type `मंज़ूरी` — it notices which
  script you are using and searches that way. The label above the box shows
  which direction is active.
- **Pronunciation.** English words show IPA (`/ˈɡʌ.vɚ.mənt/`), a plain
  respelling (`GUH-vur-muhnt`) and the syllable count. Press **🔊 Speak** to
  hear it, using the voice built into Windows.
- **Similar words.** Misspell something and it offers the closest matches —
  type `governmnet` and it suggests *government*. Click any suggestion to jump
  to it.
- **Related words.** Every entry shows clickable synonyms and antonyms.
- **Spelling variants are handled.** `मंज़ूरी` and `मंजूरी` find the same entry,
  as do words written with a chandrabindu instead of an anusvara.

### The government glossary

The **Glossary** in the navigation rail lists 177 central government
administrative terms across 15 categories — designations, noting and drafting,
service matters, finance, procurement, legislative, official language and more.
Each carries the English and Hindi headword, a definition in **both** languages,
and an example sentence in **both**.

### Appearance

**Ctrl+T** switches between the light and dark themes. **Ctrl +** and
**Ctrl −** change the text size. Both are remembered.

---

## Checking the installation

Inside the app: **Help → About** shows the version, and the status bar names the
model and dictionary in use.

From a command prompt, in the installation folder:

```bat
AnuvadPlus.exe --check
```

```
  [ok]   Python 3.13.1
  [ok]   tkinter (window toolkit) available
  [ok]   ctranslate2 4.8.1
  [ok]   sentencepiece 0.2.2
  [ok]   model: C:\...\Anuvad Plus\models\en_hi
  [ok]   test translation: यह एक परीक्षण है।
  [ok]   dictionary: C:\...\Anuvad Plus\models\dictionary\dictionary.sqlite
         150052 head words, 177 administrative terms

All checks passed.
```

The command line can also do the work directly:

```bat
AnuvadPlus.exe --file input.txt --out hindi.txt
AnuvadPlus.exe --define sanction
AnuvadPlus.exe --define अधिसूचना
AnuvadPlus.exe --define government --speak
AnuvadPlus.exe --admin-glossary
```

---

## If something goes wrong

### "Windows protected your PC" when running the installer

Windows SmartScreen shows this for any installer that is not code-signed, which
includes this one. Click **More info** → **Run anyway**. Signing requires a paid
certificate; if your organisation has one, sign `AnuvadPlusSetup.exe` with it
and the warning disappears.

### "DLL load failed" or "One component is missing"

The PC is missing Microsoft's C++ runtime. The installer normally handles this
by itself. If you used the portable folder instead, run `vc_redist.x64.exe` from
[aka.ms/vs/17/release/vc_redist.x64.exe](https://aka.ms/vs/17/release/vc_redist.x64.exe)
once — the app tells you this in plain words when it happens.

### Hindi shows as boxes □□□

**Tools → Settings**, and choose **Nirmala UI** or **Mangal**. Both come with
Windows.

### Speak does nothing

Speech uses the voice built into Windows, reached through PowerShell. If
PowerShell is blocked by policy on that PC, the written pronunciation still
works — only the audio is unavailable. The status line says so when you press
Speak.

### A word is not in the dictionary

Try the base form. Coverage is about 150,000 head words, and roughly 36,000 of
them carry a pronunciation — every common word does, but rare technical terms
and proper nouns may not.

### Translation feels slow

**Tools → Settings**: set **Beam size** to 1 or 2, raise **Sentences per batch**
to 32, and set **CPU threads** to the number of cores. Quality drops very
slightly; speed improves a lot.

---

## Moving or removing it

**Move**: copy the folder, or run the installer again on the other PC.

**Remove**: use *Add or remove programs*, or the uninstaller in the Start Menu.
Settings live in `%LOCALAPPDATA%\AnuvadPlus\settings.json` and are removed with
it.

---

## Frequently asked

**Does it ever use the internet?**
No. There is no network code in the application. Downloading happens only in
Part A, on a different machine.

**Does the offline PC need Python?**
No. The `.exe` has its own Python inside it.

**How big is it?**
The installer is around 180 MB; installed, about 400 MB. Most of that is the
translation model and the dictionary.

**How accurate is the translation?**
Good on ordinary prose; weaker on idiom, poetry, and dense legal or technical
wording. Sentences are translated independently, so context does not carry
across sentence boundaries. Have important output checked by a Hindi speaker.

**Can we add our own terminology?**
Yes. Edit `data\admin_glossary.tsv` — a tab-separated file Excel opens — then
rebuild on a connected PC with `python tools\build_dictionary.py` and re-run the
build script.
