@echo off
setlocal enabledelayedexpansion
cd /d "%~dp0"

echo ============================================================
echo  Medral Build — MedralPlayer.exe
echo ============================================================
echo.

if not exist "venv\Scripts\activate.bat" (
    echo [setup] Creating virtual environment...
    python -m venv venv
    if errorlevel 1 ( echo [error] Failed to create venv & pause & exit /b 1 )
)
call venv\Scripts\activate.bat

echo [setup] Installing dependencies...
pip install --pre -q -r requirements.txt
pip install -q -r client\requirements.txt
if errorlevel 1 ( echo [error] pip install failed & pause & exit /b 1 )

ffmpeg -version >nul 2>&1
if errorlevel 1 (
    echo [warning] FFmpeg not found. Audio won't work in local mode.
    echo           Get it from https://ffmpeg.org and put ffmpeg.exe next to MedralPlayer.exe.
    echo.
)

echo.
echo [build] PyInstaller...
pyinstaller client\client.spec --distpath dist --workpath build --noconfirm
if errorlevel 1 ( echo [error] Build failed & pause & exit /b 1 )

copy /y version.txt dist\version.txt >nul

echo.
echo ============================================================
echo  Done!  dist\MedralPlayer.exe
echo ============================================================
echo.
echo  To use locally:  copy MedralPlayer.exe + .env to one folder
echo  To connect VPS:  just run MedralPlayer.exe, enter server IP
echo  To publish update: run release.bat
echo ============================================================
pause
