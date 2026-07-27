from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "src-tauri/src/admin/handlers/desktop.rs"
text = TARGET.read_text(encoding="utf-8")


def replace_once(old: str, new: str, label: str) -> None:
    global text
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"r28 manual guard {label}: expected exactly one anchor, found {count}")
    text = text.replace(old, new, 1)


# CAS-HYBRID-DIRECT-R28-MANUAL-CLEAR-GUARD
# `desktop_clear` restores Transfer snapshots and unstashes auth.json. That is a useful
# transition operation BEFORE Hybrid Direct is enabled, but once CC Switch owns live
# Codex provider/auth state it must be impossible to replay an older Transfer snapshot.
if "CAS-HYBRID-DIRECT-R28-MANUAL-CLEAR-GUARD" not in text:
    replace_once(
        "pub async fn desktop_clear() -> impl IntoResponse {\n",
        '''pub async fn desktop_clear() -> impl IntoResponse {
    // CAS-HYBRID-DIRECT-R28-MANUAL-CLEAR-GUARD
    if crate::admin::services::desktop::hybrid_direct::enabled() {
        return err(
            StatusCode::CONFLICT,
            crate::admin::services::desktop::hybrid_direct::mutation_blocked(
                "手动清除/还原 Codex config.toml 与 auth.json",
            ),
        )
        .into_response();
    }
''',
        "desktop_clear",
    )

# CAS-HYBRID-DIRECT-R28-MANUAL-RESTORE-GUARD
if "CAS-HYBRID-DIRECT-R28-MANUAL-RESTORE-GUARD" not in text:
    replace_once(
        "pub async fn desktop_restore(Json(payload): Json<DesktopRestoreRequest>) -> impl IntoResponse {\n",
        '''pub async fn desktop_restore(Json(payload): Json<DesktopRestoreRequest>) -> impl IntoResponse {
    // CAS-HYBRID-DIRECT-R28-MANUAL-RESTORE-GUARD
    if crate::admin::services::desktop::hybrid_direct::enabled() {
        return err(
            StatusCode::CONFLICT,
            crate::admin::services::desktop::hybrid_direct::mutation_blocked(
                "恢复历史 Transfer Codex 快照",
            ),
        )
        .into_response();
    }
''',
        "desktop_restore",
    )

# CAS-HYBRID-DIRECT-R28-RESIDUAL-REPAIR-GUARD
# A legitimate CC Switch Grok provider intentionally points to Transfer localhost. The
# legacy residual detector knows Transfer ports and could classify that live route as
# pollution; never allow its repair path to strip CC Switch-owned config in Hybrid mode.
# The read-only scan endpoint remains available for diagnostics.
if "CAS-HYBRID-DIRECT-R28-RESIDUAL-REPAIR-GUARD" not in text:
    replace_once(
        '''pub async fn desktop_repair_residual(
    Json(payload): Json<ResidualRepairRequest>,
) -> impl IntoResponse {
''',
        '''pub async fn desktop_repair_residual(
    Json(payload): Json<ResidualRepairRequest>,
) -> impl IntoResponse {
    // CAS-HYBRID-DIRECT-R28-RESIDUAL-REPAIR-GUARD
    if crate::admin::services::desktop::hybrid_direct::enabled() {
        return err(
            StatusCode::CONFLICT,
            crate::admin::services::desktop::hybrid_direct::mutation_blocked(
                "执行 Transfer residual repair（可能误删 CC Switch 的 Grok→Transfer 路由）",
            ),
        )
        .into_response();
    }
''',
        "desktop_repair_residual",
    )

TARGET.write_text(text, encoding="utf-8")

for marker in (
    "CAS-HYBRID-DIRECT-R28-MANUAL-CLEAR-GUARD",
    "CAS-HYBRID-DIRECT-R28-MANUAL-RESTORE-GUARD",
    "CAS-HYBRID-DIRECT-R28-RESIDUAL-REPAIR-GUARD",
):
    if text.count(marker) != 1:
        raise SystemExit(f"r28 manual guard materialization invalid: {marker} count={text.count(marker)}")

print("r28 Hybrid Direct manual Codex mutation guards: materialized")
