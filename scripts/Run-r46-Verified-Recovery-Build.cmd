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
echo Codex App Transfer r46 - Verified Recovery Build
echo ============================================================
echo This build does NOT modify any Codex conversation.
echo It only materializes, tests, compiles and packages r46.
echo.

pwsh.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File ".\scripts\build-r46-recovery-local-package-verified.ps1"
set "RC=%ERRORLEVEL%"
echo.
if not "%RC%"=="0" (
  echo [FAILED] r46 verified build exit code: %RC%
) else (
  echo [PASS] r46 verified recovery package build completed.
  echo Output root: V:\Codex-App-Transfer-Packages\r46-thread-recovery\
)
pause
exit /b %RC%
