@echo off
setlocal EnableDelayedExpansion
chcp 65001 >nul
cd /d "%~dp0"
title OCR2Heb - build

echo ==============================================================
echo   OCR2Heb - build  (creates release\OCR2Heb.exe)
echo ==============================================================
echo.

rem ---------------------------------------------------------------- find Python
set "PY="
for %%V in (3.12 3.11 3.13 3.10 3.9) do (
    if not defined PY (
        py -%%V -c "import sys" >nul 2>nul && set "PY=py -%%V"
    )
)
if not defined PY (
    python -c "import sys; assert (3,9) <= sys.version_info[:2] <= (3,13)" >nul 2>nul && set "PY=python"
)
if not defined PY (
    echo [X] Python 3.9 - 3.13 was not found. Install Python 3.12 from python.org
    echo     ^(tick "Add python.exe to PATH"^) and run this file again.
    pause
    exit /b 1
)
echo Using: %PY%
%PY% --version

rem ---------------------------------------------------------------- virtual env
if not exist ".venv\Scripts\python.exe" (
    echo.
    echo [1/5] Creating virtual environment...
    %PY% -m venv .venv
    if errorlevel 1 ( echo [X] could not create venv & pause & exit /b 1 )
)
set "VPY=.venv\Scripts\python.exe"

echo.
echo [2/5] Installing packages (first time takes a few minutes)...
"%VPY%" -m pip install --upgrade pip >nul 2>nul
"%VPY%" -m pip install -r requirements.txt
if errorlevel 1 (
    echo.
    echo winrt packages failed to install - trying the winsdk fallback...
    "%VPY%" -m pip install -r requirements-winsdk.txt
    if errorlevel 1 ( echo [X] package install failed & pause & exit /b 1 )
)

rem ---------------------------------------------------------------- self-test (source)
echo.
echo [3/5] Self-test from source (OCR, translation, mouse hook)...
"%VPY%" src\main.py --selftest
if errorlevel 1 (
    echo.
    echo [!] The self-test reported a problem ^(see FAIL lines above^).
    choice /c YN /n /m "Build the exe anyway? [Y/N] "
    if errorlevel 2 ( pause & exit /b 1 )
)

rem ---------------------------------------------------------------- package
echo.
echo [4/5] Building the single-file exe with PyInstaller...
"%VPY%" tools\make_icon.py
"%VPY%" -m PyInstaller --noconfirm --clean --onefile --noconsole --uac-admin ^
    --name OCR2Heb --icon assets\app.ico --paths src ^
    --hidden-import winrt.windows.foundation ^
    --hidden-import winrt.windows.foundation.collections ^
    --hidden-import winrt.windows.storage ^
    --hidden-import winrt.windows.storage.streams ^
    --hidden-import winrt.windows.globalization ^
    --hidden-import winrt.windows.graphics.imaging ^
    --hidden-import winrt.windows.media.ocr ^
    --exclude-module tkinter --exclude-module matplotlib --exclude-module numpy ^
    src\main.py
if errorlevel 1 ( echo [X] PyInstaller failed & pause & exit /b 1 )

if not exist release mkdir release
copy /y dist\OCR2Heb.exe release\OCR2Heb.exe >nul
copy /y uninstall.bat release\uninstall.bat >nul
copy /y HEBREW_NOTE.txt release\HEBREW_NOTE.txt >nul

rem ---------------------------------------------------------------- self-test (exe)
echo.
echo [5/5] Self-test of the finished exe (Windows will ask for Administrator - click Yes)...
set "REPORT=%LOCALAPPDATA%\OCR2Heb\logs\selftest.txt"
if exist "%REPORT%" del "%REPORT%"
powershell -NoProfile -Command "Start-Process -FilePath '%CD%\release\OCR2Heb.exe' -ArgumentList '--selftest' -Verb RunAs -Wait"
if exist "%REPORT%" (
    type "%REPORT%"
) else (
    echo [!] The exe produced no report - it probably failed to start. Send me a screenshot of this window.
)

echo.
echo ==============================================================
echo   Done:  %CD%\release\OCR2Heb.exe
echo   Copy that single file to Grandpa's PC and double-click it once.
echo ==============================================================
pause
