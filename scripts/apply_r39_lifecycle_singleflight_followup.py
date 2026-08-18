from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REL = "src-tauri/src/proxy_runner.rs"
MARKER = "CAS-R39-LIFECYCLE-SINGLEFLIGHT-FOLLOWUP"
path = ROOT / REL
body = path.read_text(encoding="utf-8")

if MARKER in body:
    print("r39 lifecycle single-flight follow-up: already applied")
    raise SystemExit(0)

old = '''        if self.starting.swap(true, Ordering::AcqRel) {
            return Err("proxy lifecycle busy: another start is already in progress".to_owned());
        }
        let _starting_reset = AtomicFlagReset(&self.starting);

        // If a previous server thread ended unexpectedly, remove its stale manager
'''
new = '''        if self.starting.swap(true, Ordering::AcqRel) {
            return Err("proxy lifecycle busy: another start is already in progress".to_owned());
        }
        let _starting_reset = AtomicFlagReset(&self.starting);
        // CAS-R39-LIFECYCLE-SINGLEFLIGHT-FOLLOWUP
        // Close the two-atomic race: stop may begin after the first `stopping`
        // read but before `starting` is claimed. Re-check after claiming start;
        // stop sets `stopping` before it waits for any in-flight start.
        if self.stopping.load(Ordering::Acquire) {
            return Err("proxy lifecycle busy: stop started while start was being claimed".to_owned());
        }

        // If a previous server thread ended unexpectedly, remove its stale manager
'''
if body.count(old) != 1:
    raise SystemExit("r39 single-flight follow-up: start gate anchor mismatch")
body = body.replace(old, new, 1)

old = '''    pub fn stop_verified(&self) -> ProxyStopReport {
        self.flush_session_cache();
        if !self.wait_for_start_to_finish_sync() {
            let report = ProxyStopReport::busy("proxy start did not finish before shutdown deadline");
            self.set_fault("proxy_lifecycle_busy", report.error.clone().unwrap_or_default());
            return report;
        }
        if self.stopping.swap(true, Ordering::AcqRel) {
            return ProxyStopReport::busy("proxy stop is already in progress");
        }
        let _stopping_reset = AtomicFlagReset(&self.stopping);
        let handle = self.handle.lock().unwrap().take();
'''
new = '''    pub fn stop_verified(&self) -> ProxyStopReport {
        self.flush_session_cache();
        // Claim STOP before waiting. This blocks every new start while an existing
        // start is draining and removes the check-then-act window between the two.
        if self.stopping.swap(true, Ordering::AcqRel) {
            return ProxyStopReport::busy("proxy stop is already in progress");
        }
        let _stopping_reset = AtomicFlagReset(&self.stopping);
        if !self.wait_for_start_to_finish_sync() {
            let report = ProxyStopReport::busy("proxy start did not finish before shutdown deadline");
            self.set_fault("proxy_lifecycle_busy", report.error.clone().unwrap_or_default());
            return report;
        }
        let handle = self.handle.lock().unwrap().take();
'''
if body.count(old) != 1:
    raise SystemExit("r39 single-flight follow-up: sync stop gate anchor mismatch")
body = body.replace(old, new, 1)

old = '''    pub async fn stop_verified_async(&self) -> ProxyStopReport {
        self.flush_session_cache();
        if !self.wait_for_start_to_finish().await {
            let report = ProxyStopReport::busy("proxy start did not finish before shutdown deadline");
            self.set_fault("proxy_lifecycle_busy", report.error.clone().unwrap_or_default());
            return report;
        }
        if self.stopping.swap(true, Ordering::AcqRel) {
            return ProxyStopReport::busy("proxy stop is already in progress");
        }
        let _stopping_reset = AtomicFlagReset(&self.stopping);
        let handle = self.handle.lock().unwrap().take();
'''
new = '''    pub async fn stop_verified_async(&self) -> ProxyStopReport {
        self.flush_session_cache();
        // Same ordering as the synchronous exit path: claim STOP first, then let
        // any already-owned start finish. New starts observe `stopping=true`.
        if self.stopping.swap(true, Ordering::AcqRel) {
            return ProxyStopReport::busy("proxy stop is already in progress");
        }
        let _stopping_reset = AtomicFlagReset(&self.stopping);
        if !self.wait_for_start_to_finish().await {
            let report = ProxyStopReport::busy("proxy start did not finish before shutdown deadline");
            self.set_fault("proxy_lifecycle_busy", report.error.clone().unwrap_or_default());
            return report;
        }
        let handle = self.handle.lock().unwrap().take();
'''
if body.count(old) != 1:
    raise SystemExit("r39 single-flight follow-up: async stop gate anchor mismatch")
body = body.replace(old, new, 1)

path.write_text(body, encoding="utf-8")
print("r39 lifecycle single-flight follow-up: COMPLETE")
