@echo off
setlocal
cd /d "%~dp0.."

echo ============================================================
echo Codex App Transfer r53 - FAST REAL-USE BUILD
echo ============================================================
echo Reuses the proven r52/r51/r50/r49/r48/r47/r46 local build caches.
echo Fixes Sub2API OpenAI OAuth compact max_output_tokens rejection.
echo Full validation suites remain intentionally skipped.
echo.

python ".\scripts\apply_r53_fast_current_tree.py"
if errorlevel 1 (
  echo [FAILED] r53 fast current-tree composition.
  pause
  exit /b 1
)

python ".\scripts\prepare-r53-fast-builder.py"
if errorlevel 1 (
  echo [FAILED] r53 fast builder preparation.
  pause
  exit /b 1
)

pwsh -NoProfile -ExecutionPolicy Bypass -File ".\scripts\build-r53-fast-real-use.ps1"
set "RC=%ERRORLEVEL%"
if not "%RC%"=="0" (
  echo.
  echo [FAILED] r53 FAST REAL-USE build exit code: %RC%
  pause
  exit /b %RC%
)

echo.
echo [PASS] r53 FAST REAL-USE build complete.
pause
exit /b 0
