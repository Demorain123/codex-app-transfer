from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
injector = (ROOT / "src-tauri/src/codex_quota_injector.rs").read_text(encoding="utf-8")
diagnostic = (ROOT / "src-tauri/src/admin/handlers/diagnostic.rs").read_text(encoding="utf-8")
admin = (ROOT / "src-tauri/src/admin/mod.rs").read_text(encoding="utf-8")
system_api = (ROOT / "frontend/src/api/system.ts").read_text(encoding="utf-8")
settings = (ROOT / "frontend/src/pages/SettingsPage.vue").read_text(encoding="utf-8")

for token in (
    "CAS-R38-CODEX-USAGE-INJECTOR-COMPAT",
    "var VERSION = 8",
    "legacy-class",
    "semantic-section",
    "semantic-popup-sections",
    "semantic-popup",
    "__catQuotaDiagnostic",
    "QuotaInjectorStatus",
    "panel_present",
    "context_source",
    "conversation_id_found",
    "codex_not_reachable",
):
    if token not in injector:
        raise SystemExit(f"r38 usage review: injector missing {token}")

# Panel mounting must no longer be coupled to the legacy Context usage donut.
find_start = injector.find("function findScroller()")
find_end = injector.find("function el(", find_start)
locator = injector[find_start:find_end]
if 'group/section-toggle' not in locator:
    raise SystemExit("r38 usage review: legacy locator fallback was lost")
if "[aria-label^=\"Context usage:\"]" in locator:
    raise SystemExit("r38 usage review: mount locator must not depend on Context usage ring")

# The old single-shot shape must not survive as the only mount decision.
if "var scroller = findScroller();\n    if (!scroller)" in injector:
    raise SystemExit("r38 usage review: old brittle findScroller call shape remains")

for token in (
    "CAS-R38-CODEX-USAGE-STATUS-UI",
    "codex_quota_injector_status",
):
    if token not in diagnostic:
        raise SystemExit(f"r38 usage review: backend diagnostic missing {token}")
if "/api/diagnostic/codex-quota" not in admin:
    raise SystemExit("r38 usage review: admin route missing")
if "getCodexQuotaInjectorStatus" not in system_api or "CodexQuotaInjectorStatus" not in system_api:
    raise SystemExit("r38 usage review: frontend diagnostic API missing")
for token in (
    "CAS-R38-CODEX-USAGE-STATUS-UI",
    "codexQuotaStatusDescription",
    "codexQuotaStatusCdpUnavailable",
    "codexQuotaStatusAnchorMissing",
    "codexQuotaStatusPanelNoContext",
):
    if token not in settings and token not in (ROOT / "frontend/src/i18n/zh.ts").read_text(encoding="utf-8"):
        raise SystemExit(f"r38 usage review: settings/status marker missing {token}")

for rel in ("frontend/src/i18n/zh.ts", "frontend/src/i18n/en.ts"):
    text = (ROOT / rel).read_text(encoding="utf-8")
    for token in (
        "settings.codexQuotaStatusCdpUnavailable",
        "settings.codexQuotaStatusAnchorMissing",
        "settings.codexQuotaStatusPanelNoContext",
        "settings.codexQuotaStatusHealthy",
    ):
        if token not in text:
            raise SystemExit(f"r38 usage review: {rel} missing {token}")

print("r38 usage injector review: PASS (multi-anchor mount + context-independent panel + visible diagnostics)")
