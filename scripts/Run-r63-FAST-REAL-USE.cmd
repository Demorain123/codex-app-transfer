@echo off
setlocal
cd /d "%~dp0.."

echo ============================================================
echo Codex App Transfer r63 - FAST REAL-USE BUILD
echo ============================================================
echo Reuses the proven r62/r61/r60/r59/r58/r57/r56 local build caches.
echo Keeps r62 compact self-repair, r61 legacy-V1 compaction, and r60 replay compatibility intact.
echo Adds a persistent privacy-safe auth epoch per session fingerprint.
echo After an account boundary, opaque reasoning history is fenced on every future replay for that session.
echo Backend-confirmed invalid_encrypted_content gets one portable retry only; there is no retry loop.
echo Raw account IDs, tokens, session IDs, prompts and encrypted blobs are never persisted by r63.
echo Full validation suites remain intentionally skipped by this FAST real-use runner.
echo.

python ".\scripts\apply_r63_fast_current_tree.py"
if errorlevel 1 (
  echo [FAILED] r63 fast current-tree composition.
  pause
  exit /b 1
)

python ".\scripts\prepare-r63-fast-builder.py"
if errorlevel 1 (
  echo [FAILED] r63 fast builder preparation.
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

pwsh -NoProfile -ExecutionPolicy Bypass -File ".\scripts\build-r63-fast-real-use.ps1"
set "RC=%ERRORLEVEL%"
if not "%RC%"=="0" (
  echo.
  echo [FAILED] r63 FAST REAL-USE build exit code: %RC%
  pause
  exit /b %RC%
)

echo.
echo [PASS] r63 FAST REAL-USE build complete.
echo NOTE: first test a brand-new short Luna session under the currently selected Codex account.
echo NOTE: then test the previously failing session without rollback/fork; r63 should recover invalid encrypted history once and keep a sticky fence.
echo NOTE: after a real account switch, proxy log should show [auth-epoch-r63] action=switch without any raw account id.
echo NOTE: recovery evidence is [encrypted-history-r63] action=invalid_encrypted_content_recovery_retry_1 followed by recovery_retry_result.
pause
exit /b 0
