use serde::Serialize;
use serde_json::{json, Value};
use std::fs;
use std::path::{Path, PathBuf};
use std::process::{Command, Stdio};

const MIN_NODE_MAJOR: u32 = 22;
const TARGET_MODULE: &[u8] = b"@worklouder/device-kit-oai";
const SERIALPORT_MARKER: &[u8] = b"serialport";
const FEATURE_GATE_MARKER: &[u8] = b"3207467860";
const STUB_SHAPE_MARKERS: &[&[u8]] = &[
    b"ConnectionEventType",
    b"DeviceType",
    b"OAILightingEffect",
    b"RPCApiOAI",
    b"WLDeviceCommImpl",
    b"WLDeviceDiscovery",
];
const LAUNCHER_JS: &str = include_str!("../../../../resources/codex_no_micro_launcher.mjs");

#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct NoMicroDoctor {
    pub supported: bool,
    pub platform: String,
    pub package_found: bool,
    pub package_version: Option<String>,
    pub executable_path: Option<String>,
    pub app_asar_path: Option<String>,
    pub node_path: Option<String>,
    pub node_version: Option<String>,
    pub node_compatible: bool,
    pub target_module_count: usize,
    pub serialport_count: usize,
    pub feature_gate_count: usize,
    pub stub_shape_ok: bool,
    pub process_state: String,
    pub process_pids: Vec<u32>,
    pub compatible: bool,
    pub launch_ready: bool,
    pub last_launch: Option<Value>,
    pub warnings: Vec<String>,
}

impl NoMicroDoctor {
    fn unsupported() -> Self {
        Self {
            supported: false,
            platform: std::env::consts::OS.to_owned(),
            package_found: false,
            package_version: None,
            executable_path: None,
            app_asar_path: None,
            node_path: None,
            node_version: None,
            node_compatible: false,
            target_module_count: 0,
            serialport_count: 0,
            feature_gate_count: 0,
            stub_shape_ok: false,
            process_state: "unsupported".to_owned(),
            process_pids: Vec::new(),
            compatible: false,
            launch_ready: false,
            last_launch: read_last_launch(),
            warnings: vec![
                "Codex No Micro 目前仅支持 Windows Store/MSIX 版 Codex Desktop".to_owned(),
            ],
        }
    }
}

pub fn doctor() -> NoMicroDoctor {
    #[cfg(target_os = "windows")]
    {
        doctor_windows()
    }
    #[cfg(not(target_os = "windows"))]
    {
        NoMicroDoctor::unsupported()
    }
}

// CAS-NO-MICRO-R23-LAUNCH-ARGS
pub fn launch() -> Result<Value, String> {
    launch_with_args(&[])
}

/// Launch through the hardened No Micro injector while preserving the same Codex
/// launch arguments prepared by the legacy Restart pipeline (CDP/theme/quota/etc.).
pub fn launch_with_args(extra_args: &[String]) -> Result<Value, String> {
    #[cfg(target_os = "windows")]
    {
        launch_windows(extra_args)
    }
    #[cfg(not(target_os = "windows"))]
    {
        let _ = extra_args;
        Err("Codex No Micro 目前仅支持 Windows".to_owned())
    }
}

fn no_micro_dir() -> Option<PathBuf> {
    codex_app_transfer_registry::paths::resolve_home()
        .map(|home| home.join(".codex-app-transfer").join("codex-no-micro"))
}

fn last_launch_path() -> Option<PathBuf> {
    no_micro_dir().map(|dir| dir.join("last-launch.json"))
}

fn read_last_launch() -> Option<Value> {
    let path = last_launch_path()?;
    let bytes = fs::read(path).ok()?;
    serde_json::from_slice(&bytes).ok()
}

fn count_occurrences(haystack: &[u8], needle: &[u8]) -> usize {
    if needle.is_empty() || haystack.len() < needle.len() {
        return 0;
    }
    haystack
        .windows(needle.len())
        .filter(|window| *window == needle)
        .count()
}

