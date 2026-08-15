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

echo.
echo [1/4] Pruefe Python...
%PY% --version
if errorlevel 1 (
    echo.
    echo FEHLER: Python 3.11 wurde nicht gefunden.
    echo Installiere Python 3.11 x64 und aktiviere "Add Python to PATH".
    pause
    exit /b 1
)

echo.
echo [2/4] Erstelle virtuelle Umgebung...
if not exist ".venv\Scripts\python.exe" (
    %PY% -m venv .venv
)
if errorlevel 1 goto :error

echo.
echo [3/4] Aktualisiere pip...
".venv\Scripts\python.exe" -m pip install --upgrade pip setuptools wheel
if errorlevel 1 goto :error

echo.
echo [4/4] Installiere Python-Pakete...
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 goto :error

echo.
where ffmpeg >nul 2>nul
if errorlevel 1 (
    echo HINWEIS: FFmpeg wurde nicht im PATH gefunden.
    echo Installiere FFmpeg und fuege dessen bin-Ordner zum PATH hinzu.
) else (
    echo FFmpeg wurde gefunden.
)

echo.
echo Installation abgeschlossen.
echo Starte danach STARTEN.cmd.
pause
exit /b 0

:error
echo.
echo Installation fehlgeschlagen.
pause
exit /b 1
