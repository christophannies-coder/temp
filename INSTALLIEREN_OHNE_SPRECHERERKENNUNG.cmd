@echo off
setlocal
cd /d "%~dp0"

set "PY=python"
where py >nul 2>nul
if %errorlevel%==0 (
    py -3.11 --version >nul 2>nul
    if not errorlevel 1 (
        set "PY=py -3.11"
    ) else (
        py -3.12 --version >nul 2>nul
        if not errorlevel 1 set "PY=py -3.12"
    )
)

if not exist ".venv\Scripts\python.exe" (
    %PY% -m venv .venv
)
if errorlevel 1 goto :error

".venv\Scripts\python.exe" -m pip install --upgrade pip setuptools wheel
if errorlevel 1 goto :error

".venv\Scripts\python.exe" -m pip install faster-whisper edge-tts deep-translator langdetect tkinterdnd2
if errorlevel 1 goto :error

echo.
echo Installation ohne pyannote abgeschlossen.
echo Die Transkription und Voiceover-Erzeugung funktionieren,
echo nur die automatische Sprechertrennung bleibt deaktiviert.
pause
exit /b 0

:error
echo Installation fehlgeschlagen.
pause
exit /b 1
