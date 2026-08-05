from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "src-tauri/src/admin/handlers/chain_health.rs"

body = TARGET.read_text(encoding="utf-8")
body = body.replace(
    "use chrono::{Local, NaiveTime};",
    "use chrono::{Local, NaiveTime, Timelike};",
    1,
)
body = body.replace(
    "        base_url: raw.to_owned(),",
    "        // CAS-R33-CHAIN-HEALTH-PRIVACY: never serialize URL userinfo/query/fragment.\n"
    "        base_url: url.to_string().trim_end_matches('/').to_owned(),",
    1,
)
if "CAS-R33-CHAIN-HEALTH-PRIVACY" not in body:
    raise SystemExit("r33 privacy hardening anchor did not apply")
TARGET.write_text(body, encoding="utf-8")
print("r33 chain health hardening: COMPLETE")
