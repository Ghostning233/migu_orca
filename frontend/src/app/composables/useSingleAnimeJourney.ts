/**
 * Single-anime journey state (US-275).
 *
 * This module is deliberately API-free. It is the request-scoped state
 * boundary for the three-step flow; hosts attach transport calls in a later
 * story. Opaque capabilities and the idempotency key therefore live only in
 * the returned in-memory state and are never serialised by this module.
 *
 * The snapshot is a reactive source (US-341): hosts derive their disabled
 * states and in-place reasons from `state`/`canConfirm()`, so a successful
 * modify must invalidate those host computeds.
 */
import { shallowRef } from 'vue'

import type { operations } from '@/api/generated/api'

type JsonBody<Operation extends keyof operations> = NonNullable<
  operations[Operation]['requestBody']
>['content']['application/json']

type JsonResult<Operation extends keyof operations> = operations[Operation]['responses'][200] extends {
  content: { 'application/json': { result: infer Result } }
}
  ? NonNullable<Result>
  : never

export type CreateRequestBody = JsonBody<'createRequest'>
export type CreateRequestResult = JsonResult<'createRequest'>
export type PreviewModifyRequestBody = JsonBody<'previewModifyRequest'>
export type PreviewModifyResult = JsonResult<'previewModifyRequest'>
export type ConfirmRequestSaveBody = JsonBody<'confirmRequestSave'>
export type ConfirmRequestSaveResult = JsonResult<'confirmRequestSave'>
export type AcceptRequestBody = JsonBody<'acceptRequest'>
export type AcceptRequestResult = JsonResult<'acceptRequest'>
export type TrackingItemsResult = JsonResult<'listTrackingItems'>
export type TrackingItemDetailResult = JsonResult<'getTrackingItemDetail'>

export type JourneyPhase =
  | 'input'
  | 'candidates'
  | 'review'
  | 'confirming'
  | 'saved_pending_confirm'
  | 'verification_pending'
  | 'confirmed_pending_tracking'
  | 'complete'

export type JourneyBusyPhase = 'searching' | 'applying' | 'saving' | 'accepting' | null

export interface JourneySnapshot {
  readonly phase: JourneyPhase
  readonly title: string
  readonly candidateCount: number
  readonly selectedCandidate: boolean
  readonly draftId: string | null
  readonly draftRevision: number | null
  readonly dirty: boolean
  readonly busy: JourneyBusyPhase
  readonly idempotencyKey: string | null
  readonly requestId: string | null
  readonly trackingId: string | null
  readonly error: SafeJourneyError | null
}

export interface SafeJourneyError {
  readonly type: string
  readonly message: string
  readonly field?: 'base_revision' | 'draft_id' | 'idempotency_key' | 'request_id'
  readonly currentRevision?: number
  readonly requestId?: string
  readonly retryAction?: 'ACCEPT_SAVED_REQUEST'
}

const PHASES = new Set<JourneyPhase>([
  'input',
  'candidates',
  'review',
  'confirming',
  'saved_pending_confirm',
  'confirmed_pending_tracking',
  'complete',
])

const TRANSITIONS: Record<JourneyPhase, readonly JourneyPhase[]> = {
  input: ['candidates'],
  candidates: ['input', 'review'],
  review: ['input', 'candidates', 'confirming'],
  confirming: ['saved_pending_confirm', 'confirmed_pending_tracking', 'review'],
  saved_pending_confirm: ['confirmed_pending_tracking', 'saved_pending_confirm'],
  verification_pending: ['complete', 'saved_pending_confirm', 'verification_pending'],
  confirmed_pending_tracking: ['complete', 'confirmed_pending_tracking'],
  complete: ['input'],
}

const SAFE_ERROR_TYPES = new Set([
  'draft_expired',
  'draft_evicted',
  'draft_replayed',
  'draft_revision_conflict',
  'draft_reserved',
  'save_confirm_failed',
  'idempotency_conflict',
  'request_cancelled',
  'network_error',
])

