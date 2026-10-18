@echo off
chcp 65001 >nul
cd /d "%~dp0.."
title OCR2Heb bench watcher - leave this window open
if not exist ".venv\Scripts\python.exe" (
    echo The build environment .venv was not found. Run build.bat once first.
    pause
    exit /b 1
)
if not exist "bench\jobs" mkdir "bench\jobs"
echo ==============================================================
echo   OCR2Heb bench watcher
echo   Runs only a fixed list of test tasks on code placed in bench\jobs.
echo   Leave this window open while the AI agents work. Close it to stop.
echo ==============================================================
".venv\Scripts\python.exe" bench\watcher.py
pause
