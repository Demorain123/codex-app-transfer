# r31 Auto Review provider-modal layout hotfix

r31 is intentionally a UI-only hotfix on top of the validated r30 unified stack.

## User-visible bug

In the provider edit modal, the r29/r30 Auto Review mapping editor could force the modal body wider than the dialog. Symptoms included:

- a horizontal scrollbar at the bottom of the provider form;
- left-side model/field labels clipped or partially missing;
- the `Auto Review` row title squeezed vertically;
- the right side of the mapping editor extending outside the normal modal content area.

## Root cause

`SettingsRow` uses a horizontal flex layout and its control slot has `flex-shrink: 0`. The Auto Review editor is a wide `width: 100%` control. Putting the editor into that generic non-shrinking right-hand slot can make the row require `left label width + full editor width`, which exceeds the wide modal content width.

The editor row also used fixed `150px` minimum grid columns, making it less tolerant of constrained modal widths.

## Fix

Only the Auto Review SettingsRow is changed:

- stack its title above the editor;
- allow its control slot to occupy the row width with `min-width: 0`;
- keep the generic `SettingsRow` component unchanged;
- use `minmax(0, 1fr)` for the two model columns;
- explicitly make the editor `border-box` at `width: 100%`.

## Scope freeze

r31 does not change:

- r30 Hybrid Direct routing or CC Switch ownership;
- provider/base-URL/auth behavior;
- Apps MCP auth;
- runtime diagnostics;
- No Micro / proxy lifecycle;
- Auto Review storage, reviewer selection, API transport, catalog copy-on-write, or live-apply semantics.

Visible test revision: `r31 / v2.4.5+31`.
