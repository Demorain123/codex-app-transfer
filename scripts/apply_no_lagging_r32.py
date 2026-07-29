from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def write(rel: str, text: str) -> None:
    path = ROOT / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    print(f"patched {rel}")


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if new in text:
        return text
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"r32 No Lagging {label}: expected one anchor, found {count}")
    return text.replace(old, new, 1)


# ---------------------------------------------------------------------------
# Materialize the privacy-safe MCP/helper exit guard from the overlay source.
# ---------------------------------------------------------------------------
janitor_source = read("scripts/no_lagging_r32_mcp_exit_guard.ps1")
if "CAS-NO-LAGGING-R32-MCP-EXIT-GUARD" not in janitor_source:
    raise SystemExit("r32 janitor source marker missing")
write("src-tauri/resources/codex_no_lagging_janitor.ps1", janitor_source)


# ---------------------------------------------------------------------------
# Backend: keep the proven r23 injector, widen the doctor from old serialport
# evidence to the whole Work Louder accessory path, and start the exit guard.
# ---------------------------------------------------------------------------
rel = "src-tauri/src/admin/services/desktop/no_micro.rs"
text = read(rel)
text = replace_once(
    text,
    'const SERIALPORT_MARKER: &[u8] = b"serialport";\nconst FEATURE_GATE_MARKER: &[u8] = b"3207467860";',
    'const SERIALPORT_MARKER: &[u8] = b"serialport";\nconst HID_MARKERS: &[&[u8]] = &[b"node-hid", b"HID.node", b"hid.dll"];\nconst FEATURE_GATE_MARKER: &[u8] = b"3207467860";',
    "HID/accessory markers",
)
text = replace_once(
    text,
    'const LAUNCHER_JS: &str = include_str!("../../../../resources/codex_no_micro_launcher.mjs");',
    'const LAUNCHER_JS: &str = include_str!("../../../../resources/codex_no_micro_launcher.mjs");\n// CAS-NO-LAGGING-R32-MCP-EXIT-GUARD\nconst MCP_EXIT_GUARD_PS1: &str = include_str!("../../../../resources/codex_no_lagging_janitor.ps1");',
    "embedded exit guard",
)
text = replace_once(
    text,
    '    pub serialport_count: usize,\n    pub feature_gate_count: usize,',
    '    pub serialport_count: usize,\n    pub hid_marker_count: usize,\n    pub feature_gate_count: usize,',
    "doctor HID field",
)
# Two constructors contain this exact block.
old_init = '            serialport_count: 0,\n            feature_gate_count: 0,'
new_init = '            serialport_count: 0,\n            hid_marker_count: 0,\n            feature_gate_count: 0,'
if new_init not in text:
    if text.count(old_init) != 2:
        raise SystemExit(f"r32 No Lagging doctor init: expected two anchors, found {text.count(old_init)}")
    text = text.replace(old_init, new_init)