fn parse_node_major(version: &str) -> Option<u32> {
    version
        .trim()
        .trim_start_matches('v')
        .split('.')
        .next()?
        .parse()
        .ok()
}

#[cfg(target_os = "windows")]
fn hide_console_window(command: &mut Command) -> &mut Command {
    use std::os::windows::process::CommandExt;
    const CREATE_NO_WINDOW: u32 = 0x0800_0000;
    command.creation_flags(CREATE_NO_WINDOW);
    command
}

#[cfg(target_os = "windows")]
fn run_powershell(script: &str, envs: &[(&str, &str)]) -> Result<String, String> {
    let mut command = Command::new("powershell.exe");
    command
        .args([
            "-NoLogo",
            "-NoProfile",
            "-NonInteractive",
            "-Command",
            script,
        ])
        .stdin(Stdio::null())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped());
    for (key, value) in envs {
        command.env(key, value);
    }
    let output = hide_console_window(&mut command)
        .output()
        .map_err(|e| format!("无法启动 Windows PowerShell 5.1: {e}"))?;
    if !output.status.success() {
        let stderr = String::from_utf8_lossy(&output.stderr).trim().to_owned();
        return Err(if stderr.is_empty() {
            format!("Windows PowerShell 失败(exit={:?})", output.status.code())
        } else {
            format!("Windows PowerShell 失败: {stderr}")
        });
    }
    Ok(String::from_utf8_lossy(&output.stdout).trim().to_owned())
}

#[cfg(target_os = "windows")]
fn resolve_appx_package() -> Result<(String, PathBuf), String> {
    let script = r#"
$ErrorActionPreference = 'Stop'
$pkg = Get-AppxPackage -Name 'OpenAI.Codex' | Sort-Object Version -Descending | Select-Object -First 1
if ($null -eq $pkg) { throw 'OpenAI.Codex AppX package not found' }
[pscustomobject]@{
  version = $pkg.Version.ToString()
  installLocation = $pkg.InstallLocation
} | ConvertTo-Json -Compress
"#;
    let text = run_powershell(script, &[])?;
    let value: Value =
        serde_json::from_str(&text).map_err(|e| format!("无法解析 OpenAI.Codex AppX 信息: {e}"))?;
    let version = value
        .get("version")
        .and_then(Value::as_str)
        .filter(|v| !v.is_empty())
        .ok_or_else(|| "OpenAI.Codex AppX 版本为空".to_owned())?
        .to_owned();
    let install = value
        .get("installLocation")
        .and_then(Value::as_str)
        .filter(|v| !v.is_empty())
        .ok_or_else(|| "OpenAI.Codex AppX InstallLocation 为空".to_owned())?;
    Ok((version, PathBuf::from(install)))
}

#[cfg(target_os = "windows")]
fn resolve_codex_executable(install: &Path) -> Option<PathBuf> {
    ["ChatGPT.exe", "Codex.exe"]
        .into_iter()
        .map(|name| install.join("app").join(name))
        .find(|path| path.is_file())
}

#[cfg(target_os = "windows")]
fn command_version(program: &Path) -> Option<String> {
    let mut command = Command::new(program);
    command
        .arg("--version")
        .stdin(Stdio::null())
        .stdout(Stdio::piped())
        .stderr(Stdio::null());
    let output = hide_console_window(&mut command).output().ok()?;
    if !output.status.success() {
        return None;
    }
    let text = String::from_utf8_lossy(&output.stdout).trim().to_owned();
    (!text.is_empty()).then_some(text)
}

