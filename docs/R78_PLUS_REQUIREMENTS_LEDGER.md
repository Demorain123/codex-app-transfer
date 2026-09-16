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

The authoritative historical source branches currently present in this repository are:

| Rev | Historical source branch |
| --- | --- |
| r43 | `dev-r43-rewrite-health-mcp-overlay-local` |
| r44 | `dev-r44-orchestrate-anything-trellis-local` |
| r45 | `dev-r45-rewrite-hook-skill-rebuild-local` |
| r46 | `dev-r46-r45-official-guardrails-local` |
| r47 | `dev-r47-r42-43-44-rebase-local` |
| r48 | `dev-r48-session-hooks-local` |
| r49 | `dev-r49-scripts-hooks-local` |
| r50 | `dev-r50-trellis-addon-local` |
| r51 | `dev-r51-skill-lineage-hook-local` |
| r52 | `dev-r52-global-sessionstart-local` |
| r53 | `dev-r53-r51-r41-regression-local` |
| r54 | `dev-r54-no-hook-duplicate-rebuild-local` |
| r55 | `dev-r55-hook-triage-local` |
| r56 | `dev-r56-post-compact-continuity-local` |
| r57 | `dev-r57-windows-process-health-local` |
| r58 | `dev-r58-chatgpt-lifecycle-local` |
| r59 | `dev-r59-gpt56-luna-max-local` |
| r60 | `dev-r60-consent-transcript-structure-local` |
| r61 | `dev-r61-transition-diagnostics-local` |
| r62 | `dev-r62-canonical-local-rebase` |
| r63 | `dev-r63-scope-separation-local` |
| r64 | `dev-r64-auq-local-only-owned-primitive` |
| r65 | `dev-r65-first-turn-startup-generation-gate-local` |

These branch names are discovery inputs, not proof that their behavior is present in the current build. Each revision still requires source/test evidence. In particular, older summaries that mapped r59-r64 to unrelated later compatibility features are not authoritative and must not be used for carry-forward acceptance.

## r66-r69 negative invariant

The following experimental Hook A/B lines must **not** return as runtime behavior:

- `CAS-R66-POST-COMPACT-HOOKS-AB`
- `CAS-R67-HOOKS-RESTORED-SELECTIVE-STATE`
- `CAS-R68-SESSIONSTART-ONLY-HOOKS-AB`
- `CAS-R69-SESSIONSTART-POSTCOMPACT-HOOKS-AB`

A verifier must fail if these experimental markers/behaviors are materialized into the daily build.

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
