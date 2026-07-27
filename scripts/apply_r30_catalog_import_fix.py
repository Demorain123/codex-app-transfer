from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PATH = ROOT / "src-tauri/src/admin/services/desktop/snapshot.rs"
text = PATH.read_text(encoding="utf-8")

marker = "CAS-R30-AUTO-REVIEW-MODULE-IMPORT"
if marker not in text:
    old = '''use codex_app_transfer_codex_integration::{
    apply_auto_review_overrides, apply_provider, ensure_file_store_mode, has_snapshot,
    has_stale_active_snapshot, restore_codex_state, restore_source_if_overlay_active,
    sync_mcp_credentials, ApplyConfig, CodexPaths,
};'''
    new = '''// CAS-R30-AUTO-REVIEW-MODULE-IMPORT: r24 exposes the COW implementation as a public module,
// not as crate-root re-exports. Import from the authoritative module so full MSVC compile catches
// API drift without widening r24's public surface just for r30.
use codex_app_transfer_codex_integration::auto_review_overlay::{
    apply_auto_review_overrides, restore_source_if_overlay_active,
};
use codex_app_transfer_codex_integration::{
    apply_provider, ensure_file_store_mode, has_snapshot, has_stale_active_snapshot,
    restore_codex_state, sync_mcp_credentials, ApplyConfig, CodexPaths,
};'''
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"r30 catalog import fix expected exactly one generated root import, found {count}")
    text = text.replace(old, new, 1)
    PATH.write_text(text, encoding="utf-8")
    print("r30 fixed Auto Review COW imports to authoritative module")
else:
    print("r30 Auto Review COW module import already materialized")

text = PATH.read_text(encoding="utf-8")
for required in (
    marker,
    "codex_app_transfer_codex_integration::auto_review_overlay::{",
    "apply_auto_review_overrides, restore_source_if_overlay_active",
):
    if required not in text:
        raise SystemExit(f"r30 catalog import fix missing: {required}")

bad = '''use codex_app_transfer_codex_integration::{
    apply_auto_review_overrides,'''
if bad in text:
    raise SystemExit("r30 catalog import fix: stale crate-root Auto Review import remains")

print("r30 Auto Review module import fix: PASS")
