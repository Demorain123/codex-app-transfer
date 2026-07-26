from pathlib import Path


def read(path: str) -> str:
    return Path(path).read_text(encoding="utf-8")


def write(path: str, text: str) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(text, encoding="utf-8")
    print(f"[ok] patched {path}")


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if new in text:
        print(f"[ok] {label}: already applied")
        return text
    if old not in text:
        raise SystemExit(f"anchor not found: {label}")
    print(f"[ok] {label}: applied")
    return text.replace(old, new, 1)


COMPONENT_PATH = "frontend/src/components/provider/Sub2ApiGrokCompatControls.vue"
COMPONENT = r'''<script setup lang="ts">
import { t } from '@/i18n'
import SettingsRow from '@/components/ui/SettingsRow.vue'
import AppSwitch from '@/components/ui/AppSwitch.vue'

const props = defineProps<{
  enabled: boolean
  cacheEnabled: boolean
}>()

const emit = defineEmits<{
  'update:enabled': [value: boolean]
  'update:cacheEnabled': [value: boolean]
}>()

function setEnabled(value: boolean) {
  emit('update:enabled', value)
  // Keep persisted state clean: the cache fallback is meaningless without the
  // main Grok wire shim, so turning the parent switch off also turns this off.
  if (!value && props.cacheEnabled) emit('update:cacheEnabled', false)
}
</script>

<template>
  <div class="compat-card">
    <div class="compat-head">
      <span>{{ t('providerForm.grokCompatSection') }}</span>
      <span class="compat-badge">COMPAT</span>
    </div>
    <SettingsRow
      :title="t('providerForm.grokCompat')"
      :description="t('providerForm.grokCompatHint')"
    >
      <AppSwitch :model-value="enabled" @update:model-value="setEnabled" />
    </SettingsRow>
    <SettingsRow
      :title="t('providerForm.grokFreeCacheCompat')"
      :description="t('providerForm.grokFreeCacheCompatHint')"
    >
      <AppSwitch
        :model-value="cacheEnabled"
        :disabled="!enabled"
        @update:model-value="emit('update:cacheEnabled', $event)"
      />
    </SettingsRow>
    <div v-if="cacheEnabled" class="compat-warning">
      {{ t('providerForm.grokFreeCacheCompatWarning') }}
    </div>
  </div>
</template>

<style scoped>
.compat-card {
  margin: var(--space-3) 0 var(--space-2);
  border: 1px solid color-mix(in srgb, var(--accent) 38%, var(--border));
  border-radius: var(--radius);
  background: color-mix(in srgb, var(--accent) 5%, var(--surface));
  overflow: hidden;
}
.compat-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: var(--space-3) var(--space-4) var(--space-1);
  font-size: var(--fs-sm);
  font-weight: 650;
  color: var(--accent);
}
.compat-badge {
  padding: 2px 7px;
  border: 1px solid color-mix(in srgb, var(--accent) 45%, transparent);
  border-radius: var(--radius-full);
  font-size: 10px;
  letter-spacing: 0.06em;
}
.compat-warning {
  margin: 0 var(--space-4) var(--space-3);
  padding: var(--space-2) var(--space-3);
  border-radius: var(--radius);
  background: color-mix(in srgb, var(--warning) 10%, transparent);
  color: var(--text-secondary);
  font-size: var(--fs-xs);
  line-height: 1.45;
}
</style>
'''
write(COMPONENT_PATH, COMPONENT)


