from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PATH = ROOT / "src-tauri/src/admin/handlers/no_micro.rs"
text = PATH.read_text(encoding="utf-8")

old = '"No Micro doctor task failed: {e}"'
new = '"No Lagging doctor task failed: {e}"'
if new not in text:
    count = text.count(old)
    if count != 2:
        raise SystemExit(f"r32 handler prep expected two doctor error labels, found {count}")
    text = text.replace(old, new)
else:
    # Idempotent replay is allowed only when no stale old label remains.
    if old in text:
        raise SystemExit("r32 handler prep found mixed No Micro/No Lagging doctor labels")

PATH.write_text(text, encoding="utf-8")
print("r32 No Lagging repeated handler label prep: PASS")
