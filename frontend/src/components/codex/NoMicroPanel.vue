<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { i18nState } from '@/i18n'
import AppButton from '@/components/ui/AppButton.vue'
import { useToast } from '@/composables/useToast'
import { useConfirm } from '@/composables/useConfirm'
import {
  getNoMicroDoctor,
  launchCodexNoMicro,
  launchCodexNormalAb,
  type NoMicroDoctor,
} from '@/api/noMicro'

const { show: toast } = useToast()
const { confirm } = useConfirm()
const doctor = ref<NoMicroDoctor | null>(null)
const loading = ref(false)
const normalLaunching = ref(false)
const noMicroLaunching = ref(false)

const busy = computed(() => loading.value || normalLaunching.value || noMicroLaunching.value)
const normalReady = computed(
  () =>
    !!doctor.value?.supported &&
    !!doctor.value?.packageFound &&
    !!doctor.value?.executablePath &&
    doctor.value?.processState === 'not-running',
)

const zh = computed(() => i18nState.locale === 'zh')
const copy = computed(() =>
  zh.value
    ? {
        title: 'Codex No Micro A/B（实验性）',
        desc: '用同一面板做最小 A/B：A 为普通启动，B 为 No Micro 启动。两种启动都会把明确的 [codex-ab]、run_id、mode 和启动/退出阶段写入 Transfer 的 proxy 日志，后续分析不再依赖手工记时间。',
        doctor: '兼容性检查',
        checking: '检查中…',
        normalLaunch: '普通启动（A）',
        normalLaunching: 'A 启动中…',
        noMicroLaunch: 'No Micro 启动（B）',
        noMicroLaunching: 'B 启动中…',
        ready: '环境兼容，可以进行 A/B 实验。每一轮开始前都必须先完全退出 Codex。',
        running: 'Codex 仍在运行。请先从 Codex 菜单完全退出，再开始下一轮 A/B。',
        incompatible: 'No Micro 注入兼容性未通过；普通 A 仍可在 Codex 完全退出后使用。',
        unknown: '暂时无法确认环境状态。请重新检查。',
        normalConfirmTitle: '普通启动 Codex（A）？',
        normalConfirmMessage:
          '这是 A/B 的普通对照启动，不做 No Micro 注入。Transfer 会把 mode=normal 的明确标识写进 proxy 日志。开始前请确保 Codex 已完全退出。',
        normalConfirmLabel: '启动 A',
        noMicroConfirmTitle: '以 No Micro 模式启动 Codex（B）？',
        noMicroConfirmMessage:
          '这是 A/B 的 No Micro 实验启动，只拦截 @worklouder/device-kit-oai。Transfer 会把 mode=no-micro 的明确标识写进同一份 proxy 日志。开始前请确保 Codex 已完全退出。',
        noMicroConfirmLabel: '启动 B',
        normalLaunchOk: '普通 A 已启动并写入日志标识',
        noMicroLaunchOk: 'No Micro B 注入已验证并写入日志标识',
        lastSuccess: '最近一次 B：注入成功',
        lastFailed: '最近一次 B：注入失败',
        never: '尚无 No Micro B 启动记录',
        unsupported: '当前平台暂不支持（仅 Windows Store/MSIX Codex）。',
        logHint: '日志关键字：[codex-ab]。A 看 mode=normal，B 看 mode=no-micro；process_exit 表示该轮 Codex 已退出。',
      }
    : {
        title: 'Codex No Micro A/B (experimental)',
        desc: 'Run the minimal A/B from one panel: A is a normal launch, B is a No Micro launch. Both write explicit [codex-ab] run_id/mode/lifecycle markers into the Transfer proxy log, so later analysis does not depend on manually noted timestamps.',
        doctor: 'Compatibility check',
        checking: 'Checking…',
        normalLaunch: 'Normal launch (A)',
        normalLaunching: 'Launching A…',
        noMicroLaunch: 'No Micro launch (B)',
        noMicroLaunching: 'Launching B…',
        ready: 'Environment is compatible and ready for A/B. Fully quit Codex before every run.',
        running: 'Codex is still running. Fully quit Codex before starting the next A/B run.',
        incompatible: 'No Micro compatibility did not pass; normal A can still be used after Codex is fully stopped.',
        unknown: 'Environment state is not yet known. Run the check again.',
        normalConfirmTitle: 'Launch normal Codex (A)?',
        normalConfirmMessage:
          'This is the normal A/B control path and does not inject No Micro. Transfer will write an explicit mode=normal marker to the proxy log. Fully quit Codex first.',
        normalConfirmLabel: 'Launch A',
        noMicroConfirmTitle: 'Launch Codex with No Micro (B)?',
        noMicroConfirmMessage:
          'This is the No Micro B path and only intercepts @worklouder/device-kit-oai. Transfer will write an explicit mode=no-micro marker to the same proxy log. Fully quit Codex first.',
        noMicroConfirmLabel: 'Launch B',
        normalLaunchOk: 'Normal A launched and its log marker was written',
        noMicroLaunchOk: 'No Micro B injection verified and its log marker was written',
        lastSuccess: 'Last B: injection succeeded',
        lastFailed: 'Last B: injection failed',
        never: 'No No Micro B launch has been recorded yet',
        unsupported: 'This feature currently supports Windows Store/MSIX Codex only.',
        logHint: 'Log key: [codex-ab]. A uses mode=normal, B uses mode=no-micro; process_exit marks the end of that Codex run.',
      },
)

