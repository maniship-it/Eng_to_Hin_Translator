@echo off
setlocal EnableExtensions
title English to Hindi Translator - Check
cd /d "%~dp0"

set "PYTHONPATH=%~dp0src"

if not exist ".venv\Scripts\python.exe" (
    echo Not installed yet - run install.bat first.
    pause
    exit /b 1
)

".venv\Scripts\python.exe" -m entohin --check
echo.
pause
endlocal
