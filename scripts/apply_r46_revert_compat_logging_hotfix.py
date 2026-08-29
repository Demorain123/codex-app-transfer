from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "src-tauri/src/admin/handlers/thread_recovery.rs"
text = TARGET.read_text(encoding="utf-8")
MARKER = "CAS-R46-REVERT-COMPAT-LOGGING-HOTFIX"

if MARKER in text:
    print("r46 revert compatibility/logging hotfix already applied")
    raise SystemExit(0)

old_rpc_impl = '''impl std::fmt::Display for RpcError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        if let Some(code) = self.code {
            write!(f, "RPC {code}: {}", self.message)
        } else {
            f.write_str(&self.message)
        }
    }
}

impl RpcError {
    fn method_not_found(&self) -> bool {
        self.code == Some(-32601)
            || self
                .message
                .to_ascii_lowercase()
                .contains("method not found")
    }
}
'''
new_rpc_impl = '''// CAS-R46-REVERT-COMPAT-LOGGING-HOTFIX
fn bounded_rpc_message(message: &str) -> String {
    const MAX_CHARS: usize = 360;
    let mut chars = message.chars();
    let head: String = chars.by_ref().take(MAX_CHARS).collect();
    if chars.next().is_some() {
        format!("{head} … [app-server error truncated]")
    } else {
        head
    }
}

impl std::fmt::Display for RpcError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        let message = bounded_rpc_message(&self.message);
        if let Some(code) = self.code {
            write!(f, "RPC {code}: {message}")
        } else {
            f.write_str(&message)
        }
    }
}

impl RpcError {
    fn method_not_found(&self) -> bool {
        let lower = self.message.to_ascii_lowercase();
        self.code == Some(-32601)
            || lower.contains("method not found")
            // Older bundled app-server builds deserialize request methods as an enum
            // and report an unsupported method as `unknown variant ... expected one of`.
            // Treat that shape as method-not-found ONLY for thread/revert so the
            // existing, bounded rollback(1) compatibility fallback can run.
            || (lower.contains("unknown variant") && lower.contains("thread/revert"))
            || (lower.contains("expected one of")
                && lower.contains("thread/revert")
                && lower.contains("thread/rollback"))
    }
}
'''
if old_rpc_impl not in text:
    raise SystemExit("r46 revert compat hotfix: RpcError anchor missing")
text = text.replace(old_rpc_impl, new_rpc_impl, 1)

call_anchor = '''    fn call(&mut self, method: &str, params: Value) -> Result<Value, RpcError> {
        let id = self.next_id;
        self.next_id = self.next_id.saturating_add(1);
'''
call_replacement = '''    fn call(&mut self, method: &str, params: Value) -> Result<Value, RpcError> {
        let id = self.next_id;
        self.next_id = self.next_id.saturating_add(1);
        proxy_telemetry().logs.add(
            "INFO",
            format!("[thread-recovery-r46] stage=rpc_call method={method}"),
        );
'''
if call_anchor not in text:
    raise SystemExit("r46 revert compat hotfix: rpc_call anchor missing")
text = text.replace(call_anchor, call_replacement, 1)

old_error = '''            if let Some(error) = message.get("error") {
                return Err(RpcError {
                    code: error.get("code").and_then(Value::as_i64),
                    message: error
                        .get("message")
                        .and_then(Value::as_str)
                        .unwrap_or("unknown app-server error")
                        .to_owned(),
                });
            }
            return Ok(message.get("result").cloned().unwrap_or(Value::Null));
'''
new_error = '''            if let Some(error) = message.get("error") {
                let rpc_error = RpcError {
                    code: error.get("code").and_then(Value::as_i64),
                    message: error
                        .get("message")
                        .and_then(Value::as_str)
                        .unwrap_or("unknown app-server error")
                        .to_owned(),
                };
                proxy_telemetry().logs.add(
                    "WARN",
                    format!(
                        "[thread-recovery-r46] stage=rpc_error method={} code={} class={} message_bytes={}",
                        method,
                        rpc_error.code.map(|v| v.to_string()).unwrap_or_else(|| "none".into()),
                        if rpc_error.method_not_found() { "method_unavailable" } else { "rpc_error" },
                        rpc_error.message.len(),
                    ),
                );
                return Err(rpc_error);
            }
            proxy_telemetry().logs.add(
                "INFO",
                format!("[thread-recovery-r46] stage=rpc_ok method={method}"),
            );
            return Ok(message.get("result").cloned().unwrap_or(Value::Null));
'''
if old_error not in text:
    raise SystemExit("r46 revert compat hotfix: rpc result anchor missing")
text = text.replace(old_error, new_error, 1)

for marker in (
    MARKER,
    "app-server error truncated",
    "unknown variant",
    "stage=rpc_call",
    "stage=rpc_error",
    "stage=rpc_ok",
    "method_unavailable",
):
    if marker not in text:
        raise SystemExit(f"r46 revert compat hotfix invariant missing: {marker}")

TARGET.write_text(text, encoding="utf-8")
print("R46 REVERT COMPAT + RECOVERY LOGGING HOTFIX PASS")
