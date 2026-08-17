@echo off
setlocal EnableExtensions
title SETU - English to Hindi Translator
cd /d "%~dp0"

rem ---- find Python -----------------------------------------------------
set "PY_CMD="
where pythonw >nul 2>&1 && set "PY_CMD=pythonw"
if not defined PY_CMD (
    if exist "%LOCALAPPDATA%\Programs\Python\Python313\pythonw.exe" (
        set "PY_CMD=%LOCALAPPDATA%\Programs\Python\Python313\pythonw.exe"
    )
)
if not defined PY_CMD (
    where py >nul 2>&1 && set "PY_CMD=py -3"
)

if not defined PY_CMD (
    echo.
    echo   Python was not found on this PC.
    echo.
    echo   SETU needs Python 3.13 ^(64-bit^). Install it from the
    echo   python-3.13 installer on the USB stick, or from python.org.
    echo.
    echo   IMPORTANT: during setup, tick "Add python.exe to PATH".
    echo.
    pause
    exit /b 1
)

rem ---- start the app ---------------------------------------------------
start "" %PY_CMD% "%~dp0Setu.py"
exit /b 0
