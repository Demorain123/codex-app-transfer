from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HANDLERS = ROOT / "src-tauri/src/admin/handlers/mod.rs"
ADMIN = ROOT / "src-tauri/src/admin/mod.rs"
PROXY_PAGE = ROOT / "frontend/src/pages/ProxyPage.vue"

MARKER = "CAS-R46-MODEL-SWITCH-OLD-THREAD-RECOVERY-UI"


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if old not in text:
        raise SystemExit(f"r46 recovery UI: anchor missing: {label}")
    return text.replace(old, new, 1)


# Backend module registration.
handlers = HANDLERS.read_text(encoding="utf-8")
if "pub mod thread_recovery;" not in handlers:
    handlers = replace_once(
        handlers,
        "pub mod trace_viewer;\n",
        "pub mod trace_viewer;\npub mod thread_recovery; // CAS-R46-MODEL-SWITCH-OLD-THREAD-RECOVERY\n",
        "handlers module",
    )
    HANDLERS.write_text(handlers, encoding="utf-8")

admin = ADMIN.read_text(encoding="utf-8")
if '"/api/thread-recovery/preview"' not in admin:
    anchor = '''        .route(
            "/api/chain-health/recover",
            post(handlers::chain_health::recover_chain),
        )
'''
    routes = anchor + '''        // CAS-R46-MODEL-SWITCH-OLD-THREAD-RECOVERY: local-only, explicit recovery.
        .route(
            "/api/thread-recovery/preview",
            get(handlers::thread_recovery::preview),
        )
        .route(
            "/api/thread-recovery/action",
            post(handlers::thread_recovery::action),
        )
'''
    admin = replace_once(admin, anchor, routes, "admin routes")
    ADMIN.write_text(admin, encoding="utf-8")

page = PROXY_PAGE.read_text(encoding="utf-8")
if MARKER in page:
    print("r46 thread recovery UI already applied")
    raise SystemExit(0)

import_anchor = "import IconWrench from '~icons/lucide/wrench'\n"
page = replace_once(
    page,
    import_anchor,
    '''import IconWrench from '~icons/lucide/wrench'
import IconRotateCcw from '~icons/lucide/rotate-ccw'
import IconShieldCheck from '~icons/lucide/shield-check'
import IconXCircle from '~icons/lucide/x-circle'
import {
  getThreadRecoveryPreview,
  runThreadRecovery,
  type ThreadRecoveryPreview,
  type ThreadRecoveryResult,
} from '@/api/threadRecovery'
''',
    "frontend imports",
)

state_anchor = "// [MOC-261 一-11] 静默丢弃工具诊断(金丝雀):"
state_code = r'''// CAS-R46-MODEL-SWITCH-OLD-THREAD-RECOVERY-UI
const threadRecoveryOpen = ref(false)
const threadRecoveryLoading = ref(false)
const threadRecoveryRunning = ref(false)
const threadRecoveryThreadId = ref('')
const threadRecoveryPreview = ref<ThreadRecoveryPreview | null>(null)
const threadRecoveryResult = ref<ThreadRecoveryResult | null>(null)

function formatRecoveryBytes(bytes?: number | null) {
  if (bytes == null) return '—'
  if (bytes >= 1024 * 1024) return `${(bytes / 1024 / 1024).toFixed(2)} MB`
  if (bytes >= 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${bytes} B`
}

async function loadThreadRecoveryPreview(useTypedId = false) {
  if (threadRecoveryLoading.value) return
  threadRecoveryLoading.value = true
  threadRecoveryResult.value = null
  try {
    const preview = await getThreadRecoveryPreview(
      useTypedId ? threadRecoveryThreadId.value : '',
    )
    threadRecoveryPreview.value = preview
    threadRecoveryThreadId.value = preview.threadId
  } catch (e) {
    threadRecoveryPreview.value = null
    toast((e as Error).message || '旧会话恢复预览失败', 'error')
  } finally {
    threadRecoveryLoading.value = false
  }
}

async function openThreadRecovery() {
  threadRecoveryOpen.value = true
  await loadThreadRecoveryPreview(false)
}

async function runRecoveryAction(action: 'rewindOne' | 'forkPrevious') {
  const preview = threadRecoveryPreview.value
  if (!preview || threadRecoveryRunning.value) return
  const isRewind = action === 'rewindOne'
  const warning = isRewind
    ? `将先完整备份，然后让原会话 ${preview.threadFingerprint} 只回退最新 1 个 persisted turn。\n\n工作区文件不会回滚。每次点击最多只退 1 轮。是否继续？`
    : `将先完整备份，然后创建一个截止到前一 turn 边界的恢复副本。\n\n原会话不会被修改。是否继续？`
  if (!window.confirm(warning)) return

  threadRecoveryRunning.value = true
  try {
    const result = await runThreadRecovery(preview.threadId, action)
    threadRecoveryResult.value = result
    toast(
      isRewind
        ? '同 ID 单步恢复已执行，请先测试原会话的一条短消息'
        : `恢复副本已创建：${result.resultingThreadId}`,
      'info',
    )
    await loadChainHealth(true)
  } catch (e) {
    toast((e as Error).message || '旧会话恢复失败', 'error')
  } finally {
    threadRecoveryRunning.value = false
  }
}

'''
page = replace_once(page, state_anchor, state_code + state_anchor, "frontend state/functions")

