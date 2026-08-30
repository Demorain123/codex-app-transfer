from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SETTINGS = ROOT / "frontend/src/pages/SettingsPage.vue"
PROVIDERS = ROOT / "frontend/src/pages/ProvidersPage.vue"
DIST = ROOT / "frontend/dist"
INDEX = DIST / "index.html"
STAMP = DIST / ".cas-r48-provider-temp-control-ui"
MARKER = "CAS-R48-PROVIDER-TEMP-CONTROL"


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if old not in text:
        raise SystemExit(f"r48 provider-temp anchor missing: {label}")
    return text.replace(old, new, 1)


# -----------------------------------------------------------------------------
# Remove the r47 custom-temp controls from SettingsPage. The backend/settings
# keys remain unchanged; r48 changes only where users operate the feature.
# -----------------------------------------------------------------------------
settings = SETTINGS.read_text(encoding="utf-8")
if MARKER not in settings:
    # Remove r47 script state/handlers. It was injected immediately before the
    # next stable setting declaration, which makes this tolerant of later text drift.
    logic_start = settings.find("// CAS-R47-CODEX-CUSTOM-TEMP\n")
    logic_end_token = "const codexQuotaEnabled = toggle('codexQuotaEnabled', false)\n"
    if logic_start >= 0:
        logic_end = settings.find(logic_end_token, logic_start)
        if logic_end < 0:
            raise SystemExit("r48 provider-temp: SettingsPage custom-temp logic end anchor missing")
        settings = settings[:logic_start] + settings[logic_end:]

    # Remove the two r47 SettingsRows (toggle + path/apply row). The second row may
    # include the r47 disable/restart compatibility comment, so count row closings
    # rather than matching the whole historical block literally.
    rows_start = settings.find("      <!-- CAS-R47-CODEX-CUSTOM-TEMP -->\n")
    if rows_start >= 0:
        first_end = settings.find("      </SettingsRow>\n", rows_start)
        if first_end < 0:
            raise SystemExit("r48 provider-temp: SettingsPage first temp row end missing")
        second_end = settings.find("      </SettingsRow>\n", first_end + 1)
        if second_end < 0:
            raise SystemExit("r48 provider-temp: SettingsPage second temp row end missing")
        second_end += len("      </SettingsRow>\n")
        settings = settings[:rows_start] + settings[second_end:]

    # r47 added restartCodexApp and isWindows only for this Settings UI. Remove them
    # if no other SettingsPage code still needs them.
    if "onApplyCodexCustomTemp" not in settings and "restartCodexApp(" not in settings:
        settings = settings.replace("  restartCodexApp,\n", "", 1)
    if "codexCustomTemp" not in settings:
        settings = settings.replace(
            "const isWindows = typeof navigator !== 'undefined' && /Windows/i.test(navigator.userAgent)\n",
            "",
            1,
        )
        settings = settings.replace(".settings-input--wide {\n  width: 360px;\n}\n", "", 1)

    # File-level r48 marker documents intentional UI relocation and prevents this
    # cleanup from running twice.
    script_tag = '<script setup lang="ts">\n'
    settings = replace_once(
        settings,
        script_tag,
        script_tag + "// CAS-R48-PROVIDER-TEMP-CONTROL: custom TEMP controls moved to ProvidersPage.\n",
        "SettingsPage script marker",
    )
    SETTINGS.write_text(settings, encoding="utf-8")
    print("R48 SETTINGS TEMP UI REMOVAL PASS")
else:
    print("r48 SettingsPage temp UI already relocated")


