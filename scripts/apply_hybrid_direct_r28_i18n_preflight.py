from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

ENTRIES = {
    "frontend/src/i18n/zh.ts": '''  "settings.hybridDirect": "Hybrid Direct（CC Switch）",
  "settings.hybridDirectHint": "安全模式：Transfer 只作为 Grok/第三方本地网关，不改 Codex provider、openai/chatgpt base URL 或 auth.json。启用前必须先还原 Transfer 管理的 Codex 快照；官方 OAuth 请在 CC Switch 选择 OpenAI Official，并保持 Codex 本地路由关闭。",
  "settings.hybridDirectAutoApplyHint": "Hybrid Direct 下仅自动启动 Transfer 的 Grok/第三方网关，不会把 provider 或 OAuth 路由写入 Codex。",
  "proxy.hybridDirectGateway": "Hybrid Direct · 仅第三方网关",
''',
    "frontend/src/i18n/en.ts": '''  "settings.hybridDirect": "Hybrid Direct (CC Switch)",
  "settings.hybridDirectHint": "Safety mode: Transfer is only the local gateway for Grok/third-party traffic and will not rewrite Codex provider, openai/chatgpt base URLs, or auth.json. Restore any Transfer-managed Codex snapshot before enabling. For official OAuth, select OpenAI Official in CC Switch and keep Codex Local Routing off.",
  "settings.hybridDirectAutoApplyHint": "In Hybrid Direct, auto-apply only starts the Transfer Grok/third-party gateway; it never writes provider or OAuth routing into Codex.",
  "proxy.hybridDirectGateway": "Hybrid Direct · third-party gateway only",
''',
}

for rel, entries in ENTRIES.items():
    path = ROOT / rel
    text = path.read_text(encoding="utf-8")
    if '"settings.hybridDirect"' in text:
        print(f"r28 i18n preflight: {rel} already materialized")
        continue

    # CAS-HYBRID-DIRECT-R28-I18N-PREFLIGHT
    # zh currently ends with `;`, en without it. Accept only these exact root-dictionary
    # terminators and require exactly one match; never inject near an arbitrary inner brace.
    candidates = ["} as Record<string, string>;", "} as Record<string, string>"]
    matches = [candidate for candidate in candidates if text.endswith(candidate + "\n") or text.endswith(candidate)]
    if len(matches) != 1:
        raise SystemExit(f"r28 i18n preflight: cannot identify unique dictionary tail for {rel}: {matches}")
    tail = matches[0]
    idx = text.rfind(tail)

    # The pre-existing last property is allowed to omit its trailing comma (en.ts does).
    # When appending more properties, add exactly one comma while preserving the original
    # whitespace/newline before the root dictionary terminator. If a comma already exists
    # (zh.ts), leave it untouched. This keeps replay idempotent and valid under vue-tsc.
    prefix = text[:idx]
    trimmed = prefix.rstrip()
    trailing_ws = prefix[len(trimmed):]
    if not trimmed.endswith(","):
        trimmed += ","
    prefix = trimmed + trailing_ws

    text = prefix + entries + text[idx:]
    path.write_text(text, encoding="utf-8")
    print(f"r28 i18n preflight: materialized {rel}")

for rel in ENTRIES:
    text = (ROOT / rel).read_text(encoding="utf-8")
    for marker in ('"settings.hybridDirect"', '"settings.hybridDirectHint"', '"proxy.hybridDirectGateway"'):
        if marker not in text:
            raise SystemExit(f"r28 i18n preflight: {rel} missing {marker}")
