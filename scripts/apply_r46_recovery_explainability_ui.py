from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PAGE = ROOT / "frontend/src/pages/ProxyPage.vue"
MARKER = "CAS-R46-RECOVERY-EXPLAINABILITY-UI"

text = PAGE.read_text(encoding="utf-8")
if MARKER in text:
    print("r46 recovery explainability UI already applied")
    raise SystemExit(0)


def replace_once(old: str, new: str, label: str) -> None:
    global text
    if old not in text:
        raise SystemExit(f"r46 recovery explainability: anchor missing: {label}")
    text = text.replace(old, new, 1)


# The r46 recovery UI materializer owns these imports. Add one neutral information icon.
replace_once(
    "import IconXCircle from '~icons/lucide/x-circle'\n",
    "import IconXCircle from '~icons/lucide/x-circle'\nimport IconInfo from '~icons/lucide/info'\n",
    "IconXCircle import",
)

# Explainability state is intentionally derived from the same layer/code values shown in
# Chain Health. It does not probe the network or mutate anything.
state_anchor = "// CAS-R46-MODEL-SWITCH-OLD-THREAD-RECOVERY-UI\nconst threadRecoveryOpen"
state_code = r'''// CAS-R46-RECOVERY-EXPLAINABILITY-UI
// "尝试修复" must not be an opaque retry button. Describe its safe coverage before
// execution and suppress repeated clicks while the exact fault signature is unchanged.
type ChainRepairGuideMode = 'repair' | 'limited' | 'advice' | 'loading'
interface ChainRepairGuide {
  mode: ChainRepairGuideMode
  canRun: boolean
  label: string
  title: string
  summary: string
  willDo: string
  wontDo: string
}

const chainRepairLastAttemptSignature = ref<string | null>(null)
const chainRepairSignature = computed(() => {
  const h = chainHealth.value
  if (!h) return ''
  return [
    h.overall,
    h.diagnosis.code,
    h.transfer.code,
    h.gateway.code,
    h.runtime.layer.code,
    h.account.code,
    h.upstream.code,
    h.session.code,
    h.mcp.code,
  ].join('|')
})

const chainRepairGuide = computed<ChainRepairGuide>(() => {
  const h = chainHealth.value
  if (!h) {
    return {
      mode: 'loading', canRun: false, label: '等待诊断', title: '“尝试修复”正在等待健康检查',
      summary: '先读取当前故障分类，再决定是否存在安全的自动动作。',
      willDo: '只读等待健康检查完成。',
      wontDo: '不会在分类未知时重启服务。',
    }
  }

  if (h.transfer.code === 'transfer_stopped') {
    return {
      mode: 'repair', canRun: true, label: '尝试修复', title: '适用：Transfer 本地转发器未启动',
      summary: '当前有明确的本地可修复证据。按钮会尝试重新建立 Transfer 监听与 provider 解析器。',
      willDo: '启动 Transfer；随后重新检查链路。',
      wontDo: '不会修改账号、模型、会话历史、Docker 数据卷或 workspace 文件。',
    }
  }

  if (h.runtime.layer.code === 'docker_stack_failed') {
    return {
      mode: 'repair', canRun: true, label: '尝试修复', title: '适用：目标 Docker 服务明确异常',
      summary: '只有目标容器退出、重启、unhealthy 或网关明确不可达时才允许自动重启目标容器。',
      willDo: '必要时只重启承载当前活动端口的目标容器，并刷新 Transfer。',
      wontDo: '不会重启整个 Docker Desktop，不会删除容器/卷/数据库，也不会改账号。',
    }
  }

  if ([
    'gateway_dns_failed', 'gateway_dns_timeout', 'gateway_dns_empty',
    'gateway_tcp_timeout', 'gateway_tcp_refused',
    'gateway_http_timeout', 'gateway_http_connect_error', 'gateway_http_5xx',
  ].includes(h.gateway.code)) {
    return {
      mode: 'repair', canRun: true, label: '尝试修复', title: '适用：本地网关连接存在明确故障',
      summary: '会根据容器状态决定是否有证据支持重启目标容器；无证据时只刷新 Transfer。',
      willDo: '最多执行目标容器的定向 restart + Transfer 刷新，然后重新检查。',
      wontDo: '不会把账号额度、旧会话 400 或真正上游故障误当成本地容器故障强行重启。',
    }
  }

  if (h.account.code === 'account_pool_exhausted') {
    return {
      mode: 'advice', canRun: false, label: '此故障不适用', title: '不适用：账号池无可用账号',
      summary: '重启 Transfer、Sub2API 或 Docker 不会补充额度/账号，因此禁止把“尝试修复”当作重试按钮。',
      willDo: '请等待冷却/额度恢复，或在 Sub2API 补充可用账号。',
      wontDo: '不会自动发送模型请求，也不会通过重复重启碰运气。',
    }
  }

  if (['account_quota_elevated', 'account_quota_near_exhaustion'].includes(h.account.code)) {
    return {
      mode: 'advice', canRun: false, label: '此故障不适用', title: '不适用：额度预警',
      summary: '额度消耗不是本地服务故障，当前没有安全自动修复动作。',
      willDo: '建议减少无意义重试并准备备用账号/模型。',
      wontDo: '不会为额度预警重启健康的 Transfer、Sub2API 或 Docker。',
    }
  }

  if (['fault_session_scoped', 'fault_session_state', 'fault_compaction_context'].includes(h.diagnosis.code)) {
    return {
      mode: 'advice', canRun: false, label: '改用旧会话恢复', title: '不适用：当前更像 thread/session 局部故障',
      summary: '普通“尝试修复”不会清理或回退会话历史。r46 应先使用“旧会话恢复”做只读预览。',
      willDo: '使用“旧会话恢复”定位 thread；确认后可备份并单步回退 1 轮，或创建恢复副本。',
      wontDo: '不会通过重启 healthy 网关来掩盖持续 400 / failed compaction。',
    }
  }

  if (h.upstream.code === 'upstream_rate_limited') {
    return {
      mode: 'advice', canRun: false, label: '此故障不适用', title: '不适用：真实上游 429 / 冷却',
      summary: '这是账号/速率/冷却问题，连续点击修复只会增加抖动，不能消除 429。',
      willDo: '等待冷却并检查账号池；稍后用一次小请求验证。',
      wontDo: '不会自动重试真实模型请求，不会重启健康容器。',
    }
  }

  if ([
    'upstream_bad_gateway', 'upstream_service_unavailable', 'upstream_gateway_timeout',
    'upstream_5xx', 'upstream_transport_failed',
  ].includes(h.upstream.code)) {
    return {
      mode: 'limited', canRun: true, label: '刷新 Transfer（有限尝试）', title: '有限适用：请求已到达真实上游后失败',
      summary: '此按钮最多刷新 Transfer 的监听/解析器快照；若真正上游或账号池仍失败，它不会“修好”上游。',
      willDo: '刷新 Transfer 后重新检查本地链路。',
      wontDo: '不会自动重启 healthy Sub2API，不会改账号，也不会连续重复发送模型请求。',
    }
  }

  if (['mcp_process_explosion', 'mcp_process_count_high', 'mcp_guard_inventory_failed'].includes(h.mcp.code)) {
    return {
      mode: 'advice', canRun: false, label: '此故障不适用', title: '不适用：MCP/helper 进程异常',
      summary: '“尝试修复”不是 MCP 进程清理器。应先查看 MCP 层明细，并按 Exit Guard/退出 Codex 的路径处理。',
      willDo: '先查看 MCP/helper 进程数量、重复组和 Exit Guard 结果。',
      wontDo: '不会为了 MCP 异常盲目重启网关或反复刷新 Transfer。',
    }
  }

  if (['ok', 'idle', 'unknown'].includes(h.overall)) {
    return {
      mode: 'advice', canRun: false, label: '当前无需修复', title: '当前没有足够证据支持自动修复',
      summary: '健康检查未识别到属于“尝试修复”覆盖范围的明确本地故障。',
      willDo: '可点击“立即检查”刷新诊断，或查看明细/日志。',
      wontDo: '不会在证据不足时进行重启或配置修改。',
    }
  }

  return {
    mode: 'advice', canRun: false, label: '无安全自动动作', title: '检测到异常，但不在安全自动修复覆盖范围',
    summary: '请查看故障归因与分层明细，不要反复点击按钮碰运气。',
    willDo: '保留现场并根据故障层采取针对性操作。',
    wontDo: '不会执行未经证据支持的重启、会话回退或真实请求重试。',
  }
})

const chainRepairSameFaultLocked = computed(() => {
  const signature = chainRepairSignature.value
  return !!signature && chainRepairLastAttemptSignature.value === signature
})

const chainRepairButtonLabel = computed(() => {
  if (chainRepairSameFaultLocked.value) return '已尝试，先查看结果'
  return chainRepairGuide.value.label
})

const threadRecoveryRecommended = computed(() => {
  const code = chainHealth.value?.diagnosis.code
  return !!code && ['fault_session_scoped', 'fault_session_state', 'fault_compaction_context'].includes(code)
})

'''
replace_once(state_anchor, state_code + state_anchor, "r46 recovery state anchor")

