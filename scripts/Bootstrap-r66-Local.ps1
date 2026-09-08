$ErrorActionPreference = 'Stop'

$RepoRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $RepoRoot

Write-Host "============================================================" -ForegroundColor Cyan
Write-Host " Codex App Transfer r66 - POST-COMPACT HOOKS A/B LOCAL BUILD" -ForegroundColor Cyan
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "Local build only; no GitHub Actions." -ForegroundColor DarkGray
Write-Host ""

$expectedHead = '0515e53567b2d148b9d4a10404074ea028b4fead'
$currentHead = (& git rev-parse HEAD).Trim()
if ($LASTEXITCODE -ne 0) { throw 'git rev-parse failed' }
if ($currentHead -ne $expectedHead) {
    throw "r66 bootstrap expects the same local r64 base HEAD $expectedHead; current HEAD is $currentHead"
}

$processPath = Join-Path $RepoRoot 'src-tauri\src\admin\services\desktop\process.rs'
$processText = Get-Content -LiteralPath $processPath -Raw -Encoding UTF8
foreach ($marker in @(
    'CAS-R61-LEGACY-COMPACTION-V1',
    'CAS-R64-POST-COMPACT-CONTINUATION-GUARD',
    'CAS-R65-FIRST-TURN-STARTUP-GENERATION-GATE'
)) {
    if ($processText -notmatch [regex]::Escape($marker)) {
        throw "r66 bootstrap requires the materialized r65 local tree; missing marker: $marker"
    }
}

$patchPy = @'
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROCESS = ROOT / "src-tauri/src/admin/services/desktop/process.rs"
MARKER = "CAS-R66-POST-COMPACT-HOOKS-AB"

text = PROCESS.read_text(encoding="utf-8")

if MARKER not in text:
    if "CAS-R65-FIRST-TURN-STARTUP-GENERATION-GATE" not in text:
        raise SystemExit("r66 requires materialized r65 baseline")

    open_anchor = 'fn open_codex_app(platform: &str) -> Result<(), String> {\n'
    if open_anchor not in text:
        raise SystemExit("r66: open_codex_app anchor missing")

    helper = r'''
// CAS-R66-POST-COMPACT-HOOKS-AB
//
// r64 proved context_management=false alone does not prevent the successful-
// compaction -> silent-stop regression. Current upstream run_turn has one explicit
// early-return boundary immediately after successful mid-turn compaction:
// run_pending_session_start_hooks(...). If a SessionStart hook requests stop,
// run_turn returns Ok(None) instead of continuing the active task.
//
// r66 is a narrow A/B build. It disables the stable Codex Hooks feature while
// preserving Plugins, Apps, MCP tools, r61/r62/r63/r64 compatibility, and r65
// startup diagnostics. This disables hook handlers (including SessionStart,
// Pre/PostToolUse and Stop hooks) but does not disable plugin/MCP tool discovery.
fn sync_codex_hooks_ab_guard_r66() {
    #[cfg(not(target_os = "windows"))]
    {
        return;
    }

    #[cfg(target_os = "windows")]
    {
        let root = std::env::var_os("CODEX_HOME")
            .filter(|value| !value.is_empty())
            .map(PathBuf::from)
            .or_else(|| codex_app_transfer_registry::paths::resolve_home().map(|home| home.join(".codex")));
        let Some(root) = root else {
            tracing::warn!("[compact-r66] action=disable_codex_hooks status=skip reason=codex_home_unresolved");
            return;
        };
        if let Err(error) = fs::create_dir_all(&root) {
            tracing::warn!(path = %root.display(), error = %error, "[compact-r66] action=disable_codex_hooks status=skip reason=create_codex_home_failed");
            return;
        }
        let path = root.join("config.toml");
        let original = match fs::read_to_string(&path) {
            Ok(value) => value,
            Err(error) if error.kind() == std::io::ErrorKind::NotFound => String::new(),
            Err(error) => {
                tracing::warn!(path = %path.display(), error = %error, "[compact-r66] action=disable_codex_hooks status=skip reason=read_failed");
                return;
            }
        };

        let mut output: Vec<String> = Vec::new();
        let mut in_features = false;
        let mut saw_features = false;
        let mut wrote_hooks = false;

        for line in original.lines() {
            let trimmed = line.trim();
            let is_table = trimmed.starts_with('[') && trimmed.ends_with(']');
            if is_table {
                if in_features && !wrote_hooks {
                    output.push("hooks = false # CAS-R66 post-compact SessionStart A/B".to_owned());
                    wrote_hooks = true;
                }
                in_features = trimmed == "[features]";
                saw_features |= in_features;
                output.push(line.to_owned());
                continue;
            }

            if in_features {
                let key = trimmed
                    .split_once('=')
                    .map(|(key, _)| key.trim())
                    .unwrap_or("");
                if key == "hooks" || key == "codex_hooks" {
                    if !wrote_hooks {
                        output.push("hooks = false # CAS-R66 post-compact SessionStart A/B".to_owned());
                        wrote_hooks = true;
                    }
                    continue;
                }
            }

            output.push(line.to_owned());
        }

        if in_features && !wrote_hooks {
            output.push("hooks = false # CAS-R66 post-compact SessionStart A/B".to_owned());
            wrote_hooks = true;
        }
        if !saw_features {
            if !output.is_empty() && output.last().is_some_and(|line| !line.is_empty()) {
                output.push(String::new());
            }
            output.push("[features]".to_owned());
            output.push("hooks = false # CAS-R66 post-compact SessionStart A/B".to_owned());
            wrote_hooks = true;
        }
        if !wrote_hooks {
            tracing::warn!(path = %path.display(), "[compact-r66] action=disable_codex_hooks status=skip reason=managed_key_not_materialized");
            return;
        }

        let mut updated = output.join("\n");
        updated.push('\n');
        if updated == original {
            tracing::info!(path = %path.display(), "[compact-r66] action=disable_codex_hooks status=already_disabled reason=post_compact_session_start_ab");
            return;
        }
        if let Err(error) = fs::write(&path, updated) {
            tracing::warn!(path = %path.display(), error = %error, "[compact-r66] action=disable_codex_hooks status=skip reason=write_failed");
            return;
        }
        tracing::warn!(path = %path.display(), "[compact-r66] action=disable_codex_hooks status=applied reason=post_compact_session_start_ab");
    }
}

'''
    text = text.replace(open_anchor, helper + open_anchor, 1)

    r64_call = "    sync_codex_post_compact_continuation_guard_r64();"
    if text.count(r64_call) != 2:
        raise SystemExit("r66 expected exactly two inherited r64 launch-pipeline calls")
    r66_call = r64_call + "\n    sync_codex_hooks_ab_guard_r66();"
    text = text.replace(r64_call, r66_call)

    PROCESS.write_text(text, encoding="utf-8")
    print("R66 POST-COMPACT HOOKS A/B PATCH APPLIED")
