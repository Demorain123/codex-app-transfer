from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROCESS = ROOT / "src-tauri/src/admin/services/desktop/process.rs"
NO_MICRO = ROOT / "src-tauri/src/admin/services/desktop/no_micro.rs"
PROVIDERS = ROOT / "frontend/src/pages/ProvidersPage.vue"
NO_MICRO_PANEL = ROOT / "frontend/src/components/codex/NoMicroPanel.vue"
DIST = ROOT / "frontend/dist"
INDEX = DIST / "index.html"
STAMP = DIST / ".cas-r49-unified-codex-temp-launch-ui"
MARKER = "CAS-R49-UNIFIED-CODEX-TEMP-LAUNCH"


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if old not in text:
        raise SystemExit(f"r49 unified Codex TEMP anchor missing: {label}")
    return text.replace(old, new, 1)


# -----------------------------------------------------------------------------
# Shared backend helper: r47 already owns all validation/write-probe semantics.
# r49 only exposes it to the sibling No Lagging launcher so A/B and normal restart
# cannot drift into separate TEMP implementations.
# -----------------------------------------------------------------------------
process = PROCESS.read_text(encoding="utf-8")
if MARKER not in process:
    old = "fn codex_custom_temp_launch_env(platform: &str) -> Result<Vec<(String, String)>, String> {\n"
    new = "// CAS-R49-UNIFIED-CODEX-TEMP-LAUNCH: shared by normal/A/B launchers.\n" \
          "pub(crate) fn codex_custom_temp_launch_env(platform: &str) -> Result<Vec<(String, String)>, String> {\n"
    process = replace_once(process, old, new, "publish r47 temp helper")
    PROCESS.write_text(process, encoding="utf-8")
    print("R49 SHARED TEMP HELPER PASS")
else:
    print("r49 shared temp helper already applied")


# -----------------------------------------------------------------------------
# No Lagging B launches ChatGPT through a Node injector rather than the normal
# process launcher. Inject the exact same r47 TEMP/TMP/TMPDIR values into Node;
# the spawned ChatGPT process inherits them naturally.
# -----------------------------------------------------------------------------
no_micro = NO_MICRO.read_text(encoding="utf-8")
if MARKER not in no_micro:
    anchor = '''    let mut command = Command::new(&node);\n    command\n        .arg(&launcher)\n        .arg(&executable)\n        .args(extra_args)\n        .env("CAS_NO_MICRO_STATUS_PATH", &status_path)\n'''
    replacement = '''    // CAS-R49-UNIFIED-CODEX-TEMP-LAUNCH\n    // B bypasses the normal MSIX/direct launcher, so explicitly apply the same r47\n    // process-local TEMP environment to the Node injector. ChatGPT inherits it.\n    let custom_temp_env =\n        crate::admin::services::desktop::process::codex_custom_temp_launch_env("windows")?;\n\n    let mut command = Command::new(&node);\n    command\n        .arg(&launcher)\n        .arg(&executable)\n        .args(extra_args)\n        .env("CAS_NO_MICRO_STATUS_PATH", &status_path)\n'''
    no_micro = replace_once(no_micro, anchor, replacement, "No Lagging launcher command")

    env_anchor = '''        .env(\n            "CAS_NO_MICRO_PACKAGE_VERSION",\n            report.package_version.as_deref().unwrap_or("unknown"),\n        )\n        .stdin(Stdio::null())\n'''
    env_replacement = '''        .env(\n            "CAS_NO_MICRO_PACKAGE_VERSION",\n            report.package_version.as_deref().unwrap_or("unknown"),\n        )\n        .envs(custom_temp_env.iter().map(|(key, value)| (key, value)))\n        .stdin(Stdio::null())\n'''
    no_micro = replace_once(no_micro, env_anchor, env_replacement, "No Lagging custom temp envs")

    output_anchor = '''    let output = hide_console_window(&mut command)\n        .output()\n'''
    output_replacement = '''    if !custom_temp_env.is_empty() {\n        tracing::info!(\n            custom_temp = true,\n            launcher = "no-lagging-b",\n            "[r49] No Lagging launcher inherits Transfer-scoped Codex TEMP"\n        );\n    }\n    let output = hide_console_window(&mut command)\n        .output()\n'''
    no_micro = replace_once(no_micro, output_anchor, output_replacement, "No Lagging temp log")
    NO_MICRO.write_text(no_micro, encoding="utf-8")
    print("R49 NO-LAGGING TEMP INHERITANCE PASS")