text = replace_once(
    text,
    '        report.serialport_count = count_occurrences(&bytes, SERIALPORT_MARKER);\n        report.feature_gate_count = count_occurrences(&bytes, FEATURE_GATE_MARKER);',
    '        report.serialport_count = count_occurrences(&bytes, SERIALPORT_MARKER);\n        report.hid_marker_count = HID_MARKERS\n            .iter()\n            .map(|marker| count_occurrences(&bytes, marker))\n            .sum();\n        report.feature_gate_count = count_occurrences(&bytes, FEATURE_GATE_MARKER);',
    "doctor HID scan",
)
text = replace_once(
    text,
    '        && report.target_module_count > 0\n        && report.serialport_count > 0\n        && report.stub_shape_ok;',
    '        && report.target_module_count > 0\n        && report.stub_shape_ok; // CAS-NO-LAGGING-R32-ACCESSORY-GUARD',
    "accessory-level compatibility",
)
text = replace_once(
    text,
    '''    if report.target_module_count == 0 {
        report
            .warnings
            .push("当前 app.asar 未检测到 @worklouder/device-kit-oai；不要强行注入".to_owned());
    }
''',
    '''    if report.target_module_count == 0 {
        report
            .warnings
            .push("当前 app.asar 未检测到 @worklouder/device-kit-oai；No Lagging 不会强行注入".to_owned());
    }
    if report.target_module_count > 0 && report.serialport_count == 0 && report.hid_marker_count > 0 {
        report.warnings.push(
            "当前 build 未发现旧 serialport 标记，但仍检测到 HID/accessory 路径；r32 会继续在顶层 @worklouder/device-kit-oai 处阻断，避免进入 HID/native 枚举路径".to_owned(),
        );
    }
''',
    "accessory doctor warning",
)
text = replace_once(
    text,
    '''#[cfg(target_os = "windows")]
fn launch_windows(extra_args: &[String]) -> Result<Value, String> {
''',
    '''#[cfg(target_os = "windows")]
fn write_mcp_exit_guard() -> Result<PathBuf, String> {
    let dir = no_micro_dir().ok_or_else(|| "无法解析用户 HOME 目录".to_owned())?;
    fs::create_dir_all(&dir)
        .map_err(|e| format!("无法创建 No Lagging 目录 {}: {e}", dir.display()))?;
    let script = dir.join("mcp-exit-guard-r32.ps1");
    let unchanged = fs::read_to_string(&script)
        .map(|current| current == MCP_EXIT_GUARD_PS1)
        .unwrap_or(false);
    if !unchanged {
        fs::write(&script, MCP_EXIT_GUARD_PS1)
            .map_err(|e| format!("无法写入 MCP Exit Guard {}: {e}", script.display()))?;
    }
    Ok(script)
}

#[cfg(target_os = "windows")]
fn resolve_janitor_shell() -> PathBuf {
    let mut where_cmd = Command::new("where.exe");
    where_cmd
        .arg("pwsh.exe")
        .stdin(Stdio::null())
        .stdout(Stdio::piped())
        .stderr(Stdio::null());
    if let Ok(output) = hide_console_window(&mut where_cmd).output() {
        if output.status.success() {
            if let Some(line) = String::from_utf8_lossy(&output.stdout)
                .lines()
                .map(str::trim)
                .find(|line| !line.is_empty())
            {
                return PathBuf::from(line);
            }
        }
    }
    PathBuf::from("powershell.exe")
}

#[cfg(target_os = "windows")]
fn start_mcp_exit_guard(executable: &Path) -> Value {
    let script = match write_mcp_exit_guard() {
        Ok(path) => path,
        Err(error) => return json!({ "status": "script-write-failed", "error": error }),
    };
    let shell = resolve_janitor_shell();
    let mut command = Command::new(&shell);
    command
        .args([
            "-NoLogo",
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "Bypass",
            "-WindowStyle",
            "Hidden",
            "-File",
        ])
        .arg(&script)
        .env("CAS_NO_LAGGING_EXE", executable)
        .stdin(Stdio::null())
        .stdout(Stdio::null())
        .stderr(Stdio::null());

    match hide_console_window(&mut command).spawn() {
        Ok(mut child) => {
            let pid = child.id();
            std::thread::sleep(std::time::Duration::from_millis(250));
            match child.try_wait() {
                Ok(None) => json!({
                    "status": "watching",
                    "pid": pid,
                    "scope": "exact-codex-desktop-generation",
                }),
                Ok(Some(status)) if status.success() => json!({
                    "status": "already-active-or-clean-exit",
                    "pid": pid,
                }),
                Ok(Some(status)) => json!({
                    "status": "start-failed",
                    "pid": pid,
                    "exitCode": status.code(),
                }),
                Err(error) => json!({
                    "status": "unknown",
                    "pid": pid,
                    "error": error.to_string(),
                }),
            }
        }
        Err(error) => json!({
            "status": "spawn-failed",
            "error": error.to_string(),
            "shell": shell.to_string_lossy(),
        }),
    }
}

#[cfg(target_os = "windows")]
fn launch_windows(extra_args: &[String]) -> Result<Value, String> {
''',
    "MCP exit guard service",
)
text = replace_once(
    text,
    '''    let launcher = write_launcher()?;
    let status_path =
        last_launch_path().ok_or_else(|| "无法解析 No Micro 状态文件路径".to_owned())?;

    let mut command = Command::new(&node);
''',
    '''    let launcher = write_launcher()?;
    let status_path =
        last_launch_path().ok_or_else(|| "无法解析 No Lagging 状态文件路径".to_owned())?;
    // Start before Codex so the watcher can observe the generation from its first helper stack.
    // Failure is reported but does not block the already-proven Micro/Accessory guard.
    let mcp_exit_guard = start_mcp_exit_guard(&executable);

    let mut command = Command::new(&node);
''',
    "start guard before launch",
)
text = replace_once(
    text,
    '''            return Ok(json!({
                "success": true,
                "doctor": report,
                "launch": value,
            }));
''',
    '''            return Ok(json!({
                "success": true,
                "doctor": report,
                "launch": value,
                "noLagging": {
                    "microAccessoryGuard": "success",
                    "mcpExitGuard": mcp_exit_guard,
                },
            }));
''',
    "No Lagging launch result",
)
write(rel, text)


