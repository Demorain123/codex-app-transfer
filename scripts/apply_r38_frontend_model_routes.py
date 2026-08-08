from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MARKER = "CAS-R38-MODEL-ROUTE-OBSERVABILITY"


def load(rel: str) -> str:
    path = ROOT / rel
    if not path.is_file():
        raise SystemExit(f"r38 required file missing: {rel}")
    return path.read_text(encoding="utf-8")


def save(rel: str, body: str) -> None:
    (ROOT / rel).write_text(body, encoding="utf-8")


def replace_once(body: str, old: str, new: str, label: str) -> str:
    count = body.count(old)
    if count != 1:
        raise SystemExit(f"r38 anchor count {count}, expected 1: {label}")
    return body.replace(old, new, 1)


rel = "frontend/src/api/chainHealth.ts"
body = load(rel)
if MARKER not in body:
    body = body.replace(
        "// CAS-R37-FAULT-ATTRIBUTION-QUOTA-GUARD\n",
        "// CAS-R37-FAULT-ATTRIBUTION-QUOTA-GUARD\n// CAS-R38-MODEL-ROUTE-OBSERVABILITY\n",
        1,
    )
    body = replace_once(
        body,
        "export interface ChainHealthSnapshot {\n",
        '''export interface ModelRouteHealth {
  provider: string
  model: string
  status: ChainHealthStatus
  code: string
  summary: string
  ageMs: number
  rawStatus?: number | null
  requestBytes: number
  requestKind?: string | null
  toolCount: number
  duplicateToolNames: string[]
  inputImageCount: number
  successes: number
  failures: number
}

export interface ChainHealthSnapshot {
''',
        "frontend model route type",
    )
    body = replace_once(
        body,
        "  diagnosis: ChainHealthLayer\n  recommendations: string[]",
        "  diagnosis: ChainHealthLayer\n  modelRoutes: ModelRouteHealth[]\n  recommendations: string[]",
        "frontend model routes field",
    )
    save(rel, body)

rel = "frontend/src/pages/ProxyPage.vue"
body = load(rel)
if MARKER not in body:
    body = body.replace(
        "// CAS-R37-FAULT-ATTRIBUTION-QUOTA-GUARD\n",
        "// CAS-R37-FAULT-ATTRIBUTION-QUOTA-GUARD\n// CAS-R38-MODEL-ROUTE-OBSERVABILITY\n",
        1,
    )
    body = replace_once(
        body,
        "function chainStatusLabel(status: ChainHealthStatus) {\n  return t(`chainHealth.status.${status}`)\n}\n",
        '''function chainStatusLabel(status: ChainHealthStatus) {
  return t(`chainHealth.status.${status}`)
}
function formatRouteBytes(bytes: number) {
  if (bytes >= 1024 * 1024) return `${(bytes / 1024 / 1024).toFixed(2)} MiB`
  return `${Math.max(0, Math.round(bytes / 1024))} KiB`
}
''',
        "frontend route bytes formatter",
    )
    grid_anchor = '''      <div v-if="chainRecovery" class="chain-health__recovery-report">
'''
    routes = '''      <div v-if="chainHealth?.modelRoutes?.length" class="chain-health__model-routes">
        <strong>{{ t('chainHealth.modelRoutes') }}</strong>
        <div class="chain-health__route-grid">
          <article
            v-for="route in chainHealth.modelRoutes"
            :key="`${route.provider}-${route.model}`"
            class="chain-route"
            :class="`chain-route--${route.status}`"
          >
            <div class="chain-route__head">
              <span class="chain-layer__dot" />
              <strong>{{ route.model }}</strong>
              <span>{{ chainStatusLabel(route.status) }}</span>
            </div>
            <p>{{ route.summary }}</p>
            <small>
              {{ formatRouteBytes(route.requestBytes) }} · raw {{ route.rawStatus ?? '-' }} ·
              tools {{ route.toolCount }} · images {{ route.inputImageCount }}
            </small>
            <code v-if="route.duplicateToolNames.length">
              duplicate={{ route.duplicateToolNames.join(',') }}
            </code>
          </article>
        </div>
      </div>

'''
    body = replace_once(body, grid_anchor, routes + grid_anchor, "frontend model route cards")
    css_anchor = ".chain-health__recommendations {\n"
    css = '''.chain-health__model-routes {
  margin-top: var(--space-3);
  padding: var(--space-3);
  border: 1px solid var(--border);
  border-radius: var(--radius);
}
.chain-health__route-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(230px, 1fr));
  gap: var(--space-2);
  margin-top: var(--space-2);
}
.chain-route {
  min-width: 0;
  padding: var(--space-3);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  background: var(--surface-2);
}
.chain-route--error { border-color: color-mix(in srgb, var(--danger) 45%, var(--border)); }
.chain-route--degraded { border-color: color-mix(in srgb, #f59e0b 45%, var(--border)); }
.chain-route__head { display: flex; align-items: center; gap: 6px; }
.chain-route__head strong { flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; }
.chain-route__head span:last-child { color: var(--text-muted); font-size: var(--fs-xs); }
.chain-route p { margin: 8px 0; color: var(--text-secondary); font-size: var(--fs-xs); line-height: 1.45; }
.chain-route small, .chain-route code { display: block; color: var(--text-muted); font-family: var(--font-mono); font-size: var(--fs-xs); }

'''
    body = replace_once(body, css_anchor, css + css_anchor, "frontend model route css")
    save(rel, body)

for rel, zh in (("frontend/src/i18n/zh.ts", True), ("frontend/src/i18n/en.ts", False)):
    body = load(rel)
    if '"chainHealth.modelRoutes"' not in body:
        anchor = '  "proxy.stats.today": '
        idx = body.find(anchor)
        if idx < 0:
            raise SystemExit(f"r38 i18n anchor missing: {rel}")
        line_end = body.find("\n", idx)
        value = '  "chainHealth.modelRoutes": "模型路径",\n' if zh else '  "chainHealth.modelRoutes": "Model routes",\n'
        body = body[: line_end + 1] + value + body[line_end + 1 :]
        save(rel, body)

print("r38 frontend model routes: COMPLETE")
