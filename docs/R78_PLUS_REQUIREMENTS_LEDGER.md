# R78+ requirements ledger

This ledger is the acceptance contract for the post-r76/r77 work. A requirement is not complete merely because an older branch, experiment, or build script once contained related code. It must be **materialized**, **already-equivalent with evidence**, or **not-applicable with evidence** in the current daily-build chain.

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

Known later-range capabilities that must be explicitly verified include:

- r58 Windows ChatGPT.exe lifecycle adaptation
- r59 interrupted-tail same agent/session recovery
- r60 Sub2API terminated-SSE compatibility
- r61 compact/encrypted_content preservation
- r62 Grok item_reference compatibility
- r63 masked historical item_reference snapshot/restore
- r64 conditional placeholder stripping
- r65 Windows first-turn startup generation gate

r43-r57 must be recovered from repository history and audited individually rather than guessed.

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
