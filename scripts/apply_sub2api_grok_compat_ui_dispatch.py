from pathlib import Path
import runpy

LEGACY_PATCHER = Path("scripts/apply_sub2api_grok_compat_ui.py")


def contains(path: str, *needles: str) -> bool:
    p = Path(path)
    if not p.is_file():
        return False
    text = p.read_text(encoding="utf-8")
    return all(needle in text for needle in needles)


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if new in text:
        print(f"[ok] {label}: already applied")
        return text
    if old not in text:
        raise SystemExit(f"anchor not found: {label}")
    print(f"[ok] {label}: applied")
    return text.replace(old, new, 1)


def insert_after_once(text: str, anchor: str, addition: str, marker: str, label: str) -> str:
    if marker in text:
        print(f"[ok] {label}: already applied")
        return text
    if anchor not in text:
        raise SystemExit(f"anchor not found: {label}")
    print(f"[ok] {label}: applied")
    return text.replace(anchor, anchor + addition, 1)


def remove_if_present(text: str, old: str, label: str) -> str:
    if old not in text:
        print(f"[ok] {label}: already absent")
        return text
    print(f"[ok] {label}: removed")
    return text.replace(old, "", 1)


def overlay_complete() -> bool:
    """Semantic, formatting-insensitive completeness check for the UI/backend overlay."""
    return all(
        [
            Path("frontend/src/components/provider/Sub2ApiGrokCompatControls.vue").is_file(),
            contains(
                "src-tauri/src/admin/handlers/providers/crud.rs",
                "pub sub2api_grok_compat: Option<bool>",
                "pub sub2api_grok_free_cache_compat: Option<bool>",
                '"sub2apiGrokCompat".into()',
                '"sub2apiGrokFreeCacheCompat".into()',
                "input.sub2api_grok_compat",
                "input.sub2api_grok_free_cache_compat",
            ),
            contains(
                "frontend/src/api/types.ts",
                "sub2apiGrokCompat?: boolean",
                "sub2apiGrokFreeCacheCompat?: boolean",
            ),
            contains(
                "frontend/src/api/providers.ts",
                "sub2apiGrokCompat: !!provider.sub2apiGrokCompat",
                "sub2apiGrokFreeCacheCompat: !!provider.sub2apiGrokFreeCacheCompat",
                "sub2apiGrokCompat: !!payload.sub2apiGrokCompat",
                "sub2apiGrokFreeCacheCompat: !!payload.sub2apiGrokFreeCacheCompat",
            ),
            contains(
                "frontend/src/components/provider/ProviderFormModal.vue",
                "Sub2ApiGrokCompatControls",
                'v-model:enabled="form.sub2apiGrokCompat"',
                'v-model:cache-enabled="form.sub2apiGrokFreeCacheCompat"',
            ),
            contains(
                "frontend/src/layout/TopTabBar.vue",
                "compat-build-badge",
                "compat.buildBadge",
            ),
            contains(
                "frontend/src/layout/AppLayout.vue",
                "Codex App Transfer — Sub2API Grok Compat",
            ),
            contains(
                "src-tauri/tauri.conf.json",
                "Codex App Transfer — Sub2API Grok Compat",
            ),
            contains(
                "frontend/src/i18n/zh.ts",
                '"compat.buildBadge"',
                '"providerForm.grokCompat"',
                '"providerForm.grokFreeCacheCompat"',
            ),
            contains(
                "frontend/src/i18n/en.ts",
                '"compat.buildBadge"',
                '"providerForm.grokCompat"',
                '"providerForm.grokFreeCacheCompat"',
            ),
        ]
    )


