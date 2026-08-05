// CAS-R33-CHAIN-HEALTH
// CAS-R34-RUNTIME-BEHAVIOR-HEALTH
import { api } from './http'

export type ChainHealthStatus = 'ok' | 'degraded' | 'error' | 'unknown' | 'idle'

export interface ChainHealthLayer {
  status: ChainHealthStatus
  code: string
  summary: string
  latencyMs?: number | null
  facts: string[]
}

export interface ChainHealthProvider {
  id: string
  name: string
  baseUrl: string
  displayUrl: string
  apiFormat: string
  host: string
  port: number
  loopback: boolean
}

export interface ChainHealthContainer {
  id: string
  name: string
  service?: string | null
  running: boolean
  status: string
  health?: string | null
  restarting: boolean
  oomKilled: boolean
  exitCode: number
  restartCount: number
  restartDelta: number
  cpu?: string | null
  memory?: string | null
  pids?: string | null
  target: boolean
}

export interface ChainRuntimeHealth {
  layer: ChainHealthLayer
  kind: string
  dockerDesktop?: string | null
  dockerServerVersion?: string | null
  composeProject?: string | null
  containers: ChainHealthContainer[]
  ownerPid?: number | null
  ownerProcess?: string | null
}

export interface ChainHealthSnapshot {
  observedAt: string
  overall: ChainHealthStatus
  overallSummary: string
  provider?: ChainHealthProvider | null
  codex: ChainHealthLayer
  session: ChainHealthLayer
  mcp: ChainHealthLayer
  transfer: ChainHealthLayer
  gateway: ChainHealthLayer
  runtime: ChainRuntimeHealth
  upstream: ChainHealthLayer
  recommendations: string[]
  privacy: string[]
}

export async function getChainHealth(force = false): Promise<ChainHealthSnapshot> {
  const query = force ? '?force=true' : ''
  const result = await api<{ success: boolean; health: ChainHealthSnapshot }>(
    'GET',
    `/api/chain-health${query}`,
  )
  return result.health
}
