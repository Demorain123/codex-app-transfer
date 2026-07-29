from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PATH = ROOT / "src-tauri/src/admin/services/desktop/no_micro.rs"
text = PATH.read_text(encoding="utf-8")

pairs = [
    (
        "            serialport_count: 0,\n            feature_gate_count: 0,",
        "            serialport_count: 0,\n            hid_marker_count: 0,\n            feature_gate_count: 0,",
        "unsupported constructor",
    ),
    (
        "        serialport_count: 0,\n        feature_gate_count: 0,",
        "        serialport_count: 0,\n        hid_marker_count: 0,\n        feature_gate_count: 0,",
        "Windows doctor constructor",
    ),
]

for old, new, label in pairs:
    if new in text:
        continue
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"r32 doctor-init fix {label}: expected one anchor, found {count}")
    text = text.replace(old, new, 1)

if text.count("hid_marker_count: 0,") < 2:
    raise SystemExit("r32 doctor-init fix did not materialize both constructors")

PATH.write_text(text, encoding="utf-8")
print("r32 No Lagging doctor init indentation fix: PASS")