def apply_codex_config_preservation() -> None:
    """Keep the user's external model catalog, but do not own sandbox policy.

    The Sub2API Grok compat layer is a Responses wire shim. Its only Codex-config
    exception is preserving an already configured external model_catalog_json.
    Sandbox/approval settings are deliberately left to upstream Transfer behavior;
    the compat overlay must never introduce a new sandbox ownership rule.
    """
    path = Path("src-tauri/src/admin/services/desktop/snapshot.rs")
    text = path.read_text(encoding="utf-8")

    # r8 regression cleanup: this compat-only flag made a provider switch retain
    # sandbox/approval values that r7/upstream would have cleared. That can surface
    # Codex's Windows elevated-sandbox first-run/UAC setup unexpectedly. Remove the
    # flag completely; Grok Responses compatibility does not need sandbox ownership.
    text = remove_if_present(
        text,
        '''    /// CAS-SUB2API-GROK-COMPAT-HOOK: when Transfer network access is off,\n    /// keep the user's existing sandbox/approval policy unchanged.\n    pub preserve_user_sandbox_policy: bool,\n''',
        "DesktopConfigTarget sandbox preservation flag",
    )
    text = remove_if_present(
        text,
        '''        preserve_user_sandbox_policy: api_format_lower == "responses"\n            && provider\n                .get("sub2apiGrokCompat")\n                .and_then(Value::as_bool)\n                .unwrap_or(false),\n''',
        "compat sandbox preservation assignment",
    )
    text = remove_if_present(
        text,
        '''            preserve_user_sandbox_policy: target.preserve_user_sandbox_policy,\n''',
        "ApplyConfig sandbox preservation pass-through",
    )

    if "pub preserve_external_model_catalog: bool," not in text:
        text = replace_once(
            text,
            '''    pub is_qoder: bool,\n}''',
            '''    pub is_qoder: bool,\n    /// CAS-SUB2API-GROK-COMPAT-HOOK: keep an existing external Codex model catalog.\n    pub preserve_external_model_catalog: bool,\n}''',
            "DesktopConfigTarget preserve external catalog flag",
        )

    if "preserve_external_model_catalog: api_format_lower" not in text:
        text = replace_once(
            text,
            '''        review_model_slot: provider_review_model_slot(provider),\n        is_qoder: provider_is_qoder(provider),\n    }''',
            '''        review_model_slot: provider_review_model_slot(provider),\n        is_qoder: provider_is_qoder(provider),\n        // CAS-SUB2API-GROK-COMPAT-HOOK: wire shim, not a model-catalog owner.\n        preserve_external_model_catalog: api_format_lower == "responses"\n            && provider\n                .get("sub2apiGrokCompat")\n                .and_then(Value::as_bool)\n                .unwrap_or(false),\n    }''',
            "derive preserve external catalog from compat provider",
        )

    if "preserve_external_model_catalog: target.preserve_external_model_catalog" not in text:
        text = replace_once(
            text,
            '''            codex_network_access: target.codex_network_access,\n            preserve_chatgpt_auth,\n        },''',
            '''            codex_network_access: target.codex_network_access,\n            preserve_chatgpt_auth,\n            // CAS-SUB2API-GROK-COMPAT-HOOK\n            preserve_external_model_catalog: target.preserve_external_model_catalog,\n        },''',
            "pass preserve external catalog into ApplyConfig",
        )
    path.write_text(text, encoding="utf-8")
    print(f"[ok] patched {path}")

    path = Path("crates/codex_integration/src/apply.rs")
    text = path.read_text(encoding="utf-8")

    text = remove_if_present(
        text,
        '''    /// CAS-SUB2API-GROK-COMPAT-HOOK: keep user sandbox/approval policy when\n    /// the Transfer-specific network-access override is disabled.\n    #[serde(default)]\n    pub preserve_user_sandbox_policy: bool,\n''',
        "ApplyConfig sandbox preservation flag",
    )
    if "} else if !cfg.preserve_user_sandbox_policy {" in text:
        text = text.replace(
            "} else if !cfg.preserve_user_sandbox_policy {",
            "} else {",
            1,
        )
        print("[ok] restored upstream/r7 sandbox else branch")
    else:
        print("[ok] upstream/r7 sandbox else branch already restored")

    if "pub preserve_external_model_catalog: bool," not in text:
        text = replace_once(
            text,
            '''    #[serde(default)]\n    pub preserve_chatgpt_auth: bool,\n}''',
            '''    #[serde(default)]\n    pub preserve_chatgpt_auth: bool,\n    /// CAS-SUB2API-GROK-COMPAT-HOOK: keep user-owned model_catalog_json.\n    #[serde(default)]\n    pub preserve_external_model_catalog: bool,\n}''',
            "ApplyConfig preserve external catalog flag",
        )

    anchor = '''    let models = catalog_models_for_provider_with_display_names(\n        cfg.provider_name,\n        cfg.default_model,\n        cfg.supports_1m,\n        cfg.model_mappings,\n        cfg.model_capabilities,\n        cfg.model_display_names,\n        cfg.review_model_slot,\n        cfg.is_qoder,\n    );\n    if models.is_empty() {'''
    replacement = '''    let models = catalog_models_for_provider_with_display_names(\n        cfg.provider_name,\n        cfg.default_model,\n        cfg.supports_1m,\n        cfg.model_mappings,\n        cfg.model_capabilities,\n        cfg.model_display_names,\n        cfg.review_model_slot,\n        cfg.is_qoder,\n    );\n\n    // CAS-SUB2API-GROK-COMPAT-HOOK: preserve a user-owned external catalog.\n    let preserve_external_model_catalog = if cfg.preserve_external_model_catalog {\n        let transfer_catalog = paths\n            .model_catalog_json\n            .to_string_lossy()\n            .replace('\\\\', "/")\n            .to_ascii_lowercase();\n        std::fs::read_to_string(&paths.config_toml)\n            .ok()\n            .and_then(|content| {\n                content\n                    .lines()\n                    .take_while(|line| !line.trim_start().starts_with('['))\n                    .find_map(|line| {\n                        crate::residual::parse_root_string_value(line.trim_start(), CODEX_MODEL_CATALOG_KEY)\n                    })\n            })\n            .is_some_and(|configured| {\n                let configured = configured.replace('\\\\', "/").to_ascii_lowercase();\n                !configured.trim().is_empty() && configured != transfer_catalog\n            })\n    } else {\n        false\n    };\n\n    if preserve_external_model_catalog {\n        // External catalog is authoritative: keep its path and model_context_window.\n    } else if models.is_empty() {'''
    if "let preserve_external_model_catalog = if cfg.preserve_external_model_catalog" not in text:
        text = replace_once(
            text,
            anchor,
            replacement,
            "preserve user model catalog before provider catalog policy",
        )

    if "model_catalog_json_set: preserve_external_model_catalog || !models.is_empty()," not in text:
        text = replace_once(
            text,
            '''        model_catalog_json_set: !models.is_empty(),''',
            '''        model_catalog_json_set: preserve_external_model_catalog || !models.is_empty(),''',
            "ApplyResult catalog state",
        )
    path.write_text(text, encoding="utf-8")
    print(f"[ok] patched {path}")


