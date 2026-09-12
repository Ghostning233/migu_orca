/**
 * API-free state core for the batch review workbench (US-284).
 *
 * Item identity, review order, selection and the current detail item are
 * deliberately separate pieces of state. Capabilities and idempotency keys
 * remain in this route-local object and are never serialised by this module.
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
  | { type: 'begin_save'; itemIds: readonly string[] }
  | { type: 'save_succeeded'; itemId: string; result: BatchSaveResultItem }
  | { type: 'save_failed'; itemId: string; error: unknown }
  | { type: 'save_response_unknown'; itemIds: readonly string[]; error?: unknown }
  | { type: 'retry_saved_confirm'; itemId: string }
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
  applying: ['draft', 'apply_failed', 'blocked'],
  apply_failed: ['applying', 'draft'],
  saving: ['confirmed', 'saved_pending_confirm', 'draft', 'response_unknown'],
  confirmed: [],
  saved_pending_confirm: [],
  response_unknown: ['confirmed', 'saved_pending_confirm', 'draft', 'response_unknown'],
}

export function canTransitionBatchItem(from: BatchItemPhase, to: BatchItemPhase): boolean {
  return BATCH_PHASE_TRANSITIONS[from]?.includes(to) ?? false
}

function safeString(value: unknown): string | undefined {
  return typeof value === 'string' && value.length > 0 && value.length <= 128 ? value : undefined
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
    requestId = safeString(nested.request_id)
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
  return Boolean(item && item.phase === 'draft' && item.draftId && item.draftRevision !== null && !item.dirty && !item.error)
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
    case 'apply_succeeded': return updateItem(state, action.itemId, { phase: 'draft', dirty: false, error: null, ...(action.draftId ? { draftId: action.draftId } : {}), ...(action.revision === undefined ? {} : { draftRevision: action.revision }) })
    case 'apply_failed': return updateItem(state, action.itemId, { phase: 'apply_failed', error: toSafeBatchError(action.error) })
    case 'retry_apply': return state.items[action.itemId]?.phase === 'apply_failed' ? updateItem(state, action.itemId, { phase: 'applying', error: null }) : state
    case 'begin_save': {
      if (state.busy || action.itemIds.some((id) => !batchItemCanConfirm(state.items[id]))) return state
      const items = { ...state.items }
      for (const itemId of action.itemIds) {
        const item = items[itemId]
        if (item) items[itemId] = { ...item, phase: 'saving', idempotencyKey: item.idempotencyKey ?? randomKey(), error: null }
      }
      return { ...state, busy: 'saving', items }
    }
    case 'save_succeeded': {
      const next = updateItem(state, action.itemId, { phase: 'confirmed', selected: false, draftId: null, draftRevision: null, dirty: false, idempotencyKey: null, requestId: action.result.request_id, trackingId: action.result.tracking_id, result: action.result, error: null })
      return { ...next, busy: Object.values(next.items).some((item) => item.phase === 'saving') ? 'saving' : null }
    }
    case 'save_failed': {
      const error = toSafeBatchError(action.error)
      const saved = error.type === 'save_confirm_failed' && Boolean(error.requestId && error.retryAction)
      const next = updateItem(state, action.itemId, { phase: saved ? 'saved_pending_confirm' : 'draft', ...(saved ? { selected: false, draftId: null, draftRevision: null, dirty: false, idempotencyKey: null, requestId: error.requestId } : {}), error })
      return { ...next, busy: Object.values(next.items).some((item) => item.phase === 'saving') ? 'saving' : null }
    }
    case 'save_response_unknown': {
      const items = { ...state.items }
      for (const itemId of action.itemIds) if (items[itemId]) items[itemId] = { ...items[itemId], phase: 'response_unknown', error: action.error ? toSafeBatchError(action.error) : null }
      return { ...state, items, busy: null }
    }
    case 'retry_saved_confirm': return state.items[action.itemId]?.phase === 'saved_pending_confirm' ? updateItem(state, action.itemId, { error: null }) : state
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

export interface BatchReviewJourney { state: BatchReviewState; dispatch: (action: BatchReviewAction) => void; newIdempotencyKey: (itemId: string) => string | null }

export function useBatchReviewJourney(rawInput = ''): BatchReviewJourney {
  const stateRef = shallowRef(createBatchReviewState(rawInput))
  return {
    get state() { return stateRef.value },
    dispatch(action) { stateRef.value = reduceBatchReview(stateRef.value, action) },
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
