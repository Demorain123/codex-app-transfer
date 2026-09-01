from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "src-tauri/src/admin/services/desktop/process.rs"
MARKER = "CAS-R58-WINDOWS-CHATGPT-LIFECYCLE-GUARD"

source = TARGET.read_text(encoding="utf-8")
if MARKER in source:
    print("r58 Windows ChatGPT lifecycle guard already applied")
    raise SystemExit(0)

# r58 fixes two Windows lifecycle problems exposed by Codex Desktop 26.707+:
# 1. The packaged desktop main executable is ChatGPT.exe, while older restart code still
#    treated Codex.exe/codex.exe as the desktop process. That can terminate the internal
#    app-server child while leaving the Electron shell alive, surfacing 0xC000013A.
# 2. After r57 migrates external MCP sources, a still-running OMP/CC Switch generation can
#    retain the old install-directory webfetch helper command in memory. Do not restart
#    Codex while that exact stale helper is still alive.

old_const = 'const WINDOWS_PROCESS_NAME: &str = "Codex.exe";\n'
if old_const not in source:
    raise SystemExit("r58: Windows process-name anchor missing")
source = source.replace(
    old_const,
    '''// CAS-R58-WINDOWS-CHATGPT-LIFECYCLE-GUARD\n// Codex Desktop 26.707+ renamed the packaged main executable to ChatGPT.exe.  Do not\n// confuse its internal `codex.exe` app-server child with the desktop process.\nconst WINDOWS_MAIN_PROCESS_NAMES: &[&str] = &["ChatGPT.exe", "Codex.exe"];\n''',
    1,
)

old_running = '''        "windows" => vec![\n            "tasklist".into(),\n            "/FI".into(),\n            format!("IMAGENAME eq {WINDOWS_PROCESS_NAME}"),\n            "/FO".into(),\n            "CSV".into(),\n            "/NH".into(),\n        ],\n'''
new_running = '''        "windows" => vec![\n            "powershell".into(),\n            "-NoProfile".into(),\n            "-NonInteractive".into(),\n            "-Command".into(),\n            // Resolve the exact OpenAI.Codex package executable first.  Matching only\n            // `ChatGPT.exe` would also hit the consumer ChatGPT app; matching `codex.exe`\n            // hits the app-server child.  Exact ExecutablePath avoids both mistakes.\n            r#"$pkg=Get-AppxPackage -Name 'OpenAI.Codex' | Sort-Object Version -Descending | Select-Object -First 1; if($null -eq $pkg){exit 1}; $target=@((Join-Path $pkg.InstallLocation 'app\\ChatGPT.exe'),(Join-Path $pkg.InstallLocation 'app\\Codex.exe')) | Where-Object { Test-Path -LiteralPath $_ -PathType Leaf } | Select-Object -First 1; if(-not $target){exit 1}; $hit=@(Get-CimInstance Win32_Process -Filter \"Name='ChatGPT.exe' OR Name='Codex.exe'\" | Where-Object { $_.ExecutablePath -and [string]::Equals([IO.Path]::GetFullPath([string]$_.ExecutablePath),[IO.Path]::GetFullPath([string]$target),[StringComparison]::OrdinalIgnoreCase) }); if($hit.Count -gt 0){exit 0}else{exit 1}"#.into(),\n        ],\n'''
if old_running not in source:
    raise SystemExit("r58: Windows running-check anchor missing")
source = source.replace(old_running, new_running, 1)

