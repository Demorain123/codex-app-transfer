@echo off
setlocal
cd /d "%~dp0.."

echo ============================================================
echo Codex App Transfer r59 - FAST REAL-USE BUILD
echo ============================================================
echo Reuses the proven r58/r57/r56/r55/r54/r53/r52/r51/r50/r49/r48/r47/r46 local build caches.
echo Adds same-session interrupted/failed tail recovery for upstream Windows app-server 0xC000013A aftermath.
echo Keeps r58 lifecycle, r57 external MCP migration and r56 compact recovery intact.
echo This is a recovery mitigation; it does not claim to patch OpenAI codex.exe itself.
echo Full validation suites remain intentionally skipped.
echo.

python ".\scripts\apply_r59_fast_current_tree.py"
if errorlevel 1 (
  echo [FAILED] r59 fast current-tree composition.
  pause
  exit /b 1
)

python ".\scripts\prepare-r59-fast-builder.py"
if errorlevel 1 (
  echo [FAILED] r59 fast builder preparation.
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

pwsh -NoProfile -ExecutionPolicy Bypass -File ".\scripts\build-r59-fast-real-use.ps1"
set "RC=%ERRORLEVEL%"
if not "%RC%"=="0" (
  echo.
  echo [FAILED] r59 FAST REAL-USE build exit code: %RC%
  pause
  exit /b %RC%
)

echo.
echo [PASS] r59 FAST REAL-USE build complete.
echo NOTE: after install, open Transfer ^> Routing ^> Old Conversation Recovery and use "Same-ID interrupted-tail cleanup" only when the newest persisted turns are interrupted/failed.
pause
exit /b 0