# -----------------------------------------------------------------------------
# ProvidersPage: place the feature next to the existing Restart Codex button.
# The toggle/path are draft values. Clicking the existing restart button validates,
# persists both settings atomically, then restarts Codex so the process-local
# TEMP/TMP/TMPDIR from r47 is actually applied.
# -----------------------------------------------------------------------------
providers = PROVIDERS.read_text(encoding="utf-8")
if MARKER not in providers:
    providers = replace_once(
        providers,
        "import { useProvidersStore } from '@/stores/providers'\n",
        "import { useProvidersStore } from '@/stores/providers'\n"
        "import { useSettingsStore } from '@/stores/settings'\n",
        "settings store import",
    )
    providers = replace_once(
        providers,
        "import AppButton from '@/components/ui/AppButton.vue'\n",
        "import AppButton from '@/components/ui/AppButton.vue'\n"
        "import AppSwitch from '@/components/ui/AppSwitch.vue'\n",
        "AppSwitch import",
    )

    store_anchor = "const store = useProvidersStore()\n"
    state = r'''const store = useProvidersStore()
// CAS-R48-PROVIDER-TEMP-CONTROL
const settingsStore = useSettingsStore()
const codexTempEnabled = ref(false)
const codexTempDir = ref('')
const codexTempApplying = ref(false)

function syncCodexTempDraft() {
  codexTempEnabled.value = settingsStore.bool('codexCustomTempEnabled', false)
  codexTempDir.value = settingsStore.str('codexCustomTempDir', '')
}

async function loadCodexTempDraft() {
  try {
    if (!settingsStore.loaded) await settingsStore.load()
    syncCodexTempDraft()
  } catch (e) {
    toast((e as Error).message || '读取 Codex TEMP 设置失败', 'error')
  }
}
'''
    providers = replace_once(providers, store_anchor, state, "provider temp draft state")

    providers = replace_once(
        providers,
        "onMounted(() => store.load())\n",
        "onMounted(() => {\n"
        "  store.load()\n"
        "  void loadCodexTempDraft()\n"
        "})\n",
        "providers onMounted",
    )

    old_restart = r'''async function onRestartCodexApp() {
  try {
    await restartCodexApp()
    toast(t('toast.codexAppRestartRequested'))
  } catch (e) {
    toast((e as Error).message || t('toast.codexAppRestartFailed'), 'error')
  }
}
'''
    new_restart = r'''async function onRestartCodexApp() {
  if (codexTempApplying.value) return
  const value = codexTempDir.value.trim()
  if (isWindows && codexTempEnabled.value && !value) {
    toast(t('settings.codexCustomTempPathRequired'), 'error')
    return
  }

  codexTempApplying.value = true
  try {
    if (isWindows) {
      const warn = await settingsStore.save({
        codexCustomTempEnabled: codexTempEnabled.value,
        codexCustomTempDir: value,
      })
      codexTempDir.value = value
      if (warn) toast(warn, 'error')
    }
    await restartCodexApp()
    toast(t('toast.codexAppRestartRequested'))
  } catch (e) {
    // saveSettings rolls back its optimistic state on failure. Reload the draft so
    // the toolbar never claims a value that the backend did not persist.
    if (isWindows) await loadCodexTempDraft()
    toast((e as Error).message || t('toast.codexAppRestartFailed'), 'error')
  } finally {
    codexTempApplying.value = false
  }
}
'''
    providers = replace_once(providers, old_restart, new_restart, "restart applies temp draft")

    header_anchor = '''    <div class="providers__header">
'''
    toolbar = r'''    <div class="providers__header">
      <!-- CAS-R48-PROVIDER-TEMP-CONTROL
           TEMP is a Codex launch option, so keep it beside the existing restart action
           instead of the general Settings page. Values are persisted only when Restart
           Codex App is clicked, preventing a half-configured enabled+empty path. -->
      <div
        v-if="isWindows"
        class="providers__temp-control"
        :title="t('settings.codexCustomTempHint')"
      >
        <span class="providers__temp-label">Codex TEMP</span>
        <AppSwitch v-model="codexTempEnabled" />
        <input
          v-if="codexTempEnabled"
          v-model="codexTempDir"
          type="text"
          class="providers__temp-input"
          :placeholder="t('settings.codexCustomTempPlaceholder')"
          @keydown.enter.prevent="onRestartCodexApp"
        />
        <span class="providers__temp-apply-hint">重启时应用</span>
      </div>
'''
    providers = replace_once(providers, header_anchor, toolbar, "provider header temp toolbar")

    # The normal Restart button is also the Apply action. Disable it while saving/
    # restarting so a double click cannot race two different TEMP environments.
    button_anchor = '''        :label="t('providers.restartCodexApp')"
        @click="onRestartCodexApp"
'''
    button_new = '''        :label="t('providers.restartCodexApp')"
        :disabled="codexTempApplying"
        @click="onRestartCodexApp"
'''
    providers = replace_once(providers, button_anchor, button_new, "restart busy guard")

    style_anchor = '''.providers__header {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: var(--space-2);
  margin-bottom: var(--space-4);
}
'''
    style = style_anchor + r'''.providers__temp-control {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  min-width: 0;
  padding: 6px 10px;
  border: 1px solid var(--border);
  border-radius: var(--radius);
  background: var(--surface);
}
.providers__temp-label {
  font-size: 13px;
  font-weight: 650;
  white-space: nowrap;
}
.providers__temp-input {
  width: min(280px, 28vw);
  min-width: 150px;
  height: 34px;
  padding: 0 10px;
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  background: var(--surface);
  color: var(--text);
  outline: none;
}
.providers__temp-input:focus {
  border-color: var(--accent);
}
.providers__temp-apply-hint {
  color: var(--text-muted);
  font-size: 12px;
  white-space: nowrap;
}
@media (max-width: 980px) {
  .providers__header {
    flex-wrap: wrap;
  }
  .providers__temp-control {
    width: 100%;
    justify-content: flex-end;
  }
  .providers__temp-input {
    flex: 1;
    width: auto;
  }
}
'''
    providers = replace_once(providers, style_anchor, style, "provider temp toolbar styles")

    PROVIDERS.write_text(providers, encoding="utf-8")
    print("R48 PROVIDER TEMP CONTROL UI PASS")
