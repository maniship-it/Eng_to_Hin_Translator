# SETU — Installation Guide

**SETU** (सेतु, "bridge") is an offline English → Hindi translator with a
bilingual dictionary and a government administrative glossary. It runs entirely
on your PC and never uses the internet.

This guide has two halves:

- **[Part A](#part-a--prepare-the-usb-stick)** — done once, on a PC **with**
  internet. Produces a folder you copy to a USB stick.
- **[Part B](#part-b--install-on-the-offline-pc)** — done on the **offline** PC.
  Copy the folder, double-click one file. Nothing is installed.

The only thing the offline PC needs is **Python 3.13 (64-bit)**.

---

## Part A — prepare the USB stick

Do this on any computer with an internet connection. Windows, macOS or Linux
all work — the Windows files are downloaded correctly from any of them.

### A1. Get the project

```bash
git clone https://github.com/maniship-it/Eng_to_Hin_Translator.git
cd Eng_to_Hin_Translator
```

### A2. Build the bundle

```bash
pip install -r requirements.txt
python tools/make_offline_bundle.py --zip
```

This takes about five minutes and downloads roughly 250 MB. It produces
`dist/Setu-Offline/` containing everything:

| Item | What it is |
|---|---|
| `lib/` | Every Python library SETU needs, already unpacked |
| `models/en_hi/` | The neural translation model |
| `models/dictionary/` | The dictionary database, ~150,000 words |
| `src/`, `data/` | The application and the government glossary |
| `Start SETU.bat` | Double-click this to run SETU |
| `Check SETU.bat` | Reports any problem in plain language |
| `vc_redist.x64.exe` | Microsoft C++ runtime, only used if the PC needs it |
| `INSTALL.txt` | A short version of Part B, for whoever installs it |

The default target is **Python 3.13**. If the offline PC has a different
version, say so:

```bash
python tools/make_offline_bundle.py --python-version 312 --zip
```

### A3. Also download Python

Get the **Windows installer (64-bit)** for Python 3.13 from
[python.org/downloads/windows](https://www.python.org/downloads/windows/) and
put it on the USB stick next to the SETU folder.

Skip this only if you are certain the offline PC already has Python 3.13.

### A4. Copy to the USB stick

Copy the whole `Setu-Offline` folder (or its `.zip`) plus the Python installer.

Expect the folder to be around **250–300 MB**.

---

## Part B — install on the offline PC

### B1. Install Python — once, and only if it is missing

To check whether it is already there: press the **Windows key**, type
`python`, and see whether it appears.

If not, run the Python installer from the USB stick. On the very first screen:

> ☑ **Add python.exe to PATH** ← **tick this box**

Then click **Install Now**. Keep **tcl/tk and IDLE** ticked if you are offered
the choice — that provides the window toolkit SETU draws with.

This is the only thing that gets installed on the PC.

### B2. Copy the SETU folder

Copy the `Setu-Offline` folder from the USB stick to the PC — for example to
`C:\SETU`. Keep the folder together; everything SETU needs is inside it.

### B3. Start it

Double-click **`Start SETU.bat`**.

That is the entire installation. The window opens in a few seconds.

To make it easier to find later, right-click `Start SETU.bat` →
**Send to** → **Desktop (create shortcut)**, then rename the shortcut to SETU.

---

## Checking the installation

Double-click **`Check SETU.bat`**. It prints a report:

```
  [ok]   Python 3.13.1
  [ok]   tkinter (window toolkit) available
  [ok]   ctranslate2 4.8.1
  [ok]   sentencepiece 0.2.2
  [ok]   model: C:\SETU\models\en_hi
  [ok]   test translation: यह एक परीक्षण है।
  [ok]   dictionary: C:\SETU\models\dictionary\dictionary.sqlite
         150052 head words, 177 administrative terms

All checks passed.
```

Anything that is wrong is listed with the exact fix underneath it.

---

## If something goes wrong

### "Python was not found"

Python is not installed, or **Add python.exe to PATH** was not ticked during
setup. Re-run the Python installer, choose **Modify**, and make sure that box
is ticked. Then try again.

### "One component is missing" or "DLL load failed"

The PC does not have Microsoft's C++ runtime, which the translation engine
needs. Python does not include it.

**Fix:** double-click `vc_redist.x64.exe` in the SETU folder, accept the
prompt, and start SETU again. It takes about a minute and needs no internet.

Most Windows PCs already have this runtime because many programs install it, so
you will probably never see this message.

### "No module named tkinter"

Python was installed without the window toolkit. Re-run the Python installer,
choose **Modify**, and tick **tcl/tk and IDLE**.

### Hindi shows as boxes □□□

The font in use has no Devanagari characters. Go to **Tools → Settings** and
choose **Nirmala UI** or **Mangal**. Both ship with Windows.

### "No translation model found"

The `models` folder did not get copied, or only part of it did. Copy it again
from the USB stick into the SETU folder. You can also point SETU at it
directly: **Tools → Choose model folder**.

### The Dictionary tab says it is not available

Only the dictionary is missing — translation still works. Copy
`models\dictionary` across from the USB stick, or use
**Dictionary → Choose dictionary file**.

### Translation feels slow

**Tools → Settings**: set **Beam size** to 1 or 2, raise **Sentences per
batch** to 32, and set **CPU threads** to the number of cores in the PC.
Quality drops very slightly; speed improves a lot.

---

## Using SETU

Press **F1** inside the app at any time for the quick start guide.

| I want to… | Do this |
|---|---|
| Translate some text | Type on the left, press **Translate** (or **Ctrl+Enter**) |
| Translate a whole file | **File → Open text file**, then Translate |
| Save the Hindi | **File → Save translation** (**Ctrl+S**) |
| Get both languages side by side | **File → Save side-by-side** — opens in Excel |
| Look up a word | Double-click it, or press **Ctrl+D** |
| Find an official term | **Dictionary → Administrative glossary** |
| Make the text bigger | **Ctrl +** and **Ctrl −** |
| Stop a long translation | **Esc** |

Blank lines, indentation, bullets and numbering are preserved, so a formatted
document comes back with the same shape.

Where SETU is unsure of a translation it **keeps the English** and tells you
which lines those were, rather than showing you something it cannot vouch for.

---

## Moving SETU to another PC

Copy the whole SETU folder. Install Python 3.13 on the new PC if it is not
there. That is all — there is nothing registered in Windows, no services, and
nothing in the registry.

To uninstall, delete the folder. Settings live in
`%LOCALAPPDATA%\Setu\settings.json`; delete that too if you want no trace.

---

## Frequently asked

**Does SETU send anything over the internet?**
No. There is no network code in the application at all. The download tools are
separate scripts you run in Part A.

**Does it need administrator rights?**
Only the Python installer might. SETU itself runs as a normal user.

**Can it run from the USB stick directly?**
Yes, though it will be slower. Python still has to be installed on the PC.

**How accurate is it?**
Good for ordinary prose. Weaker on idiom, poetry and dense legal or technical
wording. Sentences are translated independently, so context does not carry
across sentence boundaries. Have important output checked by a Hindi speaker.

**Can I add my own terminology?**
Yes. Edit `data/admin_glossary.tsv` (a tab-separated file — Excel opens it),
then rebuild the dictionary on an internet-connected PC with
`python tools/build_dictionary.py`.
