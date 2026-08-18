# r38 Codex Usage Injector Compatibility Research — 2026-08-18

## Symptom

The r37 setting `Codex 内显示用量信息` / `codexQuotaEnabled` is enabled, but the Usage section does not appear in Codex Desktop.

The feature is not an always-visible composer widget. Upstream documents it as a CDP-injected `Usage` section at the bottom of Codex Desktop's top-bar `Toggle pinned summary` popup. Codex must have been launched by Codex App Transfer so the shared CDP channel is available; if Codex was already running when the toggle was enabled, a Transfer-driven Codex restart is required.

## Why r37 is fragile on newer Codex Desktop builds

The r37 `src-tauri/src/codex_quota_injector.rs` is identical to current upstream at the time of this investigation (same blob SHA `2a91a1f98cbf867e68845301a57850fcc8a9faf8`), so this is not introduced by the Sub2API/Grok compatibility overlays.

The injector still carries DOM assumptions verified against older Codex builds:

- `findScroller()` searches only `section header button[class~="group/section-toggle"]`; comments say the DOM anchor was CDP-tested on Codex `v26.608` and explicitly note that Codex upgrades require regression testing.
- context percentage lookup depends on `[aria-label^="Context usage:"]` / `[title^="Context usage:"]`.
- precise `usedTokens/contextWindow` extraction climbs React fiber from that context-ring element; comments say this was verified on `v26.609`.

Public OpenAI Codex issues around the July 2026 `26.707` merged desktop UI report the context-usage donut/indicator disappearing again, including Windows package `26.707.3748.0`. That makes the old context-ring anchor unreliable. The merged UI also changed multiple renderer/sidebar surfaces, increasing the likelihood that the pinned-summary section structure/class changed.

Therefore the leading hypothesis is an upstream compatibility regression: CDP can still be available, but the injected script's DOM anchor discovery returns `null` (panel never mounts), and/or the old context-ring anchor is absent (context data cannot be read).

## r38 requirements

### P1 — semantic multi-anchor mounting

Replace the single Tailwind-class anchor with a tiered locator:

1. current known native section-toggle structure when present;
2. semantic dialog/popover role + section structure;
3. nearby stable accessible names / text for native sections such as Environment / Sources, without requiring a specific Tailwind class;
4. safe container fallback only when the popup identity is unambiguous.

Never append into an arbitrary dialog just because it contains sections.

### P1 — decouple panel mounting from context-ring discovery

The Usage panel should still mount and show rollout-backed cumulative/cache data when the native context donut is absent. Context should degrade independently to `—` until a new source is found.

Do not make `Context usage:` aria text a prerequisite for mounting the panel.

### P1 — CDP injection observability

Make each periodic injection return a small structured diagnostic object, for example:

- `cdp_connected`
- `script_installed`
- `panel_present`
- `anchor_kind`
- `anchor_not_found`
- `context_source = fiber | aria | unavailable`
- `conversation_id_found`

Log only state transitions to avoid a 5-second log flood.

Expose the latest state beside the setting so users can distinguish:

- toggle enabled but Codex not launched with CDP;
- CDP connected but popup anchor not found;
- panel attached but context source unavailable;
- fully healthy.

### P1 — versioned compatibility fixtures

Add DOM fixture tests representing at least:

- the historical 26.608/26.609 layout expected by the current injector;
- a 26.707-style layout with the context donut absent;
- popup re-render/remount and repeated 5-second pushes.

The injector must be idempotent and must not duplicate `#cat-quota-entry`.

### P1 — runtime self-heal

Keep the existing MutationObserver/reinstall behavior, but when anchor discovery fails, periodically retry discovery without tearing down unrelated DOM or spamming errors. A later successful popup render should attach automatically.

## Immediate interpretation for r37

If the setting is ON, Codex was launched/restarted through Transfer, and opening `Toggle pinned summary` still shows no `Usage` section at the bottom, treat it as an injector compatibility failure rather than a provider/quota-data problem.

Provider quota availability only affects individual quota rows; it should not suppress the panel itself because local Context/Tokens/cache rows are built for all providers.
