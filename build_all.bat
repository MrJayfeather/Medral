@echo off
setlocal enabledelayedexpansion
cd /d "%~dp0"

echo ============================================================
echo  Medral — Full Build  (Server + Client)
echo ============================================================
echo.

:: ---- venv ----
if not exist "venv\Scripts\activate.bat" (
    echo [setup] Creating virtual environment...
    python -m venv venv
    if errorlevel 1 ( echo [error] Failed to create venv & pause & exit /b 1 )
)
call venv\Scripts\activate.bat

:: ---- all deps (server + client + pyinstaller) ----
echo [setup] Installing dependencies...
pip install --pre -r requirements.txt -q
if errorlevel 1 ( echo [error] pip install failed & pause & exit /b 1 )
pip install -r client\requirements.txt -q
if errorlevel 1 ( echo [error] pip install (client) failed & pause & exit /b 1 )

:: ---- check ffmpeg ----
ffmpeg -version >nul 2>&1
if errorlevel 1 (
    echo [warning] FFmpeg not found on PATH.
    echo           MedralServer.exe will not play audio without FFmpeg.
    echo           Get it from https://ffmpeg.org and put ffmpeg.exe next to MedralServer.exe.
    echo.
)

echo.
echo ============================================================
echo  Building MedralServer.exe
echo ============================================================
pyinstaller bot\server.spec --distpath dist --workpath build\server --noconfirm
if errorlevel 1 ( echo [error] Server build failed & pause & exit /b 1 )

echo.
echo ============================================================
echo  Building MedralPlayer.exe
echo ============================================================
pyinstaller client\client.spec --distpath dist --workpath build\client --noconfirm
if errorlevel 1 ( echo [error] Client build failed & pause & exit /b 1 )

:: ---- copy version.txt into dist/ so client can read it ----
copy /y version.txt dist\version.txt >nul

echo.
echo ============================================================
echo  Done!
echo ============================================================
echo   dist\MedralServer.exe  — run on your PC or copy to VPS
echo   dist\MedralPlayer.exe  — share with anyone; auto-starts server
echo.
echo  To distribute: put BOTH exe files + .env in the same folder.
echo  Users only need MedralPlayer.exe; it will start the server.
echo ============================================================
pause
