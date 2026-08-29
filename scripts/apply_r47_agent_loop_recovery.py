from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CHAIN = ROOT / "src-tauri/src/admin/handlers/chain_health.rs"
PAGE = ROOT / "frontend/src/pages/ProxyPage.vue"
DIST = ROOT / "frontend/dist"
INDEX = DIST / "index.html"
STAMP = DIST / ".cas-r47-agent-loop-recovery-ui"
MARKER = "CAS-R47-AGENT-LOOP-RECOVERY"


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if old not in text:
        raise SystemExit(f"r47 agent-loop recovery anchor missing: {label}")
    return text.replace(old, new, 1)


# -----------------------------------------------------------------------------
# Backend diagnosis: the runtime sanitizer emits structured event names such as
# `event=agent_loop_died`. Older builds also emitted `failed_to_start_turn` or the
# raw English phrase. Treat all of them as the same local Codex turn-start class.
# -----------------------------------------------------------------------------
text = CHAIN.read_text(encoding="utf-8")
if MARKER not in text:
    old_start = '''        let start_failed = recent_log_age_r37("failed_to_start_turn", 5 * 60).is_some()
            || recent_log_age_r37("agent loop died unexpectedly", 5 * 60).is_some();
'''
    new_start = '''        // CAS-R47-AGENT-LOOP-RECOVERY
        // Current sanitized runtime logs use structured event=agent_loop_died; keep
        // the older event/text spellings for backward-compatible evidence parsing.
        let start_failed = recent_log_age_r37("failed_to_start_turn", 5 * 60).is_some()
            || recent_log_age_r37("agent_loop_died", 5 * 60).is_some()
            || recent_log_age_r37("agent loop died unexpectedly", 5 * 60).is_some();
'''
    text = replace_once(text, old_start, new_start, "structured agent_loop_died detector")

    old_layer = '''        if start_failed {
            return HealthLayer::new(
                "error",
                "fault_session_state",
                "Codex 本地 Turn/agent loop 状态异常是当前最强证据",
            )
            .fact(format!("session_code={}", session.code));
        }
'''
    new_layer = '''        if start_failed {
            return HealthLayer::new(
                "error",
                "fault_codex_agent_loop",
                "Codex 本地 agent loop / Turn 启动失败；请求尚未进入 provider/upstream",
            )
            .fact(format!("session_code={}", session.code))
            .fact("local_runtime_event=agent_loop_start_failure");
        }
'''
    text = replace_once(text, old_layer, new_layer, "agent-loop diagnosis code")

    recommendation_anchor = '''        "fault_session_state" => out.push(
            "检测到 failed_to_start_turn/agent-loop 类本地状态异常：基础设施重启不是首选，优先新建或 fork 会话验证。".into(),
        ),
'''
    recommendation = '''        "fault_codex_agent_loop" => out.push(
            "检测到 Codex 本地 agent loop / Turn 启动失败，且尚无模型请求进入 provider：优先只重启 Codex Desktop 一次；不要重启健康的 Transfer、Docker 或网关。重启后先用一条短任务验证。".into(),
        ),
''' + recommendation_anchor
    text = replace_once(text, recommendation_anchor, recommendation, "agent-loop recommendation")

    # r46 generated trees have evolved around the session/context match list. Anchor on
    # the stable upstream-rate-limit branch instead of requiring an exact historical block.
    classify_anchor = '''    if snapshot.upstream.code == "upstream_rate_limited" {
        return "upstream_rate_limited";
    }
'''
    classify = '''    if snapshot.diagnosis.code == "fault_codex_agent_loop" {
        return "codex_agent_loop_failure";
    }
''' + classify_anchor
    text = replace_once(text, classify_anchor, classify, "agent-loop recovery classification")

    recovery_anchor = '''        "session_or_context_failure" => {
'''
    recovery_guard = '''        "codex_agent_loop_failure" => {
            actions.push(RecoveryAction::skipped(
                "use_targeted_codex_restart",
                "Codex 本地 agent loop/Turn 启动失败不应触发 provider、Docker 或网关重启；请使用页面上的“重启 Codex（agent loop）”专用动作",
            ));
        }
''' + recovery_anchor
    text = replace_once(text, recovery_anchor, recovery_guard, "agent-loop generic-recovery guard")

    CHAIN.write_text(text, encoding="utf-8")
    print("R47 AGENT-LOOP BACKEND DIAGNOSIS PASS")