def config_preservation_complete() -> bool:
    snapshot = Path("src-tauri/src/admin/services/desktop/snapshot.rs").read_text(encoding="utf-8")
    apply = Path("crates/codex_integration/src/apply.rs").read_text(encoding="utf-8")
    return all(
        [
            "preserve_external_model_catalog" in snapshot,
            'get("sub2apiGrokCompat")' in snapshot,
            "preserve_user_sandbox_policy" not in snapshot,
            "pub preserve_external_model_catalog: bool" in apply,
            "if preserve_external_model_catalog {" in apply,
            "preserve_user_sandbox_policy" not in apply,
        ]
    )


def apply_usage_table_sorting() -> None:
    """Add a sortable usage table without owning upstream usage data or APIs."""
    path = Path("frontend/src/pages/UsagePage.vue")
    text = path.read_text(encoding="utf-8")
    marker = "CAS-SUB2API-USAGE-SORT-HOOK"
    if marker in text:
        print("[ok] usage table sorting already applied")
        return

    text = replace_once(
        text,
        "import { computed, onMounted, ref } from 'vue'",
        "import { computed, onMounted, ref, watch } from 'vue'",
        "UsagePage watch import",
    )

    old_rows = '''const rows = computed<UsageRow[]>(() => {\n  const r = store.report\n  if (!r) return []\n  let list: UsageRow[]\n  if (store.activeView === 'daily') list = r.daily || []\n  else if (store.activeView === 'model') list = r.byModel || []\n  else list = r.byConversation || []\n  // daily 按日期降序;model/conversation 按 total tokens 降序\n  return list.slice().sort((a, b) => {\n    if (store.activeView === 'daily') return (b.group || '').localeCompare(a.group || '')\n    return (b.totalTokens || 0) - (a.totalTokens || 0)\n  })\n})'''
    new_rows = '''// CAS-SUB2API-USAGE-SORT-HOOK: table-header sorting kept in the compat UI overlay.\ntype UsageSortKey =\n  | 'group'\n  | 'model'\n  | 'cacheHit'\n  | 'input'\n  | 'output'\n  | 'reasoning'\n  | 'total'\n  | 'turns'\n  | 'last'\ntype SortDirection = 'asc' | 'desc'\ntype UsageSortValue = string | number | null\n\nconst sortKey = ref<UsageSortKey>('last')\nconst sortDirection = ref<SortDirection>('desc')\n\nfunction defaultSortDirection(key: UsageSortKey): SortDirection {\n  return key === 'group' || key === 'model' ? 'asc' : 'desc'\n}\n\nfunction resetSortForView(view: UsageView) {\n  if (view === 'conversation') {\n    sortKey.value = 'last'\n    sortDirection.value = 'desc'\n  } else if (view === 'daily') {\n    sortKey.value = 'group'\n    sortDirection.value = 'desc'\n  } else {\n    sortKey.value = 'total'\n    sortDirection.value = 'desc'\n  }\n}\n\nwatch(() => store.activeView, resetSortForView, { immediate: true })\n\nfunction setSort(key: UsageSortKey) {\n  if (sortKey.value === key) {\n    sortDirection.value = sortDirection.value === 'asc' ? 'desc' : 'asc'\n    return\n  }\n  sortKey.value = key\n  sortDirection.value = defaultSortDirection(key)\n}\n\nfunction sortIndicator(key: UsageSortKey): string {\n  if (sortKey.value !== key) return ''\n  return sortDirection.value === 'asc' ? '▲' : '▼'\n}\n\nfunction sortAria(key: UsageSortKey): 'ascending' | 'descending' | 'none' {\n  if (sortKey.value !== key) return 'none'\n  return sortDirection.value === 'asc' ? 'ascending' : 'descending'\n}\n\nfunction rowSortValue(row: UsageRow, key: UsageSortKey): UsageSortValue {\n  switch (key) {\n    case 'group': {\n      const value =\n        store.activeView === 'conversation' ? (row.displayName || row.group || '') : row.group || ''\n      return value.trim() || null\n    }\n    case 'model': {\n      if (store.activeView === 'conversation' && row.upstreamModel) return row.upstreamModel\n      const value = (row.models || []).join(', ').trim()\n      return value || null\n    }\n    case 'cacheHit':\n      return cacheHitPct(row)\n    case 'input':\n      return row.inputTokens ?? null\n    case 'output':\n      return row.outputTokens ?? null\n    case 'reasoning':\n      return row.reasoningOutputTokens ?? null\n    case 'total':\n      return row.totalTokens ?? null\n    case 'turns':\n      return row.turnCount ?? null\n    case 'last':\n      return row.lastActivity || null\n  }\n}\n\nfunction compareSortValues(a: UsageSortValue, b: UsageSortValue): number {\n  if (a == null && b == null) return 0\n  if (a == null) return 1\n  if (b == null) return -1\n\n  let comparison: number\n  if (typeof a === 'number' && typeof b === 'number') comparison = a - b\n  else comparison = String(a).localeCompare(String(b), undefined, { numeric: true, sensitivity: 'base' })\n  return sortDirection.value === 'asc' ? comparison : -comparison\n}\n\nfunction compareUsageRows(a: UsageRow, b: UsageRow): number {\n  const primary = compareSortValues(rowSortValue(a, sortKey.value), rowSortValue(b, sortKey.value))\n  if (primary !== 0) return primary\n  return (b.totalTokens || 0) - (a.totalTokens || 0)\n}\n\nconst rows = computed<UsageRow[]>(() => {\n  const r = store.report\n  if (!r) return []\n  let list: UsageRow[]\n  if (store.activeView === 'daily') list = r.daily || []\n  else if (store.activeView === 'model') list = r.byModel || []\n  else list = r.byConversation || []\n  return list.slice().sort(compareUsageRows)\n})'''
    text = replace_once(text, old_rows, new_rows, "UsagePage sortable rows")

    old_headers = '''                <th class="first-col">{{ firstColLabel }}</th>\n                <th v-if="showModelsCol">{{ t('usage.col.model') }}</th>\n                <th class="num">{{ t('usage.col.cacheHit') }}</th>\n                <th class="num">{{ t('usage.col.input') }}</th>\n                <th class="num">{{ t('usage.col.output') }}</th>\n                <th class="num">{{ t('usage.col.reasoning') }}</th>\n                <th class="num">{{ t('usage.col.total') }}</th>\n                <th class="num">{{ t('usage.col.turns') }}</th>\n                <th>{{ t('usage.col.lastActivity') }}</th>'''
    new_headers = '''                <th class="first-col sortable" :aria-sort="sortAria('group')">\n                  <button type="button" class="usage-sort-button" @click="setSort('group')">\n                    <span>{{ firstColLabel }}</span>\n                    <span v-if="sortIndicator('group')" class="usage-sort-indicator" aria-hidden="true">{{ sortIndicator('group') }}</span>\n                  </button>\n                </th>\n                <th v-if="showModelsCol" class="sortable" :aria-sort="sortAria('model')">\n                  <button type="button" class="usage-sort-button" @click="setSort('model')">\n                    <span>{{ t('usage.col.model') }}</span>\n                    <span v-if="sortIndicator('model')" class="usage-sort-indicator" aria-hidden="true">{{ sortIndicator('model') }}</span>\n                  </button>\n                </th>\n                <th class="num sortable" :aria-sort="sortAria('cacheHit')">\n                  <button type="button" class="usage-sort-button" @click="setSort('cacheHit')">\n                    <span>{{ t('usage.col.cacheHit') }}</span>\n                    <span v-if="sortIndicator('cacheHit')" class="usage-sort-indicator" aria-hidden="true">{{ sortIndicator('cacheHit') }}</span>\n                  </button>\n                </th>\n                <th class="num sortable" :aria-sort="sortAria('input')">\n                  <button type="button" class="usage-sort-button" @click="setSort('input')">\n                    <span>{{ t('usage.col.input') }}</span>\n                    <span v-if="sortIndicator('input')" class="usage-sort-indicator" aria-hidden="true">{{ sortIndicator('input') }}</span>\n                  </button>\n                </th>\n                <th class="num sortable" :aria-sort="sortAria('output')">\n                  <button type="button" class="usage-sort-button" @click="setSort('output')">\n                    <span>{{ t('usage.col.output') }}</span>\n                    <span v-if="sortIndicator('output')" class="usage-sort-indicator" aria-hidden="true">{{ sortIndicator('output') }}</span>\n                  </button>\n                </th>\n                <th class="num sortable" :aria-sort="sortAria('reasoning')">\n                  <button type="button" class="usage-sort-button" @click="setSort('reasoning')">\n                    <span>{{ t('usage.col.reasoning') }}</span>\n                    <span v-if="sortIndicator('reasoning')" class="usage-sort-indicator" aria-hidden="true">{{ sortIndicator('reasoning') }}</span>\n                  </button>\n                </th>\n                <th class="num sortable" :aria-sort="sortAria('total')">\n                  <button type="button" class="usage-sort-button" @click="setSort('total')">\n                    <span>{{ t('usage.col.total') }}</span>\n                    <span v-if="sortIndicator('total')" class="usage-sort-indicator" aria-hidden="true">{{ sortIndicator('total') }}</span>\n                  </button>\n                </th>\n                <th class="num sortable" :aria-sort="sortAria('turns')">\n                  <button type="button" class="usage-sort-button" @click="setSort('turns')">\n                    <span>{{ t('usage.col.turns') }}</span>\n                    <span v-if="sortIndicator('turns')" class="usage-sort-indicator" aria-hidden="true">{{ sortIndicator('turns') }}</span>\n                  </button>\n                </th>\n                <th class="sortable" :aria-sort="sortAria('last')">\n                  <button type="button" class="usage-sort-button" @click="setSort('last')">\n                    <span>{{ t('usage.col.lastActivity') }}</span>\n                    <span v-if="sortIndicator('last')" class="usage-sort-indicator" aria-hidden="true">{{ sortIndicator('last') }}</span>\n                  </button>\n                </th>'''
    text = replace_once(text, old_headers, new_headers, "UsagePage sortable headers")

    css_anchor = '''.usage-table thead th {\n  font-size: var(--fs-xs);\n  font-weight: 600;\n  color: var(--text-muted);\n  border-bottom: 1px solid var(--border);\n  background: var(--surface-2);\n  position: sticky;\n  top: 0;\n  z-index: 1;\n}'''
    css_replacement = '''.usage-table thead th {\n  font-size: var(--fs-xs);\n  font-weight: 600;\n  color: var(--text-muted);\n  border-bottom: 1px solid var(--border);\n  background: var(--surface-2);\n  position: sticky;\n  top: 0;\n  z-index: 1;\n}\n/* CAS-SUB2API-USAGE-SORT-HOOK: clickable sort headers; no extra toolbar height. */\n.usage-table th.sortable {\n  padding: 0;\n}\n.usage-sort-button {\n  width: 100%;\n  display: flex;\n  align-items: center;\n  gap: 4px;\n  padding: var(--space-2) var(--space-3);\n  border: 0;\n  background: transparent;\n  color: inherit;\n  font: inherit;\n  text-align: left;\n  white-space: nowrap;\n  cursor: pointer;\n}\n.usage-table th.num .usage-sort-button {\n  justify-content: flex-end;\n  text-align: right;\n}\n.usage-sort-button:hover {\n  color: var(--accent);\n}\n.usage-sort-button:focus-visible {\n  outline: 2px solid var(--accent);\n  outline-offset: -2px;\n}\n.usage-sort-indicator {\n  color: var(--accent);\n  font-size: 9px;\n  line-height: 1;\n}'''
    text = replace_once(text, css_anchor, css_replacement, "UsagePage sortable header styles")

    path.write_text(text, encoding="utf-8")
    print(f"[ok] patched {path} with sortable usage headers")