old_quit = '''        ("windows", false) => vec![\n            "powershell".into(),\n            "-NoProfile".into(),\n            "-Command".into(),\n            "Get-CimInstance Win32_Process -Filter \\\"Name='Codex.exe' OR Name='codex.exe'\\\" | ForEach-Object { Stop-Process -Id $_.ProcessId -ErrorAction SilentlyContinue }".into(),\n        ],\n        ("windows", true) => vec![\n            "powershell".into(),\n            "-NoProfile".into(),\n            "-Command".into(),\n            "Get-CimInstance Win32_Process -Filter \\\"Name='Codex.exe' OR Name='codex.exe'\\\" | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }".into(),\n        ],\n'''
new_quit = '''        ("windows", false) => vec![\n            "powershell".into(),\n            "-NoProfile".into(),\n            "-NonInteractive".into(),\n            "-Command".into(),\n            r#"$pkg=Get-AppxPackage -Name 'OpenAI.Codex' | Sort-Object Version -Descending | Select-Object -First 1; if($null -eq $pkg){exit 0}; $target=@((Join-Path $pkg.InstallLocation 'app\\ChatGPT.exe'),(Join-Path $pkg.InstallLocation 'app\\Codex.exe')) | Where-Object { Test-Path -LiteralPath $_ -PathType Leaf } | Select-Object -First 1; if(-not $target){exit 0}; Get-CimInstance Win32_Process -Filter \"Name='ChatGPT.exe' OR Name='Codex.exe'\" | Where-Object { $_.ExecutablePath -and [string]::Equals([IO.Path]::GetFullPath([string]$_.ExecutablePath),[IO.Path]::GetFullPath([string]$target),[StringComparison]::OrdinalIgnoreCase) } | ForEach-Object { try { $p=Get-Process -Id $_.ProcessId -ErrorAction Stop; [void]$p.CloseMainWindow() } catch {} }"#.into(),\n        ],\n        ("windows", true) => vec![\n            "powershell".into(),\n            "-NoProfile".into(),\n            "-NonInteractive".into(),\n            "-Command".into(),\n            r#"$pkg=Get-AppxPackage -Name 'OpenAI.Codex' | Sort-Object Version -Descending | Select-Object -First 1; if($null -eq $pkg){exit 0}; $target=@((Join-Path $pkg.InstallLocation 'app\\ChatGPT.exe'),(Join-Path $pkg.InstallLocation 'app\\Codex.exe')) | Where-Object { Test-Path -LiteralPath $_ -PathType Leaf } | Select-Object -First 1; if(-not $target){exit 0}; Get-CimInstance Win32_Process -Filter \"Name='ChatGPT.exe' OR Name='Codex.exe'\" | Where-Object { $_.ExecutablePath -and [string]::Equals([IO.Path]::GetFullPath([string]$_.ExecutablePath),[IO.Path]::GetFullPath([string]$target),[StringComparison]::OrdinalIgnoreCase) } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }"#.into(),\n        ],\n'''
if old_quit not in source:
    raise SystemExit("r58: Windows quit-command anchor missing")
source = source.replace(old_quit, new_quit, 1)

old_native_probe = '''    #[cfg(target_os = "windows")]\n    if platform == "windows" {\n        if let Some(running) = crate::windows_msix::is_codex_running() {\n            return running;\n        }\n    }\n'''
new_native_probe = '''    #[cfg(target_os = "windows")]\n    if platform == "windows" {\n        // r58 deliberately bypasses the old windows_msix name-only probe here.  That\n        // probe predates the 26.707 ChatGPT.exe rename and can mistake the internal\n        // codex.exe app-server for the desktop lifecycle owner.  The command below\n        // resolves OpenAI.Codex InstallLocation and checks the exact main EXE path.\n    }\n'''
if old_native_probe not in source:
    raise SystemExit("r58: native Windows running-probe anchor missing")
source = source.replace(old_native_probe, new_native_probe, 1)

old_windows_status = '''    if platform == "windows" {\n        // tasklist 即使没匹配也 exit 0,要看 stdout 里有没有 process 名\n        let mut command = Command::new(program);\n        command.args(args);\n        match hide_console_window(&mut command).output() {\n            Ok(out) => String::from_utf8_lossy(&out.stdout)\n                .to_ascii_lowercase()\n                .contains(&WINDOWS_PROCESS_NAME.to_ascii_lowercase()),\n            Err(_) => false,\n        }\n    } else {\n'''
new_windows_status = '''    if platform == "windows" {\n        // r58 PowerShell probe communicates the exact-path match via exit status.\n        let mut command = Command::new(program);\n        command.args(args).stdin(Stdio::null()).stdout(Stdio::null()).stderr(Stdio::null());\n        hide_console_window(&mut command)\n            .status()\n            .map(|s| s.success())\n            .unwrap_or(false)\n    } else {\n'''
if old_windows_status not in source:
    raise SystemExit("r58: Windows is-running result anchor missing")
source = source.replace(old_windows_status, new_windows_status, 1)

old_native_close = '''    #[cfg(target_os = "windows")]\n    if platform == "windows" && !force && crate::windows_msix::graceful_close_codex() > 0 {\n        return;\n    }\n'''
new_native_close = '''    #[cfg(target_os = "windows")]\n    if platform == "windows" {\n        // r58 uses the exact OpenAI.Codex package path in quit_command below.  Do not\n        // use the pre-26.707 name-only native window matcher here.\n    }\n'''
if old_native_close not in source:
    raise SystemExit("r58: native Windows graceful-close anchor missing")
source = source.replace(old_native_close, new_native_close, 1)

# Add an explicit stale-helper gate just before the restart pipeline.
restart_anchor = '''// CAS-NO-MICRO-R23-SHARED-RESTART-PIPELINE\n// CAS-NO-MICRO-R23-LEGACY-RESTART-PRESERVED\n'''
if restart_anchor not in source:
    raise SystemExit("r58: restart-pipeline anchor missing")
