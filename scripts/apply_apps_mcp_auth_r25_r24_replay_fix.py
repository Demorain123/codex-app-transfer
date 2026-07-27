from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GEN = ROOT / "scripts/apply_auto_review_model_overlay_r24.py"
LIB = ROOT / "crates/codex_integration/src/lib.rs"
MARKER_LINE = "pub mod auto_review_overlay; // CAS-AUTO-REVIEW-R24"


def replace_once(text: str, old: str, new: str, *, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected exactly one anchor, found {count}")
    return text.replace(old, new, 1)


# CAS-APPS-MCP-AUTH-R25-R24-REPLAY-FIX
# r24's generic replace_once replay hardening did not register the `lib module`
# rule as a semantic marker. After rustfmt reordered module declarations, a complete
# second replay could therefore insert a second auto_review_overlay module line.
# Fix the source generator itself rather than weakening r25's idempotence check or
# deleting duplicates after the fact.
gen = GEN.read_text(encoding="utf-8")
old = '''def patch_lib() -> None:
    path = "crates/codex_integration/src/lib.rs"
    text = read(path)
    text = replace_once(text, "pub mod apply;\\n", "pub mod apply;\\npub mod auto_review_overlay; // CAS-AUTO-REVIEW-R24\\n", "lib module")
    write(path, text)
'''
new = '''def patch_lib() -> None:
    path = "crates/codex_integration/src/lib.rs"
    text = read(path)
    marker = "pub mod auto_review_overlay; // CAS-AUTO-REVIEW-R24"
    marker_count = text.count(marker)
    if marker_count == 0:
        anchor = "pub mod apply;\\n"
        if text.count(anchor) != 1:
            raise SystemExit(
                f"r24 lib module anchor count unexpected: {text.count(anchor)}"
            )
        text = text.replace(anchor, anchor + marker + "\\n", 1)
    elif marker_count == 1:
        # Already materialized. Module ordering may have changed after rustfmt; the
        # exact semantic marker is authoritative and replay must remain a no-op.
        pass
    else:
        raise SystemExit(
            f"r24 auto_review_overlay module registration duplicated: {marker_count}"
        )
    write(path, text)
'''
if new in gen:
    print("r24 lib module replay fix: already installed")
elif old in gen:
    GEN.write_text(replace_once(gen, old, new, label="r24 patch_lib replay fix"), encoding="utf-8")
    print("r24 lib module replay fix: installed")
else:
    raise SystemExit("r25 prerequisite: r24 patch_lib shape drifted; manual review required")

# Current materialized base must itself be sane before the r24 generator runs. Do not
# silently repair a branch that already contains duplicates; surface it for review.
if LIB.is_file():
    count = LIB.read_text(encoding="utf-8").count(MARKER_LINE)
    if count not in (0, 1):
        raise SystemExit(
            f"r25 prerequisite: existing r24 module registration count is {count}, expected 0 or 1"
        )

# Final source-level gate: the generic `lib module` replace_once must be gone from
# patch_lib, and the explicit 0/1/>1 state machine must be present.
gen = GEN.read_text(encoding="utf-8")
for required in (
    'marker = "pub mod auto_review_overlay; // CAS-AUTO-REVIEW-R24"',
    "marker_count = text.count(marker)",
    "if marker_count == 0:",
    "elif marker_count == 1:",
    "r24 auto_review_overlay module registration duplicated",
):
    if required not in gen:
        raise SystemExit(f"r25 prerequisite: r24 replay invariant missing: {required}")

print("r25 prerequisite: r24 Auto Review module replay is idempotent by construction")
