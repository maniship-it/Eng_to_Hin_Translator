@echo off
setlocal EnableExtensions
title English to Hindi Translator - Setup

echo ============================================================
echo   English to Hindi Translator - offline setup
echo ============================================================
echo.

cd /d "%~dp0"

rem ---- locate a Python interpreter -------------------------------------
set "PY_CMD="
where py >nul 2>&1 && set "PY_CMD=py -3"
if not defined PY_CMD (
    where python >nul 2>&1 && set "PY_CMD=python"
)
if not defined PY_CMD (
    echo [ERROR] Python was not found on this PC.
    echo.
    echo Install 64-bit Python 3.11 or newer from python.org, and make sure
    echo you tick "Add python.exe to PATH" during setup.
    echo.
    pause
    exit /b 1
)

echo Using interpreter: %PY_CMD%
%PY_CMD% --version
echo.

rem ---- check tkinter is present ----------------------------------------
%PY_CMD% -c "import tkinter" >nul 2>&1
if errorlevel 1 (
    echo [ERROR] This Python was installed without tkinter.
    echo Re-run the Python installer and enable "tcl/tk and IDLE".
    echo.
    pause
    exit /b 1
)

rem ---- create the virtual environment ----------------------------------
if exist ".venv\Scripts\python.exe" (
    echo Reusing the existing virtual environment in .venv
) else (
    echo Creating a virtual environment in .venv ...
    %PY_CMD% -m venv .venv
    if errorlevel 1 (
        echo [ERROR] Could not create the virtual environment.
        pause
        exit /b 1
    )
)

set "VENV_PY=%~dp0.venv\Scripts\python.exe"

rem ---- install the dependencies ----------------------------------------
if exist "wheels\*.whl" (
    echo.
    echo Installing bundled packages from wheels\ ^(no internet needed^) ...
    "%VENV_PY%" -m pip install --no-index --find-links "wheels" --upgrade pip >nul 2>&1
    "%VENV_PY%" -m pip install --no-index --find-links "wheels" -r requirements.txt
) else (
    echo.
    echo No wheels\ folder found - installing from the internet instead.
    "%VENV_PY%" -m pip install --upgrade pip
    "%VENV_PY%" -m pip install -r requirements.txt
)

if errorlevel 1 (
    echo.
    echo [ERROR] Installing the dependencies failed.
    echo.
    echo If you see "No matching distribution found", the bundled wheels were
    echo built for a different Python version. Check bundle-info.txt for the
    echo version this bundle targets.
    echo.
    pause
    exit /b 1
)

echo.
echo ============================================================
echo   Setup finished.
echo ============================================================
echo.

rem ---- verify the install ----------------------------------------------
set "PYTHONPATH=%~dp0src"
"%VENV_PY%" -m entohin --check
echo.
echo Start the app with run.bat
echo.
pause
endlocal
