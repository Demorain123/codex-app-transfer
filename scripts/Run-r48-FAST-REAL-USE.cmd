@echo off
setlocal
cd /d "%~dp0.."

echo ============================================================
echo Codex App Transfer r48 - FAST REAL-USE BUILD
echo ============================================================
echo Reuses the proven r47/r46/r39-r42 local build caches.
echo Full validation suites remain intentionally skipped.
echo.

python ".\scripts\apply_r48_fast_current_tree.py"
if errorlevel 1 (
  echo [FAILED] r48 fast current-tree composition.
  pause
  exit /b 1
)

python ".\scripts\prepare-r48-fast-builder.py"
if errorlevel 1 (
  echo [FAILED] r48 fast builder preparation.
  pause
  exit /b 1
)

pwsh -NoProfile -ExecutionPolicy Bypass -File ".\scripts\build-r48-fast-real-use.ps1"
set "RC=%ERRORLEVEL%"
if not "%RC%"=="0" (
  echo.
  echo [FAILED] r48 FAST REAL-USE build exit code: %RC%
  pause
  exit /b %RC%
)

echo.
echo [PASS] r48 FAST REAL-USE build complete.
pause
exit /b 0
