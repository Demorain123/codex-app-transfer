from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CHAIN = ROOT / "src-tauri/src/admin/handlers/chain_health.rs"
MARKER = "CAS-R40-LIVE-BINDER-SELF-CLASSIFICATION"

body = CHAIN.read_text(encoding="utf-8")
if MARKER not in body:
    old = '''                // CAS-R40-PORT-OWNER-CLASSIFICATION
                .fact("owner_class=foreign_live")
                .fact(format!("owner_pid={} owner_alive=true", owner.pid))
                .fact(format!(
                    "owner_exe={}",
                    owner.executable.as_deref().unwrap_or("<unresolved>")
                ))
                .fact("recommended_action=stop_foreign_owner_safely"),
'''
    new = '''                // CAS-R40-PORT-OWNER-CLASSIFICATION
                // CAS-R40-LIVE-BINDER-SELF-CLASSIFICATION
                .fact(format!(
                    "owner_class={}",
                    if owner.pid == std::process::id() { "self_live" } else { "foreign_live" }
                ))
                .fact(format!("owner_pid={} owner_alive=true", owner.pid))
                .fact(format!(
                    "owner_exe={}",
                    owner.executable.as_deref().unwrap_or("<unresolved>")
                ))
                .fact(format!(
                    "recommended_action={}",
                    if owner.pid == std::process::id() {
                        "inspect_internal_lifecycle"
                    } else {
                        "stop_foreign_owner_safely"
                    }
                )),
'''
    count = body.count(old)
    if count != 1:
        raise SystemExit(f"r40 live binder classification anchor count={count}, expected 1")
    CHAIN.write_text(body.replace(old, new, 1), encoding="utf-8")

text = CHAIN.read_text(encoding="utf-8")
for token in [
    MARKER,
    '"self_live"',
    '"foreign_live"',
    '"inspect_internal_lifecycle"',
    '"stop_foreign_owner_safely"',
]:
    if token not in text:
        raise SystemExit(f"r40 live binder classification missing token: {token}")

print("r40 live binder self/foreign classification: applied")
