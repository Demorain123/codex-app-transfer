from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROCESS = ROOT / "src-tauri/src/admin/services/desktop/process.rs"
MARKER = "CAS-R65-FIRST-TURN-STARTUP-GENERATION-GATE"

text = PROCESS.read_text(encoding="utf-8")

for required in (
    "CAS-R58-WINDOWS-CHATGPT-LIFECYCLE-GUARD",
    "CAS-R61-LEGACY-COMPACTION-V1",
    "CAS-R64-POST-COMPACT-CONTINUATION-GUARD",
):
    if required not in text:
        raise SystemExit(f"r65 requires materialized r64 stack; missing: {required}")

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
