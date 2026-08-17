@echo off
setlocal EnableExtensions
title SETU - build standalone .exe
cd /d "%~dp0.."

echo ============================================================
echo   Building a standalone Setu.exe
echo ============================================================
echo.
echo Run this on an ONLINE Windows PC. The result needs no Python
echo on the target machine.
echo.

where python >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python was not found on PATH.
    pause
    exit /b 1
)

echo Installing build dependencies ...
python -m pip install -r requirements-dev.txt
if errorlevel 1 goto :failed

if not exist "models\en_hi\model\model.bin" (
    echo.
    echo Model not found - downloading it now ...
    python tools\fetch_model.py --no-verify
    if errorlevel 1 goto :failed
)

if not exist "models\dictionary\dictionary.sqlite" (
    echo.
    echo Dictionary not found - building it now ...
    python tools\build_dictionary.py
    if errorlevel 1 goto :failed
)

echo.
echo Running PyInstaller ...
python -m PyInstaller --noconfirm setu.spec
if errorlevel 1 goto :failed

echo.
echo Copying the model next to the executable ...
xcopy /E /I /Y "models" "dist\Setu\models" >nul
if errorlevel 1 goto :failed

echo.
echo ============================================================
echo   Done: dist\Setu\Setu.exe
echo ============================================================
echo.
echo Copy the whole dist\Setu folder to the offline PC
echo and double-click Setu.exe. No install needed.
echo.
pause
exit /b 0

:failed
echo.
echo [ERROR] The build failed - see the messages above.
pause
exit /b 1
