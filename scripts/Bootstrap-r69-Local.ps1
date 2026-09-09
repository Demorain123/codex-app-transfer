$ErrorActionPreference = 'Stop'

$RepoRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $RepoRoot

Write-Host "============================================================" -ForegroundColor Cyan
Write-Host " Codex App Transfer r69 - SESSIONSTART + POSTCOMPACT HOOKS A/B" -ForegroundColor Cyan
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "Local build only; no GitHub Actions." -ForegroundColor DarkGray
Write-Host ""

$expectedHead = '0515e53567b2d148b9d4a10404074ea028b4fead'
$currentHead = (& git rev-parse HEAD).Trim()
if ($LASTEXITCODE -ne 0) { throw 'git rev-parse failed' }
if ($currentHead -ne $expectedHead) {
    throw "r69 bootstrap expects the same local r64 base HEAD $expectedHead; current HEAD is $currentHead"
}

$processPath = Join-Path $RepoRoot 'src-tauri\src\admin\services\desktop\process.rs'
$processText = Get-Content -LiteralPath $processPath -Raw -Encoding UTF8
foreach ($marker in @(
    'CAS-R61-LEGACY-COMPACTION-V1',
    'CAS-R64-POST-COMPACT-CONTINUATION-GUARD',
    'CAS-R65-FIRST-TURN-STARTUP-GENERATION-GATE',
    'CAS-R66-POST-COMPACT-HOOKS-AB',
    'CAS-R67-HOOKS-RESTORED-SELECTIVE-STATE',
    'CAS-R68-SESSIONSTART-ONLY-HOOKS-AB'
)) {
    if ($processText -notmatch [regex]::Escape($marker)) {
        throw "r69 bootstrap requires the materialized r68 local tree; missing marker: $marker"
    }
}

$patchPy = @'
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROCESS = ROOT / "src-tauri/src/admin/services/desktop/process.rs"
MARKER = "CAS-R69-SESSIONSTART-POSTCOMPACT-HOOKS-AB"

text = PROCESS.read_text(encoding="utf-8")

if MARKER not in text:
    if "CAS-R68-SESSIONSTART-ONLY-HOOKS-AB" not in text:
        raise SystemExit("r69 requires materialized r68 baseline")

    open_anchor = 'fn open_codex_app(platform: &str) -> Result<(), String> {\n'
    if open_anchor not in text:
        raise SystemExit("r69: open_codex_app anchor missing")

    helper = r'''
// CAS-R69-SESSIONSTART-POSTCOMPACT-HOOKS-AB
//
// r68 kept global Hooks enabled and disabled persisted SessionStart handlers, but
// the real long-session regression still reproduced after a successful compact.
// Current Codex also runs PostCompact hooks after compaction, and a PostCompact
// handler that returns continue=false produces PostCompactHookOutcome::Stopped,
// which aborts the turn. r69 therefore keeps the r68 SessionStart A/B and adds
// only PostCompact state disabling. All other hook events remain enabled.
//
// This is still a narrowing A/B: no prompt/model/tool/compact request is retried.
fn sync_codex_compact_lifecycle_guard_r69() {
    sync_codex_session_start_only_guard_r68();

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
            tracing::warn!("[compact-r69] action=postcompact_sessionstart_ab status=skip reason=codex_home_unresolved");
            return;
        };
        let path = root.join("config.toml");
        let original = match fs::read_to_string(&path) {
            Ok(value) => value,
            Err(error) if error.kind() == std::io::ErrorKind::NotFound => {
                tracing::warn!("[compact-r69] action=postcompact_sessionstart_ab status=skip reason=config_missing");
                return;
            }
            Err(error) => {
                tracing::warn!(error = %error, "[compact-r69] action=postcompact_sessionstart_ab status=skip reason=read_failed");
                return;
            }
        };

        let mut output: Vec<String> = Vec::new();
        let mut in_post_compact_state = false;
        let mut saw_enabled_in_current = false;
        let mut matched_post_compact_state_tables = 0_u64;
        let mut changed_post_compact_states = 0_u64;

        let finish_table = |output: &mut Vec<String>,
                            in_post_compact_state: bool,
                            saw_enabled_in_current: bool,
                            changed: &mut u64| {
            if in_post_compact_state && !saw_enabled_in_current {
                output.push("enabled = false # CAS-R69 PostCompact continuation A/B".to_owned());
                *changed += 1;
            }
        };

        for line in original.lines() {
            let trimmed = line.trim();
            let lower = trimmed.to_ascii_lowercase();
            let is_table = trimmed.starts_with('[') && trimmed.ends_with(']');

            if is_table {
                finish_table(
                    &mut output,
                    in_post_compact_state,
                    saw_enabled_in_current,
                    &mut changed_post_compact_states,
                );
                in_post_compact_state = lower.starts_with("[hooks.state.")
                    && lower.contains(":post_compact:");
                saw_enabled_in_current = false;
                if in_post_compact_state {
                    matched_post_compact_state_tables += 1;
                }
                output.push(line.to_owned());
                continue;
            }

            if in_post_compact_state {
                let key = trimmed
                    .split_once('=')
                    .map(|(key, _)| key.trim().to_ascii_lowercase())
                    .unwrap_or_default();
                if key == "enabled" {
                    saw_enabled_in_current = true;
                    let desired = "enabled = false # CAS-R69 PostCompact continuation A/B";
                    if trimmed != desired {
                        changed_post_compact_states += 1;
                    }
                    output.push(desired.to_owned());
                    continue;
                }
            }

            output.push(line.to_owned());
        }

        finish_table(
            &mut output,
            in_post_compact_state,
            saw_enabled_in_current,
            &mut changed_post_compact_states,
        );

        if matched_post_compact_state_tables == 0 {
            tracing::warn!(
                "[compact-r69] action=postcompact_sessionstart_ab status=no_materialized_postcompact_states mode=sessionstart_disabled_other_hooks_on"
            );
            return;
        }

        let mut updated = output.join("\n");
        updated.push('\n');
        if updated == original {
            tracing::info!(
                matched_post_compact_state_tables,
                changed_post_compact_states,
                "[compact-r69] action=postcompact_sessionstart_ab status=already_disabled mode=sessionstart_plus_postcompact_disabled_other_hooks_on"
            );
            return;
        }
        if let Err(error) = fs::write(&path, updated) {
            tracing::warn!(error = %error, "[compact-r69] action=postcompact_sessionstart_ab status=skip reason=write_failed");
            return;
        }
        tracing::warn!(
            matched_post_compact_state_tables,
            changed_post_compact_states,
            "[compact-r69] action=postcompact_sessionstart_ab status=applied mode=sessionstart_plus_postcompact_disabled_other_hooks_on"
        );
    }
}

'''
    text = text.replace(open_anchor, helper + open_anchor, 1)

    r68_call = "    sync_codex_session_start_only_guard_r68();"
    prefix, suffix = text.split(open_anchor, 1)
    if suffix.count(r68_call) != 2:
        raise SystemExit(
            f"r69 expected exactly two inherited r68 launch-pipeline calls after open_codex_app; found {suffix.count(r68_call)}"
        )
    suffix = suffix.replace(r68_call, "    sync_codex_compact_lifecycle_guard_r69();")
    text = prefix + open_anchor + suffix

    PROCESS.write_text(text, encoding="utf-8")
    print("R69 SESSIONSTART + POSTCOMPACT HOOKS A/B PATCH APPLIED")
