from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DIAGNOSTIC = ROOT / "src-tauri/src/admin/handlers/diagnostic.rs"
ADMIN = ROOT / "src-tauri/src/admin/mod.rs"
SYSTEM_API = ROOT / "frontend/src/api/system.ts"
SETTINGS = ROOT / "frontend/src/pages/SettingsPage.vue"
ZH = ROOT / "frontend/src/i18n/zh.ts"
EN = ROOT / "frontend/src/i18n/en.ts"
MARKER = "CAS-R38-CODEX-USAGE-STATUS-UI"

# Backend diagnostic endpoint.
body = DIAGNOSTIC.read_text(encoding="utf-8")
if MARKER not in body:
    anchor = "\n#[cfg(test)]\nmod tests {"
    if anchor not in body:
        raise SystemExit("r38 quota status UI: diagnostic tests anchor missing")
    add = r'''

// CAS-R38-CODEX-USAGE-STATUS-UI
/// `GET /api/diagnostic/codex-quota` — 最近一次 Usage injector 状态。
/// 只暴露布尔/枚举运行态,不包含 prompt、token 内容、账号凭据或 CDP payload。
pub async fn codex_quota_injector_status() -> impl IntoResponse {
    Json(crate::codex_quota_injector::quota_injector_status()).into_response()
}
'''
    body = body.replace(anchor, add + anchor, 1)
    DIAGNOSTIC.write_text(body, encoding="utf-8")

body = ADMIN.read_text(encoding="utf-8")
if "/api/diagnostic/codex-quota" not in body:
    anchor = '''        .route(
            "/api/diagnostic/dropped-tools",
            get(handlers::diagnostic::dropped_tools_status),
        )
'''
    if anchor not in body:
        raise SystemExit("r38 quota status UI: diagnostic route anchor missing")
    route = '''        .route(
            "/api/diagnostic/codex-quota",
            get(handlers::diagnostic::codex_quota_injector_status),
        )
'''
    body = body.replace(anchor, anchor + route, 1)
    ADMIN.write_text(body, encoding="utf-8")

# Frontend API.
body = SYSTEM_API.read_text(encoding="utf-8")
if "CodexQuotaInjectorStatus" not in body:
    body += r'''

// CAS-R38-CODEX-USAGE-STATUS-UI: process-local CDP injection observability.
export interface CodexQuotaInjectorStatus {
  enabled: boolean
  cdpConnected: boolean
  scriptInstalled: boolean
  panelPresent: boolean
  anchorKind: string
  contextSource: 'fiber' | 'aria' | 'unavailable' | string
  conversationIdFound: boolean
  lastError?: string | null
}
export const getCodexQuotaInjectorStatus = () =>
  api<CodexQuotaInjectorStatus>('GET', '/api/diagnostic/codex-quota')
'''
    SYSTEM_API.write_text(body, encoding="utf-8")

# Settings page: poll status and replace the misleading static description.
body = SETTINGS.read_text(encoding="utf-8")
if MARKER not in body:
    old = "import { getAppVersion, checkAppUpdate, installAppUpdate, openExternalUrl } from '@/api/system'"
    new = "import { getAppVersion, checkAppUpdate, installAppUpdate, openExternalUrl, getCodexQuotaInjectorStatus, type CodexQuotaInjectorStatus } from '@/api/system'"
    if old not in body:
        raise SystemExit("r38 quota status UI: system import anchor missing")
    body = body.replace(old, new, 1)

    anchor = "const feedbackOpen = ref(false)\n"
    if anchor not in body:
        raise SystemExit("r38 quota status UI: ref anchor missing")
    body = body.replace(
        anchor,
        anchor
        + '''// CAS-R38-CODEX-USAGE-STATUS-UI\nconst codexQuotaInjectorStatus = ref<CodexQuotaInjectorStatus | null>(null)\nlet codexQuotaStatusTimer: number | undefined\nasync function refreshCodexQuotaInjectorStatus() {\n  try {\n    codexQuotaInjectorStatus.value = await getCodexQuotaInjectorStatus()\n  } catch {\n    codexQuotaInjectorStatus.value = null\n  }\n}\n''',
        1,
    )

    old = '''  refreshSuperpowersStatus()
  mcpRecovery.refresh()
})
'''
    new = '''  refreshSuperpowersStatus()
  mcpRecovery.refresh()
  void refreshCodexQuotaInjectorStatus()
  codexQuotaStatusTimer = window.setInterval(() => void refreshCodexQuotaInjectorStatus(), 3000)
})
onUnmounted(() => {
  if (codexQuotaStatusTimer) window.clearInterval(codexQuotaStatusTimer)
})
'''
    if old not in body:
        raise SystemExit("r38 quota status UI: onMounted tail anchor missing")
    body = body.replace(old, new, 1)

    old = "const codexQuotaEnabled = toggle('codexQuotaEnabled', false)\n"
    new = '''const codexQuotaEnabled = toggle('codexQuotaEnabled', false)
const codexQuotaStatusDescription = computed(() => {
  if (!codexQuotaEnabled.value) return t('settings.codexQuotaEnabledHint')
  const s = codexQuotaInjectorStatus.value
  if (!s) return t('settings.codexQuotaStatusChecking')
  if (!s.cdpConnected) return t('settings.codexQuotaStatusCdpUnavailable')
  if (!s.scriptInstalled) return t('settings.codexQuotaStatusInstalling')
  if (!s.panelPresent) {
    return s.anchorKind === 'none'
      ? t('settings.codexQuotaStatusAnchorMissing')
      : t('settings.codexQuotaStatusWaitingPopup')
  }
  if (s.contextSource === 'unavailable') return t('settings.codexQuotaStatusPanelNoContext')
  return t('settings.codexQuotaStatusHealthy')
})
'''
    if old not in body:
        raise SystemExit("r38 quota status UI: codexQuotaEnabled anchor missing")
    body = body.replace(old, new, 1)

    old = '''      <SettingsRow :title="t('settings.codexQuotaEnabled')" :description="t('settings.codexQuotaEnabledHint')">
        <AppSwitch v-model="codexQuotaEnabled" />
      </SettingsRow>
'''
    new = '''      <SettingsRow :title="t('settings.codexQuotaEnabled')" :description="codexQuotaStatusDescription">
        <AppSwitch v-model="codexQuotaEnabled" />
      </SettingsRow>
'''
    if old not in body:
        raise SystemExit("r38 quota status UI: quota row anchor missing")
    body = body.replace(old, new, 1)
    SETTINGS.write_text(body, encoding="utf-8")

