@echo off
setlocal
cd /d "%~dp0.."

where pwsh.exe >nul 2>nul
if errorlevel 1 (
  echo [ERROR] PowerShell 7 ^(pwsh.exe^) was not found.
  pause
  exit /b 1
)

echo ============================================================
echo Codex App Transfer r46 - FAST REAL-USE BUILD
echo ============================================================
echo This intentionally skips the long validation suite.
echo Goal: build an installable r46 ASAP for real old-thread testing.
echo.

pwsh.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File ".\scripts\build-r46-fast-real-use.ps1"
set "RC=%ERRORLEVEL%"
echo.
if not "%RC%"=="0" (
  echo [FAILED] r46 FAST REAL-USE build exit code: %RC%
) else (
  echo [PASS] r46 FAST REAL-USE installer is ready.
  echo Output root: V:\Codex-App-Transfer-Packages\r46-real-use\
)
pause
exit /b %RC%