else:
    print("R69 SESSIONSTART + POSTCOMPACT HOOKS A/B PATCH ALREADY APPLIED")

verify = PROCESS.read_text(encoding="utf-8")
for marker in (
    "CAS-R69-SESSIONSTART-POSTCOMPACT-HOOKS-AB",
    "sync_codex_compact_lifecycle_guard_r69",
    "[compact-r69] action=postcompact_sessionstart_ab",
    "CAS-R68-SESSIONSTART-ONLY-HOOKS-AB",
    "CAS-R67-HOOKS-RESTORED-SELECTIVE-STATE",
    "CAS-R66-POST-COMPACT-HOOKS-AB",
    "CAS-R65-FIRST-TURN-STARTUP-GENERATION-GATE",
    "CAS-R64-POST-COMPACT-CONTINUATION-GUARD",
    "CAS-R61-LEGACY-COMPACTION-V1",
):
    if marker not in verify:
        raise SystemExit(f"r69 patch invariant missing: {marker}")

if verify.count("sync_codex_compact_lifecycle_guard_r69();") != 2:
    raise SystemExit("r69 expected normal + alternate launch guards")
if verify.count("sync_codex_session_start_only_guard_r68();") < 1:
    raise SystemExit("r69 must preserve the r68 SessionStart guard internally")

print("R69 PATCH VERIFY PASS")
print("- global Codex Hooks remain ON")
print("- r68 SessionStart-disabled state retained")
print("- persisted PostCompact hook states are additionally disabled")
print("- PreToolUse/PostToolUse/Stop/UserPromptSubmit and other hooks remain enabled")
print("- Plugins/Apps/MCP settings untouched")
print("- no prompt/model/tool/compact retry added")
'@
Set-Content -LiteralPath (Join-Path $RepoRoot 'scripts\apply_r69_local.py') -Value $patchPy -Encoding UTF8

Write-Host "[1/4] Applying r69 compact-lifecycle hooks A/B patch..." -ForegroundColor Cyan
python .\scripts\apply_r69_local.py
if ($LASTEXITCODE -ne 0) { throw 'r69 patch failed' }

