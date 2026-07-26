#!/usr/bin/env python3
"""Pre/post hardening for r24 Auto Review overlay.

The revision composer runs this script before AND after the base r24 generator:
- preflight patches generator defects/anchor drift before generation can fail;
- postflight fixes/validates generated Rust ordering and serialization.
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


GEN = "scripts/apply_auto_review_model_overlay_r24.py"

# 1. Fix generator metadata serialization so generated Rust compiles.
patch(
    GEN,
    '"overrides": overrides.iter().cloned().collect::<serde_json::Map<String, Value>>()',
    '"overrides": overrides.iter().map(|(main, reviewer)| (main.clone(), Value::String(reviewer.clone()))).collect::<serde_json::Map<String, Value>>()',
    "r24 generator metadata serialization",
)

# 2. r23/current CRUD layout places the long grokWeb explanatory comment BEFORE the
# actual validation block. The initial r24 anchor assumed the reverse order. Patch the
# generator to anchor only on the real validation block and the following stable MOC-257
# comment, so it composes with the current branch without touching that explanatory text.
old_add_anchor = r'''    add_anchor = '''    if let Some(gw) = input.grok_web.as_ref() {
        if let Err(errs) = validate_grok_web_input(gw) {
            return err(StatusCode::BAD_REQUEST, format_grok_web_errs(&errs)).into_response();
        }
    }

    // silent-failure-hunter H2 + chatgpt-codex P2:grokWeb 结构在 save 时校验,
'''
    add_repl = '''    if let Some(gw) = input.grok_web.as_ref() {
        if let Err(errs) = validate_grok_web_input(gw) {
            return err(StatusCode::BAD_REQUEST, format_grok_web_errs(&errs)).into_response();
        }
    }
    if let Some(overrides) = input.auto_review_model_overrides.as_ref() {
        if let Err(message) = validate_auto_review_model_overrides_input(overrides) {
            return err(StatusCode::BAD_REQUEST, message).into_response();
        }
    }

    // silent-failure-hunter H2 + chatgpt-codex P2:grokWeb 结构在 save 时校验,
'''
'''
new_add_anchor = r'''    add_anchor = '''    if let Some(gw) = input.grok_web.as_ref() {
        if let Err(errs) = validate_grok_web_input(gw) {
            return err(StatusCode::BAD_REQUEST, format_grok_web_errs(&errs)).into_response();
        }
    }

    // [MOC-257 review] 标记本次是否新建了「首个 provider」(自动成 active)——闭包内置位,闭包外据此补
'''
    add_repl = '''    if let Some(gw) = input.grok_web.as_ref() {
        if let Err(errs) = validate_grok_web_input(gw) {
            return err(StatusCode::BAD_REQUEST, format_grok_web_errs(&errs)).into_response();
        }
    }
    if let Some(overrides) = input.auto_review_model_overrides.as_ref() {
        if let Err(message) = validate_auto_review_model_overrides_input(overrides) {
            return err(StatusCode::BAD_REQUEST, message).into_response();
        }
    }

    // [MOC-257 review] 标记本次是否新建了「首个 provider」(自动成 active)——闭包内置位,闭包外据此补
'''
'''
patch(GEN, old_add_anchor, new_add_anchor, "r24 CRUD add-validation anchor")

# 3. Fix already-generated Rust if generation happened before this postflight pass.
generated = ROOT / "crates/codex_integration/src/auto_review_overlay.rs"
if generated.exists():
    patch(
        "crates/codex_integration/src/auto_review_overlay.rs",
        '"overrides": overrides.iter().cloned().collect::<serde_json::Map<String, Value>>()',
        '"overrides": overrides.iter().map(|(main, reviewer)| (main.clone(), Value::String(reviewer.clone()))).collect::<serde_json::Map<String, Value>>()',
        "generated metadata serialization",
    )

# 4. Restore the true catalog source BEFORE taking a snapshot. In preflight the r24
# block does not exist yet, so simply defer this check to the postflight invocation.
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
    elif late in text:
        text = text.replace(late, "", 1)
        if early_anchor not in text:
            raise SystemExit("r24 hardening: apply_provider entry anchor missing")
        text = text.replace(early_anchor, early, 1)
        apply_path.write_text(text, encoding="utf-8")
        print("r24 snapshot ordering: hardened")
    else:
        print("r24 snapshot ordering: preflight (generated block not present yet)")

print("r24 auto-review hardening complete")
