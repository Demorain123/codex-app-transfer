from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OVERLAY = ROOT / "crates/codex_integration/src/auto_review_overlay.rs"
SNAPSHOT = ROOT / "src-tauri/src/admin/services/desktop/snapshot.rs"

text = OVERLAY.read_text(encoding="utf-8")
marker = "CAS-R30-AUTO-REVIEW-OVERLAY-ACTIVE-PROBE"
if marker not in text:
    anchor = '''/// If a previous Apply left `model_catalog_json` pointing at our shadow, restore the
/// user/Transfer source before normal catalog ownership detection runs.
pub fn restore_source_if_overlay_active(paths: &CodexPaths) -> Result<(), CodexError> {'''
    if text.count(anchor) != 1:
        raise SystemExit(
            f"r30 overlay-state probe expected one restore function anchor, found {text.count(anchor)}"
        )
    replacement = '''/// CAS-R30-AUTO-REVIEW-OVERLAY-ACTIVE-PROBE
/// Read-only state probe used by the r30 Hybrid Direct lifecycle telemetry. This intentionally
/// reuses r24's private path normalization/ownership rules instead of duplicating Windows path
/// comparison in the desktop layer.
pub fn auto_review_overlay_active(paths: &CodexPaths) -> Result<bool, CodexError> {
    Ok(configured_catalog_path(paths)?
        .as_deref()
        .is_some_and(|current| same_path(current, &overlay_path(paths))))
}

/// If a previous Apply left `model_catalog_json` pointing at our shadow, restore the
/// user/Transfer source before normal catalog ownership detection runs.
pub fn restore_source_if_overlay_active(paths: &CodexPaths) -> Result<(), CodexError> {'''
    text = text.replace(anchor, replacement, 1)
    OVERLAY.write_text(text, encoding="utf-8")
    print("r30 added read-only Auto Review overlay-active probe")
else:
    print("r30 Auto Review overlay-active probe already materialized")

# Import the probe from the same authoritative public module as the existing r24 helpers.
text = SNAPSHOT.read_text(encoding="utf-8")
if "auto_review_overlay_active" not in text:
    old = '''use codex_app_transfer_codex_integration::auto_review_overlay::{
    apply_auto_review_overrides, restore_source_if_overlay_active,
};'''
    new = '''use codex_app_transfer_codex_integration::auto_review_overlay::{
    apply_auto_review_overrides, auto_review_overlay_active, restore_source_if_overlay_active,
};'''
    if text.count(old) != 1:
        raise SystemExit(
            f"r30 overlay-state probe expected one authoritative import block, found {text.count(old)}"
        )
    text = text.replace(old, new, 1)
    SNAPSHOT.write_text(text, encoding="utf-8")
    print("r30 imported Auto Review overlay-active probe")
else:
    print("r30 Auto Review overlay-active probe import already materialized")

for rel, required in (
    (OVERLAY, marker),
    (OVERLAY, "pub fn auto_review_overlay_active"),
    (SNAPSHOT, "auto_review_overlay_active"),
):
    body = rel.read_text(encoding="utf-8")
    if required not in body:
        raise SystemExit(f"r30 overlay-state probe missing {rel}: {required}")

print("r30 Auto Review overlay state probe: PASS")
