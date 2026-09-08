$ErrorActionPreference = 'Stop'

$RepoRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $RepoRoot

Write-Host "============================================================" -ForegroundColor Cyan
Write-Host " Codex App Transfer r68 - SESSIONSTART-ONLY HOOKS A/B" -ForegroundColor Cyan
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "Local build only; no GitHub Actions." -ForegroundColor DarkGray
Write-Host ""

$expectedHead = '0515e53567b2d148b9d4a10404074ea028b4fead'
$currentHead = (& git rev-parse HEAD).Trim()
if ($LASTEXITCODE -ne 0) { throw 'git rev-parse failed' }
if ($currentHead -ne $expectedHead) {
    throw "r68 bootstrap expects the same local r64 base HEAD $expectedHead; current HEAD is $currentHead"
}

$processPath = Join-Path $RepoRoot 'src-tauri\src\admin\services\desktop\process.rs'
$processText = Get-Content -LiteralPath $processPath -Raw -Encoding UTF8
foreach ($marker in @(
    'CAS-R61-LEGACY-COMPACTION-V1',
    'CAS-R64-POST-COMPACT-CONTINUATION-GUARD',
    'CAS-R65-FIRST-TURN-STARTUP-GENERATION-GATE',
    'CAS-R66-POST-COMPACT-HOOKS-AB',
    'CAS-R67-HOOKS-RESTORED-SELECTIVE-STATE'
)) {
    if ($processText -notmatch [regex]::Escape($marker)) {
        throw "r68 bootstrap requires the materialized r67 local tree; missing marker: $marker"
    }
}

$patchPy = @'
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROCESS = ROOT / "src-tauri/src/admin/services/desktop/process.rs"
MARKER = "CAS-R68-SESSIONSTART-ONLY-HOOKS-AB"

text = PROCESS.read_text(encoding="utf-8")

if MARKER not in text:
    if "CAS-R67-HOOKS-RESTORED-SELECTIVE-STATE" not in text:
        raise SystemExit("r68 requires materialized r67 baseline")

    open_anchor = 'fn open_codex_app(platform: &str) -> Result<(), String> {\n'
    if open_anchor not in text:
        raise SystemExit("r68: open_codex_app anchor missing")

    helper = r'''
// CAS-R68-SESSIONSTART-ONLY-HOOKS-AB
//
// r66 proved that turning all hooks off eliminates the observed post-compaction
// silent stop, but that is too broad. r67 restored all hooks and preserved the
// user's per-hook states; the failure returned. Upstream Codex calls
// run_pending_session_start_hooks() both before first-turn admission and directly
// after a successful mid-turn auto-compaction, and a stop result ends the turn.
//
// r68 therefore keeps the global Hooks feature ON and disables only already-
// materialized SessionStart hook state entries. PreToolUse, PostToolUse, Stop,
// MCP tools, Plugins and Apps remain enabled. This is a narrowing A/B, not a
// synthetic continuation and not an HTTP/model/tool retry.
//
// We only edit [hooks.state.*] entries whose persisted hook key contains
// `:session_start:` (or `:sessionstart:` for compatibility). Existing non-
// SessionStart hook preferences are left byte-for-byte equivalent apart from the
// final normalized newline. No hook ids, paths, commands or account data are
// emitted into logs; only counts are logged.
fn sync_codex_session_start_only_guard_r68() {
    // First restore the global Hooks feature exactly as r67 does.
    sync_codex_hooks_selective_guard_r67();

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
            tracing::warn!("[compact-r68] action=session_start_only_ab status=skip reason=codex_home_unresolved");
            return;
        };
        let path = root.join("config.toml");
        let original = match fs::read_to_string(&path) {
            Ok(value) => value,
            Err(error) if error.kind() == std::io::ErrorKind::NotFound => {
                tracing::warn!("[compact-r68] action=session_start_only_ab status=skip reason=config_missing");
                return;
            }
            Err(error) => {
                tracing::warn!(error = %error, "[compact-r68] action=session_start_only_ab status=skip reason=read_failed");
                return;
            }
        };

        let mut output: Vec<String> = Vec::new();
        let mut in_session_start_state = false;
        let mut saw_enabled_in_current = false;
        let mut matched_state_tables = 0_u64;
        let mut changed_states = 0_u64;
        let mut direct_session_start_definitions = 0_u64;

        let finish_table = |output: &mut Vec<String>,
                            in_session_start_state: bool,
                            saw_enabled_in_current: bool,
                            changed_states: &mut u64| {
            if in_session_start_state && !saw_enabled_in_current {
                output.push("enabled = false # CAS-R68 SessionStart-only continuation A/B".to_owned());
                *changed_states += 1;
            }
        };

        for line in original.lines() {
            let trimmed = line.trim();
            let lower = trimmed.to_ascii_lowercase();
            let is_table = trimmed.starts_with('[') && trimmed.ends_with(']');

            if lower.contains("sessionstart") && !lower.starts_with("[hooks.state.") {
                direct_session_start_definitions += 1;
            }

            if is_table {
                finish_table(
                    &mut output,
                    in_session_start_state,
                    saw_enabled_in_current,
                    &mut changed_states,
                );

                in_session_start_state = lower.starts_with("[hooks.state.")
                    && (lower.contains(":session_start:")
                        || lower.contains(":sessionstart:"));
                saw_enabled_in_current = false;
                if in_session_start_state {
                    matched_state_tables += 1;
                }
                output.push(line.to_owned());
                continue;
            }

            if in_session_start_state {
                let key = trimmed
                    .split_once('=')
                    .map(|(key, _)| key.trim().to_ascii_lowercase())
                    .unwrap_or_default();
                if key == "enabled" {
                    saw_enabled_in_current = true;
                    let desired = "enabled = false # CAS-R68 SessionStart-only continuation A/B";
                    if trimmed != desired {
                        changed_states += 1;
                    }
                    output.push(desired.to_owned());
                    continue;
                }
            }

            output.push(line.to_owned());
        }

        finish_table(
            &mut output,
            in_session_start_state,
            saw_enabled_in_current,
            &mut changed_states,
        );

        if matched_state_tables == 0 {
            tracing::warn!(
                direct_session_start_definitions,
                "[compact-r68] action=session_start_only_ab status=no_materialized_session_start_states mode=hooks_on"
            );
            return;
        }

        let mut updated = output.join("\n");
        updated.push('\n');
        if updated == original {
            tracing::info!(
                matched_state_tables,
                changed_states,
                direct_session_start_definitions,
                "[compact-r68] action=session_start_only_ab status=already_disabled mode=hooks_on_other_events_preserved"
            );
            return;
        }
        if let Err(error) = fs::write(&path, updated) {
            tracing::warn!(error = %error, "[compact-r68] action=session_start_only_ab status=skip reason=write_failed");
            return;
        }
        tracing::warn!(
            matched_state_tables,
            changed_states,
            direct_session_start_definitions,
            "[compact-r68] action=session_start_only_ab status=applied mode=hooks_on_other_events_preserved"
        );
    }
}

'''
    text = text.replace(open_anchor, helper + open_anchor, 1)

    r67_call = "    sync_codex_hooks_selective_guard_r67();"
    if text.count(r67_call) != 2:
        raise SystemExit("r68 expected exactly two inherited r67 launch-pipeline calls")
    text = text.replace(r67_call, "    sync_codex_session_start_only_guard_r68();")

    PROCESS.write_text(text, encoding="utf-8")
    print("R68 SESSIONSTART-ONLY HOOKS A/B PATCH APPLIED")
