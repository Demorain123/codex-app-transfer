from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
path = ROOT / "src-tauri/src/admin/handlers/chain_health.rs"
text = path.read_text(encoding="utf-8")
old = "            let latest = relevant.last().copied()?;"
new = "            let latest = *relevant.last()?;"
if old in text:
    text = text.replace(old, new, 1)
elif new not in text:
    raise SystemExit("r38 health codegen fix: latest-record anchor missing")
path.write_text(text, encoding="utf-8")
print("r38 health codegen fix: PASS")
