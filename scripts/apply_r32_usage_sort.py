from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
USAGE = ROOT / "frontend/src/pages/UsagePage.vue"

MARKER = "CAS-R32-USAGE-CLICK-SORT"


def replace_once(body: str, old: str, new: str, label: str) -> str:
    count = body.count(old)
    if count != 1:
        raise SystemExit(f"r32 usage sort hotfix anchor {label!r} expected once, found {count}")
    return body.replace(old, new, 1)


body = USAGE.read_text(encoding="utf-8")
if MARKER in body:
    print("r32 usage click-sort hotfix: already applied")
    raise SystemExit(0)

old = """const showModelsCol = computed(() => store.activeView !== 'model')

const rows = computed<UsageRow[]>(() => {
  const r = store.report
  if (!r) return []
  let list: UsageRow[]
  if (store.activeView === 'daily') list = r.daily || []
  else if (store.activeView === 'model') list = r.byModel || []
  else list = r.byConversation || []
  // daily 按日期降序;model/conversation 按 total tokens 降序
  return list.slice().sort((a, b) => {
    if (store.activeView === 'daily') return (b.group || '').localeCompare(a.group || '')
    return (b.totalTokens || 0) - (a.totalTokens || 0)
  })
})
"""

new = """const showModelsCol = computed(() => store.activeView !== 'model')

// CAS-R32-USAGE-CLICK-SORT
// 表头点击排序：同一列在升/降序间切换；切换视图时恢复旧版默认顺序
// (按日=日期降序，按模型/对话=总 tokens 降序)。
type SortKey = 'group' | 'model' | 'cacheHit' | 'input' | 'output' | 'reasoning' | 'total' | 'turns' | 'lastActivity'
type SortDirection = 'asc' | 'desc'
type SortValue = string | number | null

function defaultSort(view: UsageView): { key: SortKey; direction: SortDirection } {
  return view === 'daily'
    ? { key: 'group', direction: 'desc' }
    : { key: 'total', direction: 'desc' }
}

const initialSort = defaultSort(store.activeView)
const sortKey = ref<SortKey>(initialSort.key)
const sortDirection = ref<SortDirection>(initialSort.direction)

function setUsageView(view: UsageView) {
  store.setView(view)
  const next = defaultSort(view)
  sortKey.value = next.key
  sortDirection.value = next.direction
}

function setSort(key: SortKey) {
  if (sortKey.value === key) {
    sortDirection.value = sortDirection.value === 'asc' ? 'desc' : 'asc'
    return
  }
  sortKey.value = key
  // 数值、日期/活动时间默认先看最大/最新；名称类默认 A→Z。
  sortDirection.value = key === 'group' || key === 'model' ? 'asc' : 'desc'
}

function sortAria(key: SortKey): 'ascending' | 'descending' | undefined {
  if (sortKey.value !== key) return undefined
  return sortDirection.value === 'asc' ? 'ascending' : 'descending'
}

function sortIndicator(key: SortKey): string {
  if (sortKey.value !== key) return '↕'
  return sortDirection.value === 'asc' ? '↑' : '↓'
}

function cacheHitRatio(row: UsageRow): number | null {
  const input = row.inputTokens || 0
  if (input <= 0) return null
  return (row.cachedInputTokens || 0) / input
}

function sortValue(row: UsageRow, key: SortKey): SortValue {
  switch (key) {
    case 'group':
      if (store.activeView === 'conversation') return (row.displayName || '').trim() || row.group || ''
      return row.group || ''
    case 'model':
      return modelText(row)
    case 'cacheHit':
      return cacheHitRatio(row)
    case 'input':
      return row.inputTokens ?? null
    case 'output':
      return row.outputTokens ?? null
    case 'reasoning':
      return row.reasoningOutputTokens ?? null
    case 'total':
      return row.totalTokens ?? null
    case 'turns':
      return row.turnCount ?? null
    case 'lastActivity':
      return row.lastActivity || null
  }
}

function compareSortValues(a: SortValue, b: SortValue): number {
  // 无值始终排到末尾，不因升/降序翻到最前。
  const aMissing = a === null || a === ''
  const bMissing = b === null || b === ''
  if (aMissing || bMissing) {
    if (aMissing && bMissing) return 0
    return aMissing ? 1 : -1
  }

  let result: number
  if (typeof a === 'number' && typeof b === 'number') {
    result = a - b
  } else {
    result = String(a).localeCompare(String(b), undefined, { numeric: true, sensitivity: 'base' })
  }
  return sortDirection.value === 'asc' ? result : -result
}

const rows = computed<UsageRow[]>(() => {
  const r = store.report
  if (!r) return []
  let list: UsageRow[]
  if (store.activeView === 'daily') list = r.daily || []
  else if (store.activeView === 'model') list = r.byModel || []
  else list = r.byConversation || []

  // 保持稳定排序：值相同时沿用后端原顺序，避免点击后同值行跳动。
  return list
    .map((row, index) => ({ row, index }))
    .sort((a, b) => {
      const primary = compareSortValues(sortValue(a.row, sortKey.value), sortValue(b.row, sortKey.value))
      return primary || a.index - b.index
    })
    .map(({ row }) => row)
})
"""
body = replace_once(body, old, new, "sort state and rows")