else:
    print("r49 No Lagging TEMP inheritance already applied")


# -----------------------------------------------------------------------------
# Providers toolbar owns the TEMP draft. Make one shared async pre-launch saver
# and pass it into NoMicroPanel so all three launch buttons apply the same draft.
# -----------------------------------------------------------------------------
providers = PROVIDERS.read_text(encoding="utf-8")
if MARKER not in providers:
    old_restart = '''async function onRestartCodexApp() {\n  if (codexTempApplying.value) return\n  const value = codexTempDir.value.trim()\n  if (isWindows && codexTempEnabled.value && !value) {\n    toast(t('settings.codexCustomTempPathRequired'), 'error')\n    return\n  }\n\n  codexTempApplying.value = true\n  try {\n    if (isWindows) {\n      const warn = await settingsStore.save({\n        codexCustomTempEnabled: codexTempEnabled.value,\n        codexCustomTempDir: value,\n      })\n      codexTempDir.value = value\n      if (warn) toast(warn, 'error')\n    }\n    await restartCodexApp()\n    toast(t('toast.codexAppRestartRequested'))\n  } catch (e) {\n    // saveSettings rolls back its optimistic state on failure. Reload the draft so\n    // the toolbar never claims a value that the backend did not persist.\n    if (isWindows) await loadCodexTempDraft()\n    toast((e as Error).message || t('toast.codexAppRestartFailed'), 'error')\n  } finally {\n    codexTempApplying.value = false\n  }\n}\n'''
    new_restart = '''// CAS-R49-UNIFIED-CODEX-TEMP-LAUNCH\n// Every Transfer-owned Codex launch entry calls this first. The current toolbar draft\n// therefore becomes authoritative before Restart, A or B reaches the backend.\nasync function persistCodexTempDraft(): Promise<boolean> {\n  if (!isWindows) return true\n  const value = codexTempDir.value.trim()\n  if (codexTempEnabled.value && !value) {\n    toast(t('settings.codexCustomTempPathRequired'), 'error')\n    return false\n  }\n  try {\n    const warn = await settingsStore.save({\n      codexCustomTempEnabled: codexTempEnabled.value,\n      codexCustomTempDir: value,\n    })\n    codexTempDir.value = value\n    if (warn) toast(warn, 'error')\n    return true\n  } catch (e) {\n    await loadCodexTempDraft()\n    toast((e as Error).message || '保存 Codex TEMP 设置失败', 'error')\n    return false\n  }\n}\n\nasync function onRestartCodexApp() {\n  if (codexTempApplying.value) return\n  codexTempApplying.value = true\n  try {\n    if (!(await persistCodexTempDraft())) return\n    await restartCodexApp()\n    toast(t('toast.codexAppRestartRequested'))\n  } catch (e) {\n    toast((e as Error).message || t('toast.codexAppRestartFailed'), 'error')\n  } finally {\n    codexTempApplying.value = false\n  }\n}\n'''
    providers = replace_once(providers, old_restart, new_restart, "provider restart/persist helper")

    providers = providers.replace(
        '<span class="providers__temp-apply-hint">重启时应用</span>',
        '<span class="providers__temp-apply-hint">任一启动均应用</span>',
        1,
    )

    panel_anchor = '<NoMicroPanel v-if="isWindows" class="providers__no-micro" />'
    panel_new = '<NoMicroPanel\n      v-if="isWindows"\n      class="providers__no-micro"\n      :before-launch="persistCodexTempDraft"\n    />'
    providers = replace_once(providers, panel_anchor, panel_new, "NoMicroPanel pre-launch saver")
    PROVIDERS.write_text(providers, encoding="utf-8")
    print("R49 PROVIDER TEMP PRE-LAUNCH SAVE PASS")
