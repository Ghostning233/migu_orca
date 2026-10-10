/**
 * API-free state core for the batch review workbench (US-284, #160/#161).
 *
 * The module owns the batch review session: the journey reducer below plus the
 * client-lifecycle facts that are decided by that lifecycle (parse error,
 * batch id, per-item draft generation state). It never performs IO.
 *
 * Callers use two surfaces only:
 *
 *   - `snapshot`: a read-only view of everything the surfaces render from;
 *   - named commands (`beginParse` / `finishParse` / `fail` / `reset*` /
 *     `set*`): each returns `{ accepted, effects }`. Effects are **data** —
 *     `navigate` / `notify` — and the caller maps them to routing, toast copy,
 *     focus or a confirmation dialog. Copy and IO stay out of this module.
 *
 * The reducer symbols (`reduceBatchReview`, `createBatchReviewState`,
 * `canTransitionBatchItem`, …) remain exported as the module's implementation
 * detail, pinned by `useBatchReviewJourney.test.ts`.
 *
 * Item identity, review order, selection and the current detail item are
 * deliberately separate pieces of state. Capabilities and idempotency keys
 * remain in this route-local object and are never serialised by this module.
 */
import { computed, ref, shallowRef, type ComputedRef } from 'vue'
import type { operations } from '@/api/generated/api'
import { isPublicRouteIdentifier } from '@/app/router/catalog'

type JsonBody<Operation extends keyof operations> = NonNullable<
  operations[Operation]['requestBody']
>['content']['application/json']

type JsonResult<Operation extends keyof operations> = operations[Operation]['responses'][200] extends {
  content: { 'application/json': { result: infer Result } }
}
  ? NonNullable<Result>
  : never

export type ParseBatchTitlesBody = JsonBody<'parseBatchTitles'>
export type ParseBatchTitlesResult = JsonResult<'parseBatchTitles'>
export type BatchParseItem = NonNullable<ParseBatchTitlesResult['items']>[number]
type IdentifiedBatchParseItem = BatchParseItem & { item_id: string }
export type CreateRequestBody = JsonBody<'createRequest'>
export type PreviewModifyRequestBody = JsonBody<'previewModifyRequest'>
export type PreviewModifyResult = JsonResult<'previewModifyRequest'>
export type SaveConfirmBatchItemsBody = JsonBody<'saveConfirmBatchItems'>
export type SaveConfirmBatchItemsResult = JsonResult<'saveConfirmBatchItems'>
export type BatchSaveResultItem = SaveConfirmBatchItemsResult['results'][number]
export type AcceptRequestBody = JsonBody<'acceptRequest'>
export type AcceptRequestResult = JsonResult<'acceptRequest'>
export type TrackingItemsResult = JsonResult<'listTrackingItems'>

export type BatchItemPhase =
  | 'parsing'
  | 'blocked'
  | 'candidates'
  | 'draft'
  | 'applying'
  | 'apply_failed'
  | 'saving'
  | 'confirmed'
  | 'saved_pending_confirm'
  | 'response_unknown'

export type BatchBusyPhase = 'parsing' | 'saving' | null

export interface SafeBatchError {
  readonly type: string
  readonly message: string
  readonly field?: 'base_revision' | 'draft_id' | 'idempotency_key' | 'request_id'
  readonly currentRevision?: number
  readonly requestId?: string
  readonly retryAction?: 'ACCEPT_SAVED_REQUEST'
}

export interface BatchReviewItem {
  readonly itemId: string
  readonly inputIndex: number
  readonly reviewIndex: number
  readonly rawTitle: string
  readonly source: IdentifiedBatchParseItem | null
  readonly phase: BatchItemPhase
  readonly selected: boolean
  readonly draftId: string | null
  readonly draftRevision: number | null
  readonly dirty: boolean
  readonly idempotencyKey: string | null
  readonly requestId: string | null
  readonly trackingId: string | null
  readonly result: BatchSaveResultItem | null
  readonly error: SafeBatchError | null
}

export interface BatchReviewState {
  readonly phase: 'input' | 'parsing' | 'review'
  readonly rawInput: string
  readonly inputOrder: readonly string[]
  readonly reviewOrder: readonly string[]
  readonly currentItemId: string | null
  readonly items: Readonly<Record<string, BatchReviewItem>>
  readonly busy: BatchBusyPhase
}

