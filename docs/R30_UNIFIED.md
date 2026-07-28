# r30 Unified acceptance contract

r30 is the first intentional integration of the parallel r28 and r29 lines.

## Included stack

- r24: per-model Auto Review copy-on-write overlay for an external `model_catalog_json`.
- r25: hosted Apps MCP official ChatGPT auth/privacy hardening.
- r26: runtime, process, reconnect/compaction and subagent failure diagnostics.
- r27: Windows proxy same-port lifecycle/restart hardening.
- r28: Hybrid Direct for CC Switch and zero-proxy official ChatGPT/OpenAI OAuth.
- r29: provider-model-list Auto Review mapping UI plus real provider API serialization/live apply.
- r30: Hybrid Direct × Auto Review integration and lifecycle safety.

Visible identity: `v2.4.5+30 / r30`.

## Network ownership in Hybrid Direct

CC Switch remains authoritative for Codex provider/auth/network selection. Official ChatGPT/OpenAI OAuth must not be proxied through Transfer.

Transfer may continue to run its authenticated local gateway for third-party/Grok traffic. General Hybrid Direct sync must not call the normal provider/auth apply path.

## Auto Review exception

An explicit Auto Review mapping is the sole narrow Codex-config exception in Hybrid Direct.

Transfer may:

1. inspect whether `model_catalog_json` currently points at Transfer's exact Auto Review shadow;
2. restore that pointer to the recorded source catalog when required;
3. rebuild the Transfer-owned shadow from the current source catalog;
4. update only the `model_catalog_json` pointer to the new shadow.

It must not modify provider selection, OpenAI/ChatGPT base URLs, `auth.json`, CC Switch state, or proxy ownership as part of this operation.

The external/source catalog remains read-only and authoritative.

## Default and rescue reviewer behavior

With no explicit per-model mapping, r30 preserves Codex's default Auto Review behavior. The real-device baseline observed for Grok 4.5 currently resolves to `codex-auto-review` and should remain usable.

An explicit mapping such as:

`grok-4.5 -> gpt-5.6-luna`

is a rescue override. Removing the final mapping sends an explicit empty map and restores normal/default reviewer behavior; a stale shadow override must not remain active.

Saving an Auto Review mapping never automatically restarts Codex. The UI tells the user when the live catalog was rebuilt and that a Codex restart is recommended before relying on the new reviewer for newly-created approval threads.

## Lifecycle rules

- Hybrid Direct gateway/startup sync rebases the Auto Review shadow from the current source catalog, preventing an old shadow from hiding later source updates.
- Hybrid Direct exit continues to block full Transfer snapshot replay over CC Switch-owned state, but it may restore Transfer's exact Auto Review shadow pointer to its source.
- `providerAuthMutated` remains false for catalog-only operations.
- `catalogMutated`/`codexMutated` truthfully report whether the narrow model-catalog operation changed Codex state.
- The read-only overlay-state probe reuses r24's own normalized path ownership rules.

## Final CI gate

The same exact head must pass:

- complete r24→r30 materialization;
- deep r28, r29 and r30 self-review;
- rustfmt-normalized second replay idempotence;
- r24 COW catalog tests;
- r25 Apps MCP auth regressions;
- r26 subagent failure-chain regressions;
- full Windows MSVC app compile;
- r27 proxy lifecycle regressions;
- r28 Hybrid Direct safety regressions;
- adapter regressions;
- Vue production build;
- NSIS + MSI packaging and artifact upload.

PR #21 remains Draft until real-device A/B verifies both Hybrid Direct routing and default/explicit Auto Review reviewer behavior.