# Keep the proven worker-safe injector and add a new semantic marker without removing
# any r23 compatibility markers/tests.
rel = "src-tauri/resources/codex_no_micro_launcher.mjs"
text = read(rel)
text = replace_once(
    text,
    'const MODE = "micro-disabled-worker-safe";',
    'const MODE = "micro-disabled-worker-safe"; // CAS-NO-LAGGING-R32-MICRO-ACCESSORY-GUARD',
    "launcher semantic marker",
)
text = replace_once(
    text,
    '  globalThis.__CODEX_MICRO_DISABLED_LOCAL__ = true;\n',
    '  globalThis.__CODEX_MICRO_DISABLED_LOCAL__ = true;\n  globalThis.__CODEX_NO_LAGGING_MICRO_ACCESSORY_GUARD__ = true;\n',
    "launcher No Lagging global marker",
)
write(rel, text)


# ---------------------------------------------------------------------------
# Handler: preserve the old endpoint for compatibility, add canonical no-lagging
# mode, and keep normal A as a true control path.
# ---------------------------------------------------------------------------
rel = "src-tauri/src/admin/handlers/no_micro.rs"
text = read(rel)
text = replace_once(
    text,
    '''    let mode = match query.mode.as_deref() {
        Some("normal") => "normal",
        None | Some("no-micro") => "no-micro",
''',
    '''    let mode = match query.mode.as_deref() {
        Some("normal") => "normal",
        None | Some("no-micro") | Some("no-lagging") => "no-lagging",
''',
    "mode alias",
)
for old, new, label in [
    ('prepare_ab_environment(&state, &run_id, "no-micro")', 'prepare_ab_environment(&state, &run_id, "no-lagging")', 'prepare mode'),
    ('        "no-micro",\n        "launch_requested",', '        "no-lagging",\n        "launch_requested",', 'launch log mode'),
    ('pipeline=legacy-restart-shared final_launcher=no-micro', 'pipeline=legacy-restart-shared final_launcher=no-lagging', 'launcher label'),
    ('                "no-micro",\n                "injection_success",', '                "no-lagging",\n                "injection_success",', 'success log mode'),
    ('obj.insert("mode".to_owned(), Value::String("no-micro".to_owned()));', 'obj.insert("mode".to_owned(), Value::String("no-lagging".to_owned()));', 'response mode'),
    ('                "no-micro",\n                "launch_failed",', '                "no-lagging",\n                "launch_failed",', 'failure log mode'),
    ('"No Micro doctor task failed: {e}"', '"No Lagging doctor task failed: {e}"', 'doctor error'),
    ('"No Micro B 当前未通过兼容性检查"', '"No Lagging B 当前未通过兼容性检查"', 'compat error'),
]:
    text = replace_once(text, old, new, label)
# Stable marker for r32 review.
if "CAS-NO-LAGGING-R32-AB-MODE" not in text:
    text = text.replace("// CAS-NO-MICRO-R23-AB-SHARED-PIPELINE\n", "// CAS-NO-MICRO-R23-AB-SHARED-PIPELINE\n// CAS-NO-LAGGING-R32-AB-MODE\n", 1)
write(rel, text)


# ---------------------------------------------------------------------------
# Frontend API: keep old API path/function compatibility but expose r32 fields.
# ---------------------------------------------------------------------------
rel = "frontend/src/api/noMicro.ts"
text = read(rel)
text = replace_once(
    text,
    '  serialportCount: number\n  featureGateCount: number',
    '  serialportCount: number\n  hidMarkerCount: number\n  featureGateCount: number',
    "frontend HID field",
)
text = replace_once(
    text,
    "  mode?: 'no-micro'\n}",
    "  mode?: 'no-lagging' | 'no-micro'\n  noLagging?: {\n    microAccessoryGuard?: string\n    mcpExitGuard?: { status?: string; pid?: number; scope?: string; error?: string }\n  }\n}",
    "frontend No Lagging result",
)
if "launchCodexNoLagging" not in text:
    text += "\n// CAS-NO-LAGGING-R32-API-ALIAS\nexport function launchCodexNoLagging() {\n  return api<NoMicroLaunchResult>('POST', '/api/desktop/no-micro/launch?mode=no-lagging')\n}\n"
