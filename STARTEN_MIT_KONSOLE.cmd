@echo off
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo Die virtuelle Umgebung fehlt.
    echo Fuehre zuerst INSTALLIEREN.cmd aus.
    pause
    exit /b 1
)

".venv\Scripts\python.exe" app.py
pause