old = """          @update:model-value="store.setView($event as UsageView)"
"""
new = """          @update:model-value="setUsageView($event as UsageView)"
"""
body = replace_once(body, old, new, "view switch")

old = """            <thead>
              <tr>
                <th class="first-col">{{ firstColLabel }}</th>
                <th v-if="showModelsCol">{{ t('usage.col.model') }}</th>
                <th class="num">{{ t('usage.col.cacheHit') }}</th>
                <th class="num">{{ t('usage.col.input') }}</th>
                <th class="num">{{ t('usage.col.output') }}</th>
                <th class="num">{{ t('usage.col.reasoning') }}</th>
                <th class="num">{{ t('usage.col.total') }}</th>
                <th class="num">{{ t('usage.col.turns') }}</th>
                <th>{{ t('usage.col.lastActivity') }}</th>
              </tr>
            </thead>
"""
new = """            <thead>
              <tr>
                <th class="first-col" scope="col" :aria-sort="sortAria('group')">
                  <button type="button" class="usage-sort-button" @click="setSort('group')">
                    <span>{{ firstColLabel }}</span>
                    <span class="usage-sort-indicator" aria-hidden="true">{{ sortIndicator('group') }}</span>
                  </button>
                </th>
                <th v-if="showModelsCol" scope="col" :aria-sort="sortAria('model')">
                  <button type="button" class="usage-sort-button" @click="setSort('model')">
                    <span>{{ t('usage.col.model') }}</span>
                    <span class="usage-sort-indicator" aria-hidden="true">{{ sortIndicator('model') }}</span>
                  </button>
                </th>
                <th class="num" scope="col" :aria-sort="sortAria('cacheHit')">
                  <button type="button" class="usage-sort-button" @click="setSort('cacheHit')">
                    <span>{{ t('usage.col.cacheHit') }}</span>
                    <span class="usage-sort-indicator" aria-hidden="true">{{ sortIndicator('cacheHit') }}</span>
                  </button>
                </th>
                <th class="num" scope="col" :aria-sort="sortAria('input')">
                  <button type="button" class="usage-sort-button" @click="setSort('input')">
                    <span>{{ t('usage.col.input') }}</span>
                    <span class="usage-sort-indicator" aria-hidden="true">{{ sortIndicator('input') }}</span>
                  </button>
                </th>
                <th class="num" scope="col" :aria-sort="sortAria('output')">
                  <button type="button" class="usage-sort-button" @click="setSort('output')">
                    <span>{{ t('usage.col.output') }}</span>
                    <span class="usage-sort-indicator" aria-hidden="true">{{ sortIndicator('output') }}</span>
                  </button>
                </th>
                <th class="num" scope="col" :aria-sort="sortAria('reasoning')">
                  <button type="button" class="usage-sort-button" @click="setSort('reasoning')">
                    <span>{{ t('usage.col.reasoning') }}</span>
                    <span class="usage-sort-indicator" aria-hidden="true">{{ sortIndicator('reasoning') }}</span>
                  </button>
                </th>
                <th class="num" scope="col" :aria-sort="sortAria('total')">
                  <button type="button" class="usage-sort-button" @click="setSort('total')">
                    <span>{{ t('usage.col.total') }}</span>
                    <span class="usage-sort-indicator" aria-hidden="true">{{ sortIndicator('total') }}</span>
                  </button>
                </th>
                <th class="num" scope="col" :aria-sort="sortAria('turns')">
                  <button type="button" class="usage-sort-button" @click="setSort('turns')">
                    <span>{{ t('usage.col.turns') }}</span>
                    <span class="usage-sort-indicator" aria-hidden="true">{{ sortIndicator('turns') }}</span>
                  </button>
                </th>
                <th scope="col" :aria-sort="sortAria('lastActivity')">
                  <button type="button" class="usage-sort-button" @click="setSort('lastActivity')">
                    <span>{{ t('usage.col.lastActivity') }}</span>
                    <span class="usage-sort-indicator" aria-hidden="true">{{ sortIndicator('lastActivity') }}</span>
                  </button>
                </th>
              </tr>
            </thead>
"""
body = replace_once(body, old, new, "sortable table headers")

old = """.usage-table tbody tr + tr td {
  border-top: 1px solid var(--border);
}
"""
new = """.usage-sort-button {
  width: 100%;
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 0;
  border: 0;
  background: transparent;
  color: inherit;
  font: inherit;
  font-weight: inherit;
  text-align: inherit;
  cursor: pointer;
}
.usage-table th.num .usage-sort-button {
  justify-content: flex-end;
}
.usage-sort-button:hover,
.usage-sort-button:focus-visible {
  color: var(--text);
}
.usage-sort-button:focus-visible {
  outline: 2px solid var(--accent);
  outline-offset: 2px;
  border-radius: var(--radius-sm);
}
.usage-sort-indicator {
  min-width: 1em;
  color: var(--accent);
  font-family: var(--font-mono);
  text-align: center;
}
.usage-table th:not([aria-sort]) .usage-sort-indicator {
  color: var(--text-muted);
  opacity: 0.55;
}
.usage-table tbody tr + tr td {
  border-top: 1px solid var(--border);
}
"""
body = replace_once(body, old, new, "sortable header styles")

USAGE.write_text(body, encoding="utf-8")
print("r32 usage click-sort hotfix: APPLIED")
