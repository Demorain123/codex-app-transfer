@echo off
setlocal
cd /d "%~dp0.."

echo ============================================================
echo Codex App Transfer r60 - FAST REAL-USE BUILD
echo ============================================================
echo Reuses the proven r59/r58/r57/r56/r55/r54/r53/r52/r51/r50/r49/r48/r47/r46 local build caches.
echo Adds Sub2API post-compaction replay compatibility for normal Responses turns.
echo Keeps r59 same-ID recovery, r58 lifecycle, r57 external MCP migration and r56 compact SSE fallback intact.
echo Native/OpenAI Responses providers remain unchanged.
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
echo NOTE: after install, reproduce the same Luna auto-compact flow. Look for [sub2api-r60] action=post_compaction_replay_rewrite and no post-compact raw upstream 400.
pause
exit /b 0