const stateText = computed(() => {
  const d = doctor.value
  if (!d) return copy.value.unknown
  if (!d.supported) return copy.value.unsupported
  if (d.processState === 'running') return copy.value.running
  if (d.launchReady) return copy.value.ready
  if (!d.compatible) return copy.value.incompatible
  return copy.value.unknown
})

const metaText = computed(() => {
  const d = doctor.value
  if (!d) return ''
  const parts = [
    d.packageVersion ? `Codex ${d.packageVersion}` : null,
    d.nodeVersion ? `Node ${d.nodeVersion}` : null,
    `device-kit ×${d.targetModuleCount}`,
    `serialport ×${d.serialportCount}`,
    `gate ×${d.featureGateCount}`,
  ].filter(Boolean)
  return parts.join(' · ')
})

const lastText = computed(() => {
  const last = doctor.value?.lastLaunch
  if (!last?.injection?.status) return copy.value.never
  if (last.injection.status === 'success') return copy.value.lastSuccess
  const detail = [last.injection.phase, last.injection.error].filter(Boolean).join(' — ')
  return `${copy.value.lastFailed}${detail ? ` (${detail})` : ''}`
})

async function refresh() {
  if (loading.value) return
  loading.value = true
  try {
    doctor.value = await getNoMicroDoctor()
  } catch (e) {
    toast((e as Error).message, 'error')
  } finally {
    loading.value = false
  }
}

async function launchNormal() {
  if (busy.value || !normalReady.value) return
  const ok = await confirm({
    title: copy.value.normalConfirmTitle,
    message: copy.value.normalConfirmMessage,
    confirmLabel: copy.value.normalConfirmLabel,
  })
  if (!ok) return
  normalLaunching.value = true
  try {
    const result = await launchCodexNormalAb()
    toast(`${copy.value.normalLaunchOk} · run_id=${result.abRunId}`)
    window.setTimeout(() => void refresh(), 1200)
  } catch (e) {
    toast((e as Error).message, 'error')
    await refresh()
  } finally {
    normalLaunching.value = false
  }
}

