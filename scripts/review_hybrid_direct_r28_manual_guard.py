from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
path = ROOT / "src-tauri/src/admin/handlers/desktop.rs"
text = path.read_text(encoding="utf-8")

checks = [
    (
        "pub async fn desktop_clear()",
        "CAS-HYBRID-DIRECT-R28-MANUAL-CLEAR-GUARD",
        "restore_codex_state(&paths)",
        "desktop_clear",
    ),
    (
        "pub async fn desktop_restore(",
        "CAS-HYBRID-DIRECT-R28-MANUAL-RESTORE-GUARD",
        "restore_codex_snapshot(&paths",
        "desktop_restore",
    ),
    (
        "pub async fn desktop_repair_residual(",
        "CAS-HYBRID-DIRECT-R28-RESIDUAL-REPAIR-GUARD",
        "repair_residual_pollution(&report",
        "desktop_repair_residual",
    ),
]

for fn_marker, guard, mutation, label in checks:
    start = text.find(fn_marker)
    if start < 0:
        raise SystemExit(f"r28 manual review: {label} function missing")
    guard_pos = text.find(guard, start)
    mutation_pos = text.find(mutation, start)
    if guard_pos < 0 or mutation_pos < 0 or guard_pos >= mutation_pos:
        raise SystemExit(
            f"r28 manual review: {label} guard must precede mutation ({guard_pos=} {mutation_pos=})"
        )
    scope = text[start:mutation_pos]
    for required in (
        "hybrid_direct::enabled()",
        "StatusCode::CONFLICT",
        "hybrid_direct::mutation_blocked(",
    ):
        if required not in scope:
            raise SystemExit(f"r28 manual review: {label} missing fail-closed token {required}")

# Read-only residual scan deliberately remains available; do not accidentally block it
# or force users to disable Hybrid Direct merely to inspect diagnostics.
scan_start = text.find("pub async fn desktop_scan_residual()")
repair_start = text.find("pub async fn desktop_repair_residual(")
if scan_start < 0 or repair_start < 0 or scan_start >= repair_start:
    raise SystemExit("r28 manual review: residual scan/repair ordering changed unexpectedly")
scan_scope = text[scan_start:repair_start]
if "CAS-HYBRID-DIRECT-R28-RESIDUAL-REPAIR-GUARD" in scan_scope:
    raise SystemExit("r28 manual review: read-only residual scan was accidentally blocked")

print("r28 Hybrid Direct manual mutation API review: PASS")
