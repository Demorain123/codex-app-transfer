$ErrorActionPreference = 'Stop'

$RepoRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $RepoRoot

Write-Host "============================================================" -ForegroundColor Cyan
Write-Host " Codex App Transfer r65 - LOCAL BOOTSTRAP + FAST BUILD" -ForegroundColor Cyan
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "Local build only; no GitHub Actions." -ForegroundColor DarkGray
Write-Host ""

$expectedHead = '0515e53567b2d148b9d4a10404074ea028b4fead'
$currentHead = (& git rev-parse HEAD).Trim()
if ($LASTEXITCODE -ne 0) { throw 'git rev-parse failed' }
if ($currentHead -ne $expectedHead) {
    throw "r65 bootstrap expects r64 base HEAD $expectedHead; current HEAD is $currentHead"
}

$processPath = Join-Path $RepoRoot 'src-tauri\src\admin\services\desktop\process.rs'
$processText = Get-Content -LiteralPath $processPath -Raw -Encoding UTF8
foreach ($marker in @(
    'CAS-R58-WINDOWS-CHATGPT-LIFECYCLE-GUARD',
    'CAS-R61-LEGACY-COMPACTION-V1',
    'CAS-R64-POST-COMPACT-CONTINUATION-GUARD'
)) {
    if ($processText -notmatch [regex]::Escape($marker)) {
        throw "r65 bootstrap requires the materialized r64 local tree; missing marker: $marker"
    }
}

$patchPy = @'
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROCESS = ROOT / "src-tauri/src/admin/services/desktop/process.rs"
MARKER = "CAS-R65-FIRST-TURN-STARTUP-GENERATION-GATE"

text = PROCESS.read_text(encoding="utf-8")

