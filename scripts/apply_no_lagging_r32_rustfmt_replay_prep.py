from __future__ import annotations

from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
PATH = ROOT / "src-tauri/src/admin/services/desktop/no_micro.rs"
text = PATH.read_text(encoding="utf-8")

# On a first composition the r32 warning is absent and this prep is a no-op.
# After cargo fmt, Rust may wrap the long push(...) expression, so the strict
# overlay's exact `new in text` replay check cannot recognize it. Normalize only
# this already-r32 semantic block back to the overlay's canonical pre-rustfmt
# representation; cargo fmt later returns it to the same final source shape.
semantic = "当前 build 未发现旧 serialport 标记，但仍检测到 HID/accessory 路径"
if semantic in text:
    pattern = re.compile(
        r'''    if report\.target_module_count == 0 \{\n'''
        r'''        report\n'''
        r'''            \.warnings\n'''
        r'''            \.push\("当前 app\.asar 未检测到 @worklouder/device-kit-oai；No Lagging 不会强行注入"\.to_owned\(\)\);\n'''
        r'''    \}\n'''
        r'''    if report\.target_module_count > 0\s*&&\s*report\.serialport_count == 0\s*&&\s*report\.hid_marker_count > 0\s*\{\n'''
        r'''        report\.warnings\.push\(\s*\n?'''
        r'''            "当前 build 未发现旧 serialport 标记，但仍检测到 HID/accessory 路径；r32 会继续在顶层 @worklouder/device-kit-oai 处阻断，避免进入 HID/native 枚举路径"\.to_owned\(\),?\s*\n?'''
        r'''        \);\n'''
        r'''    \}\n''',
        re.MULTILINE,
    )
    canonical = '''    if report.target_module_count == 0 {\n        report\n            .warnings\n            .push("当前 app.asar 未检测到 @worklouder/device-kit-oai；No Lagging 不会强行注入".to_owned());\n    }\n    if report.target_module_count > 0 && report.serialport_count == 0 && report.hid_marker_count > 0 {\n        report.warnings.push(\n            "当前 build 未发现旧 serialport 标记，但仍检测到 HID/accessory 路径；r32 会继续在顶层 @worklouder/device-kit-oai 处阻断，避免进入 HID/native 枚举路径".to_owned(),\n        );\n    }\n'''
    updated, count = pattern.subn(canonical, text, count=1)
    if count != 1:
        raise SystemExit("r32 rustfmt replay prep: semantic warning exists but its reviewed block shape was not recognized")
    text = updated

PATH.write_text(text, encoding="utf-8")
print("r32 No Lagging rustfmt replay prep: PASS")