write(rel, text)


# ---------------------------------------------------------------------------
# UI: rename the user-facing experiment and explain that it is additive: it
# neither disables MCPs nor limits subagents, and exit cleanup runs only after
# Desktop is gone.
# ---------------------------------------------------------------------------
rel = "frontend/src/components/codex/NoMicroPanel.vue"
text = read(rel)
replacements = [
    ("title: 'Codex No Micro A/B（实验性）'", "title: 'Codex No Lagging A/B（实验性）'", "zh title"),
    ("desc: 'r23 的 A/B 直接复用已验证正常的“重启 Codex App”流程：A 使用相同配置/代理/启动路径并正常加载 Micro；B 使用相同准备与关闭/清理流程，只在最后一步改为 No Micro 注入。两边都会把 [codex-ab]、run_id、mode 和阶段写入同一份 proxy 日志。'", "desc: 'r32 在原 r23 No Micro A/B 上扩展为 No Lagging：B 仍只在顶层拦截 @worklouder/device-kit-oai，从而同时避开旧 serialport 与新 HID/accessory native 路径；并启动 MCP Exit Guard，仅在 Codex Desktop 真正退出后回收本 generation 已跟踪的残留 helper。不会减少 MCP、不会限制 subagent，也不会处理 429/503/agent-loop 类网络或会话故障。'", "zh desc"),
    ("noMicroLaunch: 'No Micro 启动（B）'", "noMicroLaunch: 'No Lagging 启动（B）'", "zh launch label"),
    ("incompatible: 'No Micro 注入兼容性未通过；A 仍可用于验证原“重启 Codex App”对照路径。'", "incompatible: 'No Lagging 的 Micro/Accessory Guard 兼容性未通过；A 仍可用于对照。'", "zh incompatible"),
    ("noMicroConfirmTitle: '以 No Micro 模式启动 Codex（B）？'", "noMicroConfirmTitle: '以 No Lagging 模式启动 Codex（B）？'", "zh confirm title"),
    ("'B 会复用与 A 相同的配置同步和关闭/清理流程，只把最终启动替换为 No Micro 注入（拦截 @worklouder/device-kit-oai）；并写入 mode=no-micro 标识。'", "'B 会复用与 A 相同的配置同步和关闭/清理流程；最终启动使用 Micro/Accessory Guard，并在后台启动 MCP Exit Guard。Exit Guard 只在 Codex Desktop 已退出时处理本 generation 的残留，不会动正在工作的 MCP/subagent。'", "zh confirm"),
    ("noMicroLaunchOk: 'No Micro B 注入已验证并写入日志标识'", "noMicroLaunchOk: 'No Lagging B：Micro/Accessory Guard 已验证，MCP Exit Guard 已请求后台监控'", "zh launch ok"),
    ("lastSuccess: '最近一次 B：注入成功'", "lastSuccess: '最近一次 B：Micro/Accessory Guard 注入成功'", "zh last success"),
    ("lastFailed: '最近一次 B：注入失败'", "lastFailed: '最近一次 B：Micro/Accessory Guard 注入失败'", "zh last fail"),
    ("never: '尚无 No Micro B 启动记录'", "never: '尚无 No Lagging B 启动记录'", "zh never"),
    ("logHint: '日志关键字：[codex-ab]。A：mode=normal + environment_ready + launch_success；B：mode=no-micro + environment_ready + injection_success。每轮 run_id 独立。'", "logHint: '日志关键字：[codex-ab]。A：mode=normal；B：mode=no-lagging + injection_success。MCP Exit Guard 另写 %LOCALAPPDATA%\\\\CodexMcpJanitorR32\\\\events.jsonl。'", "zh log hint"),
    ("title: 'Codex No Micro A/B (experimental)'", "title: 'Codex No Lagging A/B (experimental)'", "en title"),
    ("desc: 'r23 reuses the proven Restart Codex App pipeline for both sides. A keeps the same config/proxy/restart path with Micro enabled; B uses the same preparation and quit/reap path and changes only the final launcher to No Micro. Both write [codex-ab] run_id/mode/phase markers to the same proxy log.'", "desc: 'r32 extends the proven r23 No Micro A/B into No Lagging. B still intercepts only @worklouder/device-kit-oai, covering both the old serialport path and newer HID/accessory native path, and starts an MCP Exit Guard that cleans only tracked helpers after Codex Desktop has exited. It does not reduce MCPs, limit subagents, or claim to fix 429/503/agent-loop failures.'", "en desc"),
    ("noMicroLaunch: 'No Micro launch (B)'", "noMicroLaunch: 'No Lagging launch (B)'", "en launch label"),
    ("incompatible: 'No Micro compatibility did not pass; A can still validate the legacy Restart Codex App control path.'", "incompatible: 'No Lagging Micro/Accessory Guard compatibility did not pass; A remains available as the control path.'", "en incompatible"),
    ("noMicroConfirmTitle: 'Launch Codex with No Micro (B)?'", "noMicroConfirmTitle: 'Launch Codex with No Lagging (B)?'", "en confirm title"),
    ("'B reuses the same config sync and safe quit/reap path as A, but replaces only the final launcher with the No Micro interception for @worklouder/device-kit-oai. It writes a mode=no-micro marker.'", "'B reuses the same config sync and safe quit/reap path as A, adds the Micro/Accessory Guard, and starts the background MCP Exit Guard. The exit guard never kills MCP/subagent helpers while Codex Desktop is still running.'", "en confirm"),
    ("noMicroLaunchOk: 'No Micro B injection verified and its marker was written'", "noMicroLaunchOk: 'No Lagging B Micro/Accessory Guard verified; MCP Exit Guard start requested'", "en launch ok"),
    ("lastSuccess: 'Last B: injection succeeded'", "lastSuccess: 'Last B: Micro/Accessory Guard injection succeeded'", "en last success"),
    ("lastFailed: 'Last B: injection failed'", "lastFailed: 'Last B: Micro/Accessory Guard injection failed'", "en last fail"),
    ("never: 'No No Micro B launch has been recorded yet'", "never: 'No No Lagging B launch has been recorded yet'", "en never"),
    ("logHint: 'Log key: [codex-ab]. A: mode=normal + environment_ready + launch_success. B: mode=no-micro + environment_ready + injection_success. Every run has a unique run_id.'", "logHint: 'Log key: [codex-ab]. A: mode=normal. B: mode=no-lagging + injection_success. MCP Exit Guard writes %LOCALAPPDATA%\\\\CodexMcpJanitorR32\\\\events.jsonl.'", "en log hint"),
]
for old, new, label in replacements:
    text = replace_once(text, old, new, label)