else:
    print("r47 agent-loop backend diagnosis already applied")


# -----------------------------------------------------------------------------
# Frontend: expose a dedicated one-attempt Codex restart. It uses the existing
# /api/desktop/restart-codex-app path, so it preserves Transfer's normal desktop
# preparation/reinjection and, in r47, the custom TEMP launch setting as well.
# It never calls the generic chain-recovery endpoint.
# -----------------------------------------------------------------------------
text = PAGE.read_text(encoding="utf-8")
ui_changed = False
if MARKER not in text:
    import_anchor = "import { useToast } from '@/composables/useToast'\n"
    if "restartCodexApp" not in text:
        text = replace_once(
            text,
            import_anchor,
            import_anchor + "import { restartCodexApp } from '@/api/desktop'\n",
            "restartCodexApp import",
        )

    state_anchor = "const chainLayers = computed(() => {\n"
    state = r'''// CAS-R47-AGENT-LOOP-RECOVERY
const agentLoopRestarting = ref(false)
const agentLoopRestartAttemptSignature = ref<string | null>(null)
const codexAgentLoopDetected = computed(() =>
  chainHealth.value?.diagnosis.code === 'fault_codex_agent_loop' ||
  chainHealth.value?.session.code === 'fault_codex_agent_loop',
)
const agentLoopFaultSignature = computed(() => {
  if (!codexAgentLoopDetected.value || !chainHealth.value) return ''
  const h = chainHealth.value
  return [h.diagnosis.code, h.session.code, h.codex.code, h.mcp.code].join('|')
})
const agentLoopRestartLocked = computed(() =>
  !!agentLoopFaultSignature.value &&
  agentLoopRestartAttemptSignature.value === agentLoopFaultSignature.value,
)

async function onRestartCodexForAgentLoop() {
  if (agentLoopRestarting.value) return
  if (agentLoopRestartLocked.value) {
    toast('同一 agent-loop 故障已经定向重启过一次。请先查看结果；状态没有变化时不要连续重启。', 'info')
    return
  }
  const ok = window.confirm(
    '针对 Codex 本地 agent loop / Turn 启动失败执行一次定向重启。\n\n' +
      '可能执行：关闭并重新启动 Codex Desktop，并重新应用 Transfer 的正常启动期配置。\n\n' +
      '明确不会：不会重启 Docker/网关，不会切 provider/模型，不会删除、rollback、compact 会话，也不会修改 workspace 文件。\n\n' +
      '继续吗？',
  )
  if (!ok) return

  const attempted = agentLoopFaultSignature.value
  agentLoopRestarting.value = true
  try {
    await restartCodexApp()
    agentLoopRestartAttemptSignature.value = attempted
    toast('Codex 已针对 agent-loop 故障定向重启。请先在原会话/任务发送一条很短的测试；不要同时切模型或 compact。', 'info')
    window.setTimeout(() => void loadChainHealth(true), 3000)
  } catch (e) {
    toast((e as Error).message || 'Codex 定向重启失败', 'error')
  } finally {
    agentLoopRestarting.value = false
  }
}

'''
    text = replace_once(text, state_anchor, state + state_anchor, "agent-loop restart state")

    # r46 explainability is expected in the generated baseline. Tell the opaque/generic
    # repair guide to defer to the dedicated Codex-only action for this diagnosis.
    guide_anchor = "  if (['fault_session_scoped', 'fault_session_state', 'fault_compaction_context'].includes(h.diagnosis.code)) {\n"
    guide = r'''  if (h.diagnosis.code === 'fault_codex_agent_loop') {
    return {
      mode: 'advice', canRun: false, label: '使用 Codex 定向重启', title: '适用：Codex 本地 agent loop / Turn 启动失败',
      summary: '当前失败发生在模型请求形成之前。请使用旁边的“重启 Codex（agent loop）”，不要把它当 provider、Docker 或网关故障处理。',
      willDo: '专用动作只重启 Codex Desktop 一次，并重新应用正常的 Transfer 启动期配置。',
      wontDo: '不会重启 Docker/网关，不会切 provider/模型，不会删除、回退或 compact 会话，不会修改 workspace。',
    }
  }

'''
    text = replace_once(text, guide_anchor, guide + guide_anchor, "explainability agent-loop guide")

    actions_anchor = '        <div class="chain-health__actions">\n'
    button = r'''          <button
            v-if="codexAgentLoopDetected"
            class="chain-health__button chain-health__button--repair"
            :disabled="agentLoopRestarting || agentLoopRestartLocked"
            :title="agentLoopRestartLocked ? '同一故障已经定向重启过一次，请先查看结果' : '只重启 Codex Desktop；不碰 provider / Docker / 网关 / 会话历史 / workspace'"
            @click="onRestartCodexForAgentLoop"
          >
            <IconRefreshCw :class="{ 'is-spinning': agentLoopRestarting }" />
            {{ agentLoopRestartLocked ? '已重启，先验证' : '重启 Codex（agent loop）' }}
          </button>
'''
    text = replace_once(text, actions_anchor, actions_anchor + button, "agent-loop dedicated button")

    PAGE.write_text(text, encoding="utf-8")
    ui_changed = True
    print("R47 AGENT-LOOP TARGETED RESTART UI PASS")
