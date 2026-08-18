from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MAIN = ROOT / "src-tauri/src/main.rs"
MARKER = "CAS-R39-RELEASE-TEST-CONSOLE"

body = MAIN.read_text(encoding="utf-8")
new_attr = '#![cfg_attr(all(not(debug_assertions), not(test)), windows_subsystem = "windows")]'
old_attr = '#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]'

if MARKER in body:
    if new_attr not in body:
        raise SystemExit("r39 release-test console marker exists but cfg_attr is not hardened")
    print("r39 release-test console subsystem: already applied")
    raise SystemExit(0)

if old_attr not in body:
    raise SystemExit("r39 release-test console patch anchor missing in src-tauri/src/main.rs")

body = body.replace(
    old_attr,
    new_attr + " // " + MARKER,
    1,
)
MAIN.write_text(body, encoding="utf-8")

if new_attr not in body or MARKER not in body:
    raise SystemExit("r39 release-test console patch failed")

print("r39 release-test console subsystem: applied")
