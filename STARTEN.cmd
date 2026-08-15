@echo off
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\pythonw.exe" (
    echo Die virtuelle Umgebung fehlt.
    echo Fuehre zuerst INSTALLIEREN.cmd aus.
    pause
    exit /b 1
)

start "" ".venv\Scripts\pythonw.exe" app.py
