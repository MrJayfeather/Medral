@echo off
setlocal
cd /d "%~dp0.."

echo ============================================================
echo  Medral Client Build
echo ============================================================

:: ---- venv ----
if not exist "venv\Scripts\activate.bat" (
    echo [setup] Creating virtual environment...
    python -m venv venv
)
call venv\Scripts\activate.bat

:: ---- install client deps ----
echo [setup] Installing client dependencies...
pip install -r client\requirements.txt -q
if errorlevel 1 ( echo [error] pip install failed & pause & exit /b 1 )

:: ---- build ----
echo [build] Running PyInstaller...
pyinstaller ^
  --onefile ^
  --windowed ^
  --name "MedralPlayer" ^
  --paths "client" ^
  --add-data "client\ui;ui" ^
  --add-data "client\styles.py;." ^
  --hidden-import "PyQt6.QtNetwork" ^
  --hidden-import "PyQt6.sip" ^
  --hidden-import "aiohttp" ^
  --hidden-import "websockets" ^
  client\main.py

if errorlevel 1 (
    echo [error] PyInstaller failed.
    pause
    exit /b 1
)

echo.
echo [done] dist\MedralPlayer.exe is ready.
pause
