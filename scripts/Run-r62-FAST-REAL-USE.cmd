@echo off
setlocal
cd /d "%~dp0.."

echo ============================================================
echo Codex App Transfer r62 - FAST REAL-USE BUILD
echo ============================================================
echo Reuses the proven r61/r60/r59/r58/r57/r56 local build caches.
echo Keeps r61 legacy-V1 compaction selection and r60 replay compatibility intact.
echo Adds a stronger compact checkpoint self-repair contract for missing/too-short summaries.
echo Keeps the r51 quality gate: the observed 229-char summary is NOT silently accepted.
echo Full validation suites remain intentionally skipped.
echo.

python ".\scripts\apply_r62_fast_current_tree.py"
if errorlevel 1 (
  echo [FAILED] r62 fast current-tree composition.
  pause
  exit /b 1
)

python ".\scripts\prepare-r62-fast-builder.py"
if errorlevel 1 (
  echo [FAILED] r62 fast builder preparation.
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

pwsh -NoProfile -ExecutionPolicy Bypass -File ".\scripts\build-r62-fast-real-use.ps1"
set "RC=%ERRORLEVEL%"
if not "%RC%"=="0" (
  echo.
  echo [FAILED] r62 FAST REAL-USE build exit code: %RC%
  pause
  exit /b %RC%
)

echo.
echo [PASS] r62 FAST REAL-USE build complete.
echo NOTE: keep the same long Luna session; do not rollback or create a new thread.
echo NOTE: the compact prompt now self-checks/repairs once before emitting a structured checkpoint.
echo NOTE: if quality still fails, proxy log will contain [compact-r62] without printing summary text.
pause
exit /b 0
