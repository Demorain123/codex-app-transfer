from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MARKER = "CAS-R37-FAULT-ATTRIBUTION-QUOTA-GUARD"
for rel in ("frontend/src/i18n/zh.ts", "frontend/src/i18n/en.ts"):
    path = ROOT / rel
    body = path.read_text(encoding="utf-8")
    r37 = '"compat.buildBadge": "Sub2API Grok Compat r37 · v2.4.5+37",'
    r36 = '"compat.buildBadge": "Sub2API Grok Compat r36 · v2.4.5+36",'

    # On replay the r37 marker survives the inherited r24-r36 composition. In
    # that case the r37 overlay will intentionally no-op, so do NOT roll the
    # already-correct badge back to r36 here.
    if MARKER in body:
        if "Sub2API Grok Compat r37" not in body or "v2.4.5+37" not in body:
            raise SystemExit(f"r37 i18n prep: r37 marker present but badge is stale: {rel}")
        print(f"r37 i18n prep: {rel} replay already at r37")
        continue

    if r36 in body:
        print(f"r37 i18n prep: {rel} already normalized")
        continue
    if r37 not in body:
        raise SystemExit(f"r37 i18n prep: expected r36/r37 badge missing: {rel}")
    path.write_text(body.replace(r37, r36, 1), encoding="utf-8")
    print(f"r37 i18n prep: normalized {rel}")