else:
    print("R68 SESSIONSTART-ONLY HOOKS A/B PATCH ALREADY APPLIED")

verify = PROCESS.read_text(encoding="utf-8")
for marker in (
    "CAS-R68-SESSIONSTART-ONLY-HOOKS-AB",
    "sync_codex_session_start_only_guard_r68",
    "[compact-r68] action=session_start_only_ab",
    "CAS-R67-HOOKS-RESTORED-SELECTIVE-STATE",
    "CAS-R66-POST-COMPACT-HOOKS-AB",
    "CAS-R65-FIRST-TURN-STARTUP-GENERATION-GATE",
    "CAS-R64-POST-COMPACT-CONTINUATION-GUARD",
    "CAS-R61-LEGACY-COMPACTION-V1",
):
    if marker not in verify:
        raise SystemExit(f"r68 patch invariant missing: {marker}")

if verify.count("sync_codex_session_start_only_guard_r68();") != 2:
    raise SystemExit("r68 expected normal + alternate launch guards")
if verify.count("sync_codex_hooks_selective_guard_r67();") < 1:
    raise SystemExit("r68 must call the r67 global-hooks restore helper internally")

print("R68 PATCH VERIFY PASS")
print("- global Codex Hooks remain ON")
print("- only persisted SessionStart hook states are forced disabled")
print("- PreToolUse/PostToolUse/Stop and non-SessionStart plugin hooks preserved")
print("- Plugins/Apps/MCP settings untouched")
print("- no prompt/model/tool/compact retry added")
'@
Set-Content -LiteralPath (Join-Path $RepoRoot 'scripts\apply_r68_local.py') -Value $patchPy -Encoding UTF8

Write-Host "[1/4] Applying r68 SessionStart-only A/B patch..." -ForegroundColor Cyan
python .\scripts\apply_r68_local.py
if ($LASTEXITCODE -ne 0) { throw 'r68 patch failed' }