# Replace the old opaque handler with an explicit plan confirmation + same-fault lock.
old_handler = r'''// CAS-R36-SAFE-RECOVERY: only runs after an explicit click. No model inference
// request is generated by the recovery path.
async function onRecoverChain() {
  if (chainRecovering.value) return
  chainRecovering.value = true
  try {
    const result = await recoverChainHealth()
    chainRecovery.value = result.recovery
    chainHealth.value = result.health
    toast(t('chainHealth.recoveryComplete'), 'info')
  } catch (e) {
    toast((e as Error).message || t('chainHealth.recoveryFailed'), 'error')
  } finally {
    chainRecovering.value = false
  }
}
'''
new_handler = r'''// CAS-R36-SAFE-RECOVERY + CAS-R46-RECOVERY-EXPLAINABILITY-UI
// Only runs after an explicit click. No model inference request is generated by the
// recovery path. r46 additionally requires an understood coverage class and blocks an
// unchanged fault signature after one attempt to prevent restart/retry loops.
async function onRecoverChain() {
  if (chainRecovering.value) return
  const guide = chainRepairGuide.value
  if (!guide.canRun) {
    toast(`${guide.title}：${guide.summary}`, 'info')
    return
  }
  if (chainRepairSameFaultLocked.value) {
    toast('同一故障状态已经执行过一次修复。请先查看修复报告/日志并点击“立即检查”；状态没有变化时不要重复执行。', 'info')
    return
  }

  const confirmed = window.confirm(
    `“${guide.label}”执行说明\n\n` +
      `本次判断：${guide.title}\n${guide.summary}\n\n` +
      `可能执行：${guide.willDo}\n\n` +
      `明确不会：${guide.wontDo}\n\n` +
      '同一故障状态执行一次后会锁定，直到健康检查观察到状态变化。\n\n继续吗？',
  )
  if (!confirmed) return

  const attemptedSignature = chainRepairSignature.value
  chainRecovering.value = true
  try {
    const result = await recoverChainHealth()
    chainRecovery.value = result.recovery
    chainHealth.value = result.health
    chainRepairLastAttemptSignature.value = attemptedSignature
    toast(t('chainHealth.recoveryComplete'), 'info')
  } catch (e) {
    // A failed call is not marked as a completed repair attempt; backend cooldown still
    // independently protects rapid retries.
    toast((e as Error).message || t('chainHealth.recoveryFailed'), 'error')
  } finally {
    chainRecovering.value = false
  }
}
'''
replace_once(old_handler, new_handler, "opaque onRecoverChain handler")

