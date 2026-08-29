from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PAGE = ROOT / "frontend/src/pages/SettingsPage.vue"
MARKER = "CAS-R47-TEMP-TOGGLE-RESTART-FIX"

text = PAGE.read_text(encoding="utf-8")
if MARKER in text:
    print("r47 temp toggle restart fix already applied")
    raise SystemExit(0)

old = '''      <SettingsRow
        v-if="isWindows && codexCustomTempEnabled"
        :title="t('settings.codexCustomTempPath')"
'''
new = '''      <!-- CAS-R47-TEMP-TOGGLE-RESTART-FIX: keep Apply/Restart reachable when disabling -->
      <SettingsRow
        v-if="isWindows"
        :title="t('settings.codexCustomTempPath')"
'''
if old not in text:
    raise SystemExit("r47 temp toggle restart fix: settings row anchor missing")
text = text.replace(old, new, 1)

input_anchor = '''          :placeholder="t('settings.codexCustomTempPlaceholder')"
          @change="onCodexCustomTempDirChange"
'''
input_new = '''          :placeholder="t('settings.codexCustomTempPlaceholder')"
          :disabled="!codexCustomTempEnabled"
          @change="onCodexCustomTempDirChange"
'''
if input_anchor not in text:
    raise SystemExit("r47 temp toggle restart fix: input anchor missing")
text = text.replace(input_anchor, input_new, 1)

PAGE.write_text(text, encoding="utf-8")
print("R47 TEMP TOGGLE RESTART FIX PASS")