#[cfg(target_os = "windows")]
fn resolve_node() -> Option<(PathBuf, String)> {
    let mut candidates = Vec::<PathBuf>::new();
    if let Some(profile) = std::env::var_os("USERPROFILE") {
        candidates.push(
            PathBuf::from(profile)
                .join(".cache")
                .join("codex-runtimes")
                .join("codex-primary-runtime")
                .join("dependencies")
                .join("node")
                .join("bin")
                .join("node.exe"),
        );
    }
    let mut where_cmd = Command::new("where.exe");
    where_cmd
        .arg("node.exe")
        .stdin(Stdio::null())
        .stdout(Stdio::piped())
        .stderr(Stdio::null());
    if let Ok(output) = hide_console_window(&mut where_cmd).output() {
        if output.status.success() {
            for line in String::from_utf8_lossy(&output.stdout).lines() {
                let path = PathBuf::from(line.trim());
                if !line.trim().is_empty() {
                    candidates.push(path);
                }
            }
        }
    }
    // Keep insertion order: the Codex bundled runtime is deliberately preferred over PATH.
    // Sorting here would often put C:\Program Files\nodejs ahead of C:\Users\...\.cache,
    // defeating the documented bundled-first behavior and potentially selecting an old Node.
    for path in candidates {
        if !path.is_file() {
            continue;
        }
        if let Some(version) = command_version(&path) {
            return Some((path, version));
        }
    }
    None
}

#[cfg(target_os = "windows")]
fn exact_codex_process_state(executable: &Path) -> (String, Vec<u32>, Option<String>) {
    let Some(target) = executable.to_str() else {
        return (
            "unknown".to_owned(),
            Vec::new(),
            Some("Codex executable path is not valid UTF-8".to_owned()),
        );
    };
    let script = r#"
$ErrorActionPreference = 'Stop'
$target = $env:CAS_NO_MICRO_EXE
$candidates = @(Get-CimInstance Win32_Process -Filter "Name='ChatGPT.exe' OR Name='Codex.exe'")
$matched = @($candidates | Where-Object {
  $_.ExecutablePath -and [string]::Equals($_.ExecutablePath, $target, [System.StringComparison]::OrdinalIgnoreCase)
})
$unreadable = @($candidates | Where-Object { -not $_.ExecutablePath })
[pscustomobject]@{
  state = $(if ($matched.Count -gt 0) { 'running' } elseif ($unreadable.Count -gt 0) { 'unknown' } else { 'not-running' })
  pids = @($matched | ForEach-Object { [int64]$_.ProcessId })
  unreadableCount = [int]$unreadable.Count
} | ConvertTo-Json -Compress
"#;
    match run_powershell(script, &[("CAS_NO_MICRO_EXE", target)]) {
        Ok(text) => match serde_json::from_str::<Value>(&text) {
            Ok(value) => {
                let state = value
                    .get("state")
                    .and_then(Value::as_str)
                    .unwrap_or("unknown")
                    .to_owned();
                let pids = value
                    .get("pids")
                    .and_then(Value::as_array)
                    .map(|items| {
                        items
                            .iter()
                            .filter_map(Value::as_u64)
                            .filter_map(|pid| u32::try_from(pid).ok())
                            .collect()
                    })
                    .unwrap_or_default();
                let warning = (state == "unknown").then(|| {
                    let count = value
                        .get("unreadableCount")
                        .and_then(Value::as_u64)
                        .unwrap_or(1);
                    format!(
                        "发现 {count} 个 ChatGPT.exe/Codex.exe 候选进程，但 Windows 未允许读取 ExecutablePath"
                    )
                });
                (state, pids, warning)
            }
            Err(e) => (
                "unknown".to_owned(),
                Vec::new(),
                Some(format!("无法解析 Codex 进程检测结果: {e}")),
            ),
        },
        Err(e) => ("unknown".to_owned(), Vec::new(), Some(e)),
    }
}