if MARKER not in text:
    anchor = "\nfn open_codex_app(platform: &str) -> Result<(), String> {"
    helper = r'''
// CAS-R65-FIRST-TURN-STARTUP-GENERATION-GATE
//
// Do not retry a user's prompt. After Transfer launches Codex, observe only the
// exact packaged app/resources/codex.exe generation. Any PID replacement resets
// the readiness window. This targets the first-turn startup race where the
// app-server generation can be replaced by startup/runtime synchronization.
#[cfg(target_os = "windows")]
fn wait_for_codex_startup_generation_r65() -> bool {
    let script = r#"
$ErrorActionPreference='Stop'
$pkg = Get-AppxPackage -Name 'OpenAI.Codex' |
    Sort-Object Version -Descending |
    Select-Object -First 1

if($null -eq $pkg){
    Write-Output 'status=skip reason=package_not_found'
    exit 0
}

$server = Join-Path $pkg.InstallLocation 'app\resources\codex.exe'
if(-not (Test-Path -LiteralPath $server -PathType Leaf)){
    Write-Output 'status=skip reason=app_server_binary_not_found'
    exit 0
}

$serverFull=[IO.Path]::GetFullPath($server)
$deadline=[DateTime]::UtcNow.AddSeconds(18)
$requiredMs=4000
$lastKey=''
$stableSince=$null
$changes=0
$everSeen=$false
$maxCount=0

while([DateTime]::UtcNow -lt $deadline){
    $pids=@(
        Get-CimInstance Win32_Process -Filter "Name='codex.exe'" |
        Where-Object {
            $_.ExecutablePath -and
            [string]::Equals(
                [IO.Path]::GetFullPath([string]$_.ExecutablePath),
                $serverFull,
                [StringComparison]::OrdinalIgnoreCase
            )
        } |
        Sort-Object ProcessId |
        ForEach-Object { [int]$_.ProcessId }
    )

    if($pids.Count -gt $maxCount){ $maxCount=$pids.Count }
    $key=$pids -join ','

    if($pids.Count -gt 0){
        $everSeen=$true
        if($key -ne $lastKey){
            if(-not [string]::IsNullOrEmpty($lastKey)){ $changes++ }
            $lastKey=$key
            $stableSince=[DateTime]::UtcNow
        } elseif(
            $null -ne $stableSince -and
            (([DateTime]::UtcNow-$stableSince).TotalMilliseconds -ge $requiredMs)
        ){
            Write-Output ('status=stable count={0} changes={1} max_count={2} stable_ms={3}' -f $pids.Count,$changes,$maxCount,$requiredMs)
            exit 0
        }
    } else {
        if(-not [string]::IsNullOrEmpty($lastKey)){ $changes++ }
        $lastKey=''
        $stableSince=$null
    }

    Start-Sleep -Milliseconds 400
}

Write-Output ('status=timeout seen={0} changes={1} max_count={2}' -f ([int]$everSeen),$changes,$maxCount)
exit 0
"#;

    let mut command = Command::new("powershell");
    command
        .args(["-NoProfile", "-NonInteractive", "-Command", script])
        .stdin(Stdio::null())
        .stderr(Stdio::null());

    let output = match hide_console_window(&mut command).output() {
        Ok(output) => output,
        Err(error) => {
            tracing::warn!(
                error = %error,
                "[turn-start-r65] action=startup_generation_gate status=probe_failed_fail_open"
            );
            return false;
        }
    };

    if !output.status.success() {
        tracing::warn!(
            exit_code = ?output.status.code(),
            "[turn-start-r65] action=startup_generation_gate status=probe_failed_fail_open"
        );
        return false;
    }

    let summary = String::from_utf8_lossy(&output.stdout)
        .trim()
        .replace('\r', "")
        .replace('\n', " ");

    if summary.contains("status=stable") {
        tracing::info!(
            result = %summary,
            "[turn-start-r65] action=startup_generation_gate status=stable"
        );
        true
    } else {
        tracing::warn!(
            result = %summary,
            "[turn-start-r65] action=startup_generation_gate status=degraded_fail_open"
        );
        false
    }
}

#[cfg(not(target_os = "windows"))]
fn wait_for_codex_startup_generation_r65() -> bool {
    true
}

'''
    if anchor not in text:
        raise SystemExit("r65 patch: open_codex_app anchor missing")
    text = text.replace(anchor, "\n" + helper + anchor, 1)

    old = '''    if was_running {
        std::thread::sleep(POST_QUIT_LAUNCHD_GRACE);
    }
    launcher()
}'''
    new = '''    if was_running {
        std::thread::sleep(POST_QUIT_LAUNCHD_GRACE);
    }

    let launched = launcher()?;
    let generation_stable = wait_for_codex_startup_generation_r65();
    if generation_stable {
        tracing::info!(
            "[turn-start-r65] action=restart_return status=first_turn_ready"
        );
    } else {
        tracing::warn!(
            "[turn-start-r65] action=restart_return status=generation_gate_degraded_fail_open"
        );
    }
    Ok(launched)
}'''
    if old not in text:
        raise SystemExit("r65 patch: shared restart pipeline anchor missing")
    text = text.replace(old, new, 1)
    PROCESS.write_text(text, encoding="utf-8")
    print("R65 STARTUP GENERATION GATE APPLIED")
else:
    print("R65 STARTUP GENERATION GATE ALREADY APPLIED")

verify = PROCESS.read_text(encoding="utf-8")
for marker in (
    "CAS-R65-FIRST-TURN-STARTUP-GENERATION-GATE",
    "wait_for_codex_startup_generation_r65",
    "[turn-start-r65] action=startup_generation_gate",
    "[turn-start-r65] action=restart_return status=first_turn_ready",
    "CAS-R64-POST-COMPACT-CONTINUATION-GUARD",
    "CAS-R61-LEGACY-COMPACTION-V1",
):
    if marker not in verify:
        raise SystemExit(f"r65 patch invariant missing: {marker}")

print("R65 PATCH VERIFY PASS")
'@
Set-Content -LiteralPath (Join-Path $RepoRoot 'scripts\apply_r65_local.py') -Value $patchPy -Encoding UTF8

Write-Host "[1/4] Applying r65 local patch..." -ForegroundColor Cyan
python .\scripts\apply_r65_local.py
if ($LASTEXITCODE -ne 0) { throw 'r65 patch failed' }

Write-Host "[2/4] Stamping r65 version..." -ForegroundColor Cyan
Set-Content -LiteralPath .\SUB2API_GROK_COMPAT_REVISION.txt -Value '65' -Encoding ASCII
python .\scripts\apply_sub2api_grok_compat_revision.py
if ($LASTEXITCODE -ne 0) { throw 'r65 version materialization failed' }