# Make the button self-describing even before reading the explanatory cards.
old_button = r'''          <button
            class="chain-health__button chain-health__button--repair"
            :disabled="chainRecovering"
            @click="onRecoverChain"
          >
            <IconWrench :class="{ 'is-spinning': chainRecovering }" />
            {{ t('chainHealth.recover') }}
          </button>
'''
new_button = r'''          <button
            class="chain-health__button chain-health__button--repair"
            :class="`is-${chainRepairGuide.mode}`"
            :disabled="chainRecovering || !chainRepairGuide.canRun || chainRepairSameFaultLocked"
            :title="`${chainRepairGuide.title}。${chainRepairGuide.summary}`"
            @click="onRecoverChain"
          >
            <IconWrench :class="{ 'is-spinning': chainRecovering }" />
            {{ chainRepairButtonLabel }}
          </button>
'''
replace_once(old_button, new_button, "chain repair button")

# r46 old-thread button should say that opening it is a preview, not an immediate rollback.
old_thread_button = r'''          <button
            class="chain-health__button chain-health__button--thread-recovery"
            :disabled="threadRecoveryRunning"
            @click="openThreadRecovery"
          >
            <IconRotateCcw :class="{ 'is-spinning': threadRecoveryRunning }" />
            旧会话恢复
          </button>
'''
new_thread_button = r'''          <button
            class="chain-health__button chain-health__button--thread-recovery"
            :class="{ 'is-recommended': threadRecoveryRecommended }"
            :disabled="threadRecoveryRunning"
            title="针对切模型/compact 后某个旧 thread 持续失败、而新会话正常的局部故障。点击只打开只读预览，不会立即回退。"
            @click="openThreadRecovery"
          >
            <IconRotateCcw :class="{ 'is-spinning': threadRecoveryRunning }" />
            旧会话恢复（先预览）
          </button>
'''
replace_once(old_thread_button, new_thread_button, "old thread recovery button")