button_anchor = '''          <button class="chain-health__button" :disabled="chainLoading" @click="loadChainHealth(true)">
'''
button = '''          <button
            class="chain-health__button chain-health__button--thread-recovery"
            :disabled="threadRecoveryRunning"
            @click="openThreadRecovery"
          >
            <IconRotateCcw :class="{ 'is-spinning': threadRecoveryRunning }" />
            旧会话恢复
          </button>
''' + button_anchor
page = replace_once(page, button_anchor, button, "recovery button")

panel_anchor = '''      <div v-if="chainHealth?.recommendations?.length" class="chain-health__recommendations">
'''
panel = r'''      <div v-if="threadRecoveryOpen" class="thread-recovery-r46">
        <div class="thread-recovery-r46__head">
          <div>
            <strong><IconShieldCheck /> 跨模型旧会话恢复</strong>
            <p>先只读诊断；执行前自动备份。不会修改 workspace 文件，也不会自动连续回退多轮。</p>
          </div>
          <button class="thread-recovery-r46__close" @click="threadRecoveryOpen = false">
            <IconXCircle />
          </button>
        </div>

        <div class="thread-recovery-r46__lookup">
          <input
            v-model="threadRecoveryThreadId"
            class="thread-recovery-r46__input"
            placeholder="完整 thread id；留空/首次打开会自动检测最近失败会话"
            spellcheck="false"
          />
          <button
            class="chain-health__button"
            :disabled="threadRecoveryLoading || !threadRecoveryThreadId.trim()"
            @click="loadThreadRecoveryPreview(true)"
          >
            <IconRefreshCw :class="{ 'is-spinning': threadRecoveryLoading }" />
            读取
          </button>
          <button
            class="chain-health__button"
            :disabled="threadRecoveryLoading"
            @click="loadThreadRecoveryPreview(false)"
          >
            自动检测最近失败
          </button>
        </div>

        <div v-if="threadRecoveryLoading" class="thread-recovery-r46__empty">正在只读分析...</div>
        <template v-else-if="threadRecoveryPreview">
          <div class="thread-recovery-r46__evidence">
            <span><b>会话</b> {{ threadRecoveryPreview.threadFingerprint }}</span>
            <span><b>模型</b> {{ threadRecoveryPreview.evidence.model || '未知' }}</span>
            <span><b>请求类型</b> {{ threadRecoveryPreview.evidence.requestKind || '未知' }}</span>
            <span><b>Raw HTTP</b> {{ threadRecoveryPreview.evidence.rawStatus ?? '—' }}</span>
            <span><b>请求体</b> {{ formatRecoveryBytes(threadRecoveryPreview.evidence.requestBytes) }}</span>
            <span><b>rollout</b> {{ formatRecoveryBytes(threadRecoveryPreview.rolloutBytes) }}</span>
            <span v-if="threadRecoveryPreview.evidence.compactionTrigger">
              <b>compact</b>
              {{ threadRecoveryPreview.evidence.compactionTrigger }} / {{ threadRecoveryPreview.evidence.compactionReason || '—' }}
            </span>
          </div>
          <details class="thread-recovery-r46__details">
            <summary>恢复前安全检查</summary>
            <code>thread={{ threadRecoveryPreview.threadId }}</code>
            <code>rollout_sha256={{ threadRecoveryPreview.rolloutSha256 }}</code>
            <code>{{ threadRecoveryPreview.rolloutPath }}</code>
            <ul>
              <li v-for="item in threadRecoveryPreview.safeguards" :key="item">{{ item }}</li>
            </ul>
          </details>

          <div class="thread-recovery-r46__actions">
            <button
              class="chain-health__button chain-health__button--repair"
              :disabled="threadRecoveryRunning || !threadRecoveryPreview.codexCliFound"
              @click="runRecoveryAction('rewindOne')"
            >
              <IconRotateCcw :class="{ 'is-spinning': threadRecoveryRunning }" />
              同 ID 回退 1 轮（推荐）
            </button>
            <button
              class="chain-health__button"
              :disabled="threadRecoveryRunning || !threadRecoveryPreview.codexCliFound"
              @click="runRecoveryAction('forkPrevious')"
            >
              创建恢复副本（原会话不动）
            </button>
          </div>
          <p v-if="!threadRecoveryPreview.codexCliFound" class="thread-recovery-r46__warning">
            当前未找到 Codex app-server 可执行文件。先启动一次 Codex Desktop，再点“读取”。
          </p>
        </template>

        <div v-if="threadRecoveryResult" class="thread-recovery-r46__result">
          <strong>恢复动作已完成</strong>
          <code>method={{ threadRecoveryResult.method }}</code>
          <code>source={{ threadRecoveryResult.sourceThreadId }}</code>
          <code>result={{ threadRecoveryResult.resultingThreadId }}</code>
          <code v-if="threadRecoveryResult.boundaryTurnId">boundary={{ threadRecoveryResult.boundaryTurnId }}</code>
          <code>backup={{ threadRecoveryResult.backup.directory }}</code>
          <p>{{ threadRecoveryResult.note }}</p>
        </div>
      </div>

''' + panel_anchor
page = replace_once(page, panel_anchor, panel, "recovery panel")

