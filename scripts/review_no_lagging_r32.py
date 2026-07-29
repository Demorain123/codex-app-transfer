from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def text(rel: str) -> str:
    path = ROOT / rel
    if not path.is_file():
        raise SystemExit(f"r32 review missing file: {rel}")
    return path.read_text(encoding="utf-8")


backend = text("src-tauri/src/admin/services/desktop/no_micro.rs")
launcher = text("src-tauri/resources/codex_no_micro_launcher.mjs")
janitor = text("src-tauri/resources/codex_no_lagging_janitor.ps1")
handler = text("src-tauri/src/admin/handlers/no_micro.rs")
ui = text("frontend/src/components/codex/NoMicroPanel.vue")
api = text("frontend/src/api/noMicro.ts")
overlay = text("scripts/apply_no_lagging_r32.py")

# The old r23 worker-safe mitigation remains the exact injection primitive. r32 widens
# the doctor's applicability to accessory/HID builds but must not start intercepting
# unrelated native modules globally.
for marker in (
    '@worklouder/device-kit-oai',
    '__CODEX_MICRO_DISABLED_LOCAL__',
    '__CODEX_NO_LAGGING_MICRO_ACCESSORY_GUARD__',
    'execArgv: safeOptions.execArgv ?? []',
    'process.getBuiltinModule("inspector").close()',
    'cleanupOwnChild(child, executable)',
):
    if marker not in launcher:
        raise SystemExit(f"r32 review: hardened launcher invariant missing: {marker}")

if 'if (request === "node-hid")' in launcher or 'if (request === "serialport")' in launcher:
    raise SystemExit("r32 review: do not broaden interception below the reviewed device-kit-oai boundary")

# New public reports show serialport can disappear while HID/accessory enumeration still hangs.
# Therefore serialport must be evidence, not an enablement requirement.
for marker in (
    "HID_MARKERS",
    "hid_marker_count",
    "CAS-NO-LAGGING-R32-ACCESSORY-GUARD",
    "start_mcp_exit_guard",
    '"microAccessoryGuard": "success"',
):
    if marker not in backend:
        raise SystemExit(f"r32 review: backend invariant missing: {marker}")
if "&& report.serialport_count > 0" in backend:
    raise SystemExit("r32 review: serialport marker incorrectly remains a hard compatibility gate")

# MCP/helper cleanup is deliberately exit-only and generation-evidence based. It must not
# inspect/log command lines or kill by generic executable name.
for marker in (
    "CAS-NO-LAGGING-R32-MCP-EXIT-GUARD",
    "CAS_NO_LAGGING_EXE",
    "Get-Desktop-Ancestry",
    "StartUtc",
    "Same-Identity",
    "cleanup_cancelled_desktop_reappeared",
    "Stop-Process -Id $r.Pid",
    "guard_waiting_next_generation",
):
    if marker not in janitor:
        raise SystemExit(f"r32 review: MCP exit guard invariant missing: {marker}")
for forbidden in (
    "CommandLine",
    "taskkill",
    "Stop-Process -Name",
    "Get-Credential",
    "Bearer ",
):
    if forbidden in janitor:
        raise SystemExit(f"r32 review: privacy/scope regression in MCP exit guard: {forbidden}")

# Canonical new A/B label while keeping the old endpoint and no-micro alias compatible.
for marker in (
    'Some("no-micro") | Some("no-lagging") => "no-lagging"',
    '"no-lagging",\n        "launch_requested"',
    'Value::String("no-lagging".to_owned())',
):
    if marker not in handler:
        raise SystemExit(f"r32 review: handler No Lagging marker missing: {marker}")

for marker in (
    "Codex No Lagging A/B",
    "HID/accessory",
    "MCP Exit Guard",
    "不会减少 MCP",
    "does not reduce MCPs",
    "CAS-NO-LAGGING-R32-UI",
):
    if marker not in ui:
        raise SystemExit(f"r32 review: UI scope/wording missing: {marker}")
if "hidMarkerCount" not in api:
    raise SystemExit("r32 review: frontend API lacks HID marker count")

# This overlay must not take ownership of provider/auth/model routing. r30 Hybrid Direct
# remains authoritative for those surfaces.
for forbidden in (
    "model_provider",
    "openai_base_url",
    "chatgpt_base_url",
    "auth.json",
    "apply_provider",
    "model_catalog_json",
):
    if forbidden in overlay:
        raise SystemExit(f"r32 review: No Lagging overlay leaked into provider/auth/catalog behavior: {forbidden}")

print("r32 No Lagging deep safety review: PASS")
