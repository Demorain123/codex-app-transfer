from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PATH = ROOT / "src-tauri/src/admin/handlers/chain_health.rs"
MARKER = "CAS-R38-RECOVERY-ASYNC-STOP"

body = PATH.read_text(encoding="utf-8")
if MARKER in body:
    print("r38 recovery async stop: already applied")
    raise SystemExit(0)

old = '''    if force_refresh && state.proxy_manager.status().running {
        if let Err(error) = state.proxy_manager.stop() {
            return RecoveryAction::failed(
                "stop_transfer_verified",
                format!("Transfer stop 未通过端口释放验证，已中止后续 rebind: {}", compact_error(&error)),
            );
        }
    }
'''
new = '''    if force_refresh && state.proxy_manager.status().running {
        // CAS-R38-RECOVERY-ASYNC-STOP: verified stop may wait for graceful shutdown + OS port
        // release. Keep that bounded synchronous barrier off Tokio request workers.
        let manager = state.proxy_manager.clone();
        match tokio::task::spawn_blocking(move || manager.stop()).await {
            Ok(Ok(())) => {}
            Ok(Err(error)) => {
                return RecoveryAction::failed(
                    "stop_transfer_verified",
                    format!("Transfer stop 未通过端口释放验证，已中止后续 rebind: {}", compact_error(&error)),
                );
            }
            Err(error) => {
                return RecoveryAction::failed(
                    "stop_transfer_verified",
                    format!("Transfer stop worker 异常，已中止后续 rebind: {}", compact_error(&error.to_string())),
                );
            }
        }
    }
'''
if old not in body:
    raise SystemExit("r38 recovery async stop: verified stop anchor missing")
body = body.replace(old, new, 1)
PATH.write_text(body, encoding="utf-8")

for token in (MARKER, "spawn_blocking(move || manager.stop())", "stop_transfer_verified"):
    if token not in body:
        raise SystemExit(f"r38 recovery async stop missing {token}")
print("r38 recovery async stop: applied")
