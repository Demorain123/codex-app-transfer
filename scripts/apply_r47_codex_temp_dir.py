from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROCESS = ROOT / "src-tauri/src/admin/services/desktop/process.rs"
MSIX = ROOT / "src-tauri/src/windows_msix.rs"
SETTINGS_RS = ROOT / "src-tauri/src/admin/handlers/settings.rs"
PAGE = ROOT / "frontend/src/pages/SettingsPage.vue"
ZH = ROOT / "frontend/src/i18n/zh.ts"
EN = ROOT / "frontend/src/i18n/en.ts"
MARKER = "CAS-R47-CODEX-CUSTOM-TEMP"

# -----------------------------------------------------------------------------
# Backend: read/validate Transfer-only temp setting and inject it only into the
# Codex process tree launched by Transfer. Never mutates user/system env.
# -----------------------------------------------------------------------------
text = PROCESS.read_text(encoding="utf-8")
if MARKER not in text:
    helper_anchor = "fn open_command(\n"
    if helper_anchor not in text:
        raise SystemExit("r47 custom temp: process open_command anchor missing")
    helper = r'''// CAS-R47-CODEX-CUSTOM-TEMP
// A per-launch environment override for Codex Desktop only. This deliberately does
// NOT call setx, SetEnvironmentVariable for the user/machine, edit config.toml, move
// CODEX_HOME, or touch existing temp contents. Children of the launched Codex process
// inherit TEMP/TMP/TMPDIR naturally.
fn codex_custom_temp_launch_env(platform: &str) -> Result<Vec<(String, String)>, String> {
    if platform != "windows" {
        return Ok(Vec::new());
    }
    let cfg = crate::admin::registry_io::load()
        .map_err(|e| format!("读取 Transfer 设置失败，无法确定 Codex 临时目录: {e}"))?;
    let settings = cfg.get("settings");
    let enabled = settings
        .and_then(|s| s.get("codexCustomTempEnabled"))
        .and_then(Value::as_bool)
        .unwrap_or(false);
    if !enabled {
        return Ok(Vec::new());
    }
    let raw = settings
        .and_then(|s| s.get("codexCustomTempDir"))
        .and_then(Value::as_str)
        .unwrap_or("")
        .trim();
    if raw.is_empty() {
        return Err("已启用 Codex 自定义临时目录，但路径为空；请在 Transfer 设置中填写绝对路径".into());
    }
    let dir = PathBuf::from(raw);
    if !dir.is_absolute() {
        return Err(format!("Codex 自定义临时目录必须是绝对路径: {}", dir.display()));
    }
    fs::create_dir_all(&dir)
        .map_err(|e| format!("无法创建 Codex 自定义临时目录 {}: {e}", dir.display()))?;
    let meta = fs::metadata(&dir)
        .map_err(|e| format!("无法读取 Codex 自定义临时目录 {}: {e}", dir.display()))?;
    if !meta.is_dir() {
        return Err(format!("Codex 自定义临时目录不是文件夹: {}", dir.display()));
    }

    // Bounded write probe before Codex is launched: fail closed instead of silently
    // falling back to C:\Users\...\Temp after the user explicitly enabled this mode.
    let nonce = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .unwrap_or_default()
        .as_nanos();
    let probe = dir.join(format!(".codex-app-transfer-temp-probe-{}-{nonce}.tmp", std::process::id()));
    let mut options = fs::OpenOptions::new();
    options.write(true).create_new(true);
    let mut file = options
        .open(&probe)
        .map_err(|e| format!("Codex 自定义临时目录不可写 {}: {e}", dir.display()))?;
    use std::io::Write as _;
    file.write_all(b"codex-app-transfer-r47")
        .map_err(|e| format!("Codex 自定义临时目录写入测试失败 {}: {e}", dir.display()))?;
    drop(file);
    let _ = fs::remove_file(&probe);

    let value = dir.to_string_lossy().into_owned();
    tracing::info!(
        custom_temp = true,
        temp_dir = %value,
        "[r47] Codex launch will use Transfer-scoped TEMP/TMP/TMPDIR"
    );
    Ok(vec![
        ("TEMP".into(), value.clone()),
        ("TMP".into(), value.clone()),
        ("TMPDIR".into(), value),
    ])
}

'''
    text = text.replace(helper_anchor, helper + helper_anchor, 1)

    old_windows = '''    #[cfg(target_os = "windows")]
    if crate::windows_msix::try_launch_codex(&should_attach_debug_port()) {
        return Ok(());
    }
'''
    new_windows = '''    #[cfg(target_os = "windows")]
    {
        let extra_args = should_attach_debug_port();
        let custom_temp_env = codex_custom_temp_launch_env(platform)?;
        if !custom_temp_env.is_empty() {
            // COM/MSIX activation is brokered and cannot promise inheritance of this
            // process-local environment. When the user explicitly enables custom temp,
            // launch the current package's GUI executable directly and inject env on
            // that exact process tree. Fail closed if direct launch is unavailable.
            let pid = crate::windows_msix::launch_codex_direct_with_env(
                &extra_args,
                &custom_temp_env,
            )?;
            tracing::info!(pid, custom_temp = true, "[r47] Codex Desktop direct-launched with custom temp");
            return Ok(());
        }
        if crate::windows_msix::try_launch_codex(&extra_args) {
            return Ok(());
        }
    }
'''
    if old_windows not in text:
        raise SystemExit("r47 custom temp: Windows launch anchor missing")
    text = text.replace(old_windows, new_windows, 1)
    PROCESS.write_text(text, encoding="utf-8")
    print("R47 CODEX CUSTOM TEMP PROCESS PASS")