const SAFE_MESSAGES: Record<string, string> = {
  draft_expired: '订阅草案已失效，请重新生成。',
  draft_evicted: '订阅草案已失效，请重新生成。',
  draft_replayed: '订阅草案已处理，请刷新状态。',
  draft_revision_conflict: '草案已更新，请基于最新版本重试。',
  draft_reserved: '订阅草案正在处理中，请稍后重试。',
  save_confirm_failed: '已保存订阅方案，但确认未完成，可直接重试确认。',
  idempotency_conflict: '本次操作与已有操作冲突，请重新开始。',
  request_cancelled: '操作已取消。',
  network_error: '网络暂不可用，请重试。',
}

function randomKey(): string {
  if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') return crypto.randomUUID()
  return `journey-${Date.now()}-${Math.random().toString(36).slice(2)}`
}

function asSafeString(value: unknown): string | undefined {
  return typeof value === 'string' && value.length > 0 && value.length <= 128 ? value : undefined
}

/** Project an API failure into the small, safe error vocabulary the UI may render. */
export function toSafeJourneyError(error: unknown): SafeJourneyError {
  const source = error && typeof error === 'object' ? error as Record<string, unknown> : {}
  const rawType = source.type
  let type = typeof rawType === 'string' && SAFE_ERROR_TYPES.has(rawType) ? rawType : 'journey_error'
  const details = source.details && typeof source.details === 'object' ? source.details as Record<string, unknown> : {}
  let field: SafeJourneyError['field']
  let currentRevision: number | undefined
  let requestId: string | undefined
  let retryAction: SafeJourneyError['retryAction']
  if (details.field === 'base_revision' || details.field === 'draft_id' || details.field === 'idempotency_key' || details.field === 'request_id') {
    field = details.field
  }
  if (type === 'draft_revision_conflict' && Number.isInteger(details.current_revision)) {
    currentRevision = details.current_revision as number
  }
  if (type === 'save_confirm_failed' && details.details && typeof details.details === 'object') {
    const nested = details.details as Record<string, unknown>
    const savedRequestId = asSafeString(nested.request_id)
    if (nested.outcome !== 'SAVED_CONFIRM_FAILED' || !savedRequestId || nested.retry_action !== 'ACCEPT_SAVED_REQUEST') {
      type = 'journey_error'
    } else {
      requestId = savedRequestId
      retryAction = nested.retry_action
    }
  }
  return {
    type,
    message: SAFE_MESSAGES[type] ?? '操作失败，请重新尝试。',
    ...(field ? { field } : {}),
    ...(currentRevision === undefined ? {} : { currentRevision }),
    ...(requestId ? { requestId } : {}),
    ...(retryAction ? { retryAction } : {}),
  }
}

export function canTransition(from: JourneyPhase, to: JourneyPhase): boolean {
  return PHASES.has(from) && TRANSITIONS[from].includes(to)
}

export interface SingleAnimeJourney {
  readonly state: JourneySnapshot
  transition: (phase: JourneyPhase) => void
  setTitle: (title: string) => void
  setCandidates: (count: number) => void
  selectCandidate: () => void
  setDraft: (draftId: string, revision: number) => void
  setDirty: (dirty: boolean) => void
  begin: (busy: Exclude<JourneyBusyPhase, null>) => boolean
  finishConfirm: (result?: { requestId?: string; savedOnly?: boolean }) => void
  finishTracking: (trackingId?: string) => void
  finishVerificationPending: () => void
  returnToSavedPending: () => void
  fail: (error: unknown) => void
  discard: () => void
  newConfirmOperation: () => string | null
  canConfirm: () => boolean
}