else:
    print("R66 POST-COMPACT HOOKS A/B PATCH ALREADY APPLIED")

verify = PROCESS.read_text(encoding="utf-8")
for marker in (
    "CAS-R66-POST-COMPACT-HOOKS-AB",
    "sync_codex_hooks_ab_guard_r66",
    "hooks = false # CAS-R66 post-compact SessionStart A/B",
    "[compact-r66] action=disable_codex_hooks",
    "CAS-R65-FIRST-TURN-STARTUP-GENERATION-GATE",
    "CAS-R64-POST-COMPACT-CONTINUATION-GUARD",
    "CAS-R61-LEGACY-COMPACTION-V1",
):
    if marker not in verify:
        raise SystemExit(f"r66 patch invariant missing: {marker}")

if verify.count("sync_codex_hooks_ab_guard_r66();") != 2:
    raise SystemExit("r66 expected normal + alternate launch guards")

print("R66 PATCH VERIFY PASS")
print("- Codex Hooks disabled for A/B; Plugins/Apps/MCP settings untouched")
print("- no prompt, model, compact, or tool-call retry added")
'@
Set-Content -LiteralPath (Join-Path $RepoRoot 'scripts\apply_r66_local.py') -Value $patchPy -Encoding UTF8

Write-Host "[1/4] Applying r66 hooks A/B patch..." -ForegroundColor Cyan
python .\scripts\apply_r66_local.py
if ($LASTEXITCODE -ne 0) { throw 'r66 patch failed' }

Write-Host "[2/4] Stamping r66 version..." -ForegroundColor Cyan
Set-Content -LiteralPath .\SUB2API_GROK_COMPAT_REVISION.txt -Value '66' -Encoding ASCII
python .\scripts\apply_sub2api_grok_compat_revision.py
if ($LASTEXITCODE -ne 0) { throw 'r66 version materialization failed' }