# ---------------------------------------------------------------------------
# Backend: the upstream admin input is intentionally strict. Keep the compat
# fields as a tiny persistence hook while all runtime behavior lives in the
# separate Rust overlay module.
# ---------------------------------------------------------------------------
path = "src-tauri/src/admin/handlers/providers/crud.rs"
text = read(path)
text = replace_once(
    text,
    '''    #[serde(rename = "reviewModelSlot")]
    pub review_model_slot: Option<String>,
}''',
    '''    #[serde(rename = "reviewModelSlot")]
    pub review_model_slot: Option<String>,
    // CAS-SUB2API-GROK-COMPAT-HOOK: persisted overlay flags.
    #[serde(rename = "sub2apiGrokCompat")]
    pub sub2api_grok_compat: Option<bool>,
    #[serde(rename = "sub2apiGrokFreeCacheCompat")]
    pub sub2api_grok_free_cache_compat: Option<bool>,
}''',
    "AddProviderInput compat fields",
)
text = replace_once(
    text,
    '''        new_provider.insert(
            "requestOptions".into(),
            input.request_options.clone().unwrap_or_else(|| json!({})),
        );
        // [MOC-173] auto-review''',
    '''        new_provider.insert(
            "requestOptions".into(),
            input.request_options.clone().unwrap_or_else(|| json!({})),
        );
        // CAS-SUB2API-GROK-COMPAT-HOOK
        new_provider.insert(
            "sub2apiGrokCompat".into(),
            Value::Bool(input.sub2api_grok_compat.unwrap_or(false)),
        );
        new_provider.insert(
            "sub2apiGrokFreeCacheCompat".into(),
            Value::Bool(input.sub2api_grok_free_cache_compat.unwrap_or(false)),
        );
        // [MOC-173] auto-review''',
    "add_provider persist compat flags",
)
text = replace_once(
    text,
    '''        if let Some(opts) = input.request_options.clone() {
            updated.insert("requestOptions".into(), opts);
        }
        // [MOC-173] auto-review''',
    '''        if let Some(opts) = input.request_options.clone() {
            updated.insert("requestOptions".into(), opts);
        }
        // CAS-SUB2API-GROK-COMPAT-HOOK
        if let Some(enabled) = input.sub2api_grok_compat {
            updated.insert("sub2apiGrokCompat".into(), Value::Bool(enabled));
        }
        if let Some(enabled) = input.sub2api_grok_free_cache_compat {
            updated.insert(
                "sub2apiGrokFreeCacheCompat".into(),
                Value::Bool(enabled),
            );
        }
        // [MOC-173] auto-review''',
    "update_provider persist compat flags",
)
write(path, text)


# ---------------------------------------------------------------------------
# Frontend API: four tiny field plumbing hooks.
# ---------------------------------------------------------------------------
path = "frontend/src/api/types.ts"
text = read(path)
text = replace_once(
    text,
    '''  requestOptions: Record<string, unknown>
  default: boolean''',
    '''  requestOptions: Record<string, unknown>
  // CAS-SUB2API-GROK-COMPAT-HOOK
  sub2apiGrokCompat?: boolean
  sub2apiGrokFreeCacheCompat?: boolean
  default: boolean''',
    "Provider compat fields",
)
text = replace_once(
    text,
    '''  requestOptions?: Record<string, unknown>
  reviewModelSlot?: string | null''',
    '''  requestOptions?: Record<string, unknown>
  // CAS-SUB2API-GROK-COMPAT-HOOK
  sub2apiGrokCompat?: boolean
  sub2apiGrokFreeCacheCompat?: boolean
  reviewModelSlot?: string | null''',
    "ProviderPayload compat fields",
)
write(path, text)

path = "frontend/src/api/providers.ts"
text = read(path)
text = replace_once(
    text,
    '''    requestOptions: provider.requestOptions || {},
    default: provider.id === activeId,''',
    '''    requestOptions: provider.requestOptions || {},
    // CAS-SUB2API-GROK-COMPAT-HOOK
    sub2apiGrokCompat: !!provider.sub2apiGrokCompat,
    sub2apiGrokFreeCacheCompat: !!provider.sub2apiGrokFreeCacheCompat,
    default: provider.id === activeId,''',
    "mapProvider compat fields",
)
text = replace_once(
    text,
    '''    requestOptions: payload.requestOptions || {},
  }''',
    '''    requestOptions: payload.requestOptions || {},
    // CAS-SUB2API-GROK-COMPAT-HOOK
    sub2apiGrokCompat: !!payload.sub2apiGrokCompat,
    sub2apiGrokFreeCacheCompat: !!payload.sub2apiGrokFreeCacheCompat,
  }''',
    "providerBody compat fields",
)
write(path, text)


# ---------------------------------------------------------------------------
# Provider form: migrate the old inline card/styles to one overlay component;
# only state/persistence hooks stay in the upstream form file.
# ---------------------------------------------------------------------------
path = "frontend/src/components/provider/ProviderFormModal.vue"
text = read(path)

