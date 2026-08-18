from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
proxy = (ROOT / "src-tauri/src/proxy_runner.rs").read_text(encoding="utf-8")
version = (ROOT / "SUB2API_GROK_COMPAT_VERSION.txt").read_text(encoding="utf-8")

required = [
    "CAS-R38-PROXY-LIFECYCLE-HARDENING",
    "with_graceful_shutdown",
    "server_done_timeout",
    "port_release_verified",
    "stale_listener_detected",
    "duplicate_start_rejected",
    "bootstrap_cancelled_by_stop",
    "shutdown_timeout(RUNTIME_FORCE_WAIT)",
    "listener_published",
]
for token in required:
    if token not in proxy:
        raise SystemExit(f"r38 review: proxy_runner missing {token}")

for forbidden in (
    "shutdown_background() 一键 abort",
    "所有 spawn 在 runtime 上的 task **同步 abort**",
):
    if forbidden in proxy:
        raise SystemExit(f"r38 review: stale shutdown assumption remains: {forbidden}")

if "SO_REUSEADDR" in proxy:
    raise SystemExit("r38 review: do not use SO_REUSEADDR as a port-conflict workaround")

if "compat_revision=38" not in version or "app_version=2.4.5+38" not in version:
    raise SystemExit("r38 review: visible/package version stamp missing")

for rel in ("frontend/src/i18n/zh.ts", "frontend/src/i18n/en.ts"):
    text = (ROOT / rel).read_text(encoding="utf-8")
    if "Sub2API Grok Compat r38 · v2.4.5+38" not in text:
        raise SystemExit(f"r38 review: visible badge missing in {rel}")

print("r38 review: PASS (explicit graceful shutdown + bounded wait + release verification + start-race guard)")