else:
    print("r47 Codex custom temp process already applied")

# -----------------------------------------------------------------------------
# Windows packaged app direct launch with an explicit per-process env block.
# -----------------------------------------------------------------------------
text = MSIX.read_text(encoding="utf-8")
if MARKER not in text:
    import_anchor = "use std::os::windows::process::CommandExt;\n"
    if import_anchor not in text:
        raise SystemExit("r47 custom temp: windows_msix import anchor missing")
    text = text.replace(import_anchor, import_anchor + "use std::path::PathBuf;\n", 1)

    insert_anchor = "/// 完整的 \"尝试用 ActivateApplication 启动 Codex MSIX\" 流程封装。\n"
    if insert_anchor not in text:
        raise SystemExit("r47 custom temp: windows_msix launch insertion anchor missing")
    direct = r'''// CAS-R47-CODEX-CUSTOM-TEMP
/// Resolve the executable of the currently installed OpenAI.Codex package and
/// launch it directly with a process-local environment. Used only when the user
/// explicitly enables the Transfer-scoped Codex temp override.
fn resolve_codex_gui_executable() -> Result<PathBuf, String> {
    const CREATE_NO_WINDOW: u32 = 0x0800_0000;
    let output = Command::new("powershell")
        .args([
            "-NoProfile",
            "-Command",
            "Get-AppxPackage -Name 'OpenAI.Codex' | Select-Object -First 1 -ExpandProperty InstallLocation",
        ])
        .creation_flags(CREATE_NO_WINDOW)
        .stdout(Stdio::piped())
        .stderr(Stdio::null())
        .stdin(Stdio::null())
        .output()
        .map_err(|e| format!("Get-AppxPackage 启动失败: {e}"))?;
    if !output.status.success() {
        return Err("无法查询 OpenAI.Codex MSIX 安装目录".into());
    }
    let root = String::from_utf8(output.stdout)
        .map_err(|e| format!("Codex 安装目录不是有效 UTF-8: {e}"))?;
    let root = root.trim();
    if root.is_empty() {
        return Err("未找到 OpenAI.Codex MSIX 安装目录".into());
    }
    let exe = PathBuf::from(root).join("app").join("ChatGPT.exe");
    if !exe.is_file() {
        return Err(format!("当前 Codex 包内未找到 app\\ChatGPT.exe: {}", exe.display()));
    }
    Ok(exe)
}

pub fn launch_codex_direct_with_env(
    extra_args: &[String],
    extra_env: &[(String, String)],
) -> Result<u32, String> {
    const CREATE_NO_WINDOW: u32 = 0x0800_0000;
    let exe = resolve_codex_gui_executable()?;
    let mut command = Command::new(&exe);
    command
        .args(extra_args)
        .envs(extra_env.iter().map(|(k, v)| (k, v)))
        .stdin(Stdio::null())
        .stdout(Stdio::null())
        .stderr(Stdio::null())
        .creation_flags(CREATE_NO_WINDOW);
    let child = command.spawn().map_err(|e| {
        format!(
            "无法以自定义 TEMP 启动 Codex Desktop {}: {e}。未回退到普通 MSIX 启动，以免自定义临时目录设置被静默忽略",
            exe.display()
        )
    })?;
    Ok(child.id())
}

'''
    text = text.replace(insert_anchor, direct + insert_anchor, 1)
    MSIX.write_text(text, encoding="utf-8")
    print("R47 CODEX CUSTOM TEMP MSIX PASS")
else:
    print("r47 Codex custom temp MSIX already applied")

