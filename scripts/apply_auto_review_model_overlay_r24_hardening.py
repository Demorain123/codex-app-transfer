#!/usr/bin/env python3
"""Hardening pass for r24 Auto Review overlay.

Runs after apply_auto_review_model_overlay_r24.py. It intentionally stays small:
1. fix metadata serialization for Vec<(String, String)> -> serde_json::Map<String, Value>;
2. move shadow-source restoration before snapshot capture, so a missing/new snapshot can
   never capture Transfer's temporary shadow as the user's original model catalog.
"""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def patch(path: str, old: str, new: str, label: str) -> None:
    p = ROOT / path
    text = p.read_text(encoding="utf-8")
    if new in text:
        print(f"{label}: already hardened")
        return
    if old not in text:
        raise SystemExit(f"r24 hardening anchor not found: {label}")
    p.write_text(text.replace(old, new, 1), encoding="utf-8")
    print(f"{label}: hardened")


# Fix the generator itself, so any later direct replay emits compiling Rust.
patch(
    "scripts/apply_auto_review_model_overlay_r24.py",
    '"overrides": overrides.iter().cloned().collect::<serde_json::Map<String, Value>>()',
    '"overrides": overrides.iter().map(|(main, reviewer)| (main.clone(), Value::String(reviewer.clone()))).collect::<serde_json::Map<String, Value>>()',
    "r24 generator metadata serialization",
)

# Fix already-generated Rust if the base r24 script ran before this hardening pass.
generated = ROOT / "crates/codex_integration/src/auto_review_overlay.rs"
if generated.exists():
    patch(
        "crates/codex_integration/src/auto_review_overlay.rs",
        '"overrides": overrides.iter().cloned().collect::<serde_json::Map<String, Value>>()',
        '"overrides": overrides.iter().map(|(main, reviewer)| (main.clone(), Value::String(reviewer.clone()))).collect::<serde_json::Map<String, Value>>()',
        "generated metadata serialization",
    )

# Restore the true catalog source BEFORE taking a snapshot. This matters if a prior
# snapshot was cleaned up while config.toml still points to the temporary shadow.
apply_path = ROOT / "crates/codex_integration/src/apply.rs"
if apply_path.exists():
    text = apply_path.read_text(encoding="utf-8")
    late = '''    // CAS-AUTO-REVIEW-R24: if the previous Apply pointed config.toml at our shadow,
    // restore the recorded source first so external-catalog ownership detection sees the
    // user's real catalog rather than mistaking the Transfer shadow for a new source.
    crate::auto_review_overlay::restore_source_if_overlay_active(paths)?;

'''
    early_anchor = '''pub fn apply_provider(paths: &CodexPaths, cfg: &ApplyConfig) -> Result<ApplyResult, CodexError> {
    // 1. snapshot(幂等;已有快照不会覆盖)
'''
    early = '''pub fn apply_provider(paths: &CodexPaths, cfg: &ApplyConfig) -> Result<ApplyResult, CodexError> {
    // CAS-AUTO-REVIEW-R24: restore our temporary shadow pointer first. Snapshot must see
    // the real user/Transfer source catalog, never the copy-on-write overlay.
    crate::auto_review_overlay::restore_source_if_overlay_active(paths)?;

    // 1. snapshot(幂等;已有快照不会覆盖)
'''
    if early in text:
        if late in text:
            text = text.replace(late, "", 1)
            apply_path.write_text(text, encoding="utf-8")
        print("r24 snapshot ordering: already hardened")
    else:
        if late not in text:
            raise SystemExit("r24 hardening: late restore block missing")
        text = text.replace(late, "", 1)
        if early_anchor not in text:
            raise SystemExit("r24 hardening: apply_provider entry anchor missing")
        text = text.replace(early_anchor, early, 1)
        apply_path.write_text(text, encoding="utf-8")
        print("r24 snapshot ordering: hardened")

print("r24 auto-review hardening complete")
