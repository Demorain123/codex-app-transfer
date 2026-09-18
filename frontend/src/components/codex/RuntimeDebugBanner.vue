<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { i18nState } from '@/i18n'
import { getAppVersion } from '@/api/system'
import { getNoMicroDoctor, type NoMicroDoctor } from '@/api/noMicro'
import { useSettingsStore } from '@/stores/settings'

// CAS-R94-RUNTIME-DEBUG-BANNER-V1
// Visible only when settings.runtimeDebugMode=true. The goal is screenshot-grade
// identity evidence: Transfer package revision + current Codex PID relationship +
// the last No Lagging renderer runtime that was actually armed.
const DEBUG_PROTOCOL = 'DBG94-1'

const store = useSettingsStore()
const appVersion = ref('')
const doctor = ref<NoMicroDoctor | null>(null)
let pollTimer: number | undefined

const enabled = computed(() => store.bool('runtimeDebugMode', false))
const zh = computed(() => i18nState.locale === 'zh')

function revisionNumber(value: unknown): number | null {
  const text = String(value || '')
  const direct = text.match(/\br(\d+)\b/i)
  if (direct) return Number(direct[1])
  const build = text.match(/\+(\d+)(?:\D|$)/)
  return build ? Number(build[1]) : null
}

const transferRevisionNumber = computed(() => revisionNumber(appVersion.value))
const transferRevision = computed(() =>
  transferRevisionNumber.value == null ? 'r?' : `r${transferRevisionNumber.value}`,
)
const lastLaunch = computed(() => doctor.value?.lastLaunch ?? null)
const lastRuntime = computed(() => lastLaunch.value?.outputTelemetry?.runtime || '')
const lastRuntimeRevision = computed(() => revisionNumber(lastRuntime.value))
const currentLaunchEvidence = computed(() => {
  const d = doctor.value
  const pid = Number(lastLaunch.value?.processId)
  return !!(
    d?.processState === 'running' &&
    Number.isFinite(pid) &&
    pid > 0 &&
    Array.isArray(d.processPids) &&
    d.processPids.includes(pid)
  )
})

type DebugState = 'match' | 'legacy' | 'mismatch' | 'unknown' | 'offline' | 'failed'
const debugState = computed<DebugState>(() => {
  const d = doctor.value
  if (!d) return 'unknown'
  if (d.processState === 'not-running') return 'offline'
  if (d.processState !== 'running') return 'unknown'
  if (!currentLaunchEvidence.value) return 'unknown'
  if (lastLaunch.value?.injection?.status && lastLaunch.value.injection.status !== 'success') return 'failed'
  const expected = transferRevisionNumber.value
  const actual = lastRuntimeRevision.value
  if (expected == null || actual == null) return 'unknown'
  if (actual === expected) return 'match'
  if (actual < expected) return 'legacy'
  return 'mismatch'
})

const copy = computed(() =>
  zh.value
    ? {
        match: '当前 Codex runtime 与 Transfer 匹配',
        legacy: '检测到旧 Codex runtime',
        mismatch: 'Codex runtime 与 Transfer 版本不一致',
        unknown: '当前 Codex runtime 无可靠同 PID 证据',
        offline: 'Codex 当前未运行',
        failed: '最近一次 No Lagging 注入失败',
        current: '当前',
        stale: '历史',
        noRuntime: '无 runtime 记录',
      }
    : {
        match: 'Current Codex runtime matches Transfer',
        legacy: 'Legacy Codex runtime detected',
        mismatch: 'Codex runtime does not match Transfer',
        unknown: 'No reliable same-PID runtime evidence for current Codex',
        offline: 'Codex is not running',
        failed: 'Last No Lagging injection failed',
        current: 'current',
        stale: 'stale',
        noRuntime: 'no runtime record',
      },
)

const headline = computed(() => copy.value[debugState.value])
const runtimeEvidenceLabel = computed(() => {
  const runtime = lastRuntime.value || copy.value.noRuntime
  const scope = currentLaunchEvidence.value ? copy.value.current : copy.value.stale
  return `${scope}: ${runtime}`
})

async function refresh() {
  const [versionResult, doctorResult] = await Promise.allSettled([getAppVersion(), getNoMicroDoctor()])
  if (versionResult.status === 'fulfilled') appVersion.value = versionResult.value.version || ''
  if (doctorResult.status === 'fulfilled') doctor.value = doctorResult.value
}

function stopPolling() {
  if (pollTimer != null) {
    window.clearInterval(pollTimer)
    pollTimer = undefined
  }
}

function startPolling() {
  stopPolling()
  void refresh()
  pollTimer = window.setInterval(() => void refresh(), 2500)
}

watch(
  enabled,
  (value) => {
    if (value) startPolling()
    else stopPolling()
  },
  { immediate: true },
)

onBeforeUnmount(stopPolling)
</script>

<template>
  <aside
    v-if="enabled"
    class="runtime-debug-banner"
    :data-state="debugState"
    data-cas-runtime-debug="DBG94-1"
  >
    <div class="runtime-debug-banner__headline">
      <strong>DEBUG · {{ headline }}</strong>
      <span class="runtime-debug-banner__protocol">{{ DEBUG_PROTOCOL }}</span>
    </div>
    <div class="runtime-debug-banner__facts">
      <span>Transfer {{ transferRevision }} · v{{ appVersion || '?' }}</span>
      <span>Codex {{ doctor?.processState || 'unknown' }}</span>
      <span>Last B {{ runtimeEvidenceLabel }}</span>
      <span v-if="lastLaunch?.processId">PID {{ lastLaunch.processId }}</span>
    </div>
  </aside>
</template>

<style scoped>
.runtime-debug-banner {
  flex-shrink: 0;
  display: grid;
  gap: 4px;
  padding: 7px 14px;
  border-top: 1px solid color-mix(in srgb, #d97706 45%, var(--border));
  border-bottom: 1px solid color-mix(in srgb, #d97706 55%, var(--border));
  background: color-mix(in srgb, #f59e0b 12%, var(--surface));
  color: var(--text);
  font: 11px/1.35 ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  user-select: text;
}
.runtime-debug-banner[data-state='match'] {
  border-color: color-mix(in srgb, #16a34a 60%, var(--border));
  background: color-mix(in srgb, #22c55e 11%, var(--surface));
}
.runtime-debug-banner[data-state='legacy'],
.runtime-debug-banner[data-state='mismatch'],
.runtime-debug-banner[data-state='failed'] {
  border-color: color-mix(in srgb, #dc2626 68%, var(--border));
  background: color-mix(in srgb, #ef4444 12%, var(--surface));
}
.runtime-debug-banner__headline,
.runtime-debug-banner__facts {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 6px 14px;
}
.runtime-debug-banner__protocol {
  padding: 1px 6px;
  border: 1px solid currentColor;
  border-radius: 999px;
  font-weight: 700;
}
.runtime-debug-banner__facts {
  color: var(--text-secondary);
}
</style>