Write-Host "[3/4] Preparing r65 fast builder..." -ForegroundColor Cyan
if (-not (Test-Path -LiteralPath .\scripts\build-r64-fast-real-use.ps1)) {
    python .\scripts\prepare-r64-fast-builder.py
    if ($LASTEXITCODE -ne 0) { throw 'r64 builder preparation failed' }
}

$prepPy = @'
from __future__ import annotations
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "scripts/build-r64-fast-real-use.ps1"
TARGET = ROOT / "scripts/build-r65-fast-real-use.ps1"

if not SOURCE.is_file():
    raise SystemExit("r65 builder: r64 builder missing")

text = SOURCE.read_text(encoding="utf-8")
replacements = [
    ("Codex App Transfer r64 - FAST REAL-USE BUILD", "Codex App Transfer r65 - FAST REAL-USE BUILD"),
    ("[1/9] Materialize r64", "[1/9] Materialize r65"),
    ("Warm r64 materialization detected; SKIP.", "Warm r65 materialization detected; SKIP."),
    (".\\scripts\\apply_r64_unified.py", ".\\scripts\\apply_r65_local.py"),
    ("compat_revision=64", "compat_revision=65"),
    ("app_version=2\\.4\\.5\\+64", "app_version=2\\.4\\.5\\+65"),
    ("app_version=2.4.5+64", "app_version=2.4.5+65"),
    ("2.4.5+64", "2.4.5+65"),
    ("2.4.5-r64", "2.4.5-r65"),
    ("r64-real-use", "r65-real-use"),
    ("R64 FAST REAL-USE BUILD PASS", "R65 FAST REAL-USE BUILD PASS"),
    ("r64 FAST REAL-USE", "r65 FAST REAL-USE"),
    ("r64 FAST real-use", "r65 FAST real-use"),
    ("compatRevision = 64", "compatRevision = 65"),
]
for old, new in replacements:
    text = text.replace(old, new)

r64_guard = " -and ((Get-Content -LiteralPath (Join-Path $repoRoot 'src-tauri\\src\\admin\\services\\desktop\\process.rs') -Raw -Encoding UTF8) -match 'CAS-R64-POST-COMPACT-CONTINUATION-GUARD')"
r65_guard = r64_guard + " -and ((Get-Content -LiteralPath (Join-Path $repoRoot 'src-tauri\\src\\admin\\services\\desktop\\process.rs') -Raw -Encoding UTF8) -match 'CAS-R65-FIRST-TURN-STARTUP-GENERATION-GATE')"
if r64_guard not in text:
    raise SystemExit("r65 builder: r64 guard tail missing")
text = text.replace(r64_guard, r65_guard, 1)

for marker in (
    ".\\scripts\\apply_r65_local.py",
    "compat_revision=65",
    "app_version=2\\.4\\.5\\+65",
    "CAS-R64-POST-COMPACT-CONTINUATION-GUARD",
    "CAS-R65-FIRST-TURN-STARTUP-GENERATION-GATE",
    "r65-real-use",
):
    if marker not in text:
        raise SystemExit(f"r65 builder invariant missing: {marker}")

TARGET.write_text(text, encoding="utf-8")
print("R65 FAST BUILDER PREP PASS")
'@
Set-Content -LiteralPath (Join-Path $RepoRoot 'scripts\prepare-r65-local-builder.py') -Value $prepPy -Encoding UTF8
python .\scripts\prepare-r65-local-builder.py
if ($LASTEXITCODE -ne 0) { throw 'r65 builder generation failed' }

if (Test-Path -LiteralPath .\scripts\Repair-r57-Build-Space.ps1) {
    pwsh -NoProfile -ExecutionPolicy Bypass -File .\scripts\Repair-r57-Build-Space.ps1
    if ($LASTEXITCODE -ne 0) { throw 'V: build-space check failed' }
}

Write-Host "[4/4] Building r65 locally..." -ForegroundColor Cyan
pwsh -NoProfile -ExecutionPolicy Bypass -File .\scripts\build-r65-fast-real-use.ps1
if ($LASTEXITCODE -ne 0) { throw "r65 FAST build failed with exit code $LASTEXITCODE" }

Write-Host ""
Write-Host "[PASS] r65 local FAST REAL-USE build complete." -ForegroundColor Green
Write-Host "Test by restarting Codex through Transfer, wait for first_turn_ready, then send the first prompt once." -ForegroundColor Green
