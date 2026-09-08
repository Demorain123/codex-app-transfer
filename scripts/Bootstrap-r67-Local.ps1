$ErrorActionPreference = 'Stop'

$RepoRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $RepoRoot

Write-Host "============================================================" -ForegroundColor Cyan
Write-Host " Codex App Transfer r67 - HOOKS RESTORED / SELECTIVE STATE" -ForegroundColor Cyan
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "Local build only; no GitHub Actions." -ForegroundColor DarkGray
Write-Host ""

$expectedHead = '0515e53567b2d148b9d4a10404074ea028b4fead'
$currentHead = (& git rev-parse HEAD).Trim()
if ($LASTEXITCODE -ne 0) { throw 'git rev-parse failed' }
if ($currentHead -ne $expectedHead) {
    throw "r67 bootstrap expects the same local r64 base HEAD $expectedHead; current HEAD is $currentHead"
}

$processPath = Join-Path $RepoRoot 'src-tauri\src\admin\services\desktop\process.rs'
$processText = Get-Content -LiteralPath $processPath -Raw -Encoding UTF8
foreach ($marker in @(
    'CAS-R61-LEGACY-COMPACTION-V1',
    'CAS-R64-POST-COMPACT-CONTINUATION-GUARD',
    'CAS-R65-FIRST-TURN-STARTUP-GENERATION-GATE',
    'CAS-R66-POST-COMPACT-HOOKS-AB'
)) {
    if ($processText -notmatch [regex]::Escape($marker)) {
        throw "r67 bootstrap requires the materialized r66 local tree; missing marker: $marker"
    }
}

$patchPy = @'
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROCESS = ROOT / "src-tauri/src/admin/services/desktop/process.rs"
MARKER = "CAS-R67-HOOKS-RESTORED-SELECTIVE-STATE"

text = PROCESS.read_text(encoding="utf-8")

if MARKER not in text:
    if "CAS-R66-POST-COMPACT-HOOKS-AB" not in text:
        raise SystemExit("r67 requires materialized r66 baseline")

    open_anchor = 'fn open_codex_app(platform: &str) -> Result<(), String> {\n'
    if open_anchor not in text:
        raise SystemExit("r67: open_codex_app anchor missing")

    helper = r'''
// CAS-R67-HOOKS-RESTORED-SELECTIVE-STATE
//
// r66 proved that globally disabling Codex Hooks removes the observed
// successful-compaction -> silent-stop failure, but that A/B is too broad for
// daily use because SessionStart/PreToolUse/PostToolUse/Stop/plugin hooks all
// disappear together.
//
// r67 restores the stable Hooks feature globally and deliberately leaves every
// per-hook [hooks.state.*] preference untouched. This makes r67 compatible with
// selectively disabling a smaller set of hooks in Codex while keeping MCP,
// Plugins, Apps and the remaining hook lifecycle available.
//
// This is a narrowing A/B build, not a claim that the upstream core lifecycle
// boundary itself has been patched. No user prompt, model request, tool call or
// compaction request is synthesized or retried.
fn sync_codex_hooks_selective_guard_r67() {
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
            tracing::warn!("[compact-r67] action=restore_codex_hooks status=skip reason=codex_home_unresolved");
            return;
        };
        if let Err(error) = fs::create_dir_all(&root) {
            tracing::warn!(path = %root.display(), error = %error, "[compact-r67] action=restore_codex_hooks status=skip reason=create_codex_home_failed");
            return;
        }

        let path = root.join("config.toml");
        let original = match fs::read_to_string(&path) {
            Ok(value) => value,
            Err(error) if error.kind() == std::io::ErrorKind::NotFound => String::new(),
            Err(error) => {
                tracing::warn!(path = %path.display(), error = %error, "[compact-r67] action=restore_codex_hooks status=skip reason=read_failed");
                return;
            }
        };

        // Only report a count; hook ids/paths/commands are intentionally not logged.
        let hook_state_tables = original
            .lines()
            .filter(|line| {
                let trimmed = line.trim();
                trimmed.starts_with("[hooks.state.") || trimmed == "[hooks.state]"
            })
            .count();

        let mut output: Vec<String> = Vec::new();
        let mut in_features = false;
        let mut saw_features = false;
        let mut wrote_hooks = false;

        for line in original.lines() {
            let trimmed = line.trim();
            let is_table = trimmed.starts_with('[') && trimmed.ends_with(']');
            if is_table {
                if in_features && !wrote_hooks {
                    output.push("hooks = true # CAS-R67 global hooks restored; per-hook state preserved".to_owned());
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
                        output.push("hooks = true # CAS-R67 global hooks restored; per-hook state preserved".to_owned());
                        wrote_hooks = true;
                    }
                    continue;
                }
            }

            output.push(line.to_owned());
        }

        if in_features && !wrote_hooks {
            output.push("hooks = true # CAS-R67 global hooks restored; per-hook state preserved".to_owned());
            wrote_hooks = true;
        }
        if !saw_features {
            if !output.is_empty() && output.last().is_some_and(|line| !line.is_empty()) {
                output.push(String::new());
            }
            output.push("[features]".to_owned());
            output.push("hooks = true # CAS-R67 global hooks restored; per-hook state preserved".to_owned());
            wrote_hooks = true;
        }
        if !wrote_hooks {
            tracing::warn!(path = %path.display(), "[compact-r67] action=restore_codex_hooks status=skip reason=managed_key_not_materialized");
            return;
        }

        let mut updated = output.join("\n");
        updated.push('\n');
        if updated == original {
            tracing::info!(hook_state_tables, "[compact-r67] action=restore_codex_hooks status=already_enabled mode=selective_per_hook_state");
            return;
        }
        if let Err(error) = fs::write(&path, updated) {
            tracing::warn!(path = %path.display(), error = %error, "[compact-r67] action=restore_codex_hooks status=skip reason=write_failed");
            return;
        }
        tracing::warn!(hook_state_tables, "[compact-r67] action=restore_codex_hooks status=applied mode=selective_per_hook_state");
    }
}

'''
    text = text.replace(open_anchor, helper + open_anchor, 1)

    r66_call = "    sync_codex_hooks_ab_guard_r66();"
    if text.count(r66_call) != 2:
        raise SystemExit("r67 expected exactly two inherited r66 launch-pipeline calls")
    text = text.replace(r66_call, "    sync_codex_hooks_selective_guard_r67();")

    PROCESS.write_text(text, encoding="utf-8")
    print("R67 HOOKS RESTORE / SELECTIVE STATE PATCH APPLIED")
