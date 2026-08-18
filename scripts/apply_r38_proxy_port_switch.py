from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PATH = ROOT / "src-tauri/src/proxy_runner.rs"
MARKER = "CAS-R38-PROXY-PORT-SWITCH"

body = PATH.read_text(encoding="utf-8")
if MARKER in body:
    print("r38 proxy port switch: already applied")
    raise SystemExit(0)

old = '''        // Fast path: already-published generation is the only state that may be reused.
        {
            let guard = self.handle.lock().unwrap();
            if let Some(h) = guard.as_ref() {
                lifecycle_log(
                    "INFO",
                    format!(
                        "reuse_listener listener_id={} app_pid={} requested_port={} actual_addr={}",
                        h.listener_id,
                        std::process::id(),
                        port,
                        h.addr
                    ),
                );
                return Ok(ProxyStatus {
                    running: true,
                    addr: Some(h.addr.to_string()),
                    gateway_auth: h.gateway_auth,
                    provider_count: h.provider_count,
                    active_provider: h.active_provider.clone(),
                });
            }
        }

        if self.start_in_progress.swap(true, Ordering::AcqRel) {
'''
new = '''        // CAS-R38-PROXY-PORT-SWITCH
        // Fast path may only reuse the exact requested port. r37/r38-slice1 reused any
        // published handle, which made a settings port change look successful while the
        // old listener remained active.
        let running_port = {
            let guard = self.handle.lock().unwrap();
            if let Some(h) = guard.as_ref() {
                if h.addr.port() == port {
                    lifecycle_log(
                        "INFO",
                        format!(
                            "reuse_listener listener_id={} app_pid={} requested_port={} actual_addr={}",
                            h.listener_id,
                            std::process::id(),
                            port,
                            h.addr
                        ),
                    );
                    return Ok(ProxyStatus {
                        running: true,
                        addr: Some(h.addr.to_string()),
                        gateway_auth: h.gateway_auth,
                        provider_count: h.provider_count,
                        active_provider: h.active_provider.clone(),
                    });
                }
                Some(h.addr.port())
            } else {
                None
            }
        };
        if let Some(old_port) = running_port {
            lifecycle_log(
                "INFO",
                format!(
                    "port_switch_requested app_pid={} old_port={old_port} requested_port={port}",
                    std::process::id()
                ),
            );
            self.stop().map_err(|e| {
                format!("cannot switch proxy port {old_port} -> {port}: {e}")
            })?;
        }

        if self.start_in_progress.swap(true, Ordering::AcqRel) {
'''
if old not in body:
    raise SystemExit("r38 proxy port switch: fast-path anchor missing")
body = body.replace(old, new, 1)
PATH.write_text(body, encoding="utf-8")
for token in (MARKER, "port_switch_requested", "h.addr.port() == port"):
    if token not in body:
        raise SystemExit(f"r38 proxy port switch missing {token}")
print("r38 proxy port switch: applied")
