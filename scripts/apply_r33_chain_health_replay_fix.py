from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def ensure_after(rel: str, required: str, anchor: str, insertion: str) -> None:
    path = ROOT / rel
    body = path.read_text(encoding="utf-8")
    if required in body:
        print(f"r33 replay wiring already present: {rel}: {required}")
        return
    if anchor not in body:
        raise SystemExit(f"r33 replay wiring anchor missing in {rel}: {anchor}")
    path.write_text(body.replace(anchor, anchor + insertion, 1), encoding="utf-8")
    print(f"r33 replay wiring restored: {rel}: {required}")


ensure_after(
    "src-tauri/src/admin/handlers/mod.rs",
    "pub mod chain_health;",
    "pub mod chrome;",
    "\n// CAS-R33-CHAIN-HEALTH-REPLAY-WIRING\npub mod chain_health;",
)

ensure_after(
    "src-tauri/src/admin/mod.rs",
    '.route("/api/chain-health", get(handlers::chain_health::chain_health))',
    '        .route("/api/proxy/status", get(handlers::proxy::proxy_status))',
    '\n        // CAS-R33-CHAIN-HEALTH-REPLAY-WIRING\n'
    '        .route("/api/chain-health", get(handlers::chain_health::chain_health))',
)

cargo = ROOT / "src-tauri/Cargo.toml"
body = cargo.read_text(encoding="utf-8")
line = next((line for line in body.splitlines() if line.startswith("tokio = ")), None)
if line is None:
    raise SystemExit("r33 replay wiring: tokio dependency line missing")
if '"process"' not in line:
    if '"net", ' not in line:
        raise SystemExit("r33 replay wiring: tokio features anchor missing")
    body = body.replace(line, line.replace('"net", ', '"net", "process", ', 1), 1)
    cargo.write_text(body, encoding="utf-8")
    print("r33 replay wiring restored: tokio process feature")
else:
    print("r33 replay wiring already present: tokio process feature")

print("r33 chain-health inherited replay wiring: PASS")
