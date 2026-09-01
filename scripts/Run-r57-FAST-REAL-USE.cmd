@echo off
setlocal
cd /d "%~dp0.."

echo ============================================================
echo Codex App Transfer r57 - FAST REAL-USE BUILD
echo ============================================================
echo Reuses the proven r56/r55/r54/r53/r52/r51/r50/r49/r48/r47/r46 local build caches.
echo Migrates stale external cat-webfetch source definitions to the detached MCP helper.
echo Reuses the workspace's existing rusqlite 0.40 / libsqlite3-sys line.
echo Full validation suites remain intentionally skipped.
echo.

python ".\scripts\apply_r57_fast_current_tree.py"
if errorlevel 1 (
  echo [FAILED] r57 fast current-tree composition.
  pause
  exit /b 1
)

python ".\scripts\prepare-r57-fast-builder.py"
if errorlevel 1 (
  echo [FAILED] r57 fast builder preparation.
  pause
  exit /b 1
)

pwsh -NoProfile -ExecutionPolicy Bypass -File ".\scripts\build-r57-fast-real-use.ps1"
set "RC=%ERRORLEVEL%"
if not "%RC%"=="0" (
  echo.
  echo [FAILED] r57 FAST REAL-USE build exit code: %RC%
  pause
  exit /b %RC%
)

echo.
echo [PASS] r57 FAST REAL-USE build complete.
echo NOTE: launch r57 once before restarting OMP/CC Switch so stale external MCP sources can migrate.
pause
exit /b 0
