@echo off
setlocal
cd /d "%~dp0.."

echo ============================================================
echo Codex App Transfer r61 - FAST REAL-USE BUILD
echo ============================================================
echo Reuses the proven r60/r59/r58/r57/r56/r55/r54/r53/r52/r51/r50/r49/r48/r47/r46 local build caches.
echo Keeps r60 Sub2API post-compaction replay compatibility intact.
echo Adds the Windows launch-time remote_compaction_v2=false guard so Codex selects legacy V1 compaction.
echo Legacy /responses/compact is already implemented locally by the inherited r52 compatibility path.
echo Full validation suites remain intentionally skipped.
echo.

python ".\scripts\apply_r61_fast_current_tree.py"
if errorlevel 1 (
  echo [FAILED] r61 fast current-tree composition.
  pause
  exit /b 1
)

python ".\scripts\prepare-r61-fast-builder.py"
if errorlevel 1 (
  echo [FAILED] r61 fast builder preparation.
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

pwsh -NoProfile -ExecutionPolicy Bypass -File ".\scripts\build-r61-fast-real-use.ps1"
set "RC=%ERRORLEVEL%"
if not "%RC%"=="0" (
  echo.
  echo [FAILED] r61 FAST REAL-USE build exit code: %RC%
  pause
  exit /b %RC%
)

echo.
echo [PASS] r61 FAST REAL-USE build complete.
echo NOTE: after install/restart, the proxy log should show [model-switch-r61] action=disable_remote_compaction_v2.
echo NOTE: the next auto compact should use legacy /responses/compact instead of x-codex-beta-features=remote_compaction_v2.
echo NOTE: reproduce Luna -^> Grok with one short hi; compact should happen at most once before the Grok turn continues.
pause
exit /b 0
