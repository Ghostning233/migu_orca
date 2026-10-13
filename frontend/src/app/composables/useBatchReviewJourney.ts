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
import { computed, ref, shallowReactive, shallowRef, type ComputedRef, type Ref } from 'vue'
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
  /**
   * #195：草案已被服务端保存、只能等待定位（``draft_replayed``）。
   *
   * 它不是「候选／草案已失效」：不要重新选合集、不要重新生成草案、不要换幂等键
   * 重发。此前这个结局被并进 ``candidates``/``blocked``，与展示状态
   * 「已保存，待定位」互相矛盾。
   */
  | 'saved_pending_locate'
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
  saving: ['confirmed', 'saved_pending_confirm', 'saved_pending_locate', 'draft', 'candidates', 'blocked', 'response_unknown'],
  confirmed: [],
  saved_pending_confirm: ['confirmed', 'response_unknown'],
  saved_pending_locate: ['confirmed', 'response_unknown'],
  response_unknown: ['confirmed', 'saved_pending_confirm', 'saved_pending_locate', 'draft', 'candidates', 'blocked', 'response_unknown'],
}

/**
 * #195：一次保存失败是否表示「草案已经被服务端保存」（而不是失效）。
 *
 * 这是 ``draft_replayed`` 的**唯一判定点**：批量相位（本模块）与展示投影
 * （``features/workbench/batchItemProjection``）都消费它，不再各自内联错误类型
 * 数组。语义与 #130 一致：已保存是确定事实，待核验的只是确认与定位状态。
 */
export function batchSaveErrorIsReplayed(errorType: string | null | undefined): boolean {
  return String(errorType ?? '') === 'draft_replayed'
}

/** 草案彻底失效、必须回到真实合集重新生成的失败类型。 */
const DRAFT_INVALID_ERROR_TYPES = [
  'draft_expired',
  'draft_evicted',
  'draft_revision_conflict',
] as const