Write-Host "[2/4] Stamping r68 version..." -ForegroundColor Cyan
Set-Content -LiteralPath .\SUB2API_GROK_COMPAT_REVISION.txt -Value '68' -Encoding ASCII
python .\scripts\apply_sub2api_grok_compat_revision.py
if ($LASTEXITCODE -ne 0) { throw 'r68 version materialization failed' }

Write-Host "[3/4] Preparing r68 fast builder..." -ForegroundColor Cyan
if (-not (Test-Path -LiteralPath .\scripts\build-r67-fast-real-use.ps1)) {
    throw 'r68 requires the existing local r67 fast builder; build r67 once first'
}

$prepPy = @'
from __future__ import annotations
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "scripts/build-r67-fast-real-use.ps1"
TARGET = ROOT / "scripts/build-r68-fast-real-use.ps1"

if not SOURCE.is_file():
    raise SystemExit("r68 builder: r67 builder missing")

text = SOURCE.read_text(encoding="utf-8")
replacements = [
    ("Codex App Transfer r67 - FAST REAL-USE BUILD", "Codex App Transfer r68 - FAST REAL-USE BUILD"),
    ("[1/9] Materialize r67", "[1/9] Materialize r68"),
    ("Warm r67 materialization detected; SKIP.", "Warm r68 materialization detected; SKIP."),
    (".\\scripts\\apply_r67_local.py", ".\\scripts\\apply_r68_local.py"),
    ("compat_revision=67", "compat_revision=68"),
    ("app_version=2\\.4\\.5\\+67", "app_version=2\\.4\\.5\\+68"),
    ("app_version=2.4.5+67", "app_version=2.4.5+68"),
    ("2.4.5+67", "2.4.5+68"),
    ("2.4.5-r67", "2.4.5-r68"),
    ("r67-real-use", "r68-real-use"),
    ("R67 FAST REAL-USE BUILD PASS", "R68 FAST REAL-USE BUILD PASS"),
    ("r67 FAST REAL-USE", "r68 FAST REAL-USE"),
    ("r67 FAST real-use", "r68 FAST real-use"),
    ("compatRevision = 67", "compatRevision = 68"),
]
for old, new in replacements:
    text = text.replace(old, new)

r67_guard = " -and ((Get-Content -LiteralPath (Join-Path $repoRoot 'src-tauri\\src\\admin\\services\\desktop\\process.rs') -Raw -Encoding UTF8) -match 'CAS-R67-HOOKS-RESTORED-SELECTIVE-STATE')"
r68_guard = r67_guard + " -and ((Get-Content -LiteralPath (Join-Path $repoRoot 'src-tauri\\src\\admin\\services\\desktop\\process.rs') -Raw -Encoding UTF8) -match 'CAS-R68-SESSIONSTART-ONLY-HOOKS-AB')"
if r67_guard not in text:
    raise SystemExit("r68 builder: r67 guard tail missing")
text = text.replace(r67_guard, r68_guard, 1)

for marker in (
    ".\\scripts\\apply_r68_local.py",
    "compat_revision=68",
    "app_version=2\\.4\\.5\\+68",
    "CAS-R67-HOOKS-RESTORED-SELECTIVE-STATE",
    "CAS-R68-SESSIONSTART-ONLY-HOOKS-AB",
    "r68-real-use",
):
    if marker not in text:
        raise SystemExit(f"r68 builder invariant missing: {marker}")

TARGET.write_text(text, encoding="utf-8")
print("R68 FAST BUILDER PREP PASS")
'@
Set-Content -LiteralPath (Join-Path $RepoRoot 'scripts\prepare-r68-local-builder.py') -Value $prepPy -Encoding UTF8
python .\scripts\prepare-r68-local-builder.py
if ($LASTEXITCODE -ne 0) { throw 'r68 builder generation failed' }

if (Test-Path -LiteralPath .\scripts\Repair-r57-Build-Space.ps1) {
    pwsh -NoProfile -ExecutionPolicy Bypass -File .\scripts\Repair-r57-Build-Space.ps1
    if ($LASTEXITCODE -ne 0) { throw 'V: build-space check failed' }
}

Write-Host "[4/4] Building r68 locally..." -ForegroundColor Cyan
pwsh -NoProfile -ExecutionPolicy Bypass -File .\scripts\build-r68-fast-real-use.ps1
if ($LASTEXITCODE -ne 0) { throw "r68 FAST build failed with exit code $LASTEXITCODE" }

Write-Host ""
Write-Host "[PASS] r68 local FAST REAL-USE build complete." -ForegroundColor Green
Write-Host "After install/restart, verify [compact-r68] session_start_only_ab matched_state_tables > 0." -ForegroundColor Green
Write-Host "Then test the same long thread: compact should resume without typing Continue, while non-SessionStart hooks/MCP remain available." -ForegroundColor Green
