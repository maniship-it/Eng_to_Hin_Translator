@echo off
setlocal EnableExtensions EnableDelayedExpansion
title Anuvad Plus - build the Windows installer
cd /d "%~dp0.."

echo ================================================================
echo   Anuvad Plus - building AnuvadPlusSetup.exe
echo ================================================================
echo.
echo   Run this ONCE, on a Windows PC that HAS internet access.
echo   The installer it produces works on any offline Windows PC.
echo.

rem ---------- 1. Python ------------------------------------------------
where python >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python was not found on PATH.
    echo         Install Python 3.13 ^(64-bit^) from python.org and tick
    echo         "Add python.exe to PATH".
    goto :failed
)
python --version
echo.

rem ---------- 2. Build dependencies ------------------------------------
echo [1/6] Installing build dependencies ...
python -m pip install --upgrade pip >nul
python -m pip install -r requirements-dev.txt
if errorlevel 1 goto :failed
echo.

rem ---------- 3. Translation model -------------------------------------
echo [2/6] Translation model ...
if exist "models\en_hi\model\model.bin" (
    echo       already present, skipping.
) else (
    python tools\fetch_model.py --no-verify
    if errorlevel 1 goto :failed
)
echo.

rem ---------- 4. Dictionary --------------------------------------------
echo [3/6] Dictionary database ...
if exist "models\dictionary\dictionary.sqlite" (
    echo       already present, skipping.
) else (
    python tools\build_dictionary.py
    if errorlevel 1 goto :failed
)
echo.

rem ---------- 5. Icon and executable ------------------------------------
echo [4/6] Application icon ...
python tools\make_icon.py
if errorlevel 1 goto :failed
echo.

echo [5/6] Building AnuvadPlus.exe with PyInstaller ...
python -m PyInstaller --noconfirm anuvad_plus.spec
if errorlevel 1 goto :failed

echo       Copying the model and dictionary next to the executable ...
xcopy /E /I /Y "models" "dist\AnuvadPlus\models" >nul
if errorlevel 1 goto :failed
echo.

rem ---------- 6. Microsoft C++ runtime ----------------------------------
echo [6/6] Microsoft C++ runtime for the installer ...
if exist "installer\vc_redist.x64.exe" (
    echo       already downloaded, skipping.
) else (
    powershell -NoProfile -Command ^
      "try { Invoke-WebRequest -Uri 'https://aka.ms/vs/17/release/vc_redist.x64.exe' -OutFile 'installer\vc_redist.x64.exe' -UseBasicParsing; exit 0 } catch { exit 1 }"
    if errorlevel 1 (
        echo       [warn] could not download it. The installer will still be
        echo              built, and will work on any PC that already has the
        echo              runtime - which is nearly all of them.
    )
)
echo.

rem ---------- Inno Setup -------------------------------------------------
set "ISCC="
for %%P in (
  "%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe"
  "%ProgramFiles%\Inno Setup 6\ISCC.exe"
  "%ProgramFiles(x86)%\Inno Setup 5\ISCC.exe"
) do (
  if exist %%P set "ISCC=%%~P"
)

if not defined ISCC (
    echo ================================================================
    echo   AnuvadPlus.exe is ready:  dist\AnuvadPlus\AnuvadPlus.exe
    echo ================================================================
    echo.
    echo   Inno Setup was not found, so the single-file installer was not
    echo   built. You have two options:
    echo.
    echo     A^) Copy the whole dist\AnuvadPlus folder to the offline PC and
    echo        run AnuvadPlus.exe. It needs nothing installed.
    echo.
    echo     B^) Install Inno Setup 6 from jrsoftware.org/isdl.php and run
    echo        this script again to get AnuvadPlusSetup.exe.
    echo.
    pause
    exit /b 0
)

echo Building the installer with Inno Setup ...
"%ISCC%" "installer\anuvad_plus.iss"
if errorlevel 1 goto :failed

echo.
echo ================================================================
echo   Done.
echo ================================================================
echo.
echo   Installer:  dist\AnuvadPlusSetup.exe
echo   Portable :  dist\AnuvadPlus\AnuvadPlus.exe
echo.
echo   Copy AnuvadPlusSetup.exe to any offline Windows PC and run it.
echo   Nothing else needs to be installed there.
echo.
pause
exit /b 0

:failed
echo.
echo [ERROR] The build stopped - see the messages above.
echo.
pause
exit /b 1
