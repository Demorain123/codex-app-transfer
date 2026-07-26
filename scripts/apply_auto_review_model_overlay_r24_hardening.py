#!/usr/bin/env python3
"""Pre/post hardening for r24 Auto Review overlay.

The revision composer runs this script before AND after the base r24 generator:
- preflight patches generator defects/anchor drift before generation can fail;
- postflight fixes/validates generated Rust ordering and serialization.

The generated r24 Rust module is now also materialized in the branch. Therefore
postflight checks must be semantic/idempotent rather than depend on one exact
rustfmt layout.
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
    """Accept both generator formatting and rustfmt materialized formatting."""
    text = path.read_text(encoding="utf-8")
    old = '"overrides": overrides.iter().cloned().collect::<serde_json::Map<String, Value>>()'
    fixed_single = '"overrides": overrides.iter().map(|(main, reviewer)| (main.clone(), Value::String(reviewer.clone()))).collect::<serde_json::Map<String, Value>>()'
    if old in text:
        path.write_text(text.replace(old, fixed_single, 1), encoding="utf-8")
        print("generated metadata serialization: hardened")
        return
    # rustfmt expands the iterator chain over several lines. These markers prove the
    # same semantic conversion String -> Value is present without pinning whitespace.
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


# 1. Fix generator metadata serialization so generated Rust compiles.
replace_once(
    GEN,
    '"overrides": overrides.iter().cloned().collect::<serde_json::Map<String, Value>>()',
    '"overrides": overrides.iter().map(|(main, reviewer)| (main.clone(), Value::String(reviewer.clone()))).collect::<serde_json::Map<String, Value>>()',
    "r24 generator metadata serialization",
)

# 1b. `String::replace` already returns String; the original non-Windows branch
# accidentally called Cow::into_owned() on it. Fix the generator before Linux CI compiles.
replace_once(
    GEN,
    "        raw.into_owned()\n",
    "        raw\n",
    "r24 generator non-Windows path normalization",
)

# 2. Repair current-r23 CRUD anchor drift. The long explanatory grokWeb comment is
# before the actual validation block, so use the stable MOC-257 line that really follows
# the block. Both the generator's anchor and replacement carry the same trailing line,
# therefore replacing the two embedded comment lines is sufficient and deterministic.
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
# This must tolerate rustfmt because the generated module is now materialized in the branch.
generated = ROOT / "crates/codex_integration/src/auto_review_overlay.rs"
if generated.exists():
    harden_generated_metadata(generated)
    harden_generated_non_windows_path(generated)

# 4. Restore the true catalog source BEFORE taking a snapshot. In preflight the r24
# block does not exist yet, so defer this check to the postflight invocation.
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
