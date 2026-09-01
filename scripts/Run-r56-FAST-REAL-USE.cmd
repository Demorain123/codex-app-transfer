@echo off
setlocal
cd /d "%~dp0.."

echo ============================================================
echo Codex App Transfer r56 - FAST REAL-USE BUILD
echo ============================================================
echo Reuses the proven r55/r54/r53/r52/r51/r50/r49/r48/r47/r46 local build caches.
echo Fixes successful compact Responses SSE losing summary text at response.completed.
echo Full validation suites remain intentionally skipped.
echo.

python ".\scripts\apply_r56_fast_current_tree.py"
if errorlevel 1 (
  echo [FAILED] r56 fast current-tree composition.
  pause
  exit /b 1
)

python ".\scripts\prepare-r56-fast-builder.py"
if errorlevel 1 (
  echo [FAILED] r56 fast builder preparation.
  pause
  exit /b 1
)

pwsh -NoProfile -ExecutionPolicy Bypass -File ".\scripts\build-r56-fast-real-use.ps1"
set "RC=%ERRORLEVEL%"
if not "%RC%"=="0" (
  echo.
  echo [FAILED] r56 FAST REAL-USE build exit code: %RC%
  pause
  exit /b %RC%
)

echo.
echo [PASS] r56 FAST REAL-USE build complete.
echo NOTE: r56 is a compact-response parser hotfix; ordinary turns and r55 detached MCP behavior are unchanged.
pause
exit /b 0
