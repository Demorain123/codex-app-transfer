from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "src-tauri/src/admin/handlers/settings.rs"
text = TARGET.read_text(encoding="utf-8")

# CAS-HYBRID-DIRECT-R28-DEFAULT-PREFLIGHT
# `autoApplyOnStart` exists in both production defaults and test fixtures. Scope the
# insertion to default_config_value() instead of using a whole-file cardinality check.
if '"hybridDirectMode": false' not in text:
    start = text.find("pub(super) fn default_config_value() -> Value {")
    end = text.find("\npub(super) fn normalize_imported_provider", start)
    if start < 0 or end < 0:
        raise SystemExit("r28 default preflight: default_config_value scope not found")
    block = text[start:end]
    anchor = '           "autoApplyOnStart": true,\n'
    if block.count(anchor) != 1:
        raise SystemExit(
            f"r28 default preflight: expected one autoApplyOnStart in production default scope, found {block.count(anchor)}"
        )
    block = block.replace(
        anchor,
        anchor + '           "hybridDirectMode": false,\n',
        1,
    )
    text = text[:start] + block + text[end:]
    TARGET.write_text(text, encoding="utf-8")
    print("r28 production hybridDirectMode default: materialized")
else:
    print("r28 production hybridDirectMode default: already materialized")

# Verify the marker lives in the production default scope, not merely a test fixture.
text = TARGET.read_text(encoding="utf-8")
start = text.find("pub(super) fn default_config_value() -> Value {")
end = text.find("\npub(super) fn normalize_imported_provider", start)
if start < 0 or end < 0 or '"hybridDirectMode": false' not in text[start:end]:
    raise SystemExit("r28 default preflight: production default missing hybridDirectMode=false")
