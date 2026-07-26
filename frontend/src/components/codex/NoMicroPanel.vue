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
const processStateKnown = computed(
  () => doctor.value?.processState === 'not-running' || doctor.value?.processState === 'running',
)
const normalReady = computed(
  () =>
    !!doctor.value?.supported &&
    !!doctor.value?.packageFound &&
    !!doctor.value?.executablePath &&
    processStateKnown.value,
)
const noMicroReady = computed(
  () => !!doctor.value?.supported && !!doctor.value?.compatible && processStateKnown.value,
)

const zh = computed(() => i18nState.locale === 'zh')
const copy = computed(() =>
  zh.value
    ? {
        title: 'Codex No Micro A/B（实验性）',
        desc: 'r23 的 A/B 直接复用已验证正常的“重启 Codex App”流程：A 使用相同配置/代理/启动路径并正常加载 Micro；B 使用相同准备与关闭/清理流程，只在最后一步改为 No Micro 注入。两边都会把 [codex-ab]、run_id、mode 和阶段写入同一份 proxy 日志。',
        doctor: '兼容性检查',
        checking: '检查中…',
        normalLaunch: '普通启动（A）',
        normalLaunching: 'A 启动中…',
        noMicroLaunch: 'No Micro 启动（B）',
        noMicroLaunching: 'B 启动中…',
        ready: '环境兼容，可以进行 A/B。Codex 即使正在运行也可以点击；r23 会先复用原“重启 Codex App”的安全关闭/清理流程。',
        running: 'Codex 当前正在运行；可以直接开始下一轮，r23 会先按原“重启 Codex App”流程关闭并重新启动。',
        incompatible: 'No Micro 注入兼容性未通过；A 仍可用于验证原“重启 Codex App”对照路径。',
        unknown: '无法可靠确认 Codex 进程状态。为避免误操作，A/B 暂时禁用，请重新兼容性检查。',
        normalConfirmTitle: '普通启动 Codex（A）？',
        normalConfirmMessage:
          'A 会复用原有“重启 Codex App”的配置同步、关闭/清理和正常启动路径，Micro 正常加载；额外只写入 mode=normal 的 A/B 日志标识。',
        normalConfirmLabel: '启动 A',
        noMicroConfirmTitle: '以 No Micro 模式启动 Codex（B）？',
        noMicroConfirmMessage:
          'B 会复用与 A 相同的配置同步和关闭/清理流程，只把最终启动替换为 No Micro 注入（拦截 @worklouder/device-kit-oai）；并写入 mode=no-micro 标识。',
        noMicroConfirmLabel: '启动 B',
        normalLaunchOk: '普通 A 已按原重启流程启动并写入日志标识',
        noMicroLaunchOk: 'No Micro B 注入已验证并写入日志标识',
        lastSuccess: '最近一次 B：注入成功',
        lastFailed: '最近一次 B：注入失败',
        never: '尚无 No Micro B 启动记录',
        unsupported: '当前平台暂不支持（仅 Windows Store/MSIX Codex）。',
        logHint: '日志关键字：[codex-ab]。A：mode=normal + environment_ready + launch_success；B：mode=no-micro + environment_ready + injection_success。每轮 run_id 独立。',
      }
    : {
        title: 'Codex No Micro A/B (experimental)',
        desc: 'r23 reuses the proven Restart Codex App pipeline for both sides. A keeps the same config/proxy/restart path with Micro enabled; B uses the same preparation and quit/reap path and changes only the final launcher to No Micro. Both write [codex-ab] run_id/mode/phase markers to the same proxy log.',
        doctor: 'Compatibility check',
        checking: 'Checking…',
        normalLaunch: 'Normal launch (A)',
        normalLaunching: 'Launching A…',
        noMicroLaunch: 'No Micro launch (B)',
        noMicroLaunching: 'Launching B…',
        ready: 'Environment is compatible and ready for A/B. Codex may already be running; r23 will reuse the legacy safe quit/restart flow first.',
        running: 'Codex is currently running. You may start the next run directly; r23 will first reuse the legacy safe quit/restart flow.',
        incompatible: 'No Micro compatibility did not pass; A can still validate the legacy Restart Codex App control path.',
        unknown: 'Codex process state cannot be verified reliably. A/B is disabled until compatibility is checked again.',
        normalConfirmTitle: 'Launch normal Codex (A)?',
        normalConfirmMessage:
          'A reuses the existing Restart Codex App config sync, safe quit/reap, and normal launch path with Micro enabled. The only addition is an explicit mode=normal A/B log marker.',
        normalConfirmLabel: 'Launch A',
        noMicroConfirmTitle: 'Launch Codex with No Micro (B)?',
        noMicroConfirmMessage:
          'B reuses the same config sync and safe quit/reap path as A, but replaces only the final launcher with the No Micro interception for @worklouder/device-kit-oai. It writes a mode=no-micro marker.',
        noMicroConfirmLabel: 'Launch B',
        normalLaunchOk: 'Normal A launched through the legacy restart path and its marker was written',
        noMicroLaunchOk: 'No Micro B injection verified and its marker was written',
        lastSuccess: 'Last B: injection succeeded',
        lastFailed: 'Last B: injection failed',
        never: 'No No Micro B launch has been recorded yet',
        unsupported: 'This feature currently supports Windows Store/MSIX Codex only.',
        logHint: 'Log key: [codex-ab]. A: mode=normal + environment_ready + launch_success. B: mode=no-micro + environment_ready + injection_success. Every run has a unique run_id.',
      },
)

const stateText = computed(() => {
  const d = doctor.value
  if (!d) return copy.value.unknown
  if (!d.supported) return copy.value.unsupported
  if (!processStateKnown.value) return copy.value.unknown
  if (!d.compatible) return copy.value.incompatible
  if (d.processState === 'running') return copy.value.running
  return copy.value.ready
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
  if (busy.value || !noMicroReady.value) return
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

    <div class="no-micro-panel__status" :class="{ 'no-micro-panel__status--ok': noMicroReady }">
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
      <AppButton variant="primary" :disabled="busy || !noMicroReady" @click="launchNoMicro">
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
