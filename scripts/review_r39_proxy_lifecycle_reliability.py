from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MARKER = "CAS-R39-PROXY-LIFECYCLE-RELIABILITY"


def read(rel: str) -> str:
    path = ROOT / rel
    if not path.is_file():
        raise SystemExit(f"r39 review missing file: {rel}")
    return path.read_text(encoding="utf-8")


def require(rel: str, *needles: str) -> str:
    body = read(rel)
    for needle in needles:
        if needle not in body:
            raise SystemExit(f"r39 review missing marker in {rel}: {needle}")
    return body


runner = require(
    "src-tauri/src/proxy_runner.rs",
    MARKER,
    "with_graceful_shutdown",
    "ProxyStopReport",
    "stop_verified_async",
    "port_release_verified=",
    "server_task_exited",
    "server_task_aborted",
    "PROXY_LISTENER_SEQUENCE",
    "proxy_port_not_released",
    "proxy_port_in_use",
    "lifecycle_r39_rapid_same_port_restart_loop",
    "lifecycle_r39_external_listener_is_never_reused_or_killed",
)
# The inherited r37/r38 header comment mentions shutdown_background() while
# explaining the old design. Reject only an executable method call, not that
# historical comment text.
if ".shutdown_background(" in runner:
    raise SystemExit("r39 review: proxy_runner still calls shutdown_background as lifecycle control")
if "set_reuseaddr" in runner or "SO_REUSEADDR" in runner or "SO_LINGER" in runner:
    raise SystemExit("r39 review: forbidden socket-reuse/linger workaround detected in proxy_runner")

handler = require(
    "src-tauri/src/admin/handlers/proxy.rs",
    MARKER,
    "stop_verified_async().await",
    "external_or_stale_listener",
    "不自动 kill",
)
if "[50, 100, 200, 400, 800]" in handler:
    raise SystemExit("r39 review: inherited blind 1.55s retry ladder still present")

health = require(
    "src-tauri/src/admin/handlers/chain_health.rs",
    MARKER,
    "RECOVERY_ACTIVE_R39",
    "recovery_in_progress",
    "cooldown_ms",
    "transfer_port_in_use",
    "stop_verified_async().await",
    "保留现场，不自动结束其他进程",
)
if "tokio::time::sleep(Duration::from_millis(150))" in health:
    raise SystemExit("r39 review: fixed 150ms listener shutdown guess still present")

api = require(
    "frontend/src/api/chainHealth.ts",
    MARKER,
    "cooldownMs: number",
)
page = require(
    "frontend/src/pages/ProxyPage.vue",
    MARKER,
    "chainRecoveryCooldownSeconds",
    "recovery_in_progress",
    "chainHealth.recovering",
    "chainHealth.recoveryCooldown",
)
for rel in ("frontend/src/i18n/zh.ts", "frontend/src/i18n/en.ts"):
    require(
        rel,
        MARKER,
        "chainHealth.recovering",
        "chainHealth.recoveryCooldown",
        "chainHealth.recoveryInProgress",
    )

main = require(
    "src-tauri/src/main.rs",
    '"quit" => {',
    "manager.stop_silent();",
    "app.exit(0);",
    "RunEvent::Exit",
)
if main.count("manager.stop_silent();") < 2:
    raise SystemExit("r39 review: tray quit + RunEvent exit cleanup paths are not both wired")

# No destructive auto-recovery should be introduced for an unknown port owner.
combined = "\n".join((runner, handler, health))
for forbidden in ("taskkill", "Stop-Process", "TerminateProcess", "process::Command::new(\"kill\")"):
    if forbidden in combined:
        raise SystemExit(f"r39 review: destructive port-owner action introduced: {forbidden}")

version = read("SUB2API_GROK_COMPAT_VERSION.txt")
if "compat_revision=39" not in version or "app_version=2.4.5+39" not in version:
    raise SystemExit("r39 review: revision/version stamp mismatch")

print("r39 proxy lifecycle reliability review: PASS")
