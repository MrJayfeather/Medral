@echo off
setlocal
cd /d "%~dp0.."

echo ============================================================
echo  Medral Client Build (standalone)
echo ============================================================

if not exist "venv\Scripts\activate.bat" (
    echo [setup] Creating virtual environment...
    python -m venv venv
)
call venv\Scripts\activate.bat

echo [setup] Installing dependencies...
pip install -q -r client\requirements.txt
if errorlevel 1 ( echo [error] pip install failed & pause & exit /b 1 )

echo [build] Running PyInstaller...
pyinstaller client\client.spec --distpath dist --workpath build\client --noconfirm
if errorlevel 1 ( echo [error] Build failed & pause & exit /b 1 )

copy /y version.txt dist\version.txt >nul

echo.
echo [done] dist\MedralPlayer.exe
pause
