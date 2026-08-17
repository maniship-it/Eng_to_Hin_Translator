# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller build recipe for a standalone Windows application.

Build it on Windows with::

    pip install -r requirements-dev.txt
    pyinstaller setu.spec

The result is ``dist/Setu/`` containing Setu.exe
and everything it needs -- no Python installation required on the target PC.

The model is deliberately NOT embedded: it is large and changes independently.
``scripts/build_windows_exe.bat`` copies ``models/`` next to the .exe, which is
where the application looks when it is frozen.  The dictionary database in
``models/dictionary/`` travels the same way.
"""

from PyInstaller.utils.hooks import collect_dynamic_libs

block_cipher = None

binaries = collect_dynamic_libs("ctranslate2") + collect_dynamic_libs("sentencepiece")

a = Analysis(
    ["src/setu/__main__.py"],
    pathex=["src"],
    binaries=binaries,
    datas=[],
    hiddenimports=[
        "ctranslate2",
        "sentencepiece",
        "setu.gui",
        "setu.gui_dictionary",
        "setu.dictionary",
        "setu.textio",
        "setu.translator",
        "setu.model",
        "setu.config",
        "setu.placeholders",
        "setu.segmenter",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    # Keep the bundle small: none of these are used.
    excludes=["torch", "transformers", "matplotlib", "scipy", "pandas",
              "PyQt5", "PySide2", "PIL", "notebook", "IPython"],
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
    name="Setu",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,          # windowed app, no console box
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
    name="Setu",
)
