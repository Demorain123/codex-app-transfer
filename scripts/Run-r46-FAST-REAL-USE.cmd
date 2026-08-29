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
echo Latest recovery hotfixes are ALWAYS rematerialized before Cargo build.
echo.

echo [PRE] Ensure a reusable NASM is available for BoringSSL...
pwsh.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File ".\scripts\ensure-r46-portable-nasm.ps1"
if errorlevel 1 (
  echo [FAILED] NASM preflight failed.
  pause
  exit /b 1
)
set "PATH=%CD%\.tools\nasm;%PATH%"

echo [PRE] Force current r46 overlay composition so no stale recovery backend is reused...
pwsh.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File ".\scripts\build-r46-fast-real-use.ps1" -ForceMaterialize
set "RC=%ERRORLEVEL%"
echo.
if not "%RC%"=="0" (
  echo [FAILED] r46 FAST REAL-USE build exit code: %RC%
) else (
  echo [PASS] r46 FAST REAL-USE installer is ready.
  echo Output root: V:\Codex-App-Transfer-Packages\r46-real-use\
  echo.
  echo IMPORTANT BEFORE INSTALLING:
  echo   1. EXIT the currently running Codex App Transfer completely.
  echo   2. Codex Desktop itself MAY remain open.
  echo   3. Install the newly built FAST-REAL-USE exe.
  echo   4. Launch Transfer again, then test old-thread recovery.
  echo.
  echo In the next recovery log, the fresh build MUST contain:
  echo   stage=rpc_call method=thread/resume
  echo   stage=thread_loaded method=thread/resume
)
pause
exit /b %RC%
