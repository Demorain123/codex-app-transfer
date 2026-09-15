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
        title: 'Codex No Lagging A/B（实验性）',
        desc: 'r73 在 r32 No Lagging 上增加输出观测：B 启动后给 Codex Desktop 每个 assistant/model 输出段加本地时间戳角标；优先使用 Codex 自带 sent-time，缺失时明确回退为“首次本地观察时间”。若当前 renderer 能观察到 token_count 流，还会额外显示 ctx%、输出 token 与 tok/s；拿不到数据就不显示，不会伪造。Micro/Accessory Guard 与 MCP Exit Guard 行为保持不变。',
        doctor: '兼容性检查',
        checking: '检查中…',
        normalLaunch: '普通启动（A）',
        normalLaunching: 'A 启动中…',
        noMicroLaunch: 'No Lagging 启动（B）',
        noMicroLaunching: 'B 启动中…',
        ready: '环境兼容，可以进行 A/B。B 会在原 No Lagging 启动钩子中同时武装 r73 每段输出时间戳；Codex 即使正在运行也可以点击，会先复用原安全关闭/清理流程。',
        running: 'Codex 当前正在运行；可以直接开始下一轮，会先按原“重启 Codex App”流程关闭并重新启动，再武装 r73 输出时间戳。',
        incompatible: 'No Lagging 的 Micro/Accessory Guard 兼容性未通过；A 仍可用于对照。',
        unknown: '无法可靠确认 Codex 进程状态。为避免误操作，A/B 暂时禁用，请重新兼容性检查。',
        normalConfirmTitle: '普通启动 Codex（A）？',
        normalConfirmMessage:
          'A 会复用原有“重启 Codex App”的配置同步、关闭/清理和正常启动路径，Micro 正常加载；额外只写入 mode=normal 的 A/B 日志标识。A 不注入 r73 输出角标，便于与 B 做对照。',
        normalConfirmLabel: '启动 A',
        noMicroConfirmTitle: '以 No Lagging 模式启动 Codex（B）？',
        noMicroConfirmMessage:
          'B 会复用与 A 相同的配置同步和关闭/清理流程；最终启动使用 Micro/Accessory Guard、MCP Exit Guard，并在 Electron renderer 创建时注入 r73 输出观测 runtime：每个 assistant/model 输出段显示本地时间戳角标；token/context/tok/s 仅在确有可观测数据时显示。',
        noMicroConfirmLabel: '启动 B',
        normalLaunchOk: '普通 A 已按原重启流程启动并写入日志标识',
        noMicroLaunchOk: 'No Lagging B：Guard 已验证，r73 每段输出时间戳 runtime 已武装',
        lastSuccess: '最近一次 B：Micro/Accessory Guard 注入成功',
        lastSuccessTelemetry: '最近一次 B：Guard 注入成功 · r73 每段输出时间戳已武装',
        lastFailed: '最近一次 B：Micro/Accessory Guard 注入失败',
        never: '尚无 No Lagging B 启动记录',
        unsupported: '当前平台暂不支持（仅 Windows Store/MSIX Codex）。',
        logHint: '日志关键字：[codex-ab]。B：mode=no-lagging + injection_success。r73 启动状态同时写 outputTelemetry.status=armed/runtime=r73.1；MCP Exit Guard 另写 %LOCALAPPDATA%\\CodexMcpJanitorR32\\events.jsonl。',
      }
    : {
        title: 'Codex No Lagging A/B (experimental)',
        desc: 'r73 adds output observability on top of r32 No Lagging. B adds a local timestamp badge to every assistant/model output segment in Codex Desktop, preferring Codex native sent-time and explicitly falling back to first-local-observation time. When a token_count stream is observable, it also shows ctx%, output tokens and tok/s; unavailable metrics stay hidden rather than guessed. Micro/Accessory Guard and MCP Exit Guard behavior is unchanged.',
        doctor: 'Compatibility check',
        checking: 'Checking…',
        normalLaunch: 'Normal launch (A)',
        normalLaunching: 'Launching A…',
        noMicroLaunch: 'No Lagging launch (B)',
        noMicroLaunching: 'Launching B…',
        ready: 'Environment is compatible and ready for A/B. B also arms the r73 per-output timestamp runtime through the existing No Lagging startup hook.',
        running: 'Codex is currently running. You may start the next run directly; the legacy safe quit/restart flow runs first and then r73 output timestamps are armed.',
        incompatible: 'No Lagging Micro/Accessory Guard compatibility did not pass; A remains available as the control path.',
        unknown: 'Codex process state cannot be verified reliably. A/B is disabled until compatibility is checked again.',
        normalConfirmTitle: 'Launch normal Codex (A)?',
        normalConfirmMessage:
          'A reuses the existing Restart Codex App config sync, safe quit/reap, and normal launch path with Micro enabled. A intentionally does not inject the r73 output badges, so it remains the control path.',
        normalConfirmLabel: 'Launch A',
        noMicroConfirmTitle: 'Launch Codex with No Lagging (B)?',
        noMicroConfirmMessage:
          'B reuses the same config sync and safe quit/reap path as A, adds the Micro/Accessory Guard and MCP Exit Guard, and injects the r73 output-observability runtime into Electron renderers. Every assistant/model output segment gets a local timestamp; token/context/tok/s appear only when real data is observable.',
        noMicroConfirmLabel: 'Launch B',
        normalLaunchOk: 'Normal A launched through the legacy restart path and its marker was written',
        noMicroLaunchOk: 'No Lagging B guards verified; r73 per-output timestamp runtime armed',
        lastSuccess: 'Last B: Micro/Accessory Guard injection succeeded',
        lastSuccessTelemetry: 'Last B: guard succeeded · r73 per-output timestamps armed',
        lastFailed: 'Last B: Micro/Accessory Guard injection failed',
        never: 'No No Lagging B launch has been recorded yet',
        unsupported: 'This feature currently supports Windows Store/MSIX Codex only.',
        logHint: 'Log key: [codex-ab]. B: mode=no-lagging + injection_success. r73 launch state also records outputTelemetry.status=armed/runtime=r73.1. MCP Exit Guard writes %LOCALAPPDATA%\\CodexMcpJanitorR32\\events.jsonl.',
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
    `HID/accessory ×${d.hidMarkerCount}`,
    `gate ×${d.featureGateCount}`,
  ].filter(Boolean)
  return parts.join(' · ')
})

const lastText = computed(() => {
  const last = doctor.value?.lastLaunch as any
  if (!last?.injection?.status) return copy.value.never
  if (last.injection.status === 'success') {
    return last?.outputTelemetry?.status === 'armed' ? copy.value.lastSuccessTelemetry : copy.value.lastSuccess
  }
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
  <section class="no-micro-panel" data-compat="CAS-R73-OUTPUT-TIMESTAMPS">
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