export function useSingleAnimeJourney(): SingleAnimeJourney {
  // Every transition replaces the snapshot object, so a shallow ref is the
  // precise reactive dependency for hosts without proxying nested fields.
  const snapshot = shallowRef<JourneySnapshot>({
    phase: 'input', title: '', candidateCount: 0, selectedCandidate: false,
    draftId: null, draftRevision: null, dirty: false, busy: null,
    idempotencyKey: null, requestId: null, trackingId: null, error: null,
  })

  const journey: SingleAnimeJourney = {
    get state() { return snapshot.value },
    transition(phase) {
      if (!canTransition(snapshot.value.phase, phase)) throw new Error(`非法单番旅程迁移: ${snapshot.value.phase} -> ${phase}`)
      snapshot.value = { ...snapshot.value, phase, error: null }
    },
    setTitle(title) { snapshot.value = { ...snapshot.value, title: title.trim(), error: null } },
    setCandidates(count) { snapshot.value = { ...snapshot.value, candidateCount: Math.max(0, Math.floor(count)), selectedCandidate: false, error: null } },
    selectCandidate() { if (snapshot.value.phase !== 'candidates' || snapshot.value.candidateCount < 1) return; snapshot.value = { ...snapshot.value, selectedCandidate: true, error: null } },
    setDraft(draftId, revision) { if (snapshot.value.phase === 'candidates') journey.transition('review'); snapshot.value = { ...snapshot.value, draftId, draftRevision: revision, dirty: false, idempotencyKey: null, error: null } },
    setDirty(dirty) { snapshot.value = { ...snapshot.value, dirty, ...(dirty ? { idempotencyKey: null } : {}) } },
    begin(busy) {
      if (snapshot.value.busy !== null) return false
      if (busy === 'searching' && snapshot.value.phase !== 'input') return false
      if (busy === 'saving' && !journey.canConfirm()) return false
      if (busy === 'accepting' && snapshot.value.phase !== 'saved_pending_confirm') return false
      snapshot.value = { ...snapshot.value, busy, error: null }
      return true
    },
    finishConfirm(result = {}) {
      snapshot.value = { ...snapshot.value, busy: null, requestId: result.requestId ?? snapshot.value.requestId, phase: result.savedOnly ? 'saved_pending_confirm' : 'confirmed_pending_tracking', dirty: false, draftId: null, draftRevision: null, idempotencyKey: null }
    },
    finishTracking(trackingId) { snapshot.value = { ...snapshot.value, busy: null, trackingId: trackingId ?? snapshot.value.trackingId, phase: trackingId ? 'complete' : 'confirmed_pending_tracking' } },
    finishVerificationPending() { snapshot.value = { ...snapshot.value, busy: null, phase: 'verification_pending' } },
    returnToSavedPending() { snapshot.value = { ...snapshot.value, busy: null, phase: 'saved_pending_confirm', error: null } },
    fail(error) {
      const safeError = toSafeJourneyError(error)
      const clearsConfirmKey = safeError.type === 'idempotency_conflict' ||
        safeError.type === 'draft_expired' || safeError.type === 'draft_evicted' ||
        safeError.type === 'draft_replayed' || safeError.type === 'draft_revision_conflict'
      if (safeError.type === 'save_confirm_failed' && safeError.requestId && safeError.retryAction === 'ACCEPT_SAVED_REQUEST') {
        snapshot.value = {
          ...snapshot.value,
          phase: 'saved_pending_confirm',
          busy: null,
          draftId: null,
          draftRevision: null,
          dirty: false,
          idempotencyKey: null,
          requestId: safeError.requestId,
          error: safeError,
        }
        return
      }
      snapshot.value = {
        ...snapshot.value,
        phase: snapshot.value.phase === 'confirming' ? 'review' : snapshot.value.phase,
        busy: null,
        error: safeError,
        ...(clearsConfirmKey ? { idempotencyKey: null } : {}),
      }
    },
    discard() { snapshot.value = { ...snapshot.value, phase: 'input', title: '', candidateCount: 0, selectedCandidate: false, draftId: null, draftRevision: null, dirty: false, busy: null, idempotencyKey: null, requestId: null, trackingId: null, error: null } },
    newConfirmOperation() {
      if (!journey.canConfirm()) return null
      if (snapshot.value.idempotencyKey) return snapshot.value.idempotencyKey
      const key = randomKey()
      snapshot.value = { ...snapshot.value, idempotencyKey: key }
      return key
    },
    canConfirm() { return snapshot.value.phase === 'review' && snapshot.value.busy === null && !snapshot.value.dirty && !!snapshot.value.draftId && snapshot.value.draftRevision !== null },
  }
  return journey
}
