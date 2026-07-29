from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def write(rel: str, text: str) -> None:
    (ROOT / rel).write_text(text, encoding="utf-8")
    print(f"patched {rel}")


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if new in text:
        return text
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"r31 layout {label}: expected one anchor, found {count}")
    return text.replace(old, new, 1)


# The r29 editor is intentionally wide, but SettingsRow's generic control slot is
# `flex-shrink: 0`. Combining that with a 100%-wide editor can make the control
# consume the whole row *plus* the left label, producing horizontal overflow and
# clipping the left side of neighbouring rows. Make only this row stacked/full-width;
# do not change the global SettingsRow behavior used by the rest of the app.
rel = "frontend/src/components/provider/ProviderFormModal.vue"
text = read(rel)
text = replace_once(
    text,
    '<SettingsRow :title="t(\'providerForm.autoReviewModelOverrides\')">',
    '<SettingsRow class="pf__auto-review-row" :title="t(\'providerForm.autoReviewModelOverrides\')">',
    "Auto Review SettingsRow class",
)
if "CAS-AUTO-REVIEW-LAYOUT-R31" not in text:
    css = r'''
/* CAS-AUTO-REVIEW-LAYOUT-R31
 * Auto Review is a wide editor. Stack its SettingsRow so the generic
 * flex-shrink:0 control slot cannot force the whole provider form wider than
 * the modal. Keep the exception local to this one row. */
.pf__auto-review-row {
  flex-direction: column;
  align-items: stretch;
  gap: var(--space-2);
}
.pf__auto-review-row :deep(.settings-row__text),
.pf__auto-review-row :deep(.settings-row__control) {
  width: 100%;
  min-width: 0;
}
.pf__auto-review-row :deep(.settings-row__control) {
  flex: 1 1 auto;
}
'''
    if "</style>" not in text:
        raise SystemExit("r31 layout: ProviderFormModal style block missing")
    text = text.replace("</style>", css + "</style>", 1)
write(rel, text)


# Make the editor itself tolerant of narrow modal content. The outer row fix is
# the primary correction; minmax(0, 1fr) additionally prevents long select labels
# from imposing a hidden minimum width. Explicit border-box keeps 100% width from
# ever becoming 100% + padding/border if global box-sizing changes upstream.
rel = "frontend/src/components/provider/AutoReviewModelOverridesEditor.vue"
text = read(rel)
if "box-sizing: border-box; /* CAS-AUTO-REVIEW-LAYOUT-R31 */" not in text:
    text = replace_once(
        text,
        ".armap {\n  width: 100%;\n",
        ".armap {\n  width: 100%;\n  box-sizing: border-box; /* CAS-AUTO-REVIEW-LAYOUT-R31 */\n",
        "editor border-box",
    )
text = replace_once(
    text,
    "grid-template-columns: minmax(150px, 1fr) 24px minmax(150px, 1fr) auto;",
    "grid-template-columns: minmax(0, 1fr) 24px minmax(0, 1fr) auto;",
    "editor responsive columns",
)
write(rel, text)

# Fail closed if the old overflow-prone combination resurfaces.
parent = read("frontend/src/components/provider/ProviderFormModal.vue")
editor = read("frontend/src/components/provider/AutoReviewModelOverridesEditor.vue")
for marker in (
    'class="pf__auto-review-row"',
    "CAS-AUTO-REVIEW-LAYOUT-R31",
    ".pf__auto-review-row :deep(.settings-row__control)",
):
    if marker not in parent:
        raise SystemExit(f"r31 layout missing ProviderForm marker: {marker}")
for marker in (
    "box-sizing: border-box; /* CAS-AUTO-REVIEW-LAYOUT-R31 */",
    "grid-template-columns: minmax(0, 1fr) 24px minmax(0, 1fr) auto;",
):
    if marker not in editor:
        raise SystemExit(f"r31 layout missing editor marker: {marker}")

print("r31 Auto Review modal overflow/layout overlay: PASS")
