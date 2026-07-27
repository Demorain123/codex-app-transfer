# r29 Auto Review model override contract

r29 keeps Codex's existing Auto Review behavior as the default and adds a usable per-model escape hatch when that default reviewer is unavailable or undesirable.

## Default behavior

When a main model has no explicit entry in `autoReviewModelOverrides`, Codex keeps the reviewer behavior from the active model catalog. r29 does not hard-code or rewrite `codex-auto-review`.

This is intentional: the real-device baseline observed for `grok-4.5` + `approvals_reviewer=auto_review` successfully used Codex's hidden `codex-auto-review` reviewer, so the default path is treated as a compatibility baseline rather than something to replace.

## Explicit rescue override

The provider editor exposes visual rows:

`main model -> Auto Review model`

For example:

`grok-4.5 -> gpt-5.6-luna`

The value is still stored through the existing r24 `autoReviewModelOverrides` object and materialized as the selected main model entry's `auto_review_model_override` in the Transfer-owned copy-on-write model catalog.

Removing a row sends an explicit empty map when the last override disappears, so a stale override is removed and Codex can return to its catalog/default reviewer behavior.

## Provider model list

The editor reuses ProviderForm's existing `availableModels` source. That source can be populated from the provider `/models` endpoint, cached models, declared model capabilities, presets, and saved mapping slugs.

Opening an existing provider shows cached/declared choices first. Only after the provider secret is loaded does r29 perform one silent model-list refresh. A silent refresh never applies backend `suggested` values to unrelated model slots.

## Save/apply semantics

The original r24 UI/backend path had two important holes that r29 closes:

1. `ProviderPayload.autoReviewModelOverrides` was present in the form/type but `providerBody()` did not serialize it into the provider PUT request.
2. Editing an active provider saved registry state but did not rebuild the live copy-on-write catalog.

r29 therefore:

- reads the field back through `mapProvider()`;
- sends the field through `providerBody()`;
- detects a real mapping change in `update_provider`;
- if the edited provider is active, reuses the existing desktop/provider sync path to rebuild the active catalog;
- reports whether the live apply succeeded;
- never automatically restarts Codex from a provider-form save.

After a successful active-provider apply, the UI tells the user to restart Codex before relying on the new reviewer for new approval threads, because a running Codex process or an existing Auto Review thread may have cached model metadata.

## Copy-on-write boundary

r29 does not become another model-catalog implementation. r24 remains authoritative:

- an external `model_catalog_json` is never edited in place;
- Transfer rebuilds its own shadow catalog from the source;
- only explicitly mapped main model entries receive `auto_review_model_override`;
- clearing overrides restores normal source/default catalog behavior.

## Scope exclusions

r29 deliberately does not change:

- r27's built-in `openai` provider-identity/fallback behavior;
- r25 Apps MCP auth behavior;
- r26 runtime diagnostics;
- r27 proxy lifecycle / No Micro behavior;
- automatic Codex process restart policy.

A future independent revision may add a user-selectable "preserve original model_provider identity" mode without coupling that experiment to Auto Review.

## Validation gates

The r29 workflows require:

- deep UI/data-flow self-review;
- provider API read/write markers;
- active-provider live-apply markers;
- Vue production build;
- Rust formatting normalization;
- complete overlay replay idempotence after rustfmt;
- r24 Auto Review copy-on-write regressions;
- r25 Apps MCP auth regressions;
- r26 subagent failure-chain regressions;
- r27 proxy lifecycle regressions;
- full Windows MSVC app compilation;
- NSIS + MSI packaging.

Real-device acceptance still requires two A/B checks after installation:

1. no explicit mapping -> `Approve for me` continues to work with Codex's default reviewer path;
2. explicit mapping such as `grok-4.5 -> gpt-5.6-luna`, followed by a Codex restart -> a newly-created approval review uses the selected reviewer.