text = replace_once(
    text,
    '    `serialport ×${d.serialportCount}`,\n    `gate ×${d.featureGateCount}`,',
    '    `serialport ×${d.serialportCount}`,\n    `HID/accessory ×${d.hidMarkerCount}`,\n    `gate ×${d.featureGateCount}`,',
    "UI HID metadata",
)
if "CAS-NO-LAGGING-R32-UI" not in text:
    text = text.replace('<section class="no-micro-panel">', '<section class="no-micro-panel" data-compat="CAS-NO-LAGGING-R32-UI">', 1)
write(rel, text)


# Assertions: keep the patch narrow and preserve the existing r23 worker-safe guard.
checks = {
    "src-tauri/src/admin/services/desktop/no_micro.rs": [
        "CAS-NO-LAGGING-R32-MCP-EXIT-GUARD",
        "CAS-NO-LAGGING-R32-ACCESSORY-GUARD",
        "hid_marker_count",
        "start_mcp_exit_guard",
        '"microAccessoryGuard": "success"',
    ],
    "src-tauri/resources/codex_no_micro_launcher.mjs": [
        "CAS-NO-LAGGING-R32-MICRO-ACCESSORY-GUARD",
        '@worklouder/device-kit-oai',
        "__CODEX_MICRO_DISABLED_LOCAL__",
        "__CODEX_NO_LAGGING_MICRO_ACCESSORY_GUARD__",
    ],
    "src-tauri/resources/codex_no_lagging_janitor.ps1": [
        "CAS-NO-LAGGING-R32-MCP-EXIT-GUARD",
        "Same-Identity",
        "cleanup_cancelled_desktop_reappeared",
    ],
    "src-tauri/src/admin/handlers/no_micro.rs": ["CAS-NO-LAGGING-R32-AB-MODE", '"no-lagging"'],
    "frontend/src/components/codex/NoMicroPanel.vue": ["CAS-NO-LAGGING-R32-UI", "Codex No Lagging"],
}
for rel, markers in checks.items():
    body = read(rel)
    for marker in markers:
        if marker not in body:
            raise SystemExit(f"r32 No Lagging missing marker in {rel}: {marker}")

print("r32 No Lagging overlay: PASS")