# -----------------------------------------------------------------------------
# Seed sane defaults while retaining free-form settings compatibility.
# -----------------------------------------------------------------------------
text = SETTINGS_RS.read_text(encoding="utf-8")
if MARKER not in text:
    anchor = '            "autoWakeCodexPet": true,\n'
    if anchor not in text:
        raise SystemExit("r47 custom temp: default settings anchor missing")
    replacement = anchor + '''            // CAS-R47-CODEX-CUSTOM-TEMP\n            "codexCustomTempEnabled": false,\n            "codexCustomTempDir": "",\n'''
    text = text.replace(anchor, replacement, 1)
    SETTINGS_RS.write_text(text, encoding="utf-8")
    print("R47 CODEX CUSTOM TEMP DEFAULTS PASS")
else:
    print("r47 Codex custom temp defaults already applied")

# -----------------------------------------------------------------------------
# Settings UI. Windows-only because the evidence/launcher implementation is Win.
# -----------------------------------------------------------------------------
text = PAGE.read_text(encoding="utf-8")
if MARKER not in text:
    import_anchor = "  getPluginUnlockStatus,\n"
    if import_anchor not in text:
        raise SystemExit("r47 custom temp: desktop api import anchor missing")
    text = text.replace(import_anchor, "  restartCodexApp,\n" + import_anchor, 1)

    toggle_anchor = "const autoWakeCodexPet = toggle('autoWakeCodexPet', true)\n"
    if toggle_anchor not in text:
        raise SystemExit("r47 custom temp: settings toggle anchor missing")
    logic = r'''// CAS-R47-CODEX-CUSTOM-TEMP
const codexCustomTempEnabled = toggle('codexCustomTempEnabled', false)
const codexCustomTempDir = ref(store.str('codexCustomTempDir', ''))
const codexTempRestarting = ref(false)
watch(
  () => store.str('codexCustomTempDir', ''),
  (v) => {
    if (v !== codexCustomTempDir.value) codexCustomTempDir.value = v
  },
)
async function onCodexCustomTempDirChange() {
  const value = codexCustomTempDir.value.trim()
  codexCustomTempDir.value = value
  await persist({ codexCustomTempDir: value })
}
async function onApplyCodexCustomTemp() {
  const value = codexCustomTempDir.value.trim()
  if (codexCustomTempEnabled.value && !value) {
    toast(t('settings.codexCustomTempPathRequired'), 'error')
    return
  }
  codexTempRestarting.value = true
  try {
    await persist({ codexCustomTempDir: value })
    await restartCodexApp()
    toast(t('settings.codexCustomTempRestarted'))
  } catch (e) {
    toast((e as Error).message || t('settings.codexCustomTempRestartFailed'), 'error')
  } finally {
    codexTempRestarting.value = false
  }
}
'''
    text = text.replace(toggle_anchor, toggle_anchor + logic, 1)

    mac_anchor = "const isMac = typeof navigator !== 'undefined' && /Mac/i.test(navigator.userAgent)\n"
    if mac_anchor not in text:
        raise SystemExit("r47 custom temp: platform anchor missing")
    text = text.replace(
        mac_anchor,
        mac_anchor + "const isWindows = typeof navigator !== 'undefined' && /Windows/i.test(navigator.userAgent)\n",
        1,
    )

    row_anchor = '''      <SettingsRow :title="t('settings.autoWakeCodexPet')" :description="t('settings.autoWakeCodexPetHint')">
        <AppSwitch v-model="autoWakeCodexPet" />
      </SettingsRow>
'''
    if row_anchor not in text:
        raise SystemExit("r47 custom temp: startup row anchor missing")
    rows = row_anchor + '''      <!-- CAS-R47-CODEX-CUSTOM-TEMP -->
      <SettingsRow
        v-if="isWindows"
        :title="t('settings.codexCustomTemp')"
        :description="t('settings.codexCustomTempHint')"
      >
        <AppSwitch v-model="codexCustomTempEnabled" />
      </SettingsRow>
      <SettingsRow
        v-if="isWindows && codexCustomTempEnabled"
        :title="t('settings.codexCustomTempPath')"
        :description="t('settings.codexCustomTempPathHint')"
      >
        <input
          v-model="codexCustomTempDir"
          type="text"
          class="settings-input settings-input--wide"
          :placeholder="t('settings.codexCustomTempPlaceholder')"
          @change="onCodexCustomTempDirChange"
        />
        <AppButton
          size="sm"
          variant="primary"
          :label="t('settings.codexCustomTempApplyRestart')"
          :disabled="codexTempRestarting"
          @click="onApplyCodexCustomTemp"
        />
      </SettingsRow>
'''
    text = text.replace(row_anchor, rows, 1)

    style_anchor = ".settings-input {\n  width: 240px;\n  max-width: 100%;\n}\n"
    if style_anchor in text:
        text = text.replace(
            style_anchor,
            style_anchor + ".settings-input--wide {\n  width: 360px;\n}\n",
            1,
        )
    PAGE.write_text(text, encoding="utf-8")
    print("R47 CODEX CUSTOM TEMP UI PASS")
