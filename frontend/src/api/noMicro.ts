import { api } from './http'

export interface NoMicroLaunchState {
  injection?: {
    status?: string
    phase?: string
    evaluation?: string
    error?: string
    globalMarker?: boolean
  }
  packageVersion?: string
  startedAt?: string
  verifiedAliveAt?: string
  cleanup?: string
  processId?: number | null
}

export interface NoMicroDoctor {
  supported: boolean
  platform: string
  packageFound: boolean
  packageVersion?: string | null
  executablePath?: string | null
  appAsarPath?: string | null
  nodePath?: string | null
  nodeVersion?: string | null
  nodeCompatible: boolean
  targetModuleCount: number
  serialportCount: number
  hidMarkerCount: number
  featureGateCount: number
  stubShapeOk: boolean
  processState: 'running' | 'not-running' | 'unknown' | 'unsupported' | string
  processPids: number[]
  compatible: boolean
  launchReady: boolean
  lastLaunch?: NoMicroLaunchState | null
  warnings: string[]
}

export interface NoMicroLaunchResult {
  success: boolean
  doctor: NoMicroDoctor
  launch: NoMicroLaunchState
  abRunId?: string
  mode?: 'no-lagging' | 'no-micro'
  noLagging?: {
    microAccessoryGuard?: string
    mcpExitGuard?: { status?: string; pid?: number; scope?: string; error?: string }
  }
}

export interface NormalAbLaunchResult {
  success: boolean
  abRunId: string
  mode: 'normal'
}

export function getNoMicroDoctor() {
  return api<NoMicroDoctor>('GET', '/api/desktop/no-micro/doctor')
}

export function launchCodexNormalAb() {
  return api<NormalAbLaunchResult>('POST', '/api/desktop/no-micro/launch?mode=normal')
}

export function launchCodexNoMicro() {
  return api<NoMicroLaunchResult>('POST', '/api/desktop/no-micro/launch')
}

// CAS-NO-LAGGING-R32-API-ALIAS
export function launchCodexNoLagging() {
  return api<NoMicroLaunchResult>('POST', '/api/desktop/no-micro/launch?mode=no-lagging')
}
