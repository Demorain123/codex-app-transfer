@echo off
setlocal
cd /d "%~dp0.."

echo ============================================================
echo Codex App Transfer r55 - FAST REAL-USE BUILD
echo ============================================================
echo Reuses the proven r54/r53/r52/r51/r50/r49/r48/r47/r46 local build caches.
echo Adds Windows detached MCP helper registration for install/update safety.
echo Full validation suites remain intentionally skipped.
echo.

python ".\scripts\apply_r55_fast_current_tree.py"
if errorlevel 1 (
  echo [FAILED] r55 fast current-tree composition.
  pause
  exit /b 1
)

python ".\scripts\prepare-r55-fast-builder.py"
if errorlevel 1 (
  echo [FAILED] r55 fast builder preparation.
  pause
  exit /b 1
)

pwsh -NoProfile -ExecutionPolicy Bypass -File ".\scripts\build-r55-fast-real-use.ps1"
set "RC=%ERRORLEVEL%"
if not "%RC%"=="0" (
  echo.
  echo [FAILED] r55 FAST REAL-USE build exit code: %RC%
  pause
  exit /b %RC%
)

echo.
echo [PASS] r55 FAST REAL-USE build complete.
echo NOTE: restart the external MCP host once after first r55 install so it reloads the detached helper command.
pause
exit /b 0
