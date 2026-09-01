@echo off
setlocal
cd /d "%~dp0.."

echo ============================================================
echo Codex App Transfer r58 - FAST REAL-USE BUILD
echo ============================================================
echo Reuses the proven r57/r56/r55/r54/r53/r52/r51/r50/r49/r48/r47/r46 local build caches.
echo Fixes Windows ChatGPT.exe lifecycle ownership and stale external MCP-host restart races.
echo Keeps r57 external MCP migration and r56 compact recovery intact.
echo Full validation suites remain intentionally skipped.
echo.

python ".\scripts\apply_r58_fast_current_tree.py"
if errorlevel 1 (
  echo [FAILED] r58 fast current-tree composition.
  pause
  exit /b 1
)

python ".\scripts\prepare-r58-fast-builder.py"
if errorlevel 1 (
  echo [FAILED] r58 fast builder preparation.
  pause
  exit /b 1
)

if exist ".\scripts\Repair-r57-Build-Space.ps1" (
  pwsh -NoProfile -ExecutionPolicy Bypass -File ".\scripts\Repair-r57-Build-Space.ps1"
  if errorlevel 1 (
    echo.
    echo [FAILED] V: build cache space is below the safe threshold.
    echo Run: pwsh -NoProfile -ExecutionPolicy Bypass -File .\scripts\Repair-r57-Build-Space.ps1 -CleanCargoTarget
    pause
    exit /b 1
  )
)

pwsh -NoProfile -ExecutionPolicy Bypass -File ".\scripts\build-r58-fast-real-use.ps1"
set "RC=%ERRORLEVEL%"
if not "%RC%"=="0" (
  echo.
  echo [FAILED] r58 FAST REAL-USE build exit code: %RC%
  pause
  exit /b %RC%
)

echo.
echo [PASS] r58 FAST REAL-USE build complete.
echo NOTE: after install, restart OMP and CC Switch once before using Restart/A/B if r58 reports a stale install-directory MCP helper.
pause
exit /b 0