/** True when the failure type means the draft can never be replayed as-is. */
export function batchSaveErrorInvalidatesDraft(errorType: string | null | undefined): boolean {
  return (DRAFT_INVALID_ERROR_TYPES as readonly string[]).includes(String(errorType ?? ''))
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

/**
 * 弱闸：只回答「这一条现在能不能进入保存确认」的最小子集——相位为 `draft`、
 * 有草案身份、没有未应用编辑。
 *
 * 视图的强闸（`itemConfirmability`）在这之上继续加判据（可展开草案、会话有效、
 * 无重算/编辑在途、无修改失败、保存不在途、字幕组与有效资源）。因此**强闸为真
 * 必然蕴含弱闸为真**：弱闸的判据是强闸判据的子集。这条关系钉在
 * `BatchWorkbenchView.test.ts` 的「弱闸 ⊂ 强闸」用例上——强闸放行的勾选集合
 * 发出的保存请求不会被 `begin_save` 拒绝。
 */
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
      // 终态条目不得再取得勾选意图：blocked 不可确认、confirmed 已提交、
      // saved_pending_confirm / saved_pending_locate 都在等待外部结果的收敛。
      return !item || ['blocked', 'confirmed', 'saved_pending_confirm', 'saved_pending_locate'].includes(item.phase) ? state : updateItem(state, action.itemId, { selected: action.selected })
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
      // #195：错误类型只在这里判定一次（与展示投影共用同一对谓词）。
      const replayed = batchSaveErrorIsReplayed(error.type)
      const invalidated = batchSaveErrorInvalidatesDraft(error.type)
      const released = saved || replayed || invalidated
      const item = state.items[action.itemId]
      // 已保存 → 待确认；草案已被保存（重放）→ 待定位；草案失效 → 回到真实合集；
      // 其余可重试失败 → 留在草案步。draft_replayed 不再伪装成 candidates/blocked。
      const phase: BatchItemPhase = saved
        ? 'saved_pending_confirm'
        : replayed
          ? 'saved_pending_locate'
          : invalidated
            ? (item?.source?.candidates?.length ? 'candidates' : 'blocked')
            : 'draft'
      const next = updateItem(state, action.itemId, {
        phase,
        ...(released ? { selected: false, draftId: null, draftRevision: null, dirty: false, idempotencyKey: null } : { idempotencyKey: null }),
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
  | { readonly kind: 'focus'; readonly target: BatchReviewFocusTarget }
  /** 无障碍播报：只更新 aria-live 文本，不移动焦点、不弹通知。 */
  | { readonly kind: 'announce'; readonly event: BatchReviewAnnounceEvent }
  | { readonly kind: 'needsConfirmation'; readonly request: BatchReviewConfirmationRequest }

/** 定位播报的事件；标题文案由视图补。 */
export type BatchReviewAnnounceEvent =
  | { readonly type: 'focus_first_failed'; readonly itemId: string }
  | { readonly type: 'focus_first_pending'; readonly itemId: string }

/** Where the caller must move focus once a command settled. */
export type BatchReviewFocusTarget =
  | { readonly target: 'search_input' }
  | { readonly target: 'selected_recheck_notice' }
  | { readonly target: 'card'; readonly itemId: string; readonly reveal: boolean }
  /** 条目删除后的焦点接力：依次尝试候选条目，最后落到列表标题。 */
  | { readonly target: 'card_or_list'; readonly candidateItemIds: readonly string[] }

/**
 * A transition the module refuses to apply without an explicit user answer
 * (`#160`: 需要用户确认的转换拆成两步). The caller asks, then calls the same
 * command again with the answer; copy and dialog stay in the view.
 */
export type BatchReviewConfirmationRequest =
  | { readonly reason: 'discard_batch_scene' }
  | { readonly reason: 'confirm_selected_batch' }
  | { readonly reason: 'leave_batch_review' }

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
  /**
   * true = 模块真的应用了一次状态转换；false = 什么都没变（转换被当前状态拒绝，
   * 或这条命令只声明效应、真正的动作由调用方执行）。调用方据 false 保持现场。
   */
  readonly accepted: boolean
  readonly effects: readonly BatchReviewEffect[]
}

/**
 * The session facts the module reads. Implementations and their IO belong to the
 * injected factory (`useDraftSession`), never to this module.
 */
export interface BatchReviewDraftSessionFacts {
  readonly draftId: Ref<string | null>
  readonly draftRevision: Ref<number | null>
  readonly dirty: Ref<boolean>
  readonly applying: Ref<boolean>
  readonly invalid: Ref<boolean>
  readonly error: Ref<unknown>
  readonly canRetry: Readonly<Ref<boolean>>
  invalidate: () => void
}

/** The scheduler facts the module reads; timers and requests stay in the implementation. */
export interface BatchReviewDraftSchedulerFacts {
  readonly waiting: Ref<boolean>
  readonly folderPending: ComputedRef<boolean>
  readonly groupPending: ComputedRef<boolean>
  dispose: () => void
  cancelTimer: () => void
  dropPending: () => void
}

/**
 * What the module needs to (re)create one item's handles. `source` is an
 * opaque caller payload (for example the public Request snapshot); the module
 * passes it through and never inspects it.
 */
export interface BatchReviewDraftFacts {
  readonly itemId: string
  readonly draftId: string
  readonly draftRevision: number
  readonly source: unknown
}

export interface BatchReviewDraftPorts<TSession, TScheduler> {
  createSession: (facts: BatchReviewDraftFacts) => TSession
  createScheduler: (facts: BatchReviewDraftFacts, session: TSession) => TScheduler
}

/**
 * The client facts the save-confirmation gate needs (#162). They are relaxed
 * from the handles on purpose: surfaces read facts, the module owns handles.
 */
export interface BatchReviewDraftViewFacts {
  readonly draftId: string | null
  readonly draftRevision: number | null
  readonly invalid: boolean
  readonly dirty: boolean
  readonly applying: boolean
  readonly hasError: boolean
  readonly canRetry: boolean
  readonly waiting: boolean
  readonly folderPending: boolean
  readonly groupPending: boolean
}

/**
 * One save-confirm operation. The frozen body is the only authority for a
 * retry after an undecidable outcome; `outcomeUnknown` is the single source of
 * the "结果待确认" state. `inFlight` covers the first attempt and the frozen
 * retry alike, so the leave guard keeps its criterion (#163).
 */
export interface BatchReviewSaveOperation {
  readonly itemIds: readonly string[]
  readonly body: SaveConfirmBatchItemsBody
  readonly outcomeUnknown: boolean
  readonly inFlight: boolean
}

/**
 * Read-only view of the client lifecycle plus the item state it decides.
 *
 * 快照只回吐表面需要的事实，reducer 的原始 state 不外泄：条目、当前条目、
 * 勾选集合与两个相位都以窄接口给出。
 */
export interface BatchReviewSnapshot {
  /** 客户端相位（input / parsing / review）。 */
  readonly phase: BatchReviewState['phase']
  readonly busy: BatchBusyPhase
  readonly items: Readonly<Record<string, BatchReviewItem>>
  readonly currentItemId: string | null
  readonly selectedItemIds: ReadonlySet<string>
  readonly parseError: string
  readonly batchId: string
  readonly draftCreateItemIds: ReadonlySet<string>
  readonly draftCreateCandidateIds: Readonly<Record<string, string>>
  readonly draftCreateErrors: Readonly<Record<string, Record<string, string>>>
  /** Per-item draft facts, keyed by item id. */
  readonly drafts: Readonly<Record<string, BatchReviewDraftViewFacts>>
  readonly acceptFeedback: Readonly<Record<string, string>>
  readonly saveFailureTypes: Readonly<Record<string, string>>
  readonly recoveryLoadingItemIds: ReadonlySet<string>
  readonly saveOperation: BatchReviewSaveOperation | null
  /** Derived: a save-confirm request is in flight (first attempt or frozen retry). */
  readonly saveInFlight: boolean
  /** Derived: items the journal still holds in the `saving` phase. */
  readonly savingItemIds: ReadonlySet<string>
}

export interface BatchReviewJourney<
  TSession extends BatchReviewDraftSessionFacts = BatchReviewDraftSessionFacts,
  TScheduler extends BatchReviewDraftSchedulerFacts = BatchReviewDraftSchedulerFacts,
> {
  readonly snapshot: ComputedRef<BatchReviewSnapshot>
  beginParse: (options?: { sceneHasUnsafeWork?: boolean; discardScene?: boolean }) => BatchReviewCommandResult
  abandonParseStart: () => BatchReviewCommandResult
  requestRouteReset: () => BatchReviewCommandResult
  rejectParseInput: (message: string) => BatchReviewCommandResult
  finishParse: (result: ParseBatchTitlesResult) => BatchReviewCommandResult
  failParse: (message: string) => BatchReviewCommandResult
  restoreBatchId: (batchId: string) => void
  beginDraftCreate: (itemId: string, candidateId: string) => BatchReviewCommandResult
  failDraftCreate: (itemId: string, candidateId: string, message: string) => BatchReviewCommandResult
  finishDraftCreate: (itemId: string) => BatchReviewCommandResult
  clearDraftCreateErrors: (itemId: string) => void
  ensureDraftSession: (facts: BatchReviewDraftFacts) => TSession | null
  ensureScheduler: (facts: BatchReviewDraftFacts) => TScheduler | null
  /** Drop the leaving item's unapplied edit intent without touching its session. */
  releaseItemEditing: (itemId: string) => void
  /** The one place an item's draft resources die: dispose, invalidate and forget. */
  invalidateItemResources: (itemId: string) => void
  invalidateAllItemResources: () => void
  disposeAllSchedulers: () => void
  mergeAcceptFeedback: (feedback: Readonly<Record<string, string>>) => BatchReviewCommandResult
  clearAcceptFeedback: (itemId: string) => BatchReviewCommandResult
  resetAcceptFeedback: () => BatchReviewCommandResult
  setSaveFailureTypesFor: (itemIds: readonly string[], errorType: string) => BatchReviewCommandResult
  clearSaveFailure: (itemId: string) => BatchReviewCommandResult
  setRecoveryLoading: (itemId: string, loading: boolean) => BatchReviewCommandResult
  beginSaveRequest: (itemIds: readonly string[], body: SaveConfirmBatchItemsBody) => BatchReviewCommandResult
  beginFrozenSaveRetry: () => BatchReviewCommandResult
  finishSaveAttempt: () => BatchReviewCommandResult
  clearSaveOperation: () => BatchReviewCommandResult
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
  beginSave: (itemIds: readonly string[], options?: { confirmed?: boolean }) => BatchReviewCommandResult
  markSelectedRecheckStale: () => BatchReviewCommandResult
  focusItemAfterSave: (itemId: string, options: { failed: boolean }) => BatchReviewCommandResult
  finishSaveItem: (itemId: string, result: BatchSaveResultItem) => BatchReviewCommandResult
  failSaveItem: (itemId: string, error: unknown) => BatchReviewCommandResult
  markSaveResponseUnknown: (itemIds: readonly string[], error?: unknown) => BatchReviewCommandResult
  retrySavedConfirm: (itemId: string) => BatchReviewCommandResult
  finishAccept: (itemId: string, requestId: string) => BatchReviewCommandResult
  locateTracking: (itemId: string, requestId: string, trackingId: string) => BatchReviewCommandResult
  markTrackingNotFound: (itemId: string) => BatchReviewCommandResult
  failTrackingVerification: (itemId: string) => BatchReviewCommandResult
  consumeConfirmed: (itemId: string) => BatchReviewCommandResult
  removeItem: (itemId: string, options?: { focusCandidates?: readonly string[] }) => BatchReviewCommandResult
  resetRoute: () => BatchReviewCommandResult
  newIdempotencyKey: (itemId: string) => string | null
}

export function useBatchReviewJourney<
  TSession extends BatchReviewDraftSessionFacts = BatchReviewDraftSessionFacts,
  TScheduler extends BatchReviewDraftSchedulerFacts = BatchReviewDraftSchedulerFacts,
>(rawInput = '', ports?: BatchReviewDraftPorts<TSession, TScheduler>): BatchReviewJourney<TSession, TScheduler> {
  const stateRef = shallowRef(createBatchReviewState(rawInput))
  const parseErrorRef = ref('')
  const batchIdRef = ref('')
  const draftCreateItemIdsRef = ref<ReadonlySet<string>>(new Set<string>())
  const draftCreateCandidateIdsRef = ref<Readonly<Record<string, string>>>({})
  const draftCreateErrorsRef = ref<Readonly<Record<string, Record<string, string>>>>({})
  const acceptFeedbackRef = ref<Readonly<Record<string, string>>>({})
  const saveFailureTypesRef = ref<Readonly<Record<string, string>>>({})
  const recoveryLoadingItemIdsRef = ref<ReadonlySet<string>>(new Set<string>())
  // shallowRef keeps the frozen request body a plain, inert object: it is the
  // exact payload the retry must resend, not reactive state.
  const saveOperationRef = shallowRef<BatchReviewSaveOperation | null>(null)
  // Handles are keyed by item id. The collections are reactive so the snapshot
  // below re-derives facts the moment a handle is created, replaced or dropped.
  const draftSessions = shallowReactive(new Map<string, TSession>())
  const editSchedulers = shallowReactive(new Map<string, { session: TSession; scheduler: TScheduler }>())

  /** Relax handles into the read-only facts surfaces may consume. */
  function draftViewFacts(): Record<string, BatchReviewDraftViewFacts> {
    const facts: Record<string, BatchReviewDraftViewFacts> = {}
    for (const [itemId, session] of draftSessions) {
      const scheduler = editSchedulers.get(itemId)?.scheduler
      facts[itemId] = {
        draftId: session.draftId.value,
        draftRevision: session.draftRevision.value,
        invalid: session.invalid.value,
        dirty: session.dirty.value,
        applying: session.applying.value,
        hasError: Boolean(session.error.value),
        canRetry: session.canRetry.value,
        waiting: scheduler?.waiting.value ?? false,
        folderPending: scheduler?.folderPending.value ?? false,
        groupPending: scheduler?.groupPending.value ?? false,
      }
    }
    return facts
  }

  const snapshot = computed<BatchReviewSnapshot>(() => ({
    phase: stateRef.value.phase,
    busy: stateRef.value.busy,
    items: stateRef.value.items,
    currentItemId: stateRef.value.currentItemId,
    selectedItemIds: new Set(
      Object.values(stateRef.value.items)
        .filter((item) => item.selected)
        .map((item) => item.itemId),
    ),
    parseError: parseErrorRef.value,
    batchId: batchIdRef.value,
    draftCreateItemIds: draftCreateItemIdsRef.value,
    draftCreateCandidateIds: draftCreateCandidateIdsRef.value,
    draftCreateErrors: draftCreateErrorsRef.value,
    drafts: draftViewFacts(),
    acceptFeedback: acceptFeedbackRef.value,
    saveFailureTypes: saveFailureTypesRef.value,
    recoveryLoadingItemIds: recoveryLoadingItemIdsRef.value,
    saveOperation: saveOperationRef.value,
    saveInFlight: stateRef.value.busy === 'saving' || Boolean(saveOperationRef.value?.inFlight),
    savingItemIds: new Set(
      Object.values(stateRef.value.items)
        .filter((item) => item.phase === 'saving')
        .map((item) => item.itemId),
    ),
  }))

  /**
   * One item, one session for one draft identity. A changed draft id means the
   * previous capability is dead, so it is replaced rather than reused.
   */
  function ensureSession(facts: BatchReviewDraftFacts): TSession | null {
    if (!ports) return null
    const existing = draftSessions.get(facts.itemId)
    if (existing && existing.draftId.value === facts.draftId) return existing
    const session = ports.createSession(facts)
    draftSessions.set(facts.itemId, session)
    return session
  }

  function ensureSchedulerFor(facts: BatchReviewDraftFacts): TScheduler | null {
    if (!ports) return null
    const session = ensureSession(facts)
    if (!session) return null
    const existing = editSchedulers.get(facts.itemId)
    if (existing && existing.session === session) return existing.scheduler
    existing?.scheduler.dispose()
    const scheduler = ports.createScheduler(facts, session)
    editSchedulers.set(facts.itemId, { session, scheduler })
    return scheduler
  }

  /** 停掉所有定时器并遗忘调度器句柄（会话是否作废由调用方决定）。 */
  function disposeSchedulers(): void {
    for (const { scheduler } of editSchedulers.values()) scheduler.dispose()
    editSchedulers.clear()
  }

  function dropItemResources(itemId: string): void {
    const handle = editSchedulers.get(itemId)
    if (handle) {
      handle.scheduler.dispose()
      editSchedulers.delete(itemId)
    }
    const session = draftSessions.get(itemId)
    if (session) {
      session.invalidate()
      draftSessions.delete(itemId)
    }
  }

  function mergeAcceptFeedback(feedback: Readonly<Record<string, string>>): BatchReviewCommandResult {
    acceptFeedbackRef.value = { ...acceptFeedbackRef.value, ...feedback }
    return { accepted: true, effects: [] }
  }

  function clearAcceptFeedback(itemId: string): BatchReviewCommandResult {
    if (!(itemId in acceptFeedbackRef.value)) return { accepted: false, effects: [] }
    const next = { ...acceptFeedbackRef.value }
    delete next[itemId]
    acceptFeedbackRef.value = next
    return { accepted: true, effects: [] }
  }

  function resetAcceptFeedback(): BatchReviewCommandResult {
    acceptFeedbackRef.value = {}
    return { accepted: true, effects: [] }
  }

  function setSaveFailureTypesFor(itemIds: readonly string[], errorType: string): BatchReviewCommandResult {
    const next = { ...saveFailureTypesRef.value }
    for (const itemId of itemIds) next[itemId] = errorType
    saveFailureTypesRef.value = next
    return { accepted: true, effects: [] }
  }

  function clearSaveFailure(itemId: string): BatchReviewCommandResult {
    if (!saveFailureTypesRef.value[itemId]) return { accepted: false, effects: [] }
    const next = { ...saveFailureTypesRef.value }
    delete next[itemId]
    saveFailureTypesRef.value = next
    return { accepted: true, effects: [] }
  }

  function setRecoveryLoading(itemId: string, loading: boolean): BatchReviewCommandResult {
    const next = new Set(recoveryLoadingItemIdsRef.value)
    if (loading) next.add(itemId)
    else next.delete(itemId)
    recoveryLoadingItemIdsRef.value = next
    return { accepted: true, effects: [] }
  }

  function beginSaveRequest(itemIds: readonly string[], body: SaveConfirmBatchItemsBody): BatchReviewCommandResult {
    saveOperationRef.value = {
      itemIds: [...itemIds],
      body,
      outcomeUnknown: false,
      inFlight: true,
    }
    return { accepted: true, effects: [] }
  }

  function beginFrozenSaveRetry(): BatchReviewCommandResult {
    const operation = saveOperationRef.value
    if (!operation) return { accepted: false, effects: [] }
    saveOperationRef.value = { ...operation, inFlight: true }
    return { accepted: true, effects: [] }
  }

  function finishSaveAttempt(): BatchReviewCommandResult {
    const operation = saveOperationRef.value
    if (operation?.inFlight) saveOperationRef.value = { ...operation, inFlight: false }
    return { accepted: true, effects: [] }
  }

  function clearSaveOperation(): BatchReviewCommandResult {
    if (!saveOperationRef.value) return { accepted: false, effects: [] }
    saveOperationRef.value = null
    return { accepted: true, effects: [] }
  }

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

  function beginParse(options: { sceneHasUnsafeWork?: boolean; discardScene?: boolean } = {}): BatchReviewCommandResult {
    // An unsafe scene is only discarded after the user answers; the command
    // changes nothing until the caller comes back with that answer.
    if (options.sceneHasUnsafeWork && !options.discardScene) {
      return { accepted: false, effects: [{ kind: 'needsConfirmation', request: { reason: 'discard_batch_scene' } }] }
    }
    // A new attempt retires the previous failure message before loading starts.
    parseErrorRef.value = ''
    return apply({ type: 'parse_started' })
  }

  /** The user refused to discard the scene: nothing changed, the caller restores its input. */
  function abandonParseStart(): BatchReviewCommandResult {
    return { accepted: false, effects: [{ kind: 'focus', target: { target: 'search_input' } }] }
  }

  /** Asking whether the route-local scene may be dropped; no state changes yet. */
  function requestRouteReset(): BatchReviewCommandResult {
    return { accepted: false, effects: [{ kind: 'needsConfirmation', request: { reason: 'leave_batch_review' } }] }
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
    abandonParseStart,
    requestRouteReset,
    rejectParseInput,
    finishParse,
    failParse,
    restoreBatchId,
    beginDraftCreate,
    failDraftCreate,
    finishDraftCreate,
    clearDraftCreateErrors,
    ensureDraftSession: ensureSession,
    ensureScheduler: ensureSchedulerFor,
    releaseItemEditing(itemId) {
      const handle = editSchedulers.get(itemId)
      if (!handle) return
      handle.scheduler.cancelTimer()
      handle.scheduler.dropPending()
    },
    mergeAcceptFeedback,
    clearAcceptFeedback,
    resetAcceptFeedback,
    setSaveFailureTypesFor,
    clearSaveFailure,
    setRecoveryLoading,
    beginSaveRequest,
    beginFrozenSaveRetry,
    finishSaveAttempt,
    clearSaveOperation,
    invalidateItemResources: dropItemResources,
    invalidateAllItemResources() {
      disposeSchedulers()
      for (const session of draftSessions.values()) session.invalidate()
      draftSessions.clear()
    },
    disposeAllSchedulers: disposeSchedulers,
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
    beginSave(itemIds, options = {}) {
      // The N-部 intent is never sent before the user answered the dialog.
      if (!options.confirmed) {
        return { accepted: false, effects: [{ kind: 'needsConfirmation', request: { reason: 'confirm_selected_batch' } }] }
      }
      return apply({ type: 'begin_save', itemIds })
    },
    /** The frozen N intent no longer matches the batch: show and focus the notice. */
    markSelectedRecheckStale() {
      return {
        accepted: false,
        effects: [{ kind: 'focus', target: { target: 'selected_recheck_notice' } }],
      }
    },
    /** The save result decided the next item to look at; the caller owns focus. */
    focusItemAfterSave(itemId, options) {
      return {
        accepted: true,
        effects: [
          {
            kind: 'announce',
            event: options.failed
              ? { type: 'focus_first_failed', itemId }
              : { type: 'focus_first_pending', itemId },
          },
          { kind: 'focus', target: { target: 'card', itemId, reveal: true } },
        ],
      }
    },
    finishSaveItem: (itemId, result) => apply({ type: 'save_succeeded', itemId, result }),
    failSaveItem: (itemId, error) => apply({ type: 'save_failed', itemId, error }),
    markSaveResponseUnknown(itemIds, error) {
      // 「结果待确认」的唯一权威来源：冻结请求与条目相位在同一次命令里落定。
      const operation = saveOperationRef.value
      if (operation) saveOperationRef.value = { ...operation, outcomeUnknown: true, inFlight: false }
      return apply({
        type: 'save_response_unknown',
        itemIds,
        ...(error === undefined ? {} : { error }),
      })
    },
    retrySavedConfirm: (itemId) => apply({ type: 'retry_saved_confirm', itemId }),
    finishAccept: (itemId, requestId) => apply({ type: 'accept_succeeded', itemId, requestId }),
    locateTracking: (itemId, requestId, trackingId) => apply({ type: 'tracking_located', itemId, requestId, trackingId }),
    markTrackingNotFound: (itemId) => apply({ type: 'tracking_not_found', itemId }),
    failTrackingVerification: (itemId) => apply({ type: 'tracking_verification_failed', itemId }),
    consumeConfirmed: (itemId) => apply({ type: 'consume_confirmed', itemId }),
    removeItem(itemId, options = {}) {
      const applied = apply({ type: 'remove_item', itemId })
      if (!applied.accepted) return applied
      // 条目离场必须把焦点交给一个真实元素；候选与兜底由视图元素决定。
      return {
        accepted: true,
        effects: [{
          kind: 'focus',
          target: { target: 'card_or_list', candidateItemIds: options.focusCandidates ?? [] },
        }],
      }
    },
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
