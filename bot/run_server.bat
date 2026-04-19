@echo off
setlocal enabledelayedexpansion
cd /d "%~dp0.."

:: Create .env from example if missing
if not exist ".env" (
    if exist ".env.example" (
        copy ".env.example" ".env" >nul
        echo [setup] Created .env from .env.example
        echo [setup] Edit .env and set your DISCORD_TOKEN, then re-run this script.
        pause
        exit /b 1
    ) else (
        echo [error] .env file not found. Create one based on .env.example
        pause
        exit /b 1
    )
)

:: Create venv if missing
if not exist "venv" (
    echo [setup] Creating virtual environment...
    python -m venv venv
    if errorlevel 1 (
        echo [error] Failed to create venv. Is Python 3.10+ installed?
        pause
        exit /b 1
    )
)

:: Activate and install deps
call venv\Scripts\activate.bat
echo [setup] Installing / updating dependencies...
pip install -r requirements.txt -q

:: Run server from bot directory so imports resolve
cd bot
echo [server] Starting...
python -m uvicorn api:app --host 0.0.0.0 --port 8000 --reload
