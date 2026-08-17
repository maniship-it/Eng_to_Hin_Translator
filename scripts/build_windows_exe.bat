@echo off
setlocal EnableExtensions
title Build standalone Windows .exe
cd /d "%~dp0.."

echo ============================================================
echo   Building a standalone EngToHinTranslator.exe
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

echo.
echo Running PyInstaller ...
python -m PyInstaller --noconfirm entohin.spec
if errorlevel 1 goto :failed

echo.
echo Copying the model next to the executable ...
xcopy /E /I /Y "models" "dist\EngToHinTranslator\models" >nul
if errorlevel 1 goto :failed

echo.
echo ============================================================
echo   Done: dist\EngToHinTranslator\EngToHinTranslator.exe
echo ============================================================
echo.
echo Copy the whole dist\EngToHinTranslator folder to the offline PC
echo and double-click EngToHinTranslator.exe. No install needed.
echo.
pause
exit /b 0

:failed
echo.
echo [ERROR] The build failed - see the messages above.
pause
exit /b 1
