# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller recipe for AnuvadPlus.exe.

Build it on Windows::

    pip install -r requirements-dev.txt
    pyinstaller --noconfirm anuvad_plus.spec

The result is ``dist/AnuvadPlus/`` containing ``AnuvadPlus.exe`` and every
library it needs. No Python installation is required on the machine that runs
it.

The model and the dictionary are deliberately NOT embedded: together they are
about 160 MB, they change independently of the code, and freezing them into the
executable would make every rebuild slow. ``scripts/Build Installer.bat`` copies
``models/`` next to the .exe, which is where the application looks when frozen.
"""

from PyInstaller.utils.hooks import collect_dynamic_libs

block_cipher = None

# CTranslate2 and SentencePiece ship compiled libraries that PyInstaller does
# not discover by import analysis alone.
binaries = collect_dynamic_libs("ctranslate2") + collect_dynamic_libs("sentencepiece")

a = Analysis(
    ["scripts/frozen_entry.py"],
    pathex=["src"],
    binaries=binaries,
    datas=[],
    hiddenimports=[
        "ctranslate2",
        "sentencepiece",
        "anuvad",
        "anuvad.config",
        "anuvad.dictionary",
        "anuvad.gui",
        "anuvad.gui_dictionary",
        "anuvad.hindi",
        "anuvad.model",
        "anuvad.placeholders",
        "anuvad.pronunciation",
        "anuvad.runtime",
        "anuvad.segmenter",
        "anuvad.speech",
        "anuvad.textio",
        "anuvad.theme",
        "anuvad.translator",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    # Keep the build small: none of these are used.
    excludes=[
        "torch", "transformers", "matplotlib", "scipy", "pandas",
        "PyQt5", "PyQt6", "PySide2", "PySide6", "PIL", "notebook",
        "IPython", "pytest", "setuptools", "pip",
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="AnuvadPlus",
    icon="installer/anuvad.ico" if __import__("os").path.exists(
        "installer/anuvad.ico") else None,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,          # a windowed app: no console box behind it
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="AnuvadPlus",
)
