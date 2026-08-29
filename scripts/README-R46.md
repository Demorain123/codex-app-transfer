# r46 — Model Switch Old-Thread Recovery + Structural Forensics

Target branch: `dev-r46-model-switch-old-thread-recovery-local`

Base: r45 model-switch continuity + Responses semantic-terminal handling.

## Why r46 exists

The real 2026-08-29 incident is not explained by a single statement such as "the request is too large" or "Grok is broken".

Observed sequence for the affected long-lived thread:

1. The same large thread worked for hours on `gpt-5.6-luna`.
2. Switching Luna -> `gpt-5.6-sol` produced ~14.2 MB 502/503 requests, but switching back to Luna recovered. This proves a large request alone is not sufficient to explain the persistent state.
3. Luna -> `grok-4.6` succeeded.
4. A later automatic pre-turn compaction unexpectedly used stale `gpt-5.6-luna` while the effective main model was Grok. The ~13.85 MB compaction failed with raw HTTP 400.
5. The main thread returned to Grok, then switched to `gpt-5.6-terra`.
6. Terra normal turns on the affected thread repeatedly sent ~13.94 MB and failed with raw 400.
7. A user-requested manual compaction correctly used Terra, but it still had to upload essentially the same ~13.94 MB history and also failed with raw 400.
8. Fresh Terra threads using the same provider continued to return 200.

Therefore r46 treats the failure as two separate layers:

- **prevention** — preserve the session's effective model across model switches and internal helpers (r45);
- **recovery** — once a persisted old thread is already stuck, allow safe local history recovery rather than repeatedly resending the same failing history (r46).

The precise invalid upstream payload element is **not yet proven**. Candidate classes include cross-model reasoning/history items, compaction state, tool-history shape, or a model/provider constraint that becomes visible only with the large mixed-model history. r46 adds structural diagnostics to distinguish those cases without logging message content.

## Recovery Center

The Proxy / Chain Health page gets **旧会话恢复**.

### Read-only preview

Opening Recovery Center first performs a read-only preview. It may auto-detect the newest failed thread from the local `proxy-*.log`, or the user can paste an exact thread id.

Preview shows only:

- thread fingerprint / exact local thread id;
- latest structural failure metadata (model, request kind, raw status, byte size, compaction trigger/reason);
- rollout path / size / SHA256;
- whether the bundled Codex app-server executable can be located.

No model request is sent.

### Same-thread recovery — recommended first

`同 ID 回退 1 轮（推荐）`

Safety contract:

1. Acquire the existing Codex maintenance lock.
2. Close Codex Desktop using the project's existing `with_codex_closed` path.
3. Copy the entire rollout into `~/.codex-app-transfer/thread-recovery/<timestamp>-<fingerprint>/source-backup/`.
4. Write `RECOVERY-BACKUP.json` containing the backup path, byte length and SHA256.
5. Start the bundled local `codex app-server` over stdio.
6. Read the newest persisted turn boundary.
7. Prefer current `thread/revert { beforeTurnId: newest }`.
8. If and only if app-server reports method-not-found, fall back to deprecated `thread/rollback { numTurns: 1 }` for compatibility with older bundled Codex builds.
9. Stop the temporary app-server and relaunch Codex if it was running before recovery.

One click can remove **at most one persisted turn**. It never loops over multiple turns.

The thread id is preserved.

### Recovery copy — non-destructive fallback

`创建恢复副本（原会话不动）`

This creates a new thread through the prior persisted boundary with `thread/fork`. The source thread is not changed. It is the safer fallback if same-thread recovery is unavailable or if preserving the original evidence is more important than preserving the thread id.

### Workspace boundary

Conversation recovery deliberately does **not** revert workspace files. A conversation rollback and a source-tree rollback are different operations. r46 reports `workspaceFilesChanged=false` for its own recovery action and does not run git reset/checkout/clean.

## Structural forensics

Generated `crates/proxy/src/forward.rs` gains `[model-switch-forensics-r46]` events.

They record only non-content structure:

- 8-char/short non-reversible session fingerprint;
- `request_kind` from `x-codex-turn-metadata` (authoritative when present);
- requested / resolved / prior effective model;
- model-switch boolean;
- compaction helper rebind boolean;
- cross-model compaction mismatch boolean;
- compaction trigger / reason;
- request body byte length;
- deterministic FNV64 body fingerprint (for detecting exact repeated replay without storing the body);
- input item count and per-type counts;
- message / reasoning / compaction / tool-like / unknown item counts;
- declared tool count;
- presence of `previous_response_id`;
- instruction byte length;
- final raw upstream status and client-facing status.

It never records:

- prompt or response text;
- tool arguments;
- raw thread/session ids in the forensics log;
- encrypted reasoning/compaction content;
- credentials/tokens;
- attachment contents.

### Important r46 classifications

`event=model_switch`
: A normal main turn moves from the previous effective model to a new model.

`event=cross_model_compaction_mismatch`
: The compaction helper's requested model does not match the session's effective model before r45 rebinding.

`event=compaction_model_rebound`
: r45/r46 corrected the stale helper model before provider routing.

`event=large_history`
: A >=1 MiB request is structurally summarized.

`event=result ... failed_compaction_preserves_history=true`
: A compaction request failed upstream, so the old history should be assumed to remain active until proven otherwise.

`event=raw_client_status_mismatch`
: Example raw upstream 400 -> client-facing 200. This is important because the Desktop may render a success-like lifecycle event even though the real upstream operation failed.

## Why `request_kind` matters

`remote_compaction_v2` is a capability flag and can also be present on normal turns. r46 therefore treats `x-codex-turn-metadata.request_kind` as authoritative when present. A normal turn carrying the beta feature flag must not be reclassified as a compaction helper.

## Materialize

```powershell
python .\scripts\apply_r46_unified.py
```

Expected version stamp:

```text
compat_revision=46
app_version=2.4.5+46
```

## Acceptance plan

Before calling r46 complete, validate on Windows:

1. Materializer + `git diff --check` + `cargo fmt --check`.
2. r45 inherited focused tests.
3. r46 proxy structural-forensics tests.
4. r46 Tauri recovery parser / thread-id guard / fingerprint tests.
5. `cargo check -p codex-app-transfer-proxy --target x86_64-pc-windows-msvc`.
6. `cargo check -p codex-app-transfer --target x86_64-pc-windows-msvc`.
7. Frontend production build.
8. Tauri NSIS package build.
9. Fresh long thread: Luna -> Grok -> compact -> Terra -> continue.
10. Existing broken thread: read-only preview first; then one same-thread rewind; test one short normal message before any further rewind.
11. Verify the backup exists and SHA256 matches before recovery.
12. Verify workspace files are unchanged.
13. Verify a failed raw 400/client 200 operation creates `raw_client_status_mismatch` rather than being mistaken for a healthy compact in diagnostics.

Do not auto-repeat rollback based only on a failed test. Each additional one-turn rewind requires another explicit user action.
