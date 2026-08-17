@echo off
setlocal EnableExtensions
cd /d "%~dp0"

set "PYTHONPATH=%~dp0src"

if exist ".venv\Scripts\pythonw.exe" (
    start "" ".venv\Scripts\pythonw.exe" -m entohin
    exit /b 0
)

if exist ".venv\Scripts\python.exe" (
    ".venv\Scripts\python.exe" -m entohin
    exit /b %errorlevel%
)

echo The application is not installed yet.
echo Run install.bat first.
echo.
pause
exit /b 1
