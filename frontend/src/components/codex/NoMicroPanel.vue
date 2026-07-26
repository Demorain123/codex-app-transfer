<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { i18nState } from '@/i18n'
import AppButton from '@/components/ui/AppButton.vue'
import { useToast } from '@/composables/useToast'
import { useConfirm } from '@/composables/useConfirm'
import {
  getNoMicroDoctor,
  launchCodexNoMicro,
  type NoMicroDoctor,
} from '@/api/noMicro'

const { show: toast } = useToast()
const { confirm } = useConfirm()
const doctor = ref<NoMicroDoctor | null>(null)
const loading = ref(false)
const launching = ref(false)

const zh = computed(() => i18nState.locale === 'zh')
const copy = computed(() =>
  zh.value
    ? {
        title: 'Codex No Micro（实验性）',
        desc: '仅本次从 Transfer 启动 Codex 时，阻止 Work Louder / Codex Micro 设备模块加载，尝试规避 serialport 原生模块造成的卡顿。不修改 AppX、app.asar、账号、会话或项目；普通 Codex 入口保持原样。',
        doctor: '兼容性检查',
        checking: '检查中…',
        launch: 'No Micro 启动',
        launching: '启动中…',
        ready: '环境兼容，可以进行 No Micro 实验启动。',
        running: '环境兼容，但 Codex 仍在运行。请先从 Codex 菜单完全退出，再点击启动。',
        incompatible: '当前 Codex / Node 环境未通过兼容性检查，已禁止注入。',
        unknown: '暂时无法确认环境状态。请重新检查。',
        confirmTitle: '以 No Micro 模式启动 Codex？',
        confirmMessage:
          '这是实验性旁路启动。它只拦截 @worklouder/device-kit-oai，并在注入失败时尝试清理本次自己创建的进程。请先确保普通 Codex 已完全退出。普通启动方式不会被替换。',
        confirmLabel: '开始实验启动',
        launchOk: 'No Micro 注入已验证，Codex 已恢复运行。请与普通启动做 A/B 对照。',
        lastSuccess: '最近一次：注入成功',
        lastFailed: '最近一次：注入失败',
        never: '尚无 No Micro 启动记录',
        unsupported: '当前平台暂不支持（仅 Windows Store/MSIX Codex）。',
      }
    : {
        title: 'Codex No Micro (experimental)',
        desc: 'For this Transfer-launched Codex session only, block the Work Louder / Codex Micro device module to test whether native serialport initialization is causing stalls. AppX, app.asar, accounts, sessions and projects are not modified; the normal Codex launcher remains untouched.',
        doctor: 'Compatibility check',
        checking: 'Checking…',
        launch: 'Launch No Micro',
        launching: 'Launching…',
        ready: 'Environment is compatible and ready for an experimental No Micro launch.',
        running: 'Compatible, but Codex is still running. Fully quit Codex first, then launch again.',
        incompatible: 'This Codex / Node environment did not pass compatibility checks, so injection is blocked.',
        unknown: 'Environment state is not yet known. Run the check again.',
        confirmTitle: 'Launch Codex in No Micro mode?',
        confirmMessage:
          'This is an experimental side-path launcher. It only intercepts @worklouder/device-kit-oai and attempts to clean up only the child it created if injection fails. Fully quit normal Codex first. Your normal launch path is not replaced.',
        confirmLabel: 'Start experimental launch',
        launchOk: 'No Micro injection was verified and Codex resumed. Compare it against a normal launch in the same scenario.',
        lastSuccess: 'Last run: injection succeeded',
        lastFailed: 'Last run: injection failed',
        never: 'No No Micro launch has been recorded yet',
        unsupported: 'This feature currently supports Windows Store/MSIX Codex only.',
      },
)

const stateText = computed(() => {
  const d = doctor.value
  if (!d) return copy.value.unknown
  if (!d.supported) return copy.value.unsupported
  if (d.compatible && d.processState === 'running') return copy.value.running
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

async function launch() {
  if (launching.value || !doctor.value?.launchReady) return
  const ok = await confirm({
    title: copy.value.confirmTitle,
    message: copy.value.confirmMessage,
    confirmLabel: copy.value.confirmLabel,
  })
  if (!ok) return
  launching.value = true
  try {
    const result = await launchCodexNoMicro()
    doctor.value = result.doctor
    toast(copy.value.launchOk)
    window.setTimeout(() => void refresh(), 1200)
  } catch (e) {
    toast((e as Error).message, 'error')
    await refresh()
  } finally {
    launching.value = false
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
      <ul v-if="doctor?.warnings?.length" class="no-micro-panel__warnings">
        <li v-for="warning in doctor.warnings" :key="warning">{{ warning }}</li>
      </ul>
    </div>

    <div class="no-micro-panel__actions">
      <AppButton
        variant="secondary"
        :disabled="loading || launching"
        @click="refresh"
      >
        {{ loading ? copy.checking : copy.doctor }}
      </AppButton>
      <AppButton
        variant="primary"
        :disabled="launching || loading || !doctor?.launchReady"
        @click="launch"
      >
        {{ launching ? copy.launching : copy.launch }}
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
.no-micro-panel__last {
  margin-top: var(--space-2);
  color: var(--text-secondary);
  font-size: var(--fs-sm);
  overflow-wrap: anywhere;
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
  gap: var(--space-2);
}
</style>