Write-Host "[2/4] Stamping r69 version..." -ForegroundColor Cyan
Set-Content -LiteralPath .\SUB2API_GROK_COMPAT_REVISION.txt -Value '69' -Encoding ASCII
python .\scripts\apply_sub2api_grok_compat_revision.py
if ($LASTEXITCODE -ne 0) { throw 'r69 version materialization failed' }

Write-Host "[3/4] Preparing r69 fast builder..." -ForegroundColor Cyan
if (-not (Test-Path -LiteralPath .\scripts\build-r68-fast-real-use.ps1)) {
    throw 'r69 requires the existing local r68 fast builder; build r68 once first'
}

$prepPy = @'
from __future__ import annotations
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "scripts/build-r68-fast-real-use.ps1"
TARGET = ROOT / "scripts/build-r69-fast-real-use.ps1"

if not SOURCE.is_file():
    raise SystemExit("r69 builder: r68 builder missing")

text = SOURCE.read_text(encoding="utf-8")
replacements = [
    ("Codex App Transfer r68 - FAST REAL-USE BUILD", "Codex App Transfer r69 - FAST REAL-USE BUILD"),
    ("[1/9] Materialize r68", "[1/9] Materialize r69"),
    ("Warm r68 materialization detected; SKIP.", "Warm r69 materialization detected; SKIP."),
    (".\\scripts\\apply_r68_local.py", ".\\scripts\\apply_r69_local.py"),
    ("compat_revision=68", "compat_revision=69"),
    ("app_version=2\\.4\\.5\\+68", "app_version=2\\.4\\.5\\+69"),
    ("app_version=2.4.5+68", "app_version=2.4.5+69"),
    ("2.4.5+68", "2.4.5+69"),
    ("2.4.5-r68", "2.4.5-r69"),
    ("r68-real-use", "r69-real-use"),
    ("R68 FAST REAL-USE BUILD PASS", "R69 FAST REAL-USE BUILD PASS"),
    ("r68 FAST REAL-USE", "r69 FAST REAL-USE"),
    ("r68 FAST real-use", "r69 FAST real-use"),
    ("compatRevision = 68", "compatRevision = 69"),
]
for old, new in replacements:
    text = text.replace(old, new)

r68_guard = " -and ((Get-Content -LiteralPath (Join-Path $repoRoot 'src-tauri\\src\\admin\\services\\desktop\\process.rs') -Raw -Encoding UTF8) -match 'CAS-R68-SESSIONSTART-ONLY-HOOKS-AB')"
r69_guard = r68_guard + " -and ((Get-Content -LiteralPath (Join-Path $repoRoot 'src-tauri\\src\\admin\\services\\desktop\\process.rs') -Raw -Encoding UTF8) -match 'CAS-R69-SESSIONSTART-POSTCOMPACT-HOOKS-AB')"
if r68_guard not in text:
    raise SystemExit("r69 builder: r68 guard tail missing")
text = text.replace(r68_guard, r69_guard, 1)

for marker in (
    ".\\scripts\\apply_r69_local.py",
    "compat_revision=69",
    "app_version=2\\.4\\.5\\+69",
    "CAS-R68-SESSIONSTART-ONLY-HOOKS-AB",
    "CAS-R69-SESSIONSTART-POSTCOMPACT-HOOKS-AB",
    "r69-real-use",
):
    if marker not in text:
        raise SystemExit(f"r69 builder invariant missing: {marker}")

TARGET.write_text(text, encoding="utf-8")
print("R69 FAST BUILDER PREP PASS")
'@
Set-Content -LiteralPath (Join-Path $RepoRoot 'scripts\prepare-r69-local-builder.py') -Value $prepPy -Encoding UTF8
python .\scripts\prepare-r69-local-builder.py
if ($LASTEXITCODE -ne 0) { throw 'r69 builder generation failed' }

if (Test-Path -LiteralPath .\scripts\Repair-r57-Build-Space.ps1) {
    pwsh -NoProfile -ExecutionPolicy Bypass -File .\scripts\Repair-r57-Build-Space.ps1
    if ($LASTEXITCODE -ne 0) { throw 'V: build-space check failed' }
}

Write-Host "[4/4] Building r69 locally..." -ForegroundColor Cyan
pwsh -NoProfile -ExecutionPolicy Bypass -File .\scripts\build-r69-fast-real-use.ps1
if ($LASTEXITCODE -ne 0) { throw "r69 FAST build failed with exit code $LASTEXITCODE" }

Write-Host ""
Write-Host "[PASS] r69 local FAST REAL-USE build complete." -ForegroundColor Green
Write-Host "After install/restart, verify [compact-r69] postcompact_sessionstart_ab matched_post_compact_state_tables > 0." -ForegroundColor Green
Write-Host "Then use the same long thread. Expected: MCP/plugins still work; automatic compact continues without manual Continue." -ForegroundColor Green
