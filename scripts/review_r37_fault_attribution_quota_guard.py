from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MARKER = "CAS-R37-FAULT-ATTRIBUTION-QUOTA-GUARD"


def text(rel: str) -> str:
    path = ROOT / rel
    if not path.is_file():
        raise SystemExit(f"r37 review missing file: {rel}")
    return path.read_text(encoding="utf-8")


def require(rel: str, *needles: str) -> None:
    body = text(rel)
    for needle in needles:
        if needle not in body:
            raise SystemExit(f"r37 review missing marker in {rel}: {needle}")


require(
    "crates/proxy/src/telemetry.rs",
    MARKER,
    "quota_primary_used_percent",
    "quota_secondary_used_percent",
    "quota_account_fingerprint",
    "pub fn mark_quota(",
)
require(
    "crates/proxy/src/forward.rs",
    MARKER,
    '"x-codex-primary-used-percent"',
    '"x-codex-secondary-used-percent"',
    '"x-codex-primary-reset-after-seconds"',
    '"x-codex-secondary-reset-after-seconds"',
    '"x-codex-user-id"',
    "sub2api_retry_runtime_diag_header_fingerprint",
)
require(
    "src-tauri/src/admin/handlers/chain_health.rs",
    MARKER,
    "account_pool_layer_r37",
    "fault_attribution_layer_r37",
    "account_pool_exhausted",
    "account_quota_near_exhaustion",
    "fault_session_scoped",
    "fault_session_state",
    "fault_compaction_context",
    "fault_shared_upstream",
    "R37_LARGE_CONTEXT_BYTES",
    "restart_fix=false",
)
require(
    "frontend/src/api/chainHealth.ts",
    MARKER,
    "account: ChainHealthLayer",
    "diagnosis: ChainHealthLayer",
)
require(
    "frontend/src/pages/ProxyPage.vue",
    MARKER,
    "chainHealth.layer.account",
    "chainHealth.attribution",
    "chainHealth.diagnosis.summary",
)
# Keep the Windows replay review ASCII-tolerant: Git Bash/console encoding can
# render the decorative middle dot differently even when the version itself is
# correct. Validate the semantic version tokens independently instead.
require(
    "frontend/src/i18n/zh.ts",
    MARKER,
    "Sub2API Grok Compat r37",
    "v2.4.5+37",
    '"chainHealth.layer.account": "账号 / 配额"',
    '"chainHealth.attribution": "故障归因"',
)
require(
    "frontend/src/i18n/en.ts",
    MARKER,
    "Sub2API Grok Compat r37",
    "v2.4.5+37",
    '"chainHealth.layer.account": "Account / quota"',
    '"chainHealth.attribution": "Fault attribution"',
)

health = text("src-tauri/src/admin/handlers/chain_health.rs")
forward = text("crates/proxy/src/forward.rs")

# Lightweight boundary: r37 must not become a Sub2API admin client, scrape Docker
# logs, or create synthetic model traffic merely to learn quota state.
for forbidden in [
    "/api/v1/admin/accounts",
    "/admin/grok/accounts",
    "docker logs",
    "compose down",
    "down -v",
]:
    if forbidden in health.lower():
        raise SystemExit(f"r37 review found forbidden heavyweight/destructive health behavior: {forbidden}")

# The only account identity accepted by the lifecycle must be a fingerprint.
if "quota_account_fingerprint" not in forward or "x-codex-user-id" not in forward:
    raise SystemExit("r37 quota identity path missing")
if "account_email" in health.lower() or "authorization" in health.lower():
    raise SystemExit("r37 health center must not expose account email/authorization")

# Preserve r35 privacy hardening: routine upstream errors must not log request bodies.
if "request body: <redacted>" not in forward:
    raise SystemExit("r37 lost r35 request-body redaction")

version = text("SUB2API_GROK_COMPAT_VERSION.txt")
if "compat_revision=37" not in version or "app_version=2.4.5+37" not in version:
    raise SystemExit("r37 version stamp mismatch")

print("r37 review: PASS (lightweight attribution + passive/header quota guard + safe recovery boundaries)")