# Always-visible descriptions remove the black-box behavior. These sit below the header
# actions and before the layer cards.
grid_anchor = '''      <div class="chain-health__grid">
'''
guides = r'''      <div class="chain-recovery-guides-r46">
        <article class="chain-recovery-guide-r46" :class="`is-${chainRepairGuide.mode}`">
          <div class="chain-recovery-guide-r46__title">
            <IconInfo />
            <strong>{{ chainRepairGuide.title }}</strong>
            <span>{{ chainRepairGuide.canRun ? '可执行' : '仅说明' }}</span>
          </div>
          <p>{{ chainRepairGuide.summary }}</p>
          <small><b>可能执行：</b>{{ chainRepairGuide.willDo }}</small>
          <small><b>明确不会：</b>{{ chainRepairGuide.wontDo }}</small>
          <small v-if="chainRepairSameFaultLocked" class="chain-recovery-guide-r46__lock">
            <b>已锁定：</b>相同故障指纹已经尝试过一次。请先查看修复报告/日志并“立即检查”；只有状态变化后才会重新开放。
          </small>
        </article>

        <article class="chain-recovery-guide-r46 is-thread" :class="{ 'is-recommended': threadRecoveryRecommended }">
          <div class="chain-recovery-guide-r46__title">
            <IconRotateCcw />
            <strong>“旧会话恢复”适用范围</strong>
            <span>{{ threadRecoveryRecommended ? '当前推荐' : '按需使用' }}</span>
          </div>
          <p>针对某个旧 thread 在切换模型 / compact 后持续 400、failed_to_start_turn 或局部状态异常，而同 provider / 模型的新会话仍可工作的情况。</p>
          <small><b>第一步只做：</b>读取最近失败证据、定位 rollout、计算 SHA256；不会立即 rollback。</small>
          <small><b>不适用：</b>429/额度耗尽、Docker/网关故障、MCP/helper 膨胀、所有会话都失败的共享上游故障。</small>
        </article>
      </div>

'''
replace_once(grid_anchor, guides + grid_anchor, "chain health grid")

