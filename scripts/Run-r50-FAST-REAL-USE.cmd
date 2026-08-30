@echo off
setlocal
cd /d "%~dp0.."

echo ============================================================
echo Codex App Transfer r50 - FAST REAL-USE BUILD
echo ============================================================
echo Reuses the proven r49/r48/r47/r46 local build caches.
echo Adds same-session cross-model Responses replay compatibility.
echo Full validation suites remain intentionally skipped.
echo.

python ".\scripts\apply_r50_fast_current_tree.py"
if errorlevel 1 (
  echo [FAILED] r50 fast current-tree composition.
  pause
  exit /b 1
)

python ".\scripts\prepare-r50-fast-builder.py"
if errorlevel 1 (
  echo [FAILED] r50 fast builder preparation.
  pause
  exit /b 1
)

pwsh -NoProfile -ExecutionPolicy Bypass -File ".\scripts\build-r50-fast-real-use.ps1"
set "RC=%ERRORLEVEL%"
if not "%RC%"=="0" (
  echo.
  echo [FAILED] r50 FAST REAL-USE build exit code: %RC%
  pause
  exit /b %RC%
)

echo.
echo [PASS] r50 FAST REAL-USE build complete.
pause
exit /b 0
