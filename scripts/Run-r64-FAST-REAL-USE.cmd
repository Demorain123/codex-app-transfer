@echo off
setlocal
cd /d "%~dp0.."

echo ============================================================
echo Codex App Transfer r64 - FAST REAL-USE BUILD
echo ============================================================
echo Reuses the proven r63/r62/r61/r60/r59/r58/r57/r56 local build caches.
echo Keeps r63 auth fencing, r62 compact self-repair, r61 legacy-V1 compaction, and r60 replay intact.
echo Adds one narrow Windows launch guard: experimental context_management is forced off before Codex starts.
echo This targets the September 2026 upstream stop-after-successful-compaction regression without replaying tools.
echo No synthetic continuation request or automatic tool-call retry is introduced.
echo Full validation suites remain intentionally skipped by this FAST real-use runner.
echo.

python ".\scripts\apply_r64_fast_current_tree.py"
if errorlevel 1 (
  echo [FAILED] r64 fast current-tree composition.
  pause
  exit /b 1
)

python ".\scripts\prepare-r64-fast-builder.py"
if errorlevel 1 (
  echo [FAILED] r64 fast builder preparation.
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

pwsh -NoProfile -ExecutionPolicy Bypass -File ".\scripts\build-r64-fast-real-use.ps1"
set "RC=%ERRORLEVEL%"
if not "%RC%"=="0" (
  echo.
  echo [FAILED] r64 FAST REAL-USE build exit code: %RC%
  pause
  exit /b %RC%
)

echo.
echo [PASS] r64 FAST REAL-USE build complete.
echo NOTE: fully exit Codex before first r64 launch so config.toml is reread.
echo NOTE: launch log should show [compact-r64] action=disable_context_management status=applied or already_disabled.
echo NOTE: keep using the same long Luna session; do not fork or clear its compaction history.
echo NOTE: success criterion is: Context automatically compacted -^> same active task resumes without a new user message.
echo NOTE: inherited compact evidence should still show compact-r56/r62 success and r60 replay on the resumed request.
pause
exit /b 0