async function launchNoMicro() {
  if (busy.value || !doctor.value?.launchReady) return
  const ok = await confirm({
    title: copy.value.noMicroConfirmTitle,
    message: copy.value.noMicroConfirmMessage,
    confirmLabel: copy.value.noMicroConfirmLabel,
  })
  if (!ok) return
  noMicroLaunching.value = true
  try {
    const result = await launchCodexNoMicro()
    doctor.value = result.doctor
    toast(`${copy.value.noMicroLaunchOk}${result.abRunId ? ` · run_id=${result.abRunId}` : ''}`)
    window.setTimeout(() => void refresh(), 1200)
  } catch (e) {
    toast((e as Error).message, 'error')
    await refresh()
  } finally {
    noMicroLaunching.value = false
  }
}

onMounted(() => void refresh())
</script>

<template>
  <section class="no-micro-panel">
    <div class="no-micro-panel__header">
      <div>
        <div class="no-micro-panel__title">{{ copy.title }}</div>
        <div class="no-micro-panel__desc">{{ copy.desc }}</div>
      </div>
      <span class="no-micro-panel__badge">Windows</span>
    </div>

    <div class="no-micro-panel__status" :class="{ 'no-micro-panel__status--ok': doctor?.launchReady }">
      <div class="no-micro-panel__state">{{ stateText }}</div>
      <div v-if="metaText" class="no-micro-panel__meta">{{ metaText }}</div>
      <div class="no-micro-panel__last">{{ lastText }}</div>
      <div class="no-micro-panel__log-hint">{{ copy.logHint }}</div>
      <ul v-if="doctor?.warnings?.length" class="no-micro-panel__warnings">
        <li v-for="warning in doctor.warnings" :key="warning">{{ warning }}</li>
      </ul>
    </div>

    <div class="no-micro-panel__actions">
      <AppButton variant="secondary" :disabled="busy" @click="refresh">
        {{ loading ? copy.checking : copy.doctor }}
      </AppButton>
      <AppButton variant="secondary" :disabled="busy || !normalReady" @click="launchNormal">
        {{ normalLaunching ? copy.normalLaunching : copy.normalLaunch }}
      </AppButton>
      <AppButton variant="primary" :disabled="busy || !doctor?.launchReady" @click="launchNoMicro">
        {{ noMicroLaunching ? copy.noMicroLaunching : copy.noMicroLaunch }}
      </AppButton>
    </div>
  </section>
</template>

<style scoped>
.no-micro-panel {
  display: grid;
  gap: var(--space-4);
  padding: var(--space-5);
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
  background: var(--surface);
}
.no-micro-panel__header {
  display: flex;
  gap: var(--space-4);
  align-items: flex-start;
  justify-content: space-between;
}
.no-micro-panel__title {
  font-size: var(--fs-lg);
  font-weight: 650;
  color: var(--text);
}
.no-micro-panel__desc {
  max-width: 820px;
  margin-top: var(--space-2);
  color: var(--text-secondary);
  line-height: 1.55;
}
.no-micro-panel__badge {
  flex-shrink: 0;
  padding: 2px 8px;
  border: 1px solid var(--border-strong);
  border-radius: 999px;
  color: var(--text-secondary);
  font-size: var(--fs-xs);
}
.no-micro-panel__status {
  padding: var(--space-3) var(--space-4);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  background: var(--bg);
}
.no-micro-panel__status--ok {
  border-color: var(--border-strong);
}
.no-micro-panel__state {
  font-weight: 600;
  color: var(--text);
}
.no-micro-panel__meta,
.no-micro-panel__last,
.no-micro-panel__log-hint {
  margin-top: var(--space-2);
  color: var(--text-secondary);
  font-size: var(--fs-sm);
  overflow-wrap: anywhere;
}
.no-micro-panel__log-hint {
  font-family: var(--font-mono);
}
.no-micro-panel__warnings {
  margin: var(--space-3) 0 0;
  padding-left: 18px;
  color: var(--danger);
  font-size: var(--fs-sm);
}
.no-micro-panel__actions {
  display: flex;
  justify-content: flex-end;
  flex-wrap: wrap;
  gap: var(--space-2);
}
</style>