else:
    print("R67 HOOKS RESTORE / SELECTIVE STATE PATCH ALREADY APPLIED")

verify = PROCESS.read_text(encoding="utf-8")
for marker in (
    "CAS-R67-HOOKS-RESTORED-SELECTIVE-STATE",
    "sync_codex_hooks_selective_guard_r67",
    "hooks = true # CAS-R67 global hooks restored; per-hook state preserved",
    "[compact-r67] action=restore_codex_hooks",
    "CAS-R66-POST-COMPACT-HOOKS-AB",
    "CAS-R65-FIRST-TURN-STARTUP-GENERATION-GATE",
    "CAS-R64-POST-COMPACT-CONTINUATION-GUARD",
    "CAS-R61-LEGACY-COMPACTION-V1",
):
    if marker not in verify:
        raise SystemExit(f"r67 patch invariant missing: {marker}")

if verify.count("sync_codex_hooks_selective_guard_r67();") != 2:
    raise SystemExit("r67 expected normal + alternate launch guards")
if verify.count("sync_codex_hooks_ab_guard_r66();") != 0:
    raise SystemExit("r67 must not execute the global r66 hooks-off guard")

print("R67 PATCH VERIFY PASS")
print("- global Codex Hooks restored")
print("- existing per-hook hooks.state preferences preserved byte-for-byte")
print("- Plugins/Apps/MCP settings untouched")
print("- no prompt/model/tool/compact retry added")
'@
Set-Content -LiteralPath (Join-Path $RepoRoot 'scripts\apply_r67_local.py') -Value $patchPy -Encoding UTF8

Write-Host "[1/4] Applying r67 selective-hooks patch..." -ForegroundColor Cyan
python .\scripts\apply_r67_local.py
if ($LASTEXITCODE -ne 0) { throw 'r67 patch failed' }

Write-Host "[2/4] Stamping r67 version..." -ForegroundColor Cyan
Set-Content -LiteralPath .\SUB2API_GROK_COMPAT_REVISION.txt -Value '67' -Encoding ASCII
python .\scripts\apply_sub2api_grok_compat_revision.py
if ($LASTEXITCODE -ne 0) { throw 'r67 version materialization failed' }

