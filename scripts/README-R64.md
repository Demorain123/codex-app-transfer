# r64 — post-compaction continuation guard

## Observed real-machine failure

On the r63 Windows build, the long Luna session reaches an automatic `context_limit` compaction and the Transfer compact stack succeeds end-to-end:

- r52 local private compaction is selected;
- r53 removes `max_output_tokens` for the Sub2API OAuth compatibility path;
- upstream returns HTTP 200;
- r56 recovers the summary from SSE (`output_text_done`);
- r62 validates/self-repairs a 6535-character summary;
- Codex UI reports `Context automatically compacted`;
- no following normal model request is emitted, so the active task stops until the user nudges it.

This is a continuation/lifecycle failure **after successful compaction**, not a summary-quality failure and not an upstream HTTP failure.

## Upstream correlation

OpenAI Codex issue #42693 (opened 2026-09-04) reports the same user-visible failure: with experimental `context_management` enabled, Codex often stops after automatic compaction instead of continuing an unfinished task.

Current upstream `run_turn` intends to continue after successful mid-turn auto-compaction. It can nevertheless end the turn during post-compaction lifecycle processing, and upstream has recently changed that lifecycle repeatedly.

Separately, issue #42468 documents that current Windows Codex builds consider `remote_compaction_v2 = false` a legacy route. r64 does **not** change that setting yet because r61 intentionally disabled V2 to fix a previously reproduced retained-history/model-switch recompaction loop, while Transfer's r52 implementation makes the legacy compact transport functional. Changing both variables at once would destroy the A/B value of this regression test.

## r64 scope

r64 keeps r63/r62/r61/r60 behavior and adds one narrow Windows launch-time compatibility override:

```toml
[features]
context_management = false
```

Equivalent dotted/nested `experimental_mode` spellings are normalized safely.

The guard is applied while Codex is closed on both normal and alternate/No-Micro launch paths. It logs only configuration outcome, never prompt/session/account/token contents:

```text
[compact-r64] action=disable_context_management status=applied reason=post_compact_continuation_stability
```

or:

```text
[compact-r64] action=disable_context_management status=already_disabled reason=post_compact_continuation_stability
```

r64 deliberately does **not** synthesize a continuation `/responses` request after compaction. Replaying a model step at the proxy layer cannot prove whether the previous tool call already committed a side effect, so an automatic retry could duplicate edits, commands, external actions, or other tool effects.

## Real-machine acceptance test

Use the same long Luna session; do not fork, clear history, or manually compact first.

Expected evidence:

1. startup log contains the r64 `disable_context_management` marker;
2. ordinary long-session requests still receive HTTP 200;
3. automatic context-limit compaction still reaches r56/r62 success;
4. after `Context automatically compacted`, the **same active task resumes without a new user message**;
5. the resumed request still passes through inherited r60 post-compaction replay when a private compaction item is present.

If step 4 still fails with r64, the next patch should move into Codex core continuation/lifecycle instrumentation rather than altering summary generation again.
