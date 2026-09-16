# R78+ requirements ledger

This ledger is the acceptance contract for the post-r76/r77 work. A requirement is not complete merely because an older branch, experiment, or build script once contained related code. It must be **materialized**, **already-equivalent with evidence**, or **not-applicable-with-evidence** in the current daily-build chain.

## Immediate correctness blockers

- [ ] **Per-output timestamps** — every visible assistant output boundary should receive a local `HH:mm:ss` timestamp. Prefer exact Codex/session event time; fall back to first-observed renderer time only when exact time is unavailable. Estimated times must be distinguishable from exact times. Cover final replies, progress/status output, agent/subagent output, tool/command/integration output, remounts, resume/reconnect, and already-visible historical assistant items when the local session log can match them.
- [ ] **Exact current-request token values** — populate input, cached input, output and reasoning from `token_count.info.last_token_usage`; never substitute cumulative totals for current-request values.
- [ ] **Context and cumulative totals** — context uses `last_token_usage.input_tokens / model_context_window`; lifetime/session cumulative display uses `total_token_usage` and is explicitly labelled `total`/`cumulative`.
- [ ] **Speed/cache fallback** — native Usage DOM may provide `tok/s` and cache hit; local/stream-derived values are fallback. Missing values remain unknown rather than fabricated.
- [ ] **Model attribution** — preserve active model/model-switch awareness, including Sub2API aliases and local models. Model labels must not silently inherit a stale previous turn.
- [ ] **Retry/reconnect/resume dedupe** — one logical usage event must not be counted twice after retry, reconnect, renderer remount, resume, or compact continuity.
- [ ] **Exact-vs-estimated provenance** — timestamps, cost and derived performance metrics must expose whether they are exact, locally observed/derived, or unavailable.

## r43-r65 formal carry-forward

For every formal release capability from r43 through r65, record one of `materialized`, `already-equivalent`, or `not-applicable-with-evidence`, with source paths/tests. Do not mark the range complete from branch names or historical commits alone.

Current repository branch discovery gives these historical inputs. r60 and r61 have multiple surviving variants and therefore remain **candidates** until their lineage/behavior is audited rather than arbitrarily picking one.

| Rev | Historical branch input(s) |
| --- | --- |
| r43 | `dev-r43-health-mcp-hardening-local` |
| r44 | `dev-r44-responses-terminal-semantics` |
| r45 | `dev-r45-model-switch-continuity-local` |
| r46 | `dev-r46-model-switch-old-thread-recovery-local` |
| r47 | `dev-r47-codex-temp-dir-local` |
| r48 | `dev-r48-provider-temp-control-local` |
| r49 | `dev-r49-unified-codex-temp-launch-local` |
| r50 | `dev-r50-same-session-cross-model-replay-local` |
| r51 | `dev-r51-model-switch-classifier-compact-handoff-local` |
| r52 | `dev-r52-cross-model-compaction-history-portable-local` |
| r53 | `dev-r53-sub2api-oauth-compact-max-output-local` |
| r54 | `dev-r54-sub2api-compact-responses-sse-local` |
| r55 | `dev-r55-detached-mcp-helper-install-safe-local` |
| r56 | `dev-r56-compact-sse-summary-fallback-local` |
| r57 | `dev-r57-external-mcp-source-migration-local` |
| r58 | `dev-r58-windows-chatgpt-lifecycle-guard-local` |
| r59 | `dev-r59-interrupted-tail-same-id-recovery-local` |
| r60 | `dev-r60-recovery-session-catalog-local`; `dev-r60-sub2api-post-compact-replay-local`; `dev-r60-sub2api-post-compaction-replay-local` |
| r61 | `dev-r61-model-switch-compact-resume-once`; `dev-r61-sub2api-compaction-loop-guard-local` |
| r62 | `dev-r62-compact-summary-repair-retry-local` |
| r63 | `dev-r63-auth-epoch-encrypted-history-fence-local` |
| r64 | `dev-r64-post-compact-continuation-guard-local` |
| r65 | `dev-r65-first-turn-startup-generation-gate-local` |

Branch names are discovery inputs, not acceptance evidence. Each revision still requires source/test evidence and, where multiple variants survive, lineage comparison. Older summaries with different r43-r65 names must not be treated as authoritative without current-repository evidence.

## r66-r69 negative invariant

The following experimental Hook A/B lines must **not** return as runtime behavior:

- `dev-r66-post-compact-hooks-ab-local`
- `dev-r67-hooks-restored-selective-state-local`
- `dev-r68-sessionstart-only-ab-local`
- `dev-r69-sessionstart-postcompact-ab-local`

A verifier must fail if these experimental behaviors are materialized into the daily build. Merely mentioning these names in a verifier/ledger is not materialization.

## Hook health: read-only only

Hook health may be diagnosed and summarized, but it must stay read-only. It may report enabled/disabled counts, broad categories such as SessionStart/PostCompact, confidence and correlation with an observed failure. It must not expose full hook commands/arguments/paths, automatically disable/delete hooks, rewrite Hook configuration, or reintroduce r66-r69 experiments.

## Unified observability target

The intended architecture remains:

`Codex/session events -> normalized usage event -> dedupe/correlation -> session/turn accumulator -> context/token/cache/speed/cost/timestamp metrics -> compact UI + detailed UI`

The implementation must remain local-first and low-overhead on Windows. Prefer proven local session JSONL fields and existing Codex UI anchors over inventing a parallel accounting protocol. Unknown/local-model pricing stays `unpriced`/unknown unless a deliberate price source exists; no guessed cost.

## Version gates

- `R78_TIMESTAMP_PASS`
- `R78_EXACT_USAGE_PASS`
- `R43_R65_CARRY_FORWARD_PASS`
- `R66_R69_EXPERIMENTS_ABSENT_PASS`
- `HOOK_HEALTH_READONLY_PASS`
- `R78_LOCAL_BUILD_PASS` (or the corresponding later build version)

The first five are behavior/source-contract gates. A packaging success alone does not satisfy them.