else:
    print("r47 Codex custom temp UI already applied")

# -----------------------------------------------------------------------------
# i18n. Insert near the top so later overlay text drift cannot break the patch.
# -----------------------------------------------------------------------------
translations = {
    ZH: '''  // CAS-R47-CODEX-CUSTOM-TEMP\n  "settings.codexCustomTemp": "Codex 专用临时目录",\n  "settings.codexCustomTempHint": "仅影响由 Transfer 启动的 Codex 进程树；不会修改 Windows 用户/系统 TEMP/TMP，也不会移动或删除现有缓存。开启后需要通过下方按钮重启 Codex 才生效。",\n  "settings.codexCustomTempPath": "Codex 临时目录路径",\n  "settings.codexCustomTempPathHint": "填写可写的 Windows 绝对目录，例如 V:\\\\CodexTemp。Codex Review/Changes 的 codex-review-objects-*、codex-index-* 等会继承该 TEMP。",\n  "settings.codexCustomTempPlaceholder": "例如 V:\\\\CodexTemp",\n  "settings.codexCustomTempApplyRestart": "应用并重启 Codex",\n  "settings.codexCustomTempPathRequired": "已启用 Codex 专用临时目录，请先填写路径",\n  "settings.codexCustomTempRestarted": "已按当前临时目录设置重启 Codex",\n  "settings.codexCustomTempRestartFailed": "Codex 临时目录设置应用失败",\n''',
    EN: '''  // CAS-R47-CODEX-CUSTOM-TEMP\n  "settings.codexCustomTemp": "Codex-only temporary directory",\n  "settings.codexCustomTempHint": "Affects only the Codex process tree launched by Transfer. It does not change Windows user/system TEMP/TMP and never moves or deletes existing caches. Restart Codex with the button below to apply it.",\n  "settings.codexCustomTempPath": "Codex temporary directory path",\n  "settings.codexCustomTempPathHint": "Use a writable absolute Windows path such as V:\\\\CodexTemp. Codex Review/Changes temp stores such as codex-review-objects-* and codex-index-* inherit this TEMP.",\n  "settings.codexCustomTempPlaceholder": "e.g. V:\\\\CodexTemp",\n  "settings.codexCustomTempApplyRestart": "Apply and restart Codex",\n  "settings.codexCustomTempPathRequired": "Custom Codex temp is enabled; enter a path first",\n  "settings.codexCustomTempRestarted": "Codex restarted with the current temp setting",\n  "settings.codexCustomTempRestartFailed": "Failed to apply the Codex temp setting",\n''',
}
for path, block in translations.items():
    source = path.read_text(encoding="utf-8")
    if MARKER in source:
        print(f"r47 Codex custom temp i18n already applied: {path.name}")
        continue
    anchor = "export default {\n"
    if anchor not in source:
        raise SystemExit(f"r47 custom temp: i18n anchor missing: {path.name}")
    source = source.replace(anchor, anchor + block, 1)
    path.write_text(source, encoding="utf-8")
    print(f"R47 CODEX CUSTOM TEMP I18N PASS: {path.name}")

# Structural invariants only; real behavior is verified with a Windows real-use launch.
checks = {
    PROCESS: (MARKER, "codexCustomTempEnabled", "codexCustomTempDir", "launch_codex_direct_with_env", '"TEMP"', '"TMP"', '"TMPDIR"'),
    MSIX: (MARKER, "resolve_codex_gui_executable", "ChatGPT.exe", "launch_codex_direct_with_env", ".envs("),
    PAGE: (MARKER, "codexCustomTempEnabled", "codexCustomTempDir", "应用并重启" if False else "settings.codexCustomTempApplyRestart"),
    SETTINGS_RS: (MARKER, "codexCustomTempEnabled", "codexCustomTempDir"),
}
for path, markers in checks.items():
    source = path.read_text(encoding="utf-8")
    for marker in markers:
        if marker not in source:
            raise SystemExit(f"r47 custom temp invariant missing in {path}: {marker}")

print("R47 CODEX CUSTOM TEMP OVERLAY PASS")
print("- Transfer-only process environment; no user/system TEMP mutation")
print("- Windows custom-temp mode direct-launches current package app\\ChatGPT.exe")
print("- invalid/unwritable paths fail closed instead of silently falling back to C: temp")
print("- existing temp caches are never moved or deleted")
