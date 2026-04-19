@echo off
cd /d "%~dp0.."

if not exist "venv" (
    echo [error] venv not found. Run run_server.bat first to create it, or create a separate client venv.
    pause
    exit /b 1
)

call venv\Scripts\activate.bat
pip install -r client\requirements.txt -q

echo [build] Packaging client with PyInstaller...
pyinstaller ^
    --onefile ^
    --windowed ^
    --name "MedralPlayer" ^
    --add-data "client\ui;ui" ^
    client\main.py

echo [build] Done. Executable is in dist\MedralPlayer.exe
pause