# Migrate old inline implementation if present.
text = text.replace("import AppSwitch from '@/components/ui/AppSwitch.vue'\n", "")
inline_block = '''      <div v-if="showSub2apiGrokCompat" class="pf__compat-card">
        <div class="pf__compat-head">
          <span>{{ t('providerForm.grokCompatSection') }}</span>
          <span class="pf__compat-badge">COMPAT</span>
        </div>
        <SettingsRow
          :title="t('providerForm.grokCompat')"
          :description="t('providerForm.grokCompatHint')"
        >
          <AppSwitch v-model="form.sub2apiGrokCompat" />
        </SettingsRow>
        <SettingsRow
          :title="t('providerForm.grokFreeCacheCompat')"
          :description="t('providerForm.grokFreeCacheCompatHint')"
        >
          <AppSwitch
            v-model="form.sub2apiGrokFreeCacheCompat"
            :disabled="!form.sub2apiGrokCompat"
          />
        </SettingsRow>
        <div v-if="form.sub2apiGrokFreeCacheCompat" class="pf__compat-warning">
          {{ t('providerForm.grokFreeCacheCompatWarning') }}
        </div>
      </div>
'''
component_block = '''      <Sub2ApiGrokCompatControls
        v-if="showSub2apiGrokCompat"
        v-model:enabled="form.sub2apiGrokCompat"
        v-model:cache-enabled="form.sub2apiGrokFreeCacheCompat"
      />
'''
if inline_block in text:
    text = text.replace(inline_block, component_block, 1)

style_start = text.find(".pf__compat-card {\n")
if style_start >= 0:
    style_end = text.find(".pf__section {\n", style_start)
    if style_end < 0:
        raise SystemExit("anchor not found: end of legacy compat styles")
    text = text[:style_start] + text[style_end:]

text = replace_once(
    text,
    "import AppButton from '@/components/ui/AppButton.vue'\n",
    "import AppButton from '@/components/ui/AppButton.vue'\nimport Sub2ApiGrokCompatControls from '@/components/provider/Sub2ApiGrokCompatControls.vue'\n",
    "compat component import",
)
text = replace_once(
    text,
    '''  requestOptions: '',
  grokSso: '',
})''',
    '''  requestOptions: '',
  grokSso: '',
  // CAS-SUB2API-GROK-COMPAT-HOOK
  sub2apiGrokCompat: false,
  sub2apiGrokFreeCacheCompat: false,
})''',
    "form compat fields",
)
text = replace_once(
    text,
    '''const isCustomProvider = computed(() => !isBuiltin.value && !matchedPreset.value)
// 编辑内置/预设 provider''',
    '''const isCustomProvider = computed(() => !isBuiltin.value && !matchedPreset.value)
// CAS-SUB2API-GROK-COMPAT-HOOK: only custom Responses providers show the overlay.
const showSub2apiGrokCompat = computed(
  () => isCustomProvider.value && form.apiFormat === 'responses',
)
// 编辑内置/预设 provider''',
    "show compat computed",
)
text = replace_once(
    text,
    '''  form.requestOptions = ''
  availableModels.value = []''',
    '''  form.requestOptions = ''
  form.sub2apiGrokCompat = false
  form.sub2apiGrokFreeCacheCompat = false
  availableModels.value = []''',
    "reset compat fields",
)
text = replace_once(
    text,
    '''  form.requestOptions = stringifyIfAny(p.requestOptions as Record<string, unknown> | undefined)
  // 该上游若之前抓过模型''',
    '''  form.requestOptions = stringifyIfAny(p.requestOptions as Record<string, unknown> | undefined)
  form.sub2apiGrokCompat = false
  form.sub2apiGrokFreeCacheCompat = false
  // 该上游若之前抓过模型''',
    "preset compat reset",
)
text = replace_once(
    text,
    '''  form.requestOptions = stringifyIfAny(p.requestOptions)
  // 该上游之前抓过模型''',
    '''  form.requestOptions = stringifyIfAny(p.requestOptions)
  form.sub2apiGrokCompat = !!p.sub2apiGrokCompat
  form.sub2apiGrokFreeCacheCompat = !!p.sub2apiGrokFreeCacheCompat
  // 该上游之前抓过模型''',
    "edit compat hydrate",
)
text = replace_once(
    text,
    '''      extraHeaders: extraHeaders as Record<string, string> | undefined,
    }''',
    '''      extraHeaders: extraHeaders as Record<string, string> | undefined,
      sub2apiGrokCompat: form.sub2apiGrokCompat,
      sub2apiGrokFreeCacheCompat: form.sub2apiGrokFreeCacheCompat,
    }''',
    "test draft compat fields",
)
text = replace_once(
    text,
    '''    modelCapabilities,
    requestOptions,
  }''',
    '''    modelCapabilities,
    requestOptions,
    sub2apiGrokCompat: form.sub2apiGrokCompat,
    sub2apiGrokFreeCacheCompat: form.sub2apiGrokFreeCacheCompat,
  }''',
    "save payload compat fields",
)
if component_block not in text:
    anchor = '''      <SettingsRow v-if="isCustomProvider" :title="t('providerForm.authScheme')">
        <SegmentedControl v-model="form.authScheme" :options="authOptions" />
      </SettingsRow>

'''
    if anchor not in text:
        raise SystemExit("anchor not found: compat component insertion")
    text = text.replace(anchor, anchor + component_block + "\n", 1)