style_anchor = "</style>"
styles = r'''
/* CAS-R46-MODEL-SWITCH-OLD-THREAD-RECOVERY-UI */
.thread-recovery-r46 {
  margin-top: 14px;
  padding: 14px;
  border: 1px solid var(--border-color, #d6d6d6);
  border-radius: 12px;
  background: color-mix(in srgb, var(--bg-secondary, #fff) 94%, #5b8cff 6%);
}
.thread-recovery-r46__head,
.thread-recovery-r46__lookup,
.thread-recovery-r46__actions {
  display: flex;
  align-items: center;
  gap: 8px;
}
.thread-recovery-r46__head { justify-content: space-between; align-items: flex-start; }
.thread-recovery-r46__head strong { display: flex; align-items: center; gap: 6px; }
.thread-recovery-r46__head p { margin: 4px 0 0; opacity: .72; font-size: 12px; }
.thread-recovery-r46__close { border: 0; background: transparent; cursor: pointer; opacity: .7; }
.thread-recovery-r46__lookup { margin-top: 12px; flex-wrap: wrap; }
.thread-recovery-r46__input {
  min-width: 360px;
  flex: 1;
  padding: 8px 10px;
  border: 1px solid var(--border-color, #d6d6d6);
  border-radius: 8px;
  background: var(--bg-primary, #fff);
  color: inherit;
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
}
.thread-recovery-r46__evidence {
  margin-top: 12px;
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
  gap: 8px;
}
.thread-recovery-r46__evidence span,
.thread-recovery-r46__result code,
.thread-recovery-r46__details code {
  padding: 7px 8px;
  border-radius: 7px;
  background: color-mix(in srgb, currentColor 6%, transparent);
  overflow-wrap: anywhere;
}
.thread-recovery-r46__details { margin-top: 10px; font-size: 12px; }
.thread-recovery-r46__details code { display: block; margin-top: 6px; }
.thread-recovery-r46__details ul { margin: 8px 0 0; padding-left: 20px; }
.thread-recovery-r46__actions { margin-top: 12px; flex-wrap: wrap; }
.thread-recovery-r46__result {
  margin-top: 12px;
  display: grid;
  gap: 6px;
  padding: 10px;
  border-radius: 8px;
  background: color-mix(in srgb, #32a852 9%, transparent);
}
.thread-recovery-r46__result p { margin: 4px 0 0; }
.thread-recovery-r46__warning { margin: 8px 0 0; color: #b86b00; }
.thread-recovery-r46__empty { margin-top: 10px; opacity: .7; }
@media (max-width: 720px) {
  .thread-recovery-r46__input { min-width: 100%; }
}
'''
if style_anchor not in page:
    raise SystemExit("r46 recovery UI: </style> missing")
page = page.rsplit(style_anchor, 1)[0] + styles + "\n" + style_anchor + page.rsplit(style_anchor, 1)[1]

if MARKER not in page or "/api/thread-recovery" not in (ROOT / "frontend/src/api/threadRecovery.ts").read_text(encoding="utf-8"):
    raise SystemExit("r46 recovery UI invariant missing")

PROXY_PAGE.write_text(page, encoding="utf-8")
print("R46 THREAD RECOVERY UI/ROUTES PASS")