#[cfg(target_os = "windows")]
fn doctor_windows() -> NoMicroDoctor {
    let mut report = NoMicroDoctor {
        supported: true,
        platform: "windows".to_owned(),
        package_found: false,
        package_version: None,
        executable_path: None,
        app_asar_path: None,
        node_path: None,
        node_version: None,
        node_compatible: false,
        target_module_count: 0,
        serialport_count: 0,
        feature_gate_count: 0,
        stub_shape_ok: false,
        process_state: "unknown".to_owned(),
        process_pids: Vec::new(),
        compatible: false,
        launch_ready: false,
        last_launch: read_last_launch(),
        warnings: Vec::new(),
    };

    let (package_version, install) = match resolve_appx_package() {
        Ok(v) => v,
        Err(e) => {
            report.warnings.push(e);
            return report;
        }
    };
    report.package_found = true;
    report.package_version = Some(package_version);

    let Some(executable) = resolve_codex_executable(&install) else {
        report.warnings.push(format!(
            "未在 {}\\app 下找到 ChatGPT.exe / Codex.exe",
            install.display()
        ));
        return report;
    };
    report.executable_path = Some(executable.to_string_lossy().into_owned());

    let app_asar = install.join("app").join("resources").join("app.asar");
    report.app_asar_path = Some(app_asar.to_string_lossy().into_owned());
    if let Ok(bytes) = fs::read(&app_asar) {
        report.target_module_count = count_occurrences(&bytes, TARGET_MODULE);
        report.serialport_count = count_occurrences(&bytes, SERIALPORT_MARKER);
        report.feature_gate_count = count_occurrences(&bytes, FEATURE_GATE_MARKER);
        report.stub_shape_ok = STUB_SHAPE_MARKERS
            .iter()
            .all(|marker| count_occurrences(&bytes, marker) > 0);
    } else {
        report
            .warnings
            .push(format!("无法读取 {}", app_asar.display()));
    }

    if let Some((node, version)) = resolve_node() {
        report.node_compatible =
            parse_node_major(&version).is_some_and(|major| major >= MIN_NODE_MAJOR);
        report.node_path = Some(node.to_string_lossy().into_owned());
        report.node_version = Some(version.clone());
        if !report.node_compatible {
            report.warnings.push(format!(
                "Node.js {version} 过旧，No Micro 需要 Node.js {MIN_NODE_MAJOR}+"
            ));
        }
    } else {
        report
            .warnings
            .push("未找到 Codex bundled Node 或 PATH 中的 node.exe".to_owned());
    }

    let (process_state, pids, process_warning) = exact_codex_process_state(&executable);
    report.process_state = process_state;
    report.process_pids = pids;
    if let Some(warning) = process_warning {
        report.warnings.push(format!(
            "无法可靠判断 Codex 是否正在运行；为安全起见禁止 No Micro 启动: {warning}"
        ));
    }

    report.compatible = report.package_found
        && report.executable_path.is_some()
        && app_asar.is_file()
        && report.node_compatible
        && report.target_module_count > 0
        && report.serialport_count > 0
        && report.stub_shape_ok;
    report.launch_ready = report.compatible && report.process_state == "not-running";
    if report.process_state == "running" {
        report
            .warnings
            .push("Codex 正在运行；请完全退出后再使用 No Micro 启动".to_owned());
    }
    if report.target_module_count == 0 {
        report
            .warnings
            .push("当前 app.asar 未检测到 @worklouder/device-kit-oai；不要强行注入".to_owned());
    }
    if !report.stub_shape_ok && report.target_module_count > 0 {
        report
            .warnings
            .push("Codex Micro 导入形状与当前 stub 不匹配；需重新审阅后再启用".to_owned());
    }
    report
}

#[cfg(target_os = "windows")]
fn write_launcher() -> Result<PathBuf, String> {
    let dir = no_micro_dir().ok_or_else(|| "无法解析用户 HOME 目录".to_owned())?;
    fs::create_dir_all(&dir)
        .map_err(|e| format!("无法创建 No Micro 目录 {}: {e}", dir.display()))?;
    let launcher = dir.join("launcher.mjs");
    let unchanged = fs::read_to_string(&launcher)
        .map(|current| current == LAUNCHER_JS)
        .unwrap_or(false);
    if !unchanged {
        fs::write(&launcher, LAUNCHER_JS)
            .map_err(|e| format!("无法写入 No Micro launcher {}: {e}", launcher.display()))?;
    }
    Ok(launcher)
}