Write-Host "[3/4] Preparing r67 fast builder..." -ForegroundColor Cyan
if (-not (Test-Path -LiteralPath .\scripts\build-r66-fast-real-use.ps1)) {
    throw 'r67 requires the existing local r66 fast builder; build r66 once first'
}

$prepPy = @'
from __future__ import annotations
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "scripts/build-r66-fast-real-use.ps1"
TARGET = ROOT / "scripts/build-r67-fast-real-use.ps1"

if not SOURCE.is_file():
    raise SystemExit("r67 builder: r66 builder missing")

text = SOURCE.read_text(encoding="utf-8")
replacements = [
    ("Codex App Transfer r66 - FAST REAL-USE BUILD", "Codex App Transfer r67 - FAST REAL-USE BUILD"),
    ("[1/9] Materialize r66", "[1/9] Materialize r67"),
    ("Warm r66 materialization detected; SKIP.", "Warm r67 materialization detected; SKIP."),
    (".\\scripts\\apply_r66_local.py", ".\\scripts\\apply_r67_local.py"),
    ("compat_revision=66", "compat_revision=67"),
    ("app_version=2\\.4\\.5\\+66", "app_version=2\\.4\\.5\\+67"),
    ("app_version=2.4.5+66", "app_version=2.4.5+67"),
    ("2.4.5+66", "2.4.5+67"),
    ("2.4.5-r66", "2.4.5-r67"),
    ("r66-real-use", "r67-real-use"),
    ("R66 FAST REAL-USE BUILD PASS", "R67 FAST REAL-USE BUILD PASS"),
    ("r66 FAST REAL-USE", "r67 FAST REAL-USE"),
    ("r66 FAST real-use", "r67 FAST real-use"),
    ("compatRevision = 66", "compatRevision = 67"),
]
for old, new in replacements:
    text = text.replace(old, new)

r66_guard = " -and ((Get-Content -LiteralPath (Join-Path $repoRoot 'src-tauri\\src\\admin\\services\\desktop\\process.rs') -Raw -Encoding UTF8) -match 'CAS-R66-POST-COMPACT-HOOKS-AB')"
r67_guard = r66_guard + " -and ((Get-Content -LiteralPath (Join-Path $repoRoot 'src-tauri\\src\\admin\\services\\desktop\\process.rs') -Raw -Encoding UTF8) -match 'CAS-R67-HOOKS-RESTORED-SELECTIVE-STATE')"
if r66_guard not in text:
    raise SystemExit("r67 builder: r66 guard tail missing")
text = text.replace(r66_guard, r67_guard, 1)

for marker in (
    ".\\scripts\\apply_r67_local.py",
    "compat_revision=67",
    "app_version=2\\.4\\.5\\+67",
    "CAS-R66-POST-COMPACT-HOOKS-AB",
    "CAS-R67-HOOKS-RESTORED-SELECTIVE-STATE",
    "r67-real-use",
):
    if marker not in text:
        raise SystemExit(f"r67 builder invariant missing: {marker}")

TARGET.write_text(text, encoding="utf-8")
print("R67 FAST BUILDER PREP PASS")
'@
Set-Content -LiteralPath (Join-Path $RepoRoot 'scripts\prepare-r67-local-builder.py') -Value $prepPy -Encoding UTF8
python .\scripts\prepare-r67-local-builder.py
if ($LASTEXITCODE -ne 0) { throw 'r67 builder generation failed' }

if (Test-Path -LiteralPath .\scripts\Repair-r57-Build-Space.ps1) {
    pwsh -NoProfile -ExecutionPolicy Bypass -File .\scripts\Repair-r57-Build-Space.ps1
    if ($LASTEXITCODE -ne 0) { throw 'V: build-space check failed' }
}

Write-Host "[4/4] Building r67 locally..." -ForegroundColor Cyan
pwsh -NoProfile -ExecutionPolicy Bypass -File .\scripts\build-r67-fast-real-use.ps1
if ($LASTEXITCODE -ne 0) { throw "r67 FAST build failed with exit code $LASTEXITCODE" }

Write-Host ""
Write-Host "[PASS] r67 local FAST REAL-USE build complete." -ForegroundColor Green
Write-Host "Expected launch log: [compact-r67] action=restore_codex_hooks ... mode=selective_per_hook_state" -ForegroundColor Green
Write-Host "Keep your intentionally disabled per-hook entries disabled; r67 does not overwrite them." -ForegroundColor Green
Write-Host "Use the same long-session compact regression fixture and verify MCP/plugins you still need." -ForegroundColor Green
