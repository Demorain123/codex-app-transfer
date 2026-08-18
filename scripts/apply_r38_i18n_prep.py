from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for rel in ("frontend/src/i18n/zh.ts", "frontend/src/i18n/en.ts"):
    path = ROOT / rel
    body = path.read_text(encoding="utf-8")
    if "Sub2API Grok Compat r38 · v2.4.5+38" in body:
        print(f"r38 i18n prep: {rel} already at r38")
        continue
    old = '"compat.buildBadge": "Sub2API Grok Compat r37 · v2.4.5+37",'
    new = '"compat.buildBadge": "Sub2API Grok Compat r38 · v2.4.5+38",'
    if old not in body:
        raise SystemExit(f"r38 i18n prep: expected r37 badge missing: {rel}")
    path.write_text(body.replace(old, new, 1), encoding="utf-8")
    print(f"r38 i18n prep: updated {rel}")