#[cfg(target_os = "windows")]
fn launch_windows(extra_args: &[String]) -> Result<Value, String> {
    let report = doctor_windows();
    if !report.compatible {
        return Err(report
            .warnings
            .first()
            .cloned()
            .unwrap_or_else(|| "当前 Codex / Node 环境未通过 No Micro 兼容性检查".to_owned()));
    }
    if report.process_state != "not-running" {
        return Err(if report.process_state == "running" {
            "Codex 仍在运行。请先完全退出 Codex，再点击 No Micro 启动。".to_owned()
        } else {
            "无法可靠确认 Codex 已完全退出；为避免误杀或留下暂停进程，本次 No Micro 启动已取消。"
                .to_owned()
        });
    }

    let executable = PathBuf::from(
        report
            .executable_path
            .as_deref()
            .ok_or_else(|| "No Micro doctor 未返回 Codex executable".to_owned())?,
    );
    let node = PathBuf::from(
        report
            .node_path
            .as_deref()
            .ok_or_else(|| "No Micro doctor 未返回 Node executable".to_owned())?,
    );
    let launcher = write_launcher()?;
    let status_path =
        last_launch_path().ok_or_else(|| "无法解析 No Micro 状态文件路径".to_owned())?;

    let mut command = Command::new(&node);
    command
        .arg(&launcher)
        .arg(&executable)
        .args(extra_args)
        .env("CAS_NO_MICRO_STATUS_PATH", &status_path)
        .env(
            "CAS_NO_MICRO_PACKAGE_VERSION",
            report.package_version.as_deref().unwrap_or("unknown"),
        )
        .stdin(Stdio::null())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped());
    let output = hide_console_window(&mut command)
        .output()
        .map_err(|e| format!("无法启动 No Micro launcher: {e}"))?;

    let stdout = String::from_utf8_lossy(&output.stdout).trim().to_owned();
    let parsed = serde_json::from_str::<Value>(&stdout)
        .ok()
        .or_else(read_last_launch);
    if output.status.success() {
        let value =
            parsed.ok_or_else(|| "No Micro launcher 成功退出但没有可解析状态".to_owned())?;
        if value.pointer("/injection/status").and_then(Value::as_str) == Some("success") {
            return Ok(json!({
                "success": true,
                "doctor": report,
                "launch": value,
            }));
        }
        return Err("No Micro launcher 未确认注入成功".to_owned());
    }

    if let Some(value) = parsed {
        let phase = value
            .pointer("/injection/phase")
            .and_then(Value::as_str)
            .unwrap_or("unknown");
        let error = value
            .pointer("/injection/error")
            .and_then(Value::as_str)
            .unwrap_or("unknown error");
        return Err(format!("No Micro 启动失败({phase}): {error}"));
    }
    let stderr = String::from_utf8_lossy(&output.stderr).trim().to_owned();
    Err(if stderr.is_empty() {
        format!("No Micro launcher 失败(exit={:?})", output.status.code())
    } else {
        format!(
            "No Micro launcher 失败: {}",
            stderr.chars().take(1200).collect::<String>()
        )
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn count_occurrences_handles_overlap_free_markers() {
        assert_eq!(count_occurrences(b"abc--abc--abc", b"abc"), 3);
        assert_eq!(count_occurrences(b"abc", b"abcd"), 0);
    }

    #[test]
    fn node_major_parser_accepts_normal_versions() {
        assert_eq!(parse_node_major("v24.14.0"), Some(24));
        assert_eq!(parse_node_major("22.0.1\n"), Some(22));
        assert_eq!(parse_node_major("not-node"), None);
    }
}
