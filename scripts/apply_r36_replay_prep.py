from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "scripts/apply_r36_safe_recovery.py"
body = TARGET.read_text(encoding="utf-8")
old = "chain_health_recover"
new = "recover_chain"
if old in body:
    TARGET.write_text(body.replace(old, new), encoding="utf-8")
    print("r36 replay prep: PATCHED recovery handler name")
elif new in body:
    print("r36 replay prep: already patched")
else:
    raise SystemExit("r36 replay prep: recovery handler marker missing")
