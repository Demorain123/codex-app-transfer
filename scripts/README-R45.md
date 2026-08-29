# r45 — Model Switch Continuity + Responses Semantic Terminal

Base branch: `dev-r43-health-mcp-hardening-local`

Target branch: `dev-r45-model-switch-continuity-local`

## Why r45 exists

Long-lived Codex threads can switch models/providers mid-session (for example Luna -> Grok). Internal helper requests, especially compaction, may still carry an older/default model even after the main thread has moved to a different effective model. That can route compaction through the wrong provider/model and produce a broken handoff. The observed failure was a Grok-selected thread whose local compact helper was sent as `gpt-5.6-luna`, then rejected by the local compact quality gate.

r45 also folds in the previously isolated r44 health fix: a Responses stream is semantically complete when `response.completed` is emitted. Waiting only for transport EOF can misclassify a successful response as `cancelled` when Codex stops polling after the terminal event.

## Runtime changes

### 1. Effective model continuity

`apply_r45_model_switch_continuity.py` injects a bounded session-effective-model registry into `crates/proxy/src/forward.rs`.

- Main, non-helper turns advance the effective model.
- Subagent and memgen requests cannot overwrite the main thread model.
- The persisted file is `~/.codex-app-transfer/effective-models-r45.json` and contains only FNV64 conversation fingerprints plus model slugs. It does not store raw session/thread IDs, prompts, credentials, tool arguments, or responses.
- The map is capped at 1024 entries.

### 2. Compaction helper rebinding

A request is eligible only when its JSON structure contains either:

- an item whose `type` is exactly `compaction`; or
- the explicit feature marker `remote_compaction_v2` / `local_compaction_v2`.

Free-text user content containing the word `compaction` is deliberately **not** a helper signal.

When an eligible helper carries a model different from the effective model already observed for that session, r45 rewrites the helper model **before resolver/provider routing**. Ordinary turns are never rewritten from the registry, so explicit Luna <-> Grok switching remains authoritative.

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

- Luna -> Grok -> normal turn -> automatic compact -> normal turn
- Grok -> Luna -> normal turn -> automatic compact -> normal turn
- multiple switches (Luna -> Grok -> another model -> Grok)
- app restart/resume before automatic compact
- subagent activity before and after switching
- an ordinary user message whose text is exactly `compaction` (must not trigger helper rebinding)
- successful Responses turns where the client drops immediately after `response.completed` (must not appear as `cancelled`)
- deliberately truncated SSE without a terminal (must be reported as failure)

## Explicit non-goals

r45 does not weaken or bypass the existing compact summary quality gate. The repository branch does not currently expose the client-side `[compact-v2] quality_check_failed` implementation that rejected the 1240-character no-heading summary, so r45 fixes the upstream model-selection cause visible to Transfer rather than silently accepting a low-quality summary.

If a future trace proves that a correctly rebound current-model compact still fails the quality gate, repair/retry belongs in the actual compact orchestrator, not in the proxy response adapter.
