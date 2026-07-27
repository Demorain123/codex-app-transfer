from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def body(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def require(rel: str, *markers: str) -> str:
    text = body(rel)
    for marker in markers:
        if marker not in text:
            raise SystemExit(f"r28 review missing marker in {rel}: {marker}")
    return text


revision = body("SUB2API_GROK_COMPAT_REVISION.txt").strip()
if revision != "28":
    raise SystemExit(f"r28 review expected revision 28, got {revision!r}")

tauri = json.loads(body("src-tauri/tauri.conf.json"))
version = str(tauri.get("version", ""))
if not version.endswith("+28"):
    raise SystemExit(f"r28 review expected Tauri version +28, got {version!r}")

helper = require(
    "src-tauri/src/admin/services/desktop/hybrid_direct.rs",
    "CAS-HYBRID-DIRECT-R28",
    "enable_preflight",
    "has_snapshot",
    "has_stale_active_snapshot",
    "active_is_synthetic",
    "Local Routing",
)

snapshot = require(
    "src-tauri/src/admin/services/desktop/snapshot.rs",
    "CAS-HYBRID-DIRECT-R28-APPLY-BLOCK",
    "CAS-HYBRID-DIRECT-R28-PLUGIN-BLOCK",
    "CAS-HYBRID-DIRECT-R28-GATEWAY-SYNC",
    "CAS-HYBRID-DIRECT-R28-AUTO-APPLY",
    "CAS-HYBRID-DIRECT-R28-RESTORE-BLOCK",
    '"codexMutated": false',
    "start_proxy_for_provider_if_needed",
)

# The safety gates are useful only if they are physically before the mutation sites.
def assert_before(text: str, first: str, later: str, label: str, start: int = 0) -> None:
    a = text.find(first, start)
    b = text.find(later, start)
    if a < 0 or b < 0 or a >= b:
        raise SystemExit(f"r28 review order failure: {label} ({a=} {b=})")

assert_before(snapshot, "CAS-HYBRID-DIRECT-R28-APPLY-BLOCK", "let result = apply_provider(", "provider apply")
plugin_start = snapshot.index("pub async fn apply_plugin_unlock_mode(")
assert_before(snapshot, "CAS-HYBRID-DIRECT-R28-PLUGIN-BLOCK", "snapshot_codex_state(", "plugin/auth mutation", plugin_start)
sync_start = snapshot.index("async fn sync_desktop_for_active_provider_impl")
assert_before(snapshot, "CAS-HYBRID-DIRECT-R28-GATEWAY-SYNC", "desktop_config_target_for_provider", "desktop sync target", sync_start)

proxy = require(
    "src-tauri/src/admin/handlers/proxy.rs",
    "CAS-HYBRID-DIRECT-R28-PROVIDER-REFRESH",
    "provider_matches",
    "status.active_provider.as_deref() == Some(expected)",
    "start_proxy_for_provider_if_needed",
    "PROXY_LIFECYCLE_R27.lock().await",
)
if "(port == 0 || current_port == Some(port)) && provider_matches" not in proxy:
    raise SystemExit("r28 review: same-port reuse is not provider-aware")

settings = require(
    "src-tauri/src/admin/handlers/settings.rs",
    "CAS-HYBRID-DIRECT-R28-ENABLE-PREFLIGHT",
    "enable_preflight()",
    "CAS-HYBRID-DIRECT-R28-SETTING-ACTIVE",
    "set_fake_account_mode(false)",
)

process = require(
    "src-tauri/src/admin/services/desktop/process.rs",
    "CAS-HYBRID-DIRECT-R28-CHAT-ENV-BLOCK",
    '"CODEX_API_BASE_URL".into(),',
)
chat_fn = process.index("fn chat_launch_env(")
assert_before(
    process,
    "CAS-HYBRID-DIRECT-R28-CHAT-ENV-BLOCK",
    '"CODEX_API_BASE_URL".into(),',
    "real launch env injection",
    chat_fn,
)

main = require(
    "src-tauri/src/main.rs",
    "CAS-HYBRID-DIRECT-R28-RESTORE-OWNER",
    "CAS-HYBRID-DIRECT-R28-FAKE-OFF",
    "CAS-HYBRID-DIRECT-R28-STARTUP-PLUGIN-SKIP",
    "CAS-HYBRID-DIRECT-R28-LOGIN-OWNER",
    "CAS-HYBRID-DIRECT-R28-TRAY-PLUGIN-SKIP",
)

app = require("frontend/src/App.vue", "CAS-HYBRID-DIRECT-R28-SESSION-OWNER", "hybridDirectMode")
if "if (!settings.bool('hybridDirectMode', false))" not in app:
    raise SystemExit("r28 review: startup foreign-session import is not gated")

settings_ui = require(
    "frontend/src/pages/SettingsPage.vue",
    "settings.hybridDirect",
    "settings.hybridDirectHint",
    'v-if="!hybridDirectMode"',
)
proxy_ui = require("frontend/src/pages/ProxyPage.vue", "proxy.hybridDirectGateway")

for rel in ("frontend/src/i18n/zh.ts", "frontend/src/i18n/en.ts"):
    require(
        rel,
        '"settings.hybridDirect"',
        '"settings.hybridDirectHint"',
        '"proxy.hybridDirectGateway"',
        "Local Routing" if rel.endswith("en.ts") else "本地路由",
    )

# r24-r27 still have to be physically present after composition.
legacy_markers = {
    "crates/codex_integration/src/auto_review_overlay.rs": "CAS-AUTO-REVIEW-R24",
    "crates/proxy/src/forward.rs": "CAS-APPS-MCP-AUTH-R25-REHYDRATE",
    "src-tauri/src/runtime_diag.rs": "CAS-RUNTIME-DIAG-R26",
    "src-tauri/src/admin/handlers/proxy.rs": "CAS-PROXY-LIFECYCLE-R27",
}
for rel, marker in legacy_markers.items():
    require(rel, marker)

print("r28 Hybrid Direct semantic/privacy review: PASS")
