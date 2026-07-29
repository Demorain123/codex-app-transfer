from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PATH = ROOT / "src-tauri/src/admin/services/desktop/no_micro.rs"
text = PATH.read_text(encoding="utf-8")

# On a first composition the r32 warning is absent and this prep is a no-op.
# After cargo fmt, Rust may wrap the long condition/string in several valid ways.
# Do not guess those whitespace choices. If the unique r32 semantic sentence is
# already present, normalize only the reviewed warning region bounded by the
# adjacent target-module and stub-shape checks. cargo fmt later restores the
# canonical final Rust layout, so the complete r32 diff remains idempotent.
semantic = "当前 build 未发现旧 serialport 标记，但仍检测到 HID/accessory 路径"
if semantic in text:
    start_marker = "    if report.target_module_count == 0 {\n"
    end_marker = "    if !report.stub_shape_ok && report.target_module_count > 0 {\n"
    start = text.find(start_marker)
    end = text.find(end_marker, start + len(start_marker)) if start >= 0 else -1
    if start < 0 or end < 0:
        raise SystemExit("r32 rustfmt replay prep: semantic warning exists but reviewed warning boundaries were not found")
    region = text[start:end]
    if semantic not in region or "No Lagging 不会强行注入" not in region:
        raise SystemExit("r32 rustfmt replay prep: warning boundaries contain unexpected semantics")
    canonical = '''    if report.target_module_count == 0 {\n        report\n            .warnings\n            .push("当前 app.asar 未检测到 @worklouder/device-kit-oai；No Lagging 不会强行注入".to_owned());\n    }\n    if report.target_module_count > 0 && report.serialport_count == 0 && report.hid_marker_count > 0 {\n        report.warnings.push(\n            "当前 build 未发现旧 serialport 标记，但仍检测到 HID/accessory 路径；r32 会继续在顶层 @worklouder/device-kit-oai 处阻断，避免进入 HID/native 枚举路径".to_owned(),\n        );\n    }\n'''
    text = text[:start] + canonical + text[end:]

PATH.write_text(text, encoding="utf-8")
print("r32 No Lagging rustfmt replay prep: PASS")