# i18n. apply_r38_i18n_prep runs before this overlay.
zh = ZH.read_text(encoding="utf-8")
en = EN.read_text(encoding="utf-8")
badge = '  "compat.buildBadge": "Sub2API Grok Compat r38 · v2.4.5+38",\n'
if badge not in zh or badge not in en:
    raise SystemExit("r38 quota status UI: r38 badge must be materialized first")
if '"settings.codexQuotaStatusHealthy"' not in zh:
    keys = '''  "settings.codexQuotaStatusChecking": "已开启，正在读取 Codex Usage 注入状态…",\n  "settings.codexQuotaStatusCdpUnavailable": "已开启，但当前无法连接 Codex CDP。请通过 Transfer 启动/重启 Codex；r38 会继续自动检测。",\n  "settings.codexQuotaStatusInstalling": "已连接 Codex，正在安装 Usage 注入脚本…",\n  "settings.codexQuotaStatusAnchorMissing": "已连接 Codex，但当前 UI 中未找到 pinned summary 的安全挂载点。r38 会在弹窗出现或 UI 重绘后自动重试。",\n  "settings.codexQuotaStatusWaitingPopup": "Usage 脚本已安装，正在等待 pinned summary 弹窗出现并挂载。",\n  "settings.codexQuotaStatusPanelNoContext": "Usage 面板已挂载；当前 Codex UI 未暴露上下文环数据，Context 暂显示 —，Tokens/缓存仍可用。",\n  "settings.codexQuotaStatusHealthy": "Usage 注入正常；面板与上下文数据源均已检测到。",\n'''
    zh = zh.replace(badge, badge + keys, 1)
if '"settings.codexQuotaStatusHealthy"' not in en:
    keys = '''  "settings.codexQuotaStatusChecking": "Enabled; reading Codex Usage injection status…",\n  "settings.codexQuotaStatusCdpUnavailable": "Enabled, but Codex CDP is not reachable. Launch/restart Codex through Transfer; r38 will keep retrying.",\n  "settings.codexQuotaStatusInstalling": "Codex CDP is connected; installing the Usage injection script…",\n  "settings.codexQuotaStatusAnchorMissing": "Codex is connected, but no safe pinned-summary mount point is visible in the current UI. r38 will retry after the popup appears or the UI rerenders.",\n  "settings.codexQuotaStatusWaitingPopup": "The Usage script is installed and is waiting for the pinned-summary popup to appear.",\n  "settings.codexQuotaStatusPanelNoContext": "Usage is mounted, but this Codex UI exposes no context-ring source. Context shows — while Tokens/cache remain available.",\n  "settings.codexQuotaStatusHealthy": "Usage injection is healthy; the panel and a context data source are both detected.",\n'''
    en = en.replace(badge, badge + keys, 1)
ZH.write_text(zh, encoding="utf-8")
EN.write_text(en, encoding="utf-8")

checks = {
    DIAGNOSTIC: [MARKER, "codex_quota_injector_status"],
    ADMIN: ["/api/diagnostic/codex-quota"],
    SYSTEM_API: ["CodexQuotaInjectorStatus", "getCodexQuotaInjectorStatus"],
    SETTINGS: [MARKER, "codexQuotaStatusDescription", "getCodexQuotaInjectorStatus"],
    ZH: ['"settings.codexQuotaStatusHealthy"'],
    EN: ['"settings.codexQuotaStatusHealthy"'],
}
for path, markers in checks.items():
    text = path.read_text(encoding="utf-8")
    for token in markers:
        if token not in text:
            raise SystemExit(f"r38 quota status UI missing {token} in {path.relative_to(ROOT)}")

print("r38 quota status UI: applied")