export type BatchReviewAction =
  | { type: 'set_input'; rawInput: string }
  | { type: 'parse_started' }
  | { type: 'parse_succeeded'; result: ParseBatchTitlesResult }
  | { type: 'parse_failed'; error: unknown }
  | { type: 'set_current'; itemId: string }
  | { type: 'set_selected'; itemId: string; selected: boolean }
  | { type: 'set_draft'; itemId: string; draftId: string; revision: number }
  | { type: 'set_dirty'; itemId: string; dirty: boolean }
  | { type: 'begin_apply'; itemId: string }
  | { type: 'apply_succeeded'; itemId: string; draftId?: string; revision?: number }
  | { type: 'apply_failed'; itemId: string; error: unknown }
  | { type: 'retry_apply'; itemId: string }
  | { type: 'reset_apply'; itemId: string }
  | { type: 'invalidate_draft'; itemId: string }
  | { type: 'begin_save'; itemIds: readonly string[] }
  | { type: 'save_succeeded'; itemId: string; result: BatchSaveResultItem }
  | { type: 'save_failed'; itemId: string; error: unknown }
  | { type: 'save_response_unknown'; itemIds: readonly string[]; error?: unknown }
  | { type: 'retry_saved_confirm'; itemId: string }
  | { type: 'accept_succeeded'; itemId: string; requestId: string }
  | { type: 'tracking_located'; itemId: string; requestId: string; trackingId: string }
  | { type: 'tracking_not_found'; itemId: string }
  | { type: 'tracking_verification_failed'; itemId: string }
  | { type: 'consume_confirmed'; itemId: string }
  | { type: 'remove_item'; itemId: string }
  | { type: 'clear_route' }

const SAFE_ERROR_TYPES = new Set([
  'draft_expired', 'draft_evicted', 'draft_replayed', 'draft_revision_conflict',
  'draft_reserved', 'save_confirm_failed', 'idempotency_conflict', 'network_error',
])

const SAFE_MESSAGES: Record<string, string> = {
  draft_expired: '订阅草案已失效，请重新生成。',
  draft_evicted: '订阅草案已失效，请重新生成。',
  draft_replayed: '订阅草案已处理，请刷新状态。',
  draft_revision_conflict: '草案已更新，请基于最新版本重试。',
  draft_reserved: '订阅草案正在处理中，请稍后重试。',
  save_confirm_failed: '已保存订阅方案，但确认未完成，可直接重试确认。',
  idempotency_conflict: '本次操作与已有操作冲突，请重新开始。',
  network_error: '网络暂不可用，请重试。',
}

const BATCH_PHASE_TRANSITIONS: Record<BatchItemPhase, readonly BatchItemPhase[]> = {
  parsing: ['blocked', 'candidates', 'draft'],
  blocked: ['candidates'],
  candidates: ['draft', 'blocked'],
  draft: ['applying', 'saving', 'blocked'],
  applying: ['draft', 'apply_failed', 'candidates', 'blocked'],
  apply_failed: ['applying', 'draft', 'candidates', 'blocked'],
  saving: ['confirmed', 'saved_pending_confirm', 'draft', 'candidates', 'blocked', 'response_unknown'],
  confirmed: [],
  saved_pending_confirm: ['confirmed', 'response_unknown'],
  response_unknown: ['confirmed', 'saved_pending_confirm', 'draft', 'candidates', 'blocked', 'response_unknown'],
}

export function canTransitionBatchItem(from: BatchItemPhase, to: BatchItemPhase): boolean {
  return BATCH_PHASE_TRANSITIONS[from]?.includes(to) ?? false
}