helper = r'''#[cfg(target_os = "windows")]
fn ensure_no_install_dir_webfetch_helper_r58() -> Result<(), String> {
    let current = std::env::current_exe()
        .map_err(|e| format!("r58 无法解析 Transfer 当前 EXE: {e}"))?;
    let current = current.to_string_lossy().to_string();
    let script = r#"
$ErrorActionPreference='Stop'
$target=[IO.Path]::GetFullPath($env:CAS_R58_TRANSFER_EXE)
$stale=@(Get-CimInstance Win32_Process -Filter "Name='codex-app-transfer.exe'" | Where-Object {
  $_.ExecutablePath -and $_.CommandLine -and
  [string]::Equals([IO.Path]::GetFullPath([string]$_.ExecutablePath),$target,[StringComparison]::OrdinalIgnoreCase) -and
  ([string]$_.CommandLine -match '--mcp-serve(?:=|-)webfetch')
})
if($stale.Count -gt 0){ exit 58 }
exit 0
"#;
    let mut command = Command::new("powershell");
    command
        .args(["-NoProfile", "-NonInteractive", "-Command", script])
        .env("CAS_R58_TRANSFER_EXE", &current)
        .stdin(Stdio::null())
        .stdout(Stdio::null())
        .stderr(Stdio::null());
    let status = hide_console_window(&mut command)
        .status()
        .map_err(|e| format!("r58 检查旧 MCP helper 失败: {e}"))?;
    if status.success() {
        return Ok(());
    }
    if status.code() == Some(58) {
        return Err(
            "检测到 OMP/CC Switch/Codex 的旧 generation 仍在使用安装目录 codex-app-transfer.exe 作为 webfetch MCP helper。r57 已迁移磁盘配置，但正在运行的外部 host 尚未 reload；请退出并重新启动 OMP/CC Switch 一次，再启动/重启 Codex。为避免只终止内部 app-server 导致 0xC000013A，本次启动已安全阻止。"
                .to_owned(),
        );
    }
    Err(format!(
        "r58 旧 MCP helper 检查异常退出: {:?}",
        status.code()
    ))
}

#[cfg(not(target_os = "windows"))]
fn ensure_no_install_dir_webfetch_helper_r58() -> Result<(), String> {
    Ok(())
}

'''
source = source.replace(restart_anchor, helper + restart_anchor, 1)

old_restart_guard = '''{\n    let _guard = CODEX_MAINTENANCE_LOCK\n        .lock()\n        .unwrap_or_else(|e| e.into_inner());\n    let was_running = is_codex_app_running(platform);\n'''
new_restart_guard = '''{\n    ensure_no_install_dir_webfetch_helper_r58()?;\n    let _guard = CODEX_MAINTENANCE_LOCK\n        .lock()\n        .unwrap_or_else(|e| e.into_inner());\n    let was_running = is_codex_app_running(platform);\n'''
# This exact block occurs in launch_codex_app_restart_with and with_codex_closed. Replace both.
count = source.count(old_restart_guard)
if count != 2:
    raise SystemExit(f"r58: expected 2 maintenance guard anchors, got {count}")
source = source.replace(old_restart_guard, new_restart_guard, 2)

# Update the existing platform-specific unit test to reflect exact package-path probing.
old_test = '''        let windows = running_check_command("windows");\n        assert_eq!(windows[0], "tasklist");\n        assert!(windows.iter().any(|a| a == "IMAGENAME eq Codex.exe"));\n        assert_eq!(running_check_command("linux"), vec!["pgrep", "-x", "codex"]);\n'''
new_test = '''        let windows = running_check_command("windows");\n        assert_eq!(windows[0], "powershell");\n        let joined = windows.join(" ");\n        assert!(joined.contains("OpenAI.Codex"));\n        assert!(joined.contains("ChatGPT.exe"));\n        assert!(joined.contains("ExecutablePath"));\n        assert_eq!(WINDOWS_MAIN_PROCESS_NAMES, &["ChatGPT.exe", "Codex.exe"]);\n        assert_eq!(running_check_command("linux"), vec!["pgrep", "-x", "codex"]);\n'''
if old_test not in source:
    raise SystemExit("r58: Windows running-check test anchor missing")
source = source.replace(old_test, new_test, 1)

TARGET.write_text(source, encoding="utf-8")
print("R58 WINDOWS CHATGPT LIFECYCLE GUARD PASS")
print("- Windows restart resolves the exact OpenAI.Codex package main executable (ChatGPT.exe; legacy Codex.exe fallback)")
print("- internal codex.exe app-server is no longer a direct restart/kill target")
print("- consumer ChatGPT.exe is not targeted because ExecutablePath must equal the OpenAI.Codex package path")
print("- stale install-directory webfetch helper blocks restart until OMP/CC Switch reload the r57 detached command")