write(path, text)


# ---------------------------------------------------------------------------
# Visible build identity. Keep the application identifier/data directory intact.
# These are intentionally tiny visual hooks.
# ---------------------------------------------------------------------------
path = "frontend/src/layout/TopTabBar.vue"
text = read(path)
text = replace_once(
    text,
    '''    </nav>
  </header>''',
    '''    </nav>
    <div class="compat-build-badge">{{ t('compat.buildBadge') }}</div>
  </header>''',
    "topbar compat badge",
)
text = replace_once(
    text,
    '''.tabbar {
''',
    '''.compat-build-badge {
  width: max-content;
  margin: 2px auto 0;
  padding: 2px 9px;
  border: 1px solid color-mix(in srgb, var(--accent) 38%, var(--border));
  border-radius: var(--radius-full);
  background: color-mix(in srgb, var(--accent) 7%, transparent);
  color: var(--accent);
  font-size: 10px;
  font-weight: 650;
  letter-spacing: 0.03em;
}
.tabbar {
''',
    "topbar compat badge styles",
)
write(path, text)

path = "frontend/src/layout/AppLayout.vue"
text = read(path)
text = text.replace(
    '<span class="titlebar__title">Codex App Transfer</span>',
    '<span class="titlebar__title">Codex App Transfer — Sub2API Grok Compat</span>',
)
write(path, text)

path = "src-tauri/tauri.conf.json"
text = read(path)
text = text.replace(
    '"title": "Codex App Transfer",',
    '"title": "Codex App Transfer — Sub2API Grok Compat",',
    1,
)
write(path, text)


# ---------------------------------------------------------------------------
# i18n additions.
# ---------------------------------------------------------------------------
translations = {
    "frontend/src/i18n/zh.ts": '''  "compat.buildBadge": "Sub2API Grok Compat 修改版",
  "providerForm.grokCompatSection": "Sub2API · Grok 兼容",
  "providerForm.grokCompat": "Grok MCP / Tools 兼容",
  "providerForm.grokCompatHint": "仅对 grok-* 的 Responses 请求启用 Codex custom / namespace / tool_search 兼容；Luna / GPT 保持原生直透。",
  "providerForm.grokFreeCacheCompat": "Grok Free 缓存兼容",
  "providerForm.grokFreeCacheCompatHint": "适合实际为 Grok Free、但 Sub2API 没显示 Free 标签的账号：保留 prompt_cache_key，并补 web_search / x_search 争取进入可缓存路由。",
  "providerForm.grokFreeCacheCompatWarning": "此模式可能改变 Grok 的 auto 工具选择。启用后请在 Sub2API 用量中用 cache_read_tokens / 蓝色缓存数字验证命中。",
''',
    "frontend/src/i18n/en.ts": '''  "compat.buildBadge": "Sub2API Grok Compat Build",
  "providerForm.grokCompatSection": "Sub2API · Grok Compatibility",
  "providerForm.grokCompat": "Grok MCP / Tools compatibility",
  "providerForm.grokCompatHint": "Enable Codex custom / namespace / tool_search compatibility only for grok-* Responses requests; Luna / GPT remain native passthrough.",
  "providerForm.grokFreeCacheCompat": "Grok Free cache compatibility",
  "providerForm.grokFreeCacheCompatHint": "For accounts that are actually Grok Free but are not labeled Free by Sub2API: preserve prompt_cache_key and add web_search / x_search to qualify for a cache-capable route.",
  "providerForm.grokFreeCacheCompatWarning": "This mode may affect Grok auto tool selection. Verify it with cache_read_tokens / the blue cache value in Sub2API usage.",
''',
}
for path, block in translations.items():
    text = read(path)
    if '"compat.buildBadge"' not in text:
        text = replace_once(text, "export default {\n", "export default {\n" + block, f"{path} translations")
    write(path, text)

print("[ok] Sub2API Grok compat UI/backend overlay complete")