else:
    print("r48 provider temp control already applied")

# One frontend rebuild is required after moving the controls.
DIST.mkdir(parents=True, exist_ok=True)
if not STAMP.exists():
    if INDEX.is_file():
        INDEX.unlink()
        print("r48 provider temp control: invalidated stale frontend index once")
    STAMP.write_text("r48 provider temp control requires rebuilt frontend assets\n", encoding="utf-8")
    print("R48 PROVIDER TEMP FRONTEND INVALIDATE-ONCE PASS")
else:
    print("r48 provider temp frontend invalidation already recorded; SKIP")

# Cheap invariants: backend r47 keys stay untouched; Settings UI is gone and the
# provider toolbar owns every interactive custom-temp reference.
settings = SETTINGS.read_text(encoding="utf-8")
providers = PROVIDERS.read_text(encoding="utf-8")
if "<!-- CAS-R47-CODEX-CUSTOM-TEMP -->" in settings:
    raise SystemExit("r48 invariant failed: old SettingsPage custom-temp rows still present")
if "onApplyCodexCustomTemp" in settings or "codexCustomTempEnabled" in settings:
    raise SystemExit("r48 invariant failed: old SettingsPage custom-temp logic still present")
for required in (
    MARKER,
    "useSettingsStore",
    "codexTempEnabled",
    "codexTempDir",
    "settingsStore.save",
    "重启时应用",
    "providers__temp-control",
):
    if required not in providers:
        raise SystemExit(f"r48 provider-temp invariant missing: {required}")

print("R48 PROVIDER TEMP CONTROL HOTFIX PASS")
print("- custom TEMP controls removed from SettingsPage")
print("- ProvidersPage header owns enable/path controls beside Restart Codex App")
print("- draft values persist atomically when the existing Restart Codex App button is clicked")
print("- disabling then restarting returns Codex to inherited system TEMP")
print("- r47 process-local TEMP/TMP/TMPDIR backend remains unchanged")