else:
    print("r49 provider TEMP pre-launch save already applied")


# -----------------------------------------------------------------------------
# A/B panel: confirmation still comes first; immediately before actual launch,
# await the parent saver. If the TEMP path is invalid or cannot be persisted,
# abort without touching the Codex runtime.
# -----------------------------------------------------------------------------
panel = NO_MICRO_PANEL.read_text(encoding="utf-8")
if MARKER not in panel:
    script_anchor = '<script setup lang="ts">\n'
    props = '''<script setup lang="ts">\n// CAS-R49-UNIFIED-CODEX-TEMP-LAUNCH\nconst props = defineProps<{\n  beforeLaunch?: () => Promise<boolean>\n}>()\n'''
    panel = replace_once(panel, script_anchor, props, "NoMicroPanel props")

    normal_anchor = '''  if (!ok) return\n  normalLaunching.value = true\n'''
    normal_new = '''  if (!ok) return\n  if (props.beforeLaunch && !(await props.beforeLaunch())) return\n  normalLaunching.value = true\n'''
    panel = replace_once(panel, normal_anchor, normal_new, "A pre-launch temp persistence")

    b_anchor = '''  if (!ok) return\n  noMicroLaunching.value = true\n'''
    b_new = '''  if (!ok) return\n  if (props.beforeLaunch && !(await props.beforeLaunch())) return\n  noMicroLaunching.value = true\n'''
    panel = replace_once(panel, b_anchor, b_new, "B pre-launch temp persistence")
    NO_MICRO_PANEL.write_text(panel, encoding="utf-8")
    print("R49 A/B TEMP PRE-LAUNCH HOOK PASS")
else:
    print("r49 A/B TEMP pre-launch hook already applied")


# Frontend moved behavior; force one rebuild only.
DIST.mkdir(parents=True, exist_ok=True)
if not STAMP.exists():
    if INDEX.is_file():
        INDEX.unlink()
        print("r49 unified Codex TEMP: invalidated stale frontend index once")
    STAMP.write_text("r49 unified Codex TEMP launch UI requires rebuilt frontend assets\n", encoding="utf-8")
    print("R49 FRONTEND INVALIDATE-ONCE PASS")
else:
    print("r49 frontend invalidation already recorded; SKIP")


# Cheap structural invariants. Real Windows Review/Changes behavior remains the proof.
process = PROCESS.read_text(encoding="utf-8")
no_micro = NO_MICRO.read_text(encoding="utf-8")
providers = PROVIDERS.read_text(encoding="utf-8")
panel = NO_MICRO_PANEL.read_text(encoding="utf-8")
for required in (
    MARKER,
    "pub(crate) fn codex_custom_temp_launch_env",
):
    if required not in process:
        raise SystemExit(f"r49 process invariant missing: {required}")
for required in (
    MARKER,
    'codex_custom_temp_launch_env("windows")',
    ".envs(custom_temp_env.iter()",
    'launcher = "no-lagging-b"',
):
    if required not in no_micro:
        raise SystemExit(f"r49 No Lagging invariant missing: {required}")
for required in (
    MARKER,
    "persistCodexTempDraft",
    ':before-launch="persistCodexTempDraft"',
    "任一启动均应用",
):
    if required not in providers:
        raise SystemExit(f"r49 Providers invariant missing: {required}")
for required in (
    MARKER,
    "beforeLaunch?: () => Promise<boolean>",
    "await props.beforeLaunch()",
):
    if required not in panel:
        raise SystemExit(f"r49 NoMicroPanel invariant missing: {required}")

print("R49 UNIFIED CODEX TEMP LAUNCH HOTFIX PASS")
print("- Restart Codex App, Normal A and No Lagging B persist the same toolbar TEMP draft before launch")
print("- normal/A launch paths reuse r47 process-local TEMP helper")
print("- B Node injector explicitly receives the same validated TEMP/TMP/TMPDIR and passes it to ChatGPT")
print("- invalid/empty enabled paths fail before any Codex launch")
print("- no user/system TEMP mutation; no old cache move/delete")
