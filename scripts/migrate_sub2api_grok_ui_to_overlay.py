from pathlib import Path

FORM = Path("frontend/src/components/provider/ProviderFormModal.vue")
COMPONENT = Path("frontend/src/components/provider/Sub2ApiGrokCompatControls.vue")

COMPONENT_SOURCE = r'''<script setup lang="ts">
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

COMPONENT.write_text(COMPONENT_SOURCE, encoding="utf-8")
text = FORM.read_text(encoding="utf-8")

text = text.replace("import AppSwitch from '@/components/ui/AppSwitch.vue'\n", "")
component_import = "import Sub2ApiGrokCompatControls from '@/components/provider/Sub2ApiGrokCompatControls.vue'\n"
if component_import not in text:
    anchor = "import AppButton from '@/components/ui/AppButton.vue'\n"
    if anchor not in text:
        raise SystemExit("missing AppButton import anchor")
    text = text.replace(anchor, anchor + component_import, 1)

legacy = '''      <div v-if="showSub2apiGrokCompat" class="pf__compat-card">
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
replacement = '''      <Sub2ApiGrokCompatControls
        v-if="showSub2apiGrokCompat"
        v-model:enabled="form.sub2apiGrokCompat"
        v-model:cache-enabled="form.sub2apiGrokFreeCacheCompat"
      />
'''
if legacy in text:
    text = text.replace(legacy, replacement, 1)
elif "<Sub2ApiGrokCompatControls" not in text:
    raise SystemExit("legacy compat card not found")

style_start = text.find(".pf__compat-card {\n")
if style_start >= 0:
    style_end = text.find(".pf__section {\n", style_start)
    if style_end < 0:
        raise SystemExit("legacy compat style end not found")
    text = text[:style_start] + text[style_end:]

FORM.write_text(text, encoding="utf-8")
print("migrated legacy ProviderForm compat card to overlay component")
