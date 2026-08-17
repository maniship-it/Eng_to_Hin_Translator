@echo off
setlocal EnableExtensions
title SETU - Check
cd /d "%~dp0"

echo ============================================================
echo   SETU - checking this installation
echo ============================================================
echo.

set "PY_CMD="
where python >nul 2>&1 && set "PY_CMD=python"
if not defined PY_CMD (
    where py >nul 2>&1 && set "PY_CMD=py -3"
)

if not defined PY_CMD (
    echo   [FAIL] Python was not found on this PC.
    echo.
    echo   Install Python 3.13 ^(64-bit^) and tick "Add python.exe to PATH".
    echo.
    pause
    exit /b 1
)

%PY_CMD% "%~dp0Setu.py" --check
echo.
pause
endlocal
