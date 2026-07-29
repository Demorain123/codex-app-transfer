from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
USAGE = ROOT / "frontend/src/pages/UsagePage.vue"

body = USAGE.read_text(encoding="utf-8")

required = [
    "CAS-R32-USAGE-CLICK-SORT",
    "type SortKey = 'group' | 'model' | 'cacheHit' | 'input' | 'output' | 'reasoning' | 'total' | 'turns' | 'lastActivity'",
    "function setSort(key: SortKey)",
    "function sortAria(key: SortKey): 'ascending' | 'descending' | undefined",
    "function cacheHitRatio(row: UsageRow): number | null",
    "function compareSortValues(a: SortValue, b: SortValue): number",
    "return primary || a.index - b.index",
    '@update:model-value="setUsageView($event as UsageView)"',
    'class="usage-sort-button"',
    ':aria-sort="sortAria(',
    ".usage-sort-button:focus-visible",
]
for marker in required:
    if marker not in body:
        raise SystemExit(f"r32 usage sort review missing: {marker}")

if body.count("CAS-R32-USAGE-CLICK-SORT") != 1:
    raise SystemExit("r32 usage sort marker must appear exactly once")

for key in ("group", "model", "cacheHit", "input", "output", "reasoning", "total", "turns", "lastActivity"):
    if f'@click="setSort(\'{key}\')"' not in body:
        raise SystemExit(f"r32 usage sort review missing clickable header: {key}")
    if f':aria-sort="sortAria(\'{key}\')"' not in body:
        raise SystemExit(f"r32 usage sort review missing aria-sort header: {key}")

if '@update:model-value="store.setView($event as UsageView)"' in body:
    raise SystemExit("r32 usage sort review found bypass of view-reset wrapper")

if "return list.slice().sort" in body:
    raise SystemExit("r32 usage sort review found legacy hard-coded sort")

if "return (row.cachedInputTokens || 0) / input" not in body:
    raise SystemExit("r32 usage sort must compare the unrounded cache-hit ratio")

print("r32 usage click-sort semantic/accessibility review: PASS")
