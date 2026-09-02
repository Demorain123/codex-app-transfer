@echo off
setlocal
cd /d "%~dp0.."

echo ============================================================
echo Codex App Transfer r60 - FAST REAL-USE BUILD
echo ============================================================
echo Reuses the proven r59/r58/r57/r56/r55/r54/r53/r52/r51/r50/r49/r48/r47/r46 local build caches.
echo Keeps the r59 same-session 0xC000013A bad-tail recovery unchanged.
echo Adds a recent Session catalog, persistent recovered-state lifecycle, and unresolved-only auto-detect.
echo Existing verified r59 recovery logs can be migrated into the r60 recovered marker without re-running history mutation.
echo Full validation suites remain intentionally skipped.
echo.

python ".\scripts\apply_r60_fast_current_tree.py"
if errorlevel 1 (
  echo [FAILED] r60 fast current-tree composition.
  pause
  exit /b 1
)

python ".\scripts\prepare-r60-fast-builder.py"
if errorlevel 1 (
  echo [FAILED] r60 fast builder preparation.
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

pwsh -NoProfile -ExecutionPolicy Bypass -File ".\scripts\build-r60-fast-real-use.ps1"
set "RC=%ERRORLEVEL%"
if not "%RC%"=="0" (
  echo.
  echo [FAILED] r60 FAST REAL-USE build exit code: %RC%
  pause
  exit /b %RC%
)

echo.
echo [PASS] r60 FAST REAL-USE build complete.
echo NOTE: after install, open Transfer ^> Routing ^> Old Conversation Recovery. The panel should show a recent Session list with Normal / Needs recovery / Recovered lifecycle chips.
pause
exit /b 0