else:
    print("r47 agent-loop targeted restart UI already applied")

# A UI overlay can land after the earlier r47 custom-temp dist stamp already exists.
# Invalidate index.html under a separate stamp exactly once so the next FAST build cannot
# accidentally embed stale ProxyPage assets.
DIST.mkdir(parents=True, exist_ok=True)
if not STAMP.exists():
    if INDEX.is_file():
        INDEX.unlink()
        print("r47 agent-loop UI: invalidated stale frontend index once")
    STAMP.write_text("r47 agent-loop recovery UI requires rebuilt frontend assets\n", encoding="utf-8")
    print("R47 AGENT-LOOP FRONTEND INVALIDATE-ONCE PASS")
elif ui_changed:
    print("r47 agent-loop UI changed while invalidation stamp already existed")
else:
    print("r47 agent-loop frontend invalidation already recorded; SKIP")

# Cheap structural invariants only; real Windows behavior remains the primary proof.
chain = CHAIN.read_text(encoding="utf-8")
page = PAGE.read_text(encoding="utf-8")
for marker in [
    "event=agent_loop_died",
    'recent_log_age_r37("agent_loop_died"',
    '"fault_codex_agent_loop"',
    'return "codex_agent_loop_failure"',
    "use_targeted_codex_restart",
]:
    if marker not in chain:
        raise SystemExit(f"r47 agent-loop backend invariant missing: {marker}")
for marker in [
    "CAS-R47-AGENT-LOOP-RECOVERY",
    "restartCodexApp",
    "codexAgentLoopDetected",
    "onRestartCodexForAgentLoop",
    "重启 Codex（agent loop）",
]:
    if marker not in page:
        raise SystemExit(f"r47 agent-loop UI invariant missing: {marker}")

print("R47 AGENT-LOOP RECOVERY HOTFIX PASS")
print("- recognizes sanitized event=agent_loop_died and legacy failed-to-start spellings")
print("- classifies the fault before provider/upstream")
print("- dedicated recovery restarts Codex only, one attempt per unchanged fault signature")
print("- no Docker/gateway/provider/model/session-history/workspace mutation")
