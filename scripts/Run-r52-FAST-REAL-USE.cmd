@echo off
setlocal
cd /d "%~dp0.."

echo ============================================================
echo Codex App Transfer r52 - FAST REAL-USE BUILD
echo ============================================================
echo Reuses the proven r51/r50/r49/r48/r47/r46 local build caches.
echo Fixes Sub2API private compaction across GPT/Luna/Grok model switches.
echo Full validation suites remain intentionally skipped.
echo.

python ".\scripts\apply_r52_fast_current_tree.py"
if errorlevel 1 (
  echo [FAILED] r52 fast current-tree composition.
  pause
  exit /b 1
)

python ".\scripts\prepare-r52-fast-builder.py"
if errorlevel 1 (
  echo [FAILED] r52 fast builder preparation.
  pause
  exit /b 1
)

pwsh -NoProfile -ExecutionPolicy Bypass -File ".\scripts\build-r52-fast-real-use.ps1"
set "RC=%ERRORLEVEL%"
if not "%RC%"=="0" (
  echo.
  echo [FAILED] r52 FAST REAL-USE build exit code: %RC%
  pause
  exit /b %RC%
)

echo.
echo [PASS] r52 FAST REAL-USE build complete.
pause
exit /b 0
