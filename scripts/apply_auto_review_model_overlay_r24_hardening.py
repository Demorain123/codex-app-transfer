#!/usr/bin/env python3
"""Pre/post hardening for r24 Auto Review overlay.

The revision composer runs this script before AND after the base r24 generator:
- preflight patches generator defects/anchor drift before generation can fail;
- postflight fixes/validates generated Rust ordering and serialization.

Generated r24 files are materialized in the branch, so replay checks must be
semantic/idempotent rather than depend on one exact rustfmt layout.
"""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GEN = ROOT / "scripts/apply_auto_review_model_overlay_r24.py"


def replace_once(path: Path, old: str, new: str, label: str) -> None:
    text = path.read_text(encoding="utf-8")
    if new in text:
        print(f"{label}: already hardened")
        return
    if old not in text:
        raise SystemExit(f"r24 hardening anchor not found: {label}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")
    print(f"{label}: hardened")


def harden_generated_metadata(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    old = '"overrides": overrides.iter().cloned().collect::<serde_json::Map<String, Value>>()'
    fixed_single = '"overrides": overrides.iter().map(|(main, reviewer)| (main.clone(), Value::String(reviewer.clone()))).collect::<serde_json::Map<String, Value>>()'
    if old in text:
        path.write_text(text.replace(old, fixed_single, 1), encoding="utf-8")
        print("generated metadata serialization: hardened")
        return
    if (
        '"overrides": overrides' in text
        and "Value::String(reviewer.clone())" in text
        and "collect::<serde_json::Map<String, Value>>()" in text
    ):
        print("generated metadata serialization: already hardened (semantic)")
        return
    raise SystemExit("r24 hardening semantic check failed: generated metadata serialization")


def harden_generated_non_windows_path(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    if "        raw.into_owned()\n" in text:
        path.write_text(text.replace("        raw.into_owned()\n", "        raw\n", 1), encoding="utf-8")
        print("generated non-Windows path normalization: hardened")
        return
    if "fn normalized_path(path: &Path) -> String" in text and "        raw\n" in text:
        print("generated non-Windows path normalization: already hardened (semantic)")
        return
    raise SystemExit("r24 hardening semantic check failed: generated non-Windows path normalization")


# 0. Make generator replay-safe after generated files have been materialized/rustfmt'd.
# Exact old anchors are still required for mutation. Semantic markers are only used
# to prove that a particular patch is already present, so genuine source drift fails closed.
gen_text = GEN.read_text(encoding="utf-8")
old_replace_once = '''def replace_once(text: str, old: str, new: str, label: str) -> str:
    if new in text:
        return text
    if old not in text:
        raise SystemExit(f"r24 anchor not found: {label}")
    return text.replace(old, new, 1)
'''
new_replace_once = '''def replace_once(text: str, old: str, new: str, label: str) -> str:
    if new in text:
        return text
    # rustfmt can change wrapping/order around already-materialized patches.
    # Each rule names the final semantic marker and the minimum expected count.
    semantic_markers = {
        "ApplyConfig field": ("pub auto_review_model_overrides: Option<&'a serde_json::Value>", 1),
        "restore before apply": ("restore_source_if_overlay_active(paths)?", 1),
        "overlay after catalog": ("apply_auto_review_overrides(", 1),
        "provider helper": ("fn provider_auto_review_model_overrides", 1),
        "snapshot imports": ("provider_auto_review_model_overrides", 1),
        "target field": ("pub auto_review_model_overrides: Value", 1),
        "target init": ("auto_review_model_overrides: provider_auto_review_model_overrides(provider)", 1),
        "ApplyConfig init": ("auto_review_model_overrides: Some(&target.auto_review_model_overrides)", 1),
        "CRUD validator": ("fn validate_auto_review_model_overrides_input", 1),
        "CRUD input field": ("pub auto_review_model_overrides: Option<Value>", 1),
        "add validation": ("input.auto_review_model_overrides.as_ref()", 2),
        "update validation": ("input.auto_review_model_overrides.as_ref()", 2),
        "add persistence": ("new_provider.insert(\\\"autoReviewModelOverrides\\\"", 1),
        "update persistence": ("updated.insert(\\\"autoReviewModelOverrides\\\"", 1),
        "Provider type": ("autoReviewModelOverrides?: Record<string, string>", 2),
        "ProviderPayload type": ("autoReviewModelOverrides?: Record<string, string>", 2),
        "form field": ("autoReviewModelOverrides: '', // CAS-AUTO-REVIEW-R24", 1),
        "edit load": ("form.autoReviewModelOverrides = stringifyIfAny", 1),
        "save local": ("let autoReviewModelOverrides: Record<string, unknown> | undefined", 1),
        "parse overrides": ("autoReviewModelOverrides = parseJsonObj(", 1),
        "payload field": ("autoReviewModelOverrides: (autoReviewModelOverrides || {})", 1),
        "UI row": ("providerForm.autoReviewModelOverrides", 1),
    }
    rule = semantic_markers.get(label)
    if rule is not None:
        marker, minimum = rule
        if text.count(marker) >= minimum:
            return text
    # Whitespace-only layout changes are also safe to treat as already applied.
    if re.sub(r"\\s+", "", new) in re.sub(r"\\s+", "", text):
        return text
    if old not in text:
        raise SystemExit(f"r24 anchor not found: {label}")
    return text.replace(old, new, 1)
'''
if new_replace_once in gen_text:
    print("r24 generator replay helper: already hardened")
elif old_replace_once in gen_text:
    GEN.write_text(gen_text.replace(old_replace_once, new_replace_once, 1), encoding="utf-8")
    print("r24 generator replay helper: hardened")
else:
    raise SystemExit("r24 hardening anchor not found: generator replace_once helper")

# The provider-form reset/preset code used an unconditional str.replace, so every replay
# could append another assignment. Turn it into an explicit idempotent insertion.
gen_text = GEN.read_text(encoding="utf-8")
old_reset = '''    # reset and preset: the same literal appears twice; replace all remaining exact anchors intentionally.
    text = text.replace("  form.reviewModelSlot = ''\\n", "  form.reviewModelSlot = ''\\n  form.autoReviewModelOverrides = ''\\n")
'''
new_reset = '''    # reset and preset: insert only when the r24 assignment is not already adjacent.
    reset_anchor = "  form.reviewModelSlot = ''\\n"
    reset_repl = "  form.reviewModelSlot = ''\\n  form.autoReviewModelOverrides = ''\\n"
    if reset_repl not in text:
        text = text.replace(reset_anchor, reset_repl)
'''
if new_reset in gen_text:
    print("r24 provider-form reset replay: already hardened")
elif old_reset in gen_text:
    GEN.write_text(gen_text.replace(old_reset, new_reset, 1), encoding="utf-8")
    print("r24 provider-form reset replay: hardened")
else:
    raise SystemExit("r24 hardening anchor not found: provider-form reset replay")

# 1. Fix generator metadata serialization so generated Rust compiles.
replace_once(
    GEN,
    '"overrides": overrides.iter().cloned().collect::<serde_json::Map<String, Value>>()',
    '"overrides": overrides.iter().map(|(main, reviewer)| (main.clone(), Value::String(reviewer.clone()))).collect::<serde_json::Map<String, Value>>()',
    "r24 generator metadata serialization",
)

# 1b. `String::replace` already returns String; the original non-Windows branch
# accidentally called Cow::into_owned() on it.
replace_once(
    GEN,
    "        raw.into_owned()\n",
    "        raw\n",
    "r24 generator non-Windows path normalization",
)

# 2. Repair current-r23 CRUD anchor drift.
gen_text = GEN.read_text(encoding="utf-8")
old_comment = "    // silent-failure-hunter H2 + chatgpt-codex P2:grokWeb 结构在 save 时校验,\n"
new_comment = "    // [MOC-257 review] 标记本次是否新建了「首个 provider」(自动成 active)——闭包内置位,闭包外据此补\n"
count = gen_text.count(old_comment)
if count == 0:
    if gen_text.count(new_comment) >= 2:
        print("r24 CRUD add-validation anchor: already hardened")
    else:
        raise SystemExit("r24 hardening anchor not found: CRUD add-validation comment")
elif count == 2:
    GEN.write_text(gen_text.replace(old_comment, new_comment), encoding="utf-8")
    print("r24 CRUD add-validation anchor: hardened")
else:
    raise SystemExit(f"r24 hardening anchor count unexpected: {count}")

# 3. Fix/validate already-generated Rust if generation happened before this postflight pass.
generated = ROOT / "crates/codex_integration/src/auto_review_overlay.rs"
if generated.exists():
    harden_generated_metadata(generated)
    harden_generated_non_windows_path(generated)

# 4. Restore the true catalog source BEFORE taking a snapshot.
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