Write-Host "[3/4] Preparing r66 fast builder..." -ForegroundColor Cyan
if (-not (Test-Path -LiteralPath .\scripts\build-r65-fast-real-use.ps1)) {
    throw 'r66 requires the existing local r65 fast builder; build r65 once first'
}

$prepPy = @'
from __future__ import annotations
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "scripts/build-r65-fast-real-use.ps1"
TARGET = ROOT / "scripts/build-r66-fast-real-use.ps1"

if not SOURCE.is_file():
    raise SystemExit("r66 builder: r65 builder missing")

text = SOURCE.read_text(encoding="utf-8")
replacements = [
    ("Codex App Transfer r65 - FAST REAL-USE BUILD", "Codex App Transfer r66 - FAST REAL-USE BUILD"),
    ("[1/9] Materialize r65", "[1/9] Materialize r66"),
    ("Warm r65 materialization detected; SKIP.", "Warm r66 materialization detected; SKIP."),
    (".\\scripts\\apply_r65_local.py", ".\\scripts\\apply_r66_local.py"),
    ("compat_revision=65", "compat_revision=66"),
    ("app_version=2\\.4\\.5\\+65", "app_version=2\\.4\\.5\\+66"),
    ("app_version=2.4.5+65", "app_version=2.4.5+66"),
    ("2.4.5+65", "2.4.5+66"),
    ("2.4.5-r65", "2.4.5-r66"),
    ("r65-real-use", "r66-real-use"),
    ("R65 FAST REAL-USE BUILD PASS", "R66 FAST REAL-USE BUILD PASS"),
    ("r65 FAST REAL-USE", "r66 FAST REAL-USE"),
    ("r65 FAST real-use", "r66 FAST real-use"),
    ("compatRevision = 65", "compatRevision = 66"),
]
for old, new in replacements:
    text = text.replace(old, new)

r65_guard = " -and ((Get-Content -LiteralPath (Join-Path $repoRoot 'src-tauri\\src\\admin\\services\\desktop\\process.rs') -Raw -Encoding UTF8) -match 'CAS-R65-FIRST-TURN-STARTUP-GENERATION-GATE')"
r66_guard = r65_guard + " -and ((Get-Content -LiteralPath (Join-Path $repoRoot 'src-tauri\\src\\admin\\services\\desktop\\process.rs') -Raw -Encoding UTF8) -match 'CAS-R66-POST-COMPACT-HOOKS-AB')"
if r65_guard not in text:
    raise SystemExit("r66 builder: r65 guard tail missing")
text = text.replace(r65_guard, r66_guard, 1)

for marker in (
    ".\\scripts\\apply_r66_local.py",
    "compat_revision=66",
    "app_version=2\\.4\\.5\\+66",
    "CAS-R65-FIRST-TURN-STARTUP-GENERATION-GATE",
    "CAS-R66-POST-COMPACT-HOOKS-AB",
    "r66-real-use",
):
    if marker not in text:
        raise SystemExit(f"r66 builder invariant missing: {marker}")

TARGET.write_text(text, encoding="utf-8")
print("R66 FAST BUILDER PREP PASS")
'@
Set-Content -LiteralPath (Join-Path $RepoRoot 'scripts\prepare-r66-local-builder.py') -Value $prepPy -Encoding UTF8
python .\scripts\prepare-r66-local-builder.py
if ($LASTEXITCODE -ne 0) { throw 'r66 builder generation failed' }

if (Test-Path -LiteralPath .\scripts\Repair-r57-Build-Space.ps1) {
    pwsh -NoProfile -ExecutionPolicy Bypass -File .\scripts\Repair-r57-Build-Space.ps1
    if ($LASTEXITCODE -ne 0) { throw 'V: build-space check failed' }
}

Write-Host "[4/4] Building r66 locally..." -ForegroundColor Cyan
pwsh -NoProfile -ExecutionPolicy Bypass -File .\scripts\build-r66-fast-real-use.ps1
if ($LASTEXITCODE -ne 0) { throw "r66 FAST build failed with exit code $LASTEXITCODE" }

Write-Host ""
Write-Host "[PASS] r66 local FAST REAL-USE build complete." -ForegroundColor Green
Write-Host "After install/restart, expect [compact-r66] action=disable_codex_hooks ..." -ForegroundColor Green
Write-Host "Then reproduce the same long-session auto-compaction without typing Continue." -ForegroundColor Green