# Make the recovery panel itself explicit enough that a user cannot mistake the next
# buttons for generic repair actions.
panel_head_anchor = r'''          <p>先只读诊断；执行前自动备份。不会修改 workspace 文件，也不会自动连续回退多轮。</p>
'''
panel_scope = r'''          <p>先只读诊断；执行前自动备份。不会修改 workspace 文件，也不会自动连续回退多轮。</p>
          <div class="thread-recovery-r46__scope">
            <span><b>适用：</b>旧 thread 在切模型/compact 后持续失败，但新会话仍正常；或出现 session/context 局部故障。</span>
            <span><b>不适用：</b>账号 429/额度、Docker/网关、MCP/helper、所有会话共同失败的真正上游故障。</span>
            <span><b>打开本面板：</b>只读，不会回退。只有下面再次确认“同 ID 回退 1 轮”或“创建恢复副本”才会写会话状态。</span>
          </div>
'''
replace_once(panel_head_anchor, panel_scope, "thread recovery panel explanation")

# Styles are deliberately compact: explanation should be visible, but not dominate the
# layer cards on a normal healthy screen.
style_anchor = "</style>"
styles = r'''
/* CAS-R46-RECOVERY-EXPLAINABILITY-UI */
.chain-recovery-guides-r46 {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 10px;
  margin: 0 0 14px;
}
.chain-recovery-guide-r46 {
  display: grid;
  gap: 5px;
  padding: 10px 12px;
  border: 1px solid var(--border-color, #ddd);
  border-radius: 10px;
  background: color-mix(in srgb, currentColor 2.5%, transparent);
}
.chain-recovery-guide-r46.is-repair { border-color: color-mix(in srgb, #22a35a 45%, var(--border-color, #ddd)); }
.chain-recovery-guide-r46.is-limited { border-color: color-mix(in srgb, #d88b00 55%, var(--border-color, #ddd)); }
.chain-recovery-guide-r46.is-advice { opacity: .88; }
.chain-recovery-guide-r46.is-thread.is-recommended { border-color: color-mix(in srgb, #4d7dff 58%, var(--border-color, #ddd)); }
.chain-recovery-guide-r46__title { display: flex; align-items: center; gap: 6px; }
.chain-recovery-guide-r46__title svg { width: 16px; height: 16px; flex: 0 0 auto; }
.chain-recovery-guide-r46__title span {
  margin-left: auto;
  font-size: 11px;
  padding: 2px 7px;
  border-radius: 999px;
  background: color-mix(in srgb, currentColor 8%, transparent);
}
.chain-recovery-guide-r46 p { margin: 0; font-size: 12px; line-height: 1.55; }
.chain-recovery-guide-r46 small { display: block; line-height: 1.5; opacity: .82; }
.chain-recovery-guide-r46__lock { color: #b35b00; opacity: 1 !important; }
.chain-health__button--repair.is-advice,
.chain-health__button--repair.is-loading { opacity: .55; }
.chain-health__button--repair.is-limited { border-style: dashed; }
.chain-health__button--thread-recovery.is-recommended {
  box-shadow: inset 0 0 0 1px color-mix(in srgb, #4d7dff 55%, transparent);
}
.thread-recovery-r46__scope {
  display: grid;
  gap: 4px;
  margin-top: 8px;
  padding: 9px 10px;
  border-radius: 8px;
  background: color-mix(in srgb, #4d7dff 7%, transparent);
  font-size: 12px;
  line-height: 1.5;
}
@media (max-width: 820px) {
  .chain-recovery-guides-r46 { grid-template-columns: 1fr; }
}
'''
if style_anchor not in text:
    raise SystemExit("r46 recovery explainability: </style> missing")
text = text.rsplit(style_anchor, 1)[0] + styles + "\n" + style_anchor + text.rsplit(style_anchor, 1)[1]

for invariant in (
    MARKER,
    "已尝试，先查看结果",
    "旧会话恢复（先预览）",
    "相同故障指纹已经尝试过一次",
    "不适用：MCP/helper 进程异常",
    "第一步只做：",
):
    if invariant not in text:
        raise SystemExit(f"r46 recovery explainability invariant missing: {invariant}")

PAGE.write_text(text, encoding="utf-8")
print("R46 RECOVERY EXPLAINABILITY UI PASS")
