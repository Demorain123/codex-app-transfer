# r45 — Model Switch Continuity + Responses Semantic Terminal

Base branch: `dev-r43-health-mcp-hardening-local`

Target branch: `dev-r45-model-switch-continuity-local`

## Why r45 exists

Long-lived Codex threads can switch models/providers mid-session (for example Luna -> Grok -> Terra). Internal helper requests, especially compaction, may still carry an older/default model after the main thread has moved to a different effective model. That can route compaction through the wrong model/provider and poison the handoff into the next turn.

The 2026-08-29 real trace made the sequence concrete:

1. the same session successfully ran `grok-4.6`;
2. an automatic pre-turn compaction later arrived as `gpt-5.6-luna` with `x-codex-turn-metadata.request_kind=compaction`, `reason=comp_hash_changed`, and a ~13.85 MB request body;
3. that compaction received raw upstream HTTP 400 while the proxy-facing client status was 200;
4. the next main request returned to `grok-4.6`;
5. after switching to `gpt-5.6-terra`, the ordinary turn itself was ~13.93 MB and again received raw upstream HTTP 400.

This strongly supports a cross-model handoff failure chain: stale-model compaction fails, the large un-compacted context survives, and the following selected-model turn is then exposed to the same oversized/broken context state.

r45 also folds in the previously isolated r44 health fix: a Responses stream is semantically complete when `response.completed` is emitted. Waiting only for transport EOF can misclassify a successful response as `cancelled` when Codex stops polling after the terminal event.

## Runtime changes

### 1. Effective model continuity

`apply_r45_model_switch_continuity.py` injects a bounded session-effective-model registry into `crates/proxy/src/forward.rs`.

- Main, non-helper turns advance the effective model.
- Subagent and memgen requests cannot overwrite the main thread model.
- The persisted file is `~/.codex-app-transfer/effective-models-r45.json` and contains only FNV64 conversation fingerprints plus model slugs. It does not store raw session/thread IDs, prompts, credentials, tool arguments, or responses.
- The map is capped at 1024 entries.

### 2. Compaction helper rebinding

The authoritative request-role signal is now:

`x-codex-turn-metadata.request_kind == "compaction"`

A structural JSON fallback is retained only for an object whose `type` or `request_kind` is exactly `compaction`.

The feature string `remote_compaction_v2` / `local_compaction_v2` is **not** a request-role signal. The 2026-08-29 trace proves that an ordinary `gpt-5.6-terra` turn can also advertise `x-codex-beta-features=remote_compaction_v2`. Therefore r45 must not classify a request as compaction merely because that feature is enabled.

Free-text user content containing `compaction` is also deliberately not a helper signal.

When a confirmed compaction helper carries a model different from the effective model already observed for that session, r45 rewrites the helper model **before resolver/provider routing**. Ordinary turns are never rewritten from the registry, so explicit Luna <-> Grok <-> Terra switching remains authoritative.

This is a compatibility repair for the current mixed-model workflow; it is not a generic "force every internal request to one model" rule.

### 3. Session-model diagnostics stop learning from helpers

The existing `session-models.jsonl` recorder is no longer updated by compaction/subagent/memgen helper traffic. This prevents an internal Luna helper from making diagnostics claim that a Grok session switched back to Luna.

### 4. Responses semantic terminal lifecycle

`RequestLifecycleStreamR34` gains an incremental SSE terminal detector. It recognizes:

- `response.completed` -> completed
- `response.incomplete` -> failed:response_incomplete
- `response.failed` -> failed:response_failed

For a Responses event-stream, EOF without any semantic terminal is now `failed:response_eof_without_terminal`, not a successful completion. Drop after a semantic terminal does not become `cancelled`.

`[DONE]` by itself is not treated as a semantic Responses terminal.

## Focused tests

The generated proxy source adds three r45 tests:

1. `r45_compaction_helper_detection_is_structural`
   - structural `type=compaction` is accepted;
   - `x-codex-turn-metadata.request_kind=compaction` is accepted;
   - an ordinary turn carrying `remote_compaction_v2` is rejected as a compaction helper;
   - user text `compaction` is rejected as a helper signal.
2. `r45_semantic_terminal_detector_handles_chunk_boundaries`
3. `r45_auxiliary_requests_do_not_advance_main_model`

Run the full inherited + r45 gate with:

```powershell
pwsh -File .\scripts\build-r45-model-switch-local-release-stress.ps1
```

Build a verified NSIS package with:

```powershell
pwsh -File .\scripts\build-r45-model-switch-local-package-verified.ps1
```

Add `-WithMsi` when an MSI is also required.

## Real-environment acceptance still required

Before calling r45 complete, exercise at least these sequences in a long existing thread:

- Luna -> Grok -> automatic pre-turn compact -> normal turn
- Grok -> Luna -> automatic pre-turn compact -> normal turn
- Grok -> Terra after a compact boundary
- multiple switches (Luna -> Grok -> Terra -> Grok)
- app restart/resume before automatic compact
- subagent activity before and after switching
- an ordinary turn with `x-codex-beta-features=remote_compaction_v2` (must remain an ordinary turn)
- an ordinary user message whose text is exactly `compaction` (must not trigger helper rebinding)
- successful Responses turns where the client drops immediately after `response.completed` (must not appear as `cancelled`)
- deliberately truncated SSE without a terminal (must be reported as failure)

For the reproduced large-thread sequence, capture these fields together:

- selected/effective model before the switch;
- compaction request model;
- `x-codex-turn-metadata.request_kind`;
- request bytes;
- raw upstream status;
- client-facing status;
- next normal-turn model and request bytes.

A successful r45 handoff should show the compaction helper rebound to the already-active effective model and should prevent the next selected-model turn from inheriting the same un-compacted ~14 MB history.

## Explicit non-goals

r45 does not weaken or bypass the existing compact summary quality gate. The repository branch does not currently expose the client-side `[compact-v2] quality_check_failed` implementation that rejected the earlier 1240-character no-heading summary, so r45 fixes the model-selection / handoff cause visible to Transfer rather than silently accepting a low-quality summary.

r45 also does not claim that every HTTP 400 in a large request is caused only by byte size. The ~13.85–13.93 MB bodies are strong failure evidence, but the exact upstream rejection reason is still masked by the generic `{"message":"Upstream request failed"}` response. The correct acceptance test is therefore behavioral: after model-continuity repair, compaction must succeed (or expose a precise failure), and the next turn must no longer be sent with the same un-compacted giant context.

If a future trace proves that a correctly rebound current-model compact still fails the quality gate or raw upstream request, repair/retry belongs in the actual compact orchestrator or a narrowly-scoped fallback path, not in a generic proxy response adapter.
