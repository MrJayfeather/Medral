@echo off
setlocal enabledelayedexpansion
cd /d "%~dp0"

set VPS=144.124.243.108

echo ============================================================
echo  Medral Release
echo ============================================================
echo.

:: ---- bump version ----
set /p CUR_VERSION=<version.txt
set /p NEW_VERSION="New version (current: !CUR_VERSION!): "
if "!NEW_VERSION!"=="" ( echo Cancelled & exit /b 0 )

echo !NEW_VERSION!> version.txt
echo [ok] version.txt = !NEW_VERSION!

:: ---- build ----
echo.
echo [build] Building MedralPlayer.exe...
call build_all.bat
if errorlevel 1 exit /b 1

:: ---- git commit + push ----
echo.
echo [git] Committing version bump...
git add version.txt
git commit -m "Release v!NEW_VERSION!"
git push origin HEAD:main

:: ---- upload exe to VPS ----
echo.
echo [upload] Uploading to VPS (!VPS!)...

where scp >nul 2>&1
if errorlevel 1 (
    echo [error] scp not found. Install OpenSSH or Git for Windows.
    pause & exit /b 1
)

ssh root@!VPS! "mkdir -p /opt/medral/dist"
scp dist\MedralPlayer.exe root@!VPS!:/opt/medral/dist/MedralPlayer.exe
if errorlevel 1 ( echo [error] Upload failed & pause & exit /b 1 )

scp version.txt root@!VPS!:/opt/medral/version.txt
if errorlevel 1 ( echo [error] version.txt upload failed & pause & exit /b 1 )

:: ---- update server code on VPS ----
echo.
echo [deploy] Updating server code on VPS...
ssh root@!VPS! "cd /opt/medral && git pull && chown -R medral:medral /opt/medral && systemctl restart medral"
if errorlevel 1 ( echo [error] Server update failed & pause & exit /b 1 )

echo.
echo ============================================================
echo  Released v!NEW_VERSION!
echo  Server updated and restarted. Clients will see the update
echo  prompt next time they connect.
echo ============================================================
pause
