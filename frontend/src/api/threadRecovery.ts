// CAS-R46-MODEL-SWITCH-OLD-THREAD-RECOVERY
import { api } from './http'

export interface ThreadFailureEvidence {
  observedAt?: string | null
  rawStatus?: number | null
  model?: string | null
  requestKind?: string | null
  requestBytes?: number | null
  turnId?: string | null
  compactionTrigger?: string | null
  compactionReason?: string | null
  source: string
}

export interface ThreadRecoveryPreview {
  threadId: string
  threadFingerprint: string
  rolloutPath: string
  rolloutBytes: number
  rolloutSha256: string
  evidence: ThreadFailureEvidence
  codexCliFound: boolean
  codexCliPath?: string | null
  sameThreadRecoverySupported: boolean
  safeguards: string[]
}

export interface ThreadRecoveryBackup {
  directory: string
  rolloutCopy: string
  sha256: string
  bytes: number
  stateDbCopies: string[]
}

export interface ThreadRecoveryResult {
  action: 'rewindOne' | 'forkPrevious'
  sourceThreadId: string
  resultingThreadId: string
  method: string
  boundaryTurnId?: string | null
  visibleTurnsBefore: number
  visibleTurnsAfter?: number | null
  backup: ThreadRecoveryBackup
  codexRelaunched: boolean
  workspaceFilesChanged: boolean
  note: string
}

export async function getThreadRecoveryPreview(threadId = ''): Promise<ThreadRecoveryPreview> {
  const query = threadId.trim() ? `?threadId=${encodeURIComponent(threadId.trim())}` : ''
  const result = await api<{ success: boolean; preview: ThreadRecoveryPreview }>(
    'GET',
    `/api/thread-recovery/preview${query}`,
  )
  return result.preview
}

export async function runThreadRecovery(
  threadId: string,
  action: 'rewindOne' | 'forkPrevious',
): Promise<ThreadRecoveryResult> {
  const result = await api<{ success: boolean; recovery: ThreadRecoveryResult }>(
    'POST',
    '/api/thread-recovery/action',
    { threadId, action },
  )
  return result.recovery
}
