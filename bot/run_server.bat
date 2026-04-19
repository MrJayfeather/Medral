@echo off
setlocal enabledelayedexpansion
cd /d "%~dp0.."

echo ============================================================
echo  Medral Server
echo ============================================================

:: ---- check .env ----
if not exist ".env" (
    if exist ".env.example" (
        copy ".env.example" ".env" >nul
        echo [setup] Created .env from .env.example
        echo [setup] Open .env and set DISCORD_TOKEN, then run this script again.
        pause
        exit /b 1
    )
    echo [error] .env not found. Create it from .env.example
    pause
    exit /b 1
)

:: ---- check Python ----
python --version >nul 2>&1
if errorlevel 1 (
    echo [error] Python not found. Install Python 3.10+ and add it to PATH.
    pause
    exit /b 1
)

:: ---- check FFmpeg ----
ffmpeg -version >nul 2>&1
if errorlevel 1 (
    echo [warning] FFmpeg not found on PATH. Audio playback will not work.
    echo           Download from https://ffmpeg.org/download.html and add bin/ to PATH.
    echo.
)

:: ---- create venv if missing ----
if not exist "venv\Scripts\activate.bat" (
    echo [setup] Creating virtual environment...
    python -m venv venv
    if errorlevel 1 (
        echo [error] Failed to create venv.
        pause
        exit /b 1
    )
)

:: ---- activate and install deps ----
call venv\Scripts\activate.bat
echo [setup] Installing / updating dependencies...
pip install -r requirements.txt -q
if errorlevel 1 (
    echo [error] pip install failed.
    pause
    exit /b 1
)

:: ---- start server ----
echo.
echo [server] Starting (Ctrl+C to stop)...
echo.
cd bot
python api.py
