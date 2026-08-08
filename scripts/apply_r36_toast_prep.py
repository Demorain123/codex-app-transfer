from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "scripts/apply_r36_safe_recovery.py"
body = TARGET.read_text(encoding="utf-8")
old = "toast(t('chainHealth.recoveryComplete'), 'success')"
new = "toast(t('chainHealth.recoveryComplete'), 'info')"
if old in body:
    TARGET.write_text(body.replace(old, new, 1), encoding="utf-8")
    print("r36 toast prep: PATCHED")
elif new in body:
    print("r36 toast prep: already patched")
else:
    raise SystemExit("r36 toast prep: recovery toast anchor missing")
