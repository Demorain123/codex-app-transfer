from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "scripts/apply_r36_safe_recovery.py"
body = TARGET.read_text(encoding="utf-8")

replacements = [
    (
        '"\'chainHealth.refresh\': \'立即检查\',"',
        '"\\\"chainHealth.refresh\\\": \'立即检查\',"',
    ),
    (
        '"\'chainHealth.refresh\': \'Check now\',"',
        '"\\\"chainHealth.refresh\\\": \'Check now\',"',
    ),
]
changed = False
for old, new in replacements:
    if old in body:
        body = body.replace(old, new, 1)
        changed = True

if changed:
    TARGET.write_text(body, encoding="utf-8")
    print("r36 i18n prep: PATCHED")
else:
    print("r36 i18n prep: already normalized")