/** Map only stable error types and explicitly public recovery fields. */
export function toSafeBatchError(error: unknown): SafeBatchError {
  const source = error && typeof error === 'object' ? error as Record<string, unknown> : {}
  const candidate = typeof source.type === 'string' && SAFE_ERROR_TYPES.has(source.type) ? source.type : 'batch_error'
  const details = source.details && typeof source.details === 'object' ? source.details as Record<string, unknown> : {}
  const field = ['base_revision', 'draft_id', 'idempotency_key', 'request_id'].includes(String(details.field))
    ? details.field as SafeBatchError['field'] : undefined
  const currentRevision = candidate === 'draft_revision_conflict' && Number.isInteger(details.current_revision)
    ? details.current_revision as number : undefined
  let type = candidate
  let requestId: string | undefined
  let retryAction: SafeBatchError['retryAction']
  if (candidate === 'save_confirm_failed') {
    const nested = details.details && typeof details.details === 'object' ? details.details as Record<string, unknown> : {}
    requestId = isPublicRouteIdentifier(nested.request_id) ? nested.request_id : undefined
    retryAction = nested.outcome === 'SAVED_CONFIRM_FAILED' && nested.retry_action === 'ACCEPT_SAVED_REQUEST'
      ? nested.retry_action : undefined
    if (!requestId || !retryAction) type = 'batch_error'
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

/** Convert a generated 200 result item to the same safe error shape. */
export function toSafeBatchResultError(result: BatchSaveResultItem): SafeBatchError {
  const source = result as unknown as Record<string, unknown>
  const errorType = typeof source.error_type === 'string' ? source.error_type : ''
  const outcome = typeof source.outcome === 'string' ? source.outcome.toUpperCase() : ''
  const requestId = typeof source.request_id === 'string' && isPublicRouteIdentifier(source.request_id)
    ? source.request_id : undefined
  if (errorType === 'save_confirm_failed' && outcome === 'FAILED' && requestId) {
    return { type: errorType, message: SAFE_MESSAGES[errorType]!, requestId }
  }
  const safeType = SAFE_ERROR_TYPES.has(errorType) ? errorType : 'batch_error'
  return { type: safeType, message: SAFE_MESSAGES[safeType] ?? '操作失败，请重新尝试。' }
}

function randomKey(): string {
  if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') return crypto.randomUUID()
  return `batch-${Date.now()}-${Math.random().toString(36).slice(2)}`
}

export function createBatchReviewState(rawInput = ''): BatchReviewState {
  return { phase: 'input', rawInput, inputOrder: [], reviewOrder: [], currentItemId: null, items: {}, busy: null }
}

function updateItem(state: BatchReviewState, itemId: string, update: Partial<BatchReviewItem>): BatchReviewState {
  const item = state.items[itemId]
  if (item && update.phase && update.phase !== item.phase && !canTransitionBatchItem(item.phase, update.phase)) return state
  return item ? { ...state, items: { ...state.items, [itemId]: { ...item, ...update } } } : state
}

export function batchItemCanConfirm(item: BatchReviewItem | undefined): boolean {
  return Boolean(item && item.phase === 'draft' && item.draftId && item.draftRevision !== null && !item.dirty)
}

export function reduceBatchReview(state: BatchReviewState, action: BatchReviewAction): BatchReviewState {
  switch (action.type) {
    case 'set_input': return state.busy ? state : { ...state, phase: 'input', rawInput: action.rawInput }
    case 'parse_started': return state.phase === 'input' && !state.busy ? { ...state, phase: 'parsing', busy: 'parsing' } : state
    case 'parse_succeeded': {
      const sourceItems = action.result.items.filter((item): item is IdentifiedBatchParseItem => typeof item.item_id === 'string')
      const inputOrder = sourceItems.map((item) => item.item_id)
      const reviewOrder = [...inputOrder].sort((a, b) => {
        const left = sourceItems.find((item) => item.item_id === a)
        const right = sourceItems.find((item) => item.item_id === b)
        const rank = (item: IdentifiedBatchParseItem | undefined) => item?.status === 'FAILED' || item?.status === 'EMPTY' ? 0 : item?.needs_user_review ? 1 : 2
        return rank(left) - rank(right) || inputOrder.indexOf(a) - inputOrder.indexOf(b)
      })
      const items = Object.fromEntries(sourceItems.map((item, inputIndex) => {
        const blocked = item.status === 'FAILED' || item.status === 'EMPTY'
        const phase: BatchItemPhase = blocked ? 'blocked' : item.preview_request ? 'draft' : item.candidates?.length ? 'candidates' : 'blocked'
        return [item.item_id, { itemId: item.item_id, inputIndex, reviewIndex: reviewOrder.indexOf(item.item_id), rawTitle: item.raw_title ?? '', source: item, phase, selected: false, draftId: item.draft_id, draftRevision: item.draft_revision, dirty: false, idempotencyKey: null, requestId: null, trackingId: null, result: null, error: null }]
      })) as Readonly<Record<string, BatchReviewItem>>
      return { ...state, phase: 'review', busy: null, inputOrder, reviewOrder, currentItemId: reviewOrder[0] ?? null, items }
    }
    case 'parse_failed': return { ...state, phase: 'input', busy: null }
    case 'set_current': return state.items[action.itemId] ? { ...state, currentItemId: action.itemId } : state
    case 'set_selected': {
      const item = state.items[action.itemId]
      return !item || item.phase === 'blocked' || item.phase === 'confirmed' || item.phase === 'saved_pending_confirm' ? state : updateItem(state, action.itemId, { selected: action.selected })
    }
    case 'set_draft': return updateItem(state, action.itemId, { phase: 'draft', draftId: action.draftId, draftRevision: action.revision, dirty: false, error: null, idempotencyKey: null })
    case 'set_dirty': return updateItem(state, action.itemId, { dirty: action.dirty, ...(action.dirty ? { idempotencyKey: null } : {}) })
    case 'begin_apply': return state.items[action.itemId]?.phase === 'draft' ? updateItem(state, action.itemId, { phase: 'applying', error: null }) : state
    case 'apply_succeeded': return updateItem(state, action.itemId, { phase: 'draft', dirty: false, error: null, idempotencyKey: null, ...(action.draftId ? { draftId: action.draftId } : {}), ...(action.revision === undefined ? {} : { draftRevision: action.revision }) })
    case 'apply_failed': return updateItem(state, action.itemId, { phase: 'apply_failed', error: toSafeBatchError(action.error) })
    case 'retry_apply': return state.items[action.itemId]?.phase === 'apply_failed' ? updateItem(state, action.itemId, { phase: 'applying', error: null }) : state
    case 'reset_apply': return state.items[action.itemId]?.phase === 'apply_failed' ? updateItem(state, action.itemId, { phase: 'draft', error: null, dirty: false }) : state
    case 'invalidate_draft': {
      const item = state.items[action.itemId]
      if (!item) return state
      const phase: BatchItemPhase = item.source?.candidates?.length ? 'candidates' : 'blocked'
      return updateItem(state, action.itemId, { phase, selected: false, draftId: null, draftRevision: null, dirty: false, idempotencyKey: null, error: null })
    }
    case 'begin_save': {
      if (state.busy || new Set(action.itemIds).size !== action.itemIds.length || action.itemIds.some((id) => !batchItemCanConfirm(state.items[id]))) return state
      const items = { ...state.items }
      for (const itemId of action.itemIds) {
        const item = items[itemId]
        if (item) items[itemId] = { ...item, phase: 'saving', idempotencyKey: randomKey(), error: null }
      }
      return { ...state, busy: 'saving', items }
    }
    case 'save_succeeded': {
      const next = updateItem(state, action.itemId, { phase: 'confirmed', selected: false, draftId: null, draftRevision: null, dirty: false, idempotencyKey: null, requestId: action.result.request_id, trackingId: action.result.tracking_id, result: action.result, error: null })
      return { ...next, busy: Object.values(next.items).some((item) => item.phase === 'saving') ? 'saving' : null }
    }
    case 'save_failed': {
      const source = action.error && typeof action.error === 'object' ? action.error as Record<string, unknown> : {}
      const error = typeof source.error_type === 'string'
        ? toSafeBatchResultError(action.error as BatchSaveResultItem)
        : toSafeBatchError(action.error)
      const saved = error.type === 'save_confirm_failed' && Boolean(error.requestId)
      const expired = ['draft_expired', 'draft_evicted', 'draft_replayed', 'draft_revision_conflict'].includes(error.type)
      const item = state.items[action.itemId]
      const next = updateItem(state, action.itemId, {
        phase: saved ? 'saved_pending_confirm' : expired ? (item?.source?.candidates?.length ? 'candidates' : 'blocked') : 'draft',
        ...(saved || expired ? { selected: false, draftId: null, draftRevision: null, dirty: false, idempotencyKey: null } : { idempotencyKey: null }),
        ...(saved ? { requestId: error.requestId } : {}),
        error,
      })
      return { ...next, busy: Object.values(next.items).some((item) => item.phase === 'saving') ? 'saving' : null }
    }
    case 'save_response_unknown': {
      const items = { ...state.items }
      for (const itemId of action.itemIds) if (items[itemId]) items[itemId] = { ...items[itemId], phase: 'response_unknown', error: action.error ? toSafeBatchError(action.error) : null }
      return { ...state, items, busy: null }
    }
    case 'retry_saved_confirm': return state.items[action.itemId]?.phase === 'saved_pending_confirm' ? updateItem(state, action.itemId, { error: null }) : state
    case 'accept_succeeded': return updateItem(state, action.itemId, { phase: 'confirmed', selected: false, requestId: action.requestId, error: null })
    case 'tracking_located': return updateItem(state, action.itemId, { phase: 'confirmed', selected: false, requestId: action.requestId, trackingId: action.trackingId, error: null })
    case 'tracking_not_found': return state.items[action.itemId]?.phase === 'response_unknown' ? updateItem(state, action.itemId, { phase: 'saved_pending_confirm', selected: false }) : state
    case 'tracking_verification_failed': return state.items[action.itemId]?.phase === 'saved_pending_confirm'
      ? updateItem(state, action.itemId, { phase: 'response_unknown', selected: false })
      : state
    case 'consume_confirmed': return state.items[action.itemId]?.phase === 'confirmed' ? updateItem(state, action.itemId, { draftId: null, idempotencyKey: null }) : state
    case 'remove_item': {
      if (!state.items[action.itemId]) return state
      const items = { ...state.items }
      delete items[action.itemId]
      const inputOrder = state.inputOrder.filter((itemId) => itemId !== action.itemId)
      const reviewOrder = state.reviewOrder.filter((itemId) => itemId !== action.itemId)
      return {
        ...state,
        inputOrder,
        reviewOrder,
        currentItemId: state.currentItemId === action.itemId ? reviewOrder[0] ?? null : state.currentItemId,
        items,
      }
    }
    case 'clear_route': return createBatchReviewState()
  }
}

/**
 * A pending side effect a command hands to its caller. Effects carry data
 * only: the module never routes, notifies, focuses or prompts by itself.
 */
export type BatchReviewEffect =
  | { readonly kind: 'navigate'; readonly batchId: string }
  | { readonly kind: 'notify'; readonly event: BatchReviewNotifyEvent }

/**
 * What happened, as data. `#160`: the Chinese copy for each event stays in the
 * view, so the module can never become a second copy source.
 */
export type BatchReviewNotifyEvent =
  | { readonly type: 'parse_input_rejected'; readonly message: string }
  | { readonly type: 'parse_succeeded'; readonly itemCount: number }
  | { readonly type: 'parse_empty' }
  | { readonly type: 'parse_failed'; readonly message: string }

export interface BatchReviewCommandResult {
  /** false = the current state rejected this transition; the caller keeps its scene. */
  readonly accepted: boolean
  readonly effects: readonly BatchReviewEffect[]
}

/** Read-only view of the client lifecycle plus the item state it decides. */
export interface BatchReviewSnapshot {
  readonly state: BatchReviewState
  readonly parseError: string
  readonly batchId: string
  readonly draftCreateItemIds: ReadonlySet<string>
  readonly draftCreateCandidateIds: Readonly<Record<string, string>>
  readonly draftCreateErrors: Readonly<Record<string, Record<string, string>>>
}

export interface BatchReviewJourney {
  readonly snapshot: ComputedRef<BatchReviewSnapshot>
  beginParse: () => BatchReviewCommandResult
  rejectParseInput: (message: string) => BatchReviewCommandResult
  finishParse: (result: ParseBatchTitlesResult) => BatchReviewCommandResult
  failParse: (message: string) => BatchReviewCommandResult
  restoreBatchId: (batchId: string) => void
  beginDraftCreate: (itemId: string, candidateId: string) => BatchReviewCommandResult
  failDraftCreate: (itemId: string, candidateId: string, message: string) => BatchReviewCommandResult
  finishDraftCreate: (itemId: string) => BatchReviewCommandResult
  clearDraftCreateErrors: (itemId: string) => void
  selectItem: (itemId: string) => BatchReviewCommandResult
  setSelected: (itemId: string, selected: boolean) => BatchReviewCommandResult
  setDraft: (itemId: string, draftId: string, revision: number) => BatchReviewCommandResult
  setDraftDirty: (itemId: string, dirty: boolean) => BatchReviewCommandResult
  beginApply: (itemId: string) => BatchReviewCommandResult
  finishApply: (itemId: string, changes?: { draftId?: string; revision?: number }) => BatchReviewCommandResult
  failApply: (itemId: string, error: unknown) => BatchReviewCommandResult
  retryApply: (itemId: string) => BatchReviewCommandResult
  resetApply: (itemId: string) => BatchReviewCommandResult
  invalidateDraft: (itemId: string) => BatchReviewCommandResult
  beginSave: (itemIds: readonly string[]) => BatchReviewCommandResult
  finishSaveItem: (itemId: string, result: BatchSaveResultItem) => BatchReviewCommandResult
  failSaveItem: (itemId: string, error: unknown) => BatchReviewCommandResult
  markSaveResponseUnknown: (itemIds: readonly string[], error?: unknown) => BatchReviewCommandResult
  retrySavedConfirm: (itemId: string) => BatchReviewCommandResult
  finishAccept: (itemId: string, requestId: string) => BatchReviewCommandResult
  locateTracking: (itemId: string, requestId: string, trackingId: string) => BatchReviewCommandResult
  markTrackingNotFound: (itemId: string) => BatchReviewCommandResult
  failTrackingVerification: (itemId: string) => BatchReviewCommandResult
  consumeConfirmed: (itemId: string) => BatchReviewCommandResult
  removeItem: (itemId: string) => BatchReviewCommandResult
  resetRoute: () => BatchReviewCommandResult
  newIdempotencyKey: (itemId: string) => string | null
}

export function useBatchReviewJourney(rawInput = ''): BatchReviewJourney {
  const stateRef = shallowRef(createBatchReviewState(rawInput))
  const parseErrorRef = ref('')
  const batchIdRef = ref('')
  const draftCreateItemIdsRef = ref<ReadonlySet<string>>(new Set<string>())
  const draftCreateCandidateIdsRef = ref<Readonly<Record<string, string>>>({})
  const draftCreateErrorsRef = ref<Readonly<Record<string, Record<string, string>>>>({})

  const snapshot = computed<BatchReviewSnapshot>(() => ({
    state: stateRef.value,
    parseError: parseErrorRef.value,
    batchId: batchIdRef.value,
    draftCreateItemIds: draftCreateItemIdsRef.value,
    draftCreateCandidateIds: draftCreateCandidateIdsRef.value,
    draftCreateErrors: draftCreateErrorsRef.value,
  }))

  function apply(action: BatchReviewAction): BatchReviewCommandResult {
    const previous = stateRef.value
    const next = reduceBatchReview(previous, action)
    if (next !== previous) stateRef.value = next
    return { accepted: next !== previous, effects: [] }
  }

  /**
   * The sanitized generation failure of one candidate. An empty map removes
   * the item entry entirely, exactly as the previous view-local map did.
   */
  function setCandidateError(itemId: string, candidateId: string, message: string | null): void {
    const itemErrors = { ...(draftCreateErrorsRef.value[itemId] ?? {}) }
    if (message) itemErrors[candidateId] = message
    else delete itemErrors[candidateId]
    if (Object.keys(itemErrors).length) {
      draftCreateErrorsRef.value = { ...draftCreateErrorsRef.value, [itemId]: itemErrors }
      return
    }
    const next = { ...draftCreateErrorsRef.value }
    delete next[itemId]
    draftCreateErrorsRef.value = next
  }

  function beginParse(): BatchReviewCommandResult {
    // A new attempt retires the previous failure message before loading starts.
    parseErrorRef.value = ''
    return apply({ type: 'parse_started' })
  }

  function rejectParseInput(message: string): BatchReviewCommandResult {
    parseErrorRef.value = message
    return { accepted: true, effects: [{ kind: 'notify', event: { type: 'parse_input_rejected', message } }] }
  }

  function finishParse(result: ParseBatchTitlesResult): BatchReviewCommandResult {
    parseErrorRef.value = ''
    const batchId = result.batch_id ?? ''
    batchIdRef.value = batchId
    const applied = apply({ type: 'parse_succeeded', result })
    const itemCount = result.items?.length ?? 0
    return {
      accepted: applied.accepted,
      effects: [
        { kind: 'navigate', batchId },
        {
          kind: 'notify',
          event: itemCount ? { type: 'parse_succeeded', itemCount } : { type: 'parse_empty' },
        },
      ],
    }
  }

  function failParse(message: string): BatchReviewCommandResult {
    // The reducer's `parse_failed` carries no error payload by design; the
    // user-facing message lives in this module's lifecycle state instead.
    parseErrorRef.value = message
    batchIdRef.value = ''
    apply({ type: 'parse_failed', error: message })
    return { accepted: true, effects: [{ kind: 'notify', event: { type: 'parse_failed', message } }] }
  }

  function restoreBatchId(batchId: string): void {
    batchIdRef.value = batchId
  }

  function beginDraftCreate(itemId: string, candidateId: string): BatchReviewCommandResult {
    draftCreateItemIdsRef.value = new Set(draftCreateItemIdsRef.value).add(itemId)
    draftCreateCandidateIdsRef.value = { ...draftCreateCandidateIdsRef.value, [itemId]: candidateId }
    setCandidateError(itemId, candidateId, null)
    return { accepted: true, effects: [] }
  }

  function failDraftCreate(itemId: string, candidateId: string, message: string): BatchReviewCommandResult {
    setCandidateError(itemId, candidateId, message)
    return { accepted: true, effects: [] }
  }

  function finishDraftCreate(itemId: string): BatchReviewCommandResult {
    const next = new Set(draftCreateItemIdsRef.value)
    next.delete(itemId)
    draftCreateItemIdsRef.value = next
    const nextCandidates = { ...draftCreateCandidateIdsRef.value }
    delete nextCandidates[itemId]
    draftCreateCandidateIdsRef.value = nextCandidates
    return { accepted: true, effects: [] }
  }

  function clearDraftCreateErrors(itemId: string): void {
    if (!draftCreateErrorsRef.value[itemId]) return
    const next = { ...draftCreateErrorsRef.value }
    delete next[itemId]
    draftCreateErrorsRef.value = next
  }

  function resetRoute(): BatchReviewCommandResult {
    draftCreateItemIdsRef.value = new Set<string>()
    draftCreateCandidateIdsRef.value = {}
    draftCreateErrorsRef.value = {}
    return apply({ type: 'clear_route' })
  }

  return {
    snapshot,
    beginParse,
    rejectParseInput,
    finishParse,
    failParse,
    restoreBatchId,
    beginDraftCreate,
    failDraftCreate,
    finishDraftCreate,
    clearDraftCreateErrors,
    selectItem: (itemId) => apply({ type: 'set_current', itemId }),
    setSelected: (itemId, selected) => apply({ type: 'set_selected', itemId, selected }),
    setDraft: (itemId, draftId, revision) => apply({ type: 'set_draft', itemId, draftId, revision }),
    setDraftDirty: (itemId, dirty) => apply({ type: 'set_dirty', itemId, dirty }),
    beginApply: (itemId) => apply({ type: 'begin_apply', itemId }),
    finishApply: (itemId, changes = {}) => apply({
      type: 'apply_succeeded',
      itemId,
      ...(changes.draftId === undefined ? {} : { draftId: changes.draftId }),
      ...(changes.revision === undefined ? {} : { revision: changes.revision }),
    }),
    failApply: (itemId, error) => apply({ type: 'apply_failed', itemId, error }),
    retryApply: (itemId) => apply({ type: 'retry_apply', itemId }),
    resetApply: (itemId) => apply({ type: 'reset_apply', itemId }),
    invalidateDraft: (itemId) => apply({ type: 'invalidate_draft', itemId }),
    beginSave: (itemIds) => apply({ type: 'begin_save', itemIds }),
    finishSaveItem: (itemId, result) => apply({ type: 'save_succeeded', itemId, result }),
    failSaveItem: (itemId, error) => apply({ type: 'save_failed', itemId, error }),
    markSaveResponseUnknown: (itemIds, error) => apply({
      type: 'save_response_unknown',
      itemIds,
      ...(error === undefined ? {} : { error }),
    }),
    retrySavedConfirm: (itemId) => apply({ type: 'retry_saved_confirm', itemId }),
    finishAccept: (itemId, requestId) => apply({ type: 'accept_succeeded', itemId, requestId }),
    locateTracking: (itemId, requestId, trackingId) => apply({ type: 'tracking_located', itemId, requestId, trackingId }),
    markTrackingNotFound: (itemId) => apply({ type: 'tracking_not_found', itemId }),
    failTrackingVerification: (itemId) => apply({ type: 'tracking_verification_failed', itemId }),
    consumeConfirmed: (itemId) => apply({ type: 'consume_confirmed', itemId }),
    removeItem: (itemId) => apply({ type: 'remove_item', itemId }),
    resetRoute,
    newIdempotencyKey(itemId) {
      const item = stateRef.value.items[itemId]
      if (!batchItemCanConfirm(item)) return null
      if (!item) return null
      if (item.idempotencyKey) return item.idempotencyKey
      const key = randomKey()
      stateRef.value = updateItem(stateRef.value, itemId, { idempotencyKey: key })
      return key
    },
  }
}
