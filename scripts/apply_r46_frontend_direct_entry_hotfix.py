from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BUILD = ROOT / "scripts/build-r46-fast-real-use.ps1"
MARKER = "CAS-R46-FRONTEND-DIRECT-ENTRY-GUARD"

text = BUILD.read_text(encoding="utf-8")
if MARKER in text:
    print("r46 frontend direct-entry guard already applied")
    raise SystemExit(0)

replacement = r'''        # CAS-R46-FRONTEND-DIRECT-ENTRY-GUARD
        # Do not trust node_modules/.bin shims: they can exist while their package
        # target is stale/broken. Validate and invoke the real JS entrypoints.
        $nodeCmd = Get-Command node.exe -ErrorAction SilentlyContinue
        if (-not $nodeCmd) { $nodeCmd = Get-Command node -ErrorAction SilentlyContinue }
        if (-not $nodeCmd) { throw 'node.exe was not found.' }
        $nodeExe = $nodeCmd.Source
        $vueTscJs = Join-Path $nodeModules 'vue-tsc\bin\vue-tsc.js'
        $viteJs = Join-Path $nodeModules 'vite\bin\vite.js'
        $frontendDepsReady = (Test-Path -LiteralPath $vueTscJs -PathType Leaf) -and (Test-Path -LiteralPath $viteJs -PathType Leaf)
        if (-not $frontendDepsReady) {
            Write-Host 'Frontend package entrypoints incomplete; running npm ci --include=dev once...' -ForegroundColor Yellow
            Invoke-Checked 'npm.cmd' 'ci' '--include=dev'
            $frontendDepsReady = (Test-Path -LiteralPath $vueTscJs -PathType Leaf) -and (Test-Path -LiteralPath $viteJs -PathType Leaf)
            if (-not $frontendDepsReady) { throw 'npm ci completed but vue-tsc/vite package entrypoints are still missing.' }
        } else {
            Write-Host 'Frontend package entrypoints ready; SKIP npm ci.' -ForegroundColor Green
        }
        Invoke-Checked $nodeExe $vueTscJs '--noEmit'
        Invoke-Checked $nodeExe $viteJs 'build'
'''

old_marker = "        # CAS-R46-FRONTEND-DEPS-COMPLETE-GUARD\n"
old_build = "        Invoke-Checked 'npm.cmd' 'run' 'build'"
if old_marker in text:
    start = text.index(old_marker)
    end = text.index(old_build, start) + len(old_build)
    text = text[:start] + replacement.rstrip("\n") + text[end:]
else:
    original = "        if (-not (Test-Path -LiteralPath $nodeModules -PathType Container)) { Invoke-Checked 'npm.cmd' 'ci' }\n        Invoke-Checked 'npm.cmd' 'run' 'build'"
    if original not in text:
        raise SystemExit("r46 frontend direct-entry guard: frontend build anchor missing")
    text = text.replace(original, replacement.rstrip("\n"), 1)

for invariant in (
    MARKER,
    "vue-tsc\\bin\\vue-tsc.js",
    "vite\\bin\\vite.js",
    "Invoke-Checked $nodeExe $vueTscJs '--noEmit'",
    "Invoke-Checked $nodeExe $viteJs 'build'",
):
    if invariant not in text:
        raise SystemExit(f"r46 frontend direct-entry guard invariant missing: {invariant}")

BUILD.write_text(text, encoding="utf-8")
print("R46 FRONTEND DIRECT-ENTRY GUARD PASS")
