@echo off
rem Removes the start-at-logon task and stops OCR2Heb. Afterwards OCR2Heb.exe can simply be deleted.
net session >nul 2>&1
if errorlevel 1 (
    powershell -NoProfile -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
    exit /b
)
schtasks /Delete /TN "OCR2Heb" /F
taskkill /F /IM OCR2Heb.exe
echo.
echo OCR2Heb was removed from startup and stopped. You can delete OCR2Heb.exe now.
pause
