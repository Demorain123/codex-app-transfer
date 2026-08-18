from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PATH = ROOT / "src-tauri/src/proxy_runner.rs"
MARKER = "CAS-R39-OWNER-THREAD-STATE-GUARD"

body = PATH.read_text(encoding="utf-8")
if MARKER in body:
    print("r39 owner-thread state guard: already applied")
    raise SystemExit(0)

old = '''    pub async fn start(&self, port: u16) -> Result<ProxyStatus, String> {
        let running_port = {
'''
new = '''    pub async fn start(&self, port: u16) -> Result<ProxyStatus, String> {
        // CAS-R39-OWNER-THREAD-STATE-GUARD
        // A server future can terminate independently (panic/error/runtime failure). Never
        // reuse a published generation whose dedicated owner thread has already exited.
        let finished_handle = {
            let mut guard = self.handle.lock().unwrap();
            let finished = guard
                .as_ref()
                .and_then(|h| h.owner_thread.as_ref())
                .map(|owner| owner.is_finished())
                .unwrap_or(false);
            if finished { guard.take() } else { None }
        };
        if let Some(handle) = finished_handle {
            lifecycle_log(
                "WARN",
                format!(
                    "finished_owner_generation_detected listener_id={} app_pid={} addr={}",
                    handle.listener_id,
                    std::process::id(),
                    handle.addr
                ),
            );
            if !shutdown_proxy_handle(handle, "finished_owner_generation") {
                return Err(
                    "previous proxy owner thread exited but its listener port is not bindable"
                        .to_owned(),
                );
            }
        }

        let running_port = {
'''
if old not in body:
    raise SystemExit("r39 owner state guard: start anchor missing")
body = body.replace(old, new, 1)

old = '''        match guard.as_ref() {
            Some(h) => ProxyStatus {
                running: true,
                addr: Some(h.addr.to_string()),
                gateway_auth: h.gateway_auth,
                provider_count: h.provider_count,
                active_provider: h.active_provider.clone(),
            },
'''
new = '''        match guard.as_ref() {
            Some(h) => {
                let owner_finished = h
                    .owner_thread
                    .as_ref()
                    .map(|owner| owner.is_finished())
                    .unwrap_or(true);
                ProxyStatus {
                    running: !owner_finished,
                    addr: if owner_finished { None } else { Some(h.addr.to_string()) },
                    gateway_auth: !owner_finished && h.gateway_auth,
                    provider_count: if owner_finished { 0 } else { h.provider_count },
                    active_provider: if owner_finished { None } else { h.active_provider.clone() },
                }
            },
'''
if old not in body:
    raise SystemExit("r39 owner state guard: status anchor missing")
body = body.replace(old, new, 1)

PATH.write_text(body, encoding="utf-8")

check = PATH.read_text(encoding="utf-8")
for token in (
    MARKER,
    "finished_owner_generation_detected",
    "owner.is_finished()",
    "previous proxy owner thread exited but its listener port is not bindable",
):
    if token not in check:
        raise SystemExit(f"r39 owner state guard missing marker: {token}")

print("r39 owner-thread state guard: applied")