def usage_table_sorting_complete() -> bool:
    return contains(
        "frontend/src/pages/UsagePage.vue",
        "CAS-SUB2API-USAGE-SORT-HOOK",
        "watch(() => store.activeView, resetSortForView, { immediate: true })",
        "@click=\"setSort('last')\"",
        "return list.slice().sort(compareUsageRows)",
    )


if overlay_complete():
    print("[ok] Sub2API Grok UI/backend overlay already complete; no-op")
else:
    if not LEGACY_PATCHER.is_file():
        raise SystemExit(f"missing first-install UI patcher: {LEGACY_PATCHER}")
    print("[info] UI/backend overlay incomplete; running first-install patcher")
    runpy.run_path(str(LEGACY_PATCHER), run_name="__main__")
    if not overlay_complete():
        raise SystemExit(
            "UI/backend patcher exited without producing a complete overlay; "
            "upstream source likely changed and needs a reviewed anchor update"
        )
    print("[ok] Sub2API Grok UI/backend overlay installed and verified")

apply_codex_config_preservation()
if not config_preservation_complete():
    raise SystemExit("Codex external-catalog preservation / sandbox isolation invariants failed")
print("[ok] Codex external catalog preservation installed; compat sandbox-policy ownership removed")

apply_usage_table_sorting()
if not usage_table_sorting_complete():
    raise SystemExit("Usage table sorting overlay invariants failed")
print("[ok] Usage table sorting overlay installed and verified")
