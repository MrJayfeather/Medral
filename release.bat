@echo off
setlocal enabledelayedexpansion
cd /d "%~dp0"

echo ============================================================
echo  Medral Release
echo ============================================================
echo.

:: ---- bump version ----
set /p NEW_VERSION="New version (current: %~dp0version.txt content): "
if "!NEW_VERSION!"=="" ( echo Cancelled & exit /b 0 )

echo !NEW_VERSION!> version.txt
echo [ok] version.txt = !NEW_VERSION!

:: ---- build ----
echo.
echo [build] Building MedralPlayer.exe...
call build_all.bat
if errorlevel 1 exit /b 1

:: ---- upload to VPS ----
echo.
echo [upload] Uploading to VPS (89.124.90.59)...

where scp >nul 2>&1
if errorlevel 1 (
    echo [error] scp not found. Install OpenSSH or Git for Windows.
    pause & exit /b 1
)

scp -o StrictHostKeyChecking=no dist\MedralPlayer.exe root@89.124.90.59:/opt/medral/dist/MedralPlayer.exe
if errorlevel 1 ( echo [error] Upload failed & pause & exit /b 1 )

scp -o StrictHostKeyChecking=no version.txt root@89.124.90.59:/opt/medral/version.txt
if errorlevel 1 ( echo [error] version.txt upload failed & pause & exit /b 1 )

:: ---- git commit + push ----
echo.
echo [git] Committing version bump...
git add version.txt
git commit -m "Release v!NEW_VERSION!"
git push origin HEAD:main

echo.
echo ============================================================
echo  Released v!NEW_VERSION!
echo  Clients will see the update prompt next time they connect.
echo ============================================================
pause
