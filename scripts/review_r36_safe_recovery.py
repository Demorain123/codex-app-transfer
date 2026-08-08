from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(rel: str) -> str:
    p = ROOT / rel
    if not p.is_file():
        raise SystemExit(f"r36 review missing file: {rel}")
    return p.read_text(encoding="utf-8")

health = read("src-tauri/src/admin/handlers/chain_health.rs")
router = read("src-tauri/src/admin/mod.rs")
api = read("frontend/src/api/chainHealth.ts")
page = read("frontend/src/pages/ProxyPage.vue")
zh = read("frontend/src/i18n/zh.ts")
en = read("frontend/src/i18n/en.ts")
version = read("SUB2API_GROK_COMPAT_VERSION.txt")

required = {
    "health": [
        "CAS-R36-SAFE-RECOVERY",
        "recover_chain",
        "RECOVERY_COOLDOWN",
        "recovery_classification",
        "restart_gateway_container",
        "restart_healthy_sub2api",
        "needs_real_request_verification",
        "start_proxy_for_provider_if_needed",
    ],
    "router": ["/api/chain-health/recover", "recover_chain"],
    "api": ["recoverChainHealth", "ChainRecoveryReport"],
    "page": ["onRecoverChain", "chainHealth.recover", "chainRecovery.needsRealRequestVerification"],
    "zh": ["尝试恢复", "需要下一次真实请求验证账号池 / 上游是否已经恢复"],
    "en": ["Try recovery", "next real request"],
    "version": ["compat_revision=36", "app_version=2.4.5+36"],
}
for name, markers in required.items():
    source = {"health": health, "router": router, "api": api, "page": page, "zh": zh, "en": en, "version": version}[name]
    for marker in markers:
        if marker not in source:
            raise SystemExit(f"r36 review missing {name} marker: {marker}")

# Safety invariants: recovery may restart a specific diagnosed target container,
# but must never run compose down/up, delete/recreate containers, mutate volumes,
# inspect secrets/env, update images, or send model inference traffic.
for forbidden in [
    '"compose".into(),\n                        "down"',
    '"rm".into()',
    '"pull".into()',
    'docker compose down',
    'docker compose up',
    'docker inspect --format {{json .Config.Env}}',
    '.Config.Env',
    'POST /v1/responses',
    'chat/completions',
]:
    if forbidden in health:
        raise SystemExit(f"r36 unsafe recovery regression: {forbidden}")

if 'target.health.as_deref() == Some("unhealthy")' not in health:
    raise SystemExit("r36 container restart is not evidence-gated")
if '目标容器仍为 healthy/running，没有证据支持自动重启' not in health:
    raise SystemExit("r36 healthy-container no-restart guard missing")
if 'RECOVERY_COOLDOWN - elapsed' not in health:
    raise SystemExit("r36 restart-loop cooldown missing")
if "chain_health_recover" in health or "chain_health_recover" in router:
    raise SystemExit("r36 replay regression: recovery handler collides with r33 substring check")

print("r36 safe recovery review: PASS")
