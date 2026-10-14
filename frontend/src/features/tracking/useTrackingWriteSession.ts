/**
 * The one local session of a tracking external write (issue #168).
 *
 * Every external write this page can send — 提交/重试 (``SUBMIT``/``RETRY``),
 * 结果恢复 (``RECOVER_*``) and 外部管理 (``MODIFY``/``SET_ENABLED``/
 * ``REFRESH_RSS``/``DELETE_EXTERNAL``) — is *one* concept: a local session for
 * one write operation.  The module owns that session:
 *
 * - the **operation kind** and the target scope it may address;
 * - the **intent** (expected revision, ``confirm`` and the opaque idempotency
 *   key) and the rule that an unresolved external result keeps it while a
 *   definite result releases it;
 * - the fixed Chinese copy for every state, conflict and impact confirmation;
 * - the **request body** builder per operation, and the endpoint it must go to;
 * - the **result projection** that distinguishes a definite business verdict, a
 *   pre-boundary refusal (409/structured 4xx) and an unreadable result, plus the
 *   read-back the page must perform to converge.
 *
 * The module is API-free.  It never performs transport, shows a dialog, routes
 * or touches the DOM: the page answers the confirmation with `begin*` again and
 * sends the returned request.  Callers use three surfaces only:
 *
 *   - the three family snapshots (`sessions`) and the lock/notice queries;
 *   - named commands, each returning what the page must do next;
 *   - the read-only scope/sendable projections the inspector and the forms
 *     filter their own offers with (`projectTrackingActionScopes`,
 *     `isSendableManagementAction`).
 *
 * The vocabulary of the previous ``trackingProjection``/``trackingManagement``
 * session halves (state enums, message tables, constructors, conflict
 * classifiers) is deliberately **not** exported: it is this module's
 * implementation detail.  ``trackingProjection`` keeps only the display
 * projection; ``trackingManagement`` keeps only the modify form/patch model.
 */
import { computed, ref, watch, type ComputedRef, type Ref } from 'vue'

import type { operations, paths } from '@/api/generated/api'

import type { ApiError } from '@/api/client'

import {
  canVerifyExternally,
  createCheckSession,
  createResubmitConfirmationBody,
  createResubmitSession,
  executableTrackingActions,
  projectCheckResult,
  projectResubmitOffer,
  projectRevalidateIssues,
  resubmitConflictMessage,
  TRACKING_CHECK_ENDPOINT,
  TRACKING_RESUBMIT_ENDPOINT,
  type CapabilityResult,
  type TrackingAction,
  type TrackingActionCode,
  type TrackingCheckBody,
  type TrackingCheckResult,
  type TrackingCheckSession,
  type TrackingItem,
  type TrackingResubmitBinding,
  type TrackingResubmitBody,
  type TrackingResubmitResult,
  type TrackingResubmitSession,
  type TrackingRevalidateIssueView,
  type TrackingScope,
} from './trackingProjection'
import {
  managementPatchPresent,
  type SavedConnectionGeneration,
  type TrackingDeleteExternalBody,
  type TrackingManagementResult,
  type TrackingModifyBody,
  type TrackingRefreshRssBody,
  type TrackingRssPatch,
  type TrackingSetEnabledBody,
  type TrackingSubscriptionPatch,
} from './trackingManagement'

type ApiPath = Extract<keyof paths, string>

// ---------------------------------------------------------------------------
// Operation kinds, families and the single state vocabulary.
// ---------------------------------------------------------------------------

/**
 * Which of the page's three result panels owns one operation.  It is the only
 * reason the page keeps three slots: a write, a recovery and a management
 * result may legitimately be visible at the same time.
 */
type TrackingWriteFamily = 'SUBMIT' | 'RECOVERY' | 'MANAGEMENT'

/**
 * Every external write operation this page can send, declared exactly once
 * (issue #193).
 *
 * What is single-sourced here: the operation vocabulary
 * (``TrackingWriteOperation``), which family owns the operation, the generated
 * route it travels to, and — derived from those — the three family action unions
 * plus every family guard.  An operation therefore cannot exist in one
 * vocabulary, be reachable in one family guard and be missing from another
 * vocabulary at the same time.  The type system continues the chain: the route
 * is checked against the generated ``ApiPath`` union, and each family's
 * per-action table is a total ``Record`` over its derived union, so a new
 * operation is a compile error until its own family wiring exists.  What is
 * *not* here, because it is genuinely per-action family behaviour, stays as that
 * family's wiring: the impact confirmation and the fixed per-state copy (one
 * entry in the family's own per-action table), the request body shape, and the
 * intent builder — the last of which fails closed (no request) rather than being
 * forced by the compiler.
 */
const TRACKING_WRITE_ACTIONS = {
  SUBMIT: { family: 'SUBMIT', endpoint: '/api/v1/tracking/items/{tracking_id}/submit' },
  RETRY: { family: 'SUBMIT', endpoint: '/api/v1/tracking/items/{tracking_id}/retry' },
  RECOVER_AUTO: { family: 'RECOVERY', endpoint: '/api/v1/tracking/items/{tracking_id}/recover' },
  MARK_SUCCEEDED: { family: 'RECOVERY', endpoint: '/api/v1/tracking/items/{tracking_id}/recover' },
  MARK_FAILED: { family: 'RECOVERY', endpoint: '/api/v1/tracking/items/{tracking_id}/recover' },
  VERIFY_EXTERNAL: { family: 'RECOVERY', endpoint: '/api/v1/tracking/items/{tracking_id}/recover' },
  MODIFY: { family: 'MANAGEMENT', endpoint: '/api/v1/tracking/items/{tracking_id}/modify' },
  SET_ENABLED: { family: 'MANAGEMENT', endpoint: '/api/v1/tracking/items/{tracking_id}/set-enabled' },
  REFRESH_RSS: { family: 'MANAGEMENT', endpoint: '/api/v1/tracking/items/{tracking_id}/refresh' },
  DELETE_EXTERNAL: { family: 'MANAGEMENT', endpoint: '/api/v1/tracking/items/{tracking_id}/delete-external' },
} as const satisfies Record<string, { readonly family: TrackingWriteFamily; readonly endpoint: ApiPath }>

type TrackingWriteOperation = keyof typeof TRACKING_WRITE_ACTIONS

/** The operations whose own declaration names this family: the family vocabulary. */
type OperationsOfFamily<F extends TrackingWriteFamily> = {
  [K in TrackingWriteOperation]: (typeof TRACKING_WRITE_ACTIONS)[K]['family'] extends F ? K : never
}[TrackingWriteOperation]

const WRITE_OPERATION_SET = new Set<string>(Object.keys(TRACKING_WRITE_ACTIONS))

/**
 * The one operation judgment every family guard is bound from.
 *
 * It accepts a value only when this page declares it *and* its declaration names
 * the requested family, so no family can send an operation it does not own and
 * an unknown code fails closed in every family.
 */
function isOperationOfFamily<F extends TrackingWriteFamily>(
  family: F,
  value: unknown,
): value is OperationsOfFamily<F> {
  return typeof value === 'string'
    && WRITE_OPERATION_SET.has(value)
    && TRACKING_WRITE_ACTIONS[value as TrackingWriteOperation].family === family
}

/** The one family lookup; the operation's declaration is its only source. */
function operationFamily(operation: TrackingWriteOperation): TrackingWriteFamily {
  return TRACKING_WRITE_ACTIONS[operation].family
}

/** The one route lookup; an operation can only ever travel to its own path. */
function operationEndpoint(operation: TrackingWriteOperation): ApiPath {
  return TRACKING_WRITE_ACTIONS[operation].endpoint
}

export type TrackingRecoveryActionCode = OperationsOfFamily<'RECOVERY'>

export type TrackingManagementActionCode = OperationsOfFamily<'MANAGEMENT'>

/**
 * The scope of a management action *as it is being requested* (US-313, A.2).
 *
 * ``TrackingScope`` is the generated public scope enum, but the requested scope
 * is only real if this page has a request body shape for it, so the vocabulary
 * lives with the write session that owns every management request.  The display
 * projection and the forms read the type and the guard from here; a scope without
 * such a shape can never be sent, and it fails closed at the guard below rather
 * than at the boundary.
 *
 * The array itself is deliberately *not* exported (issue #193, #168 review item
 * 5): the type and the guard are what consumers need, and exporting the values
 * too would add exactly the kind of consumer-less export this ticket removed.
 */
const TRACKING_MANAGEMENT_SCOPES = ['SUBSCRIPTION', 'ASSOCIATED_RSS'] as const

export type TrackingManagementScope = (typeof TRACKING_MANAGEMENT_SCOPES)[number]

export function isTrackingManagementScope(value: unknown): value is TrackingManagementScope {
  return typeof value === 'string'
    && (TRACKING_MANAGEMENT_SCOPES as readonly string[]).includes(value)
}

/**
 * One published state vocabulary for every write family.
 *
 * ``UNKNOWN`` also covers a transport result we could not read at all.
 * ``REJECTED`` is the definite counterpart: a structured non-409 HTTP 4xx the
 * server returned *before* the external boundary (D38-08.5), so Auto Bangumi
 * was provably never written.  ``SUCCEEDED``/``FAILED`` are the management
 * family's own decided verdicts, and ``needsManual`` says whether a human
 * conclusion is still required.
 */
type TrackingWriteState =
  | 'IN_FLIGHT'
  | 'ACTIVE' | 'ADDED_TO_DOWNLOAD' | 'SUBMIT_FAILED' | 'NEEDS_RECONFIRM'
  | 'VERIFYING_EXTERNAL' | 'RECOVERY_REQUIRED'
  | 'SUCCEEDED' | 'FAILED'
  | 'CONFLICT' | 'REJECTED' | 'UNKNOWN'

/** The three state unions the generated contracts publish. */
type SubmitWriteState =
  'IN_FLIGHT' | (typeof SUBMIT_OUTCOMES)[number] | 'CONFLICT' | 'REJECTED' | 'UNKNOWN'
type RecoveryWriteState =
  'IN_FLIGHT' | (typeof RECOVERY_OUTCOMES)[number] | 'CONFLICT' | 'REJECTED' | 'UNKNOWN'
type ManagementWriteState =
  'IN_FLIGHT' | 'SUCCEEDED' | 'FAILED' | 'CONFLICT' | 'REJECTED' | 'UNKNOWN'

/** True only while the external result is still indeterminate. */
function keepsIntent(state: TrackingWriteState): boolean {
  return state === 'UNKNOWN' || state === 'VERIFYING_EXTERNAL' || state === 'RECOVERY_REQUIRED'
}

interface TrackingWriteDiagnostics {
  readonly httpStatus: number | null
  readonly messageZh: string | null
  readonly messageEn: string | null
}

/** One item-scoped external write result, whichever family produced it. */
export interface TrackingWriteSession {
  readonly trackingId: string
  readonly operation: TrackingWriteOperation
  readonly family: TrackingWriteFamily
  /** The management scope this operation addressed; null for the other families. */
  readonly targetScope: TrackingManagementScope | null
  readonly state: TrackingWriteState
  /** Fixed Chinese copy; the raw server enum never reaches the DOM. */
  readonly message: string
  readonly issues: readonly TrackingRevalidateIssueView[]
  /** Published failure class of a failed/indeterminate result, when provided. */
  readonly failureCategory: string | null
  readonly diagnostics: TrackingWriteDiagnostics
  readonly needsManual: boolean
  /** The fixed manual-conclusion notice, present exactly when needsManual. */
  readonly manualNotice: string | null
  /**
   * True while this session still owns the page's single intent: the external
   * result is indeterminate, so the very same key/revision binding must be
   * replayed rather than replaced.
   */
  readonly keepsIntent: boolean
}

/** The three panels' latest session, one per write family. */
export interface TrackingWriteSessionSet {
  readonly submit: TrackingWriteSession | null
  readonly recovery: TrackingWriteSession | null
  readonly management: TrackingWriteSession | null
}

/** A fixed impact confirmation; the page renders it and returns the answer. */
interface TrackingWriteConfirmation {
  title: string
  message: string
  confirmLabel: string
  /** Only the manual "mark as failed" and the external delete are a danger. */
  danger?: boolean
}

// ---------------------------------------------------------------------------
// Generated request/result shapes of the write families.
// ---------------------------------------------------------------------------

type TrackingSubmitBody = NonNullable<
  operations['submitTrackingItem']['requestBody']['content']['application/json']
>
type TrackingSubmitResult = NonNullable<
  operations['submitTrackingItem']['responses']['200']['content']['application/json']['result']
>
type TrackingRetryBody = NonNullable<
  operations['retryTrackingItem']['requestBody']['content']['application/json']
>
type TrackingRetryResult = NonNullable<
  operations['retryTrackingItem']['responses']['200']['content']['application/json']['result']
>
/**
 * ``submit`` and ``retry`` are the two submit-family external writes (US-226):
 * the retry endpoint accepts exactly the same revision/key/confirm body and
 * answers with the same persisted-outcome result.
 */
type TrackingWriteBody = TrackingSubmitBody | TrackingRetryBody
type TrackingWriteResult = TrackingSubmitResult | TrackingRetryResult
type TrackingRecoverBody = NonNullable<
  operations['recoverTrackingItem']['requestBody']['content']['application/json']
>
type TrackingRecoverResult = NonNullable<
  operations['recoverTrackingItem']['responses']['200']['content']['application/json']['result']
>
type TrackingPlanDeleteResult = NonNullable<
  operations['deleteTrackingPlan']['responses']['200']['content']['application/json']['result']
>
type TrackingBatchResult = NonNullable<
  operations['submitTrackingBatch']['responses']['200']['content']['application/json']['result']
>

/**
 * The request-scoped Auto Bangumi generation every write carries.
 *
 * Issue #193: it is *derived* from the saved connection generation
 * ``trackingManagement`` already declares, instead of a second same-shaped
 * interface here that could silently drift from it, minus the one legacy input
 * field (``base_url``) the request builders deliberately ignore — so the write
 * seam cannot even accept a value it would never send.
 */
type TrackingWriteConfig = Omit<SavedConnectionGeneration, 'base_url'>

// ---------------------------------------------------------------------------
// The page-visible intents and requests.
// ---------------------------------------------------------------------------

/** Create one in-memory intent; callers must keep it local to the action. */
interface TrackingWriteIntent {
  readonly action: TrackingActionCode
  readonly targetScope?: TrackingScope
  readonly expectedRevision: number
  readonly confirm: true
  readonly idempotencyKey: string
}

function makeOpaqueKey(): string {
  const candidate = globalThis.crypto?.randomUUID?.()
  return candidate && /^[A-Za-z0-9-]{8,128}$/.test(candidate)
    ? candidate
    : `intent-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 14)}`
}

/** One request the page must send; endpoint, path and body travel as one unit. */
export interface TrackingWriteRequest {
  readonly endpoint: ApiPath
  /** The path parameters the endpoint template requires. */
  readonly path: Readonly<Record<string, string>>
  readonly body: unknown
}

/** Where a refused command's fixed next step must be stated. */
interface TrackingWriteRefusal {
  readonly trackingId: string
  readonly reason: 'INTENT' | 'REPLAY'
}

/** Which dialog the caller must answer before calling the command again. */
type TrackingWriteAsk = 'IMPACT' | 'SUBMISSION_MODE'

interface TrackingWriteStart {
  readonly accepted: boolean
  /**
   * Issue #184: which resubmission transport the returned request belongs to.
   * ``OFFER`` settles through ``finishResubmitOffer``; ``CONFIRMATION`` is the
   * one new-operation write and settles through ``finishSubmit``.
   */
  readonly resubmitPhase?: 'OFFER' | 'CONFIRMATION' | null
  readonly refusal: TrackingWriteRefusal | null
  readonly ask: TrackingWriteAsk | null
  readonly confirmation: TrackingWriteConfirmation | null
  readonly request: TrackingWriteRequest | null
  /**
   * Converging effects a refused/unbuildable command still owes the caller
   * (a definite page-side refusal must re-read the server, never stay stuck).
   */
  readonly effects: readonly TrackingWriteEffect[]
}

/**
 * Data the page maps to routing/IO.  The module never performs them itself.
 */
export type TrackingWriteEffect =
  /** Re-read the server: optionally the list, and the open detail when it moved. */
  | { readonly kind: 'recheck'; readonly trackingId: string | null; readonly refreshList: boolean }
  /**
   * Issue #184: the read-only phase offered a resubmit and the page must get the
   * user's explicit acceptance of the duplicate/resource risk before the one new
   * operation may be created.  The page answers with ``cancelResubmit`` or
   * ``beginResubmitConfirmation``.
   */
  | {
      readonly kind: 'confirmResubmitRisk'
      readonly trackingId: string
      readonly binding: TrackingResubmitBinding
    }
  /** A fixed verdict the page must surface (success notice or blocking dialog). */
  | { readonly kind: 'notify'; readonly feedback: TrackingWriteFeedback }

export interface TrackingWriteFeedback {
  /** ``success`` is a lightweight notice; ``dialog`` takes over with a settings link. */
  readonly channel: 'success' | 'dialog'
  readonly title: string
  readonly message: string
}

/**
 * A classified API failure, as the page's transport already normalized it.
 *
 * Issue #193: the shape is *derived* from the shared transport error rather than
 * restated field by field, so a rename or a new transport flag cannot drift into
 * a second, silently wrong vocabulary here.  Two differences stay deliberate:
 * every flag but ``status``/``httpError`` is optional because a caller states
 * only what it knows, and ``type`` stays ``unknown`` because the conflict
 * classifiers must fail closed on *any* server value, not only on a string.
 */
type TrackingWriteError =
  Pick<ApiError, 'status' | 'httpError'>
  & Partial<Pick<ApiError, 'nonJson' | 'network' | 'cancelled'>>
  & { readonly type?: unknown }

export type TrackingSubmissionMode = 'CONTINUE_TRACKING' | 'DOWNLOAD_EXISTING'

/** One batch start: the page also states which of its plans were pre-skipped. */
interface TrackingBatchStart extends TrackingWriteStart {
  readonly skipped: readonly SkippedBatchEntry[]
  /** The fixed title of the page's skipped-plans dialog, or '' when none. */
  readonly skippedTitle: string
}

/**
 * The exact binding one risk-confirmed resubmission was issued under (issue
 * #184).  It is the confirmation's identity: while the external result is
 * unproven the page replays this very body instead of re-checking or minting a
 * second operation.
 */
interface TrackingResubmitIntent {
  readonly trackingId: string
  readonly binding: TrackingResubmitBinding
}

export interface TrackingWriteTarget {
  readonly item: TrackingItem
  readonly action: TrackingAction
}

export interface TrackingWriteBeginOptions {
  /** The user's answer to the impact dialog (or the chosen submission mode). */
  readonly confirmed?: boolean
  readonly mode?: TrackingSubmissionMode | null
  /** The saved Auto Bangumi generation, read after the dialog. */
  readonly connection?: TrackingWriteConfig | null
  /** Server-root-relative storage profile for this request. */
  readonly storageDir?: string
}

const EMPTY_START: TrackingWriteStart = {
  accepted: false, refusal: null, ask: null, confirmation: null, request: null, effects: [],
}

function ignoredStart(): TrackingWriteStart {
  return EMPTY_START
}

function refusedStart(trackingId: string, reason: TrackingWriteRefusal['reason']): TrackingWriteStart {
  return { ...EMPTY_START, refusal: { trackingId, reason } }
}

function acceptedStart(request: TrackingWriteRequest): TrackingWriteStart {
  return { ...EMPTY_START, accepted: true, request }
}


/**
 * Feedback for a locked (unresolved) external intent (Stage 38 review fix).
 *
 * One page-level intent at a time is a safety invariant: while an external
 * result is still unconfirmed, minting a new key for a *different* request
 * could duplicate or double-apply the external change, so the session refuses it
 * and sends zero requests.  A refusal the user cannot see is a dead end, so the
 * fixed next step below is stated instead of returning silently.  It is
 * deliberately separate from the write/recovery/management result panels (it
 * never replaces their copy or state) and scoped to the record the user acted
 * on, so it can never leak onto another item.
 */
const INTENT_BLOCKED_MESSAGE =
  '上一次外部操作的结果仍未确认，在确认或恢复之前不能发起不同的外部操作；请先使用只读回查或恢复得出结论。'
const REPLAY_BLOCKED_MESSAGE =
  '该外部操作绑定的连接已被清除或更换，结果确认前不能使用新连接重试写入；请继续使用只读回查或恢复。'

// ---------------------------------------------------------------------------
// Submit family (US-310, US-311).
// ---------------------------------------------------------------------------

/** The submit family's own vocabulary: the operations ``TRACKING_WRITE_ACTIONS`` gives it. */
type TrackingWriteActionCode = OperationsOfFamily<'SUBMIT'>

/**
 * The generated path template and the impact confirmation are bound to the
 * server-computed action code, so the page can never send one action's request
 * with another action's copy.
 */
const WRITE_ACTION_CONFIRMATIONS: Record<TrackingWriteActionCode, TrackingWriteConfirmation> = {
  SUBMIT: {
    title: '提交 Auto Bangumi 订阅',
    message: '将在 Auto Bangumi 创建该追番的外部订阅，并可能触发下载。提交只使用已保存的 Auto Bangumi 连接，是否继续？',
    confirmLabel: '确认提交',
  },
  RETRY: {
    title: '重试 Auto Bangumi 提交',
    message: '该追番上次提交明确失败。重试会使用已保存的 Auto Bangumi 连接重新创建外部订阅，并可能触发下载，是否继续？',
    confirmLabel: '确认重试',
  },
}

/** True only for the submit-family actions this page declares it can send. */
function isWriteActionCode(value: TrackingActionCode): value is TrackingWriteActionCode {
  return isOperationOfFamily('SUBMIT', value)
}

const SUBMIT_OUTCOMES = [
  'ACTIVE', 'SUBMIT_FAILED', 'NEEDS_RECONFIRM', 'VERIFYING_EXTERNAL', 'RECOVERY_REQUIRED',
  // Issue #98/#99: a one-time "download existing resources" request Auto
  // Bangumi accepted. It is local history, not an external subscription.
  'ADDED_TO_DOWNLOAD',
] as const satisfies readonly TrackingSubmitResult['outcome'][]

const WRITE_FAILURE_CATEGORIES = [
  'CONNECTION', 'AUTHENTICATION', 'VERSION', 'DUPLICATE_SUBSCRIPTION',
  'VALIDATION', 'REJECTED', 'OUTCOME_UNKNOWN',
] as const

type WriteFailureCategory = (typeof WRITE_FAILURE_CATEGORIES)[number]

interface WriteFailurePresentation {
  readonly title: string
  readonly message: string
  /**
   * ``dialog``: a blocking connection/credential/version problem takes over the
   * page and offers a settings deep link. ``item``: the rejection belongs to the
   * record the user acted on. ``recovery``: the outcome is indeterminate and the
   * existing recovery controls must be used.
   */
  readonly channel: 'dialog' | 'item' | 'recovery'
}

const WRITE_FAILURE_PRESENTATIONS: Readonly<Record<WriteFailureCategory, WriteFailurePresentation>> = {
  CONNECTION: {
    title: '无法连接 Auto Bangumi',
    message: '保存的 Auto Bangumi 配置当前无法连接。请前往设置检查地址与网络后重试；本次未创建外部订阅。',
    channel: 'dialog',
  },
  AUTHENTICATION: {
    title: 'Auto Bangumi 认证失败',
    message: '保存的连接凭据被 Auto Bangumi 拒绝。请前往设置更新账号或密码后重试；本次未创建外部订阅。',
    channel: 'dialog',
  },
  VERSION: {
    title: 'Auto Bangumi 版本不受支持',
    message: '当前 Auto Bangumi 版本不在已验证的 3.1.18 能力范围内。请前往设置确认版本后重试；本次未创建外部订阅。',
    channel: 'dialog',
  },
  DUPLICATE_SUBSCRIPTION: {
    title: '已存在相同订阅',
    message: 'Auto Bangumi 中已存在相同订阅，本次未重复创建。请核对既有订阅后再决定是否继续。',
    channel: 'item',
  },
  VALIDATION: {
    title: '提交前检查未通过',
    message: '本地方案未通过提交前检查，本次未创建外部订阅。请按提示修改追番方案后重新提交。',
    channel: 'item',
  },
  REJECTED: {
    title: 'Auto Bangumi 明确拒绝',
    message: 'Auto Bangumi 明确拒绝了本次提交，尚未创建外部订阅。请检查方案内容后重新确认提交。',
    channel: 'item',
  },
  OUTCOME_UNKNOWN: {
    title: '提交结果待确认',
    message: '无法确认 Auto Bangumi 是否已创建订阅。请先使用恢复核验，未确认前不会再次提交。',
    channel: 'recovery',
  },
}

/** Parse the server's published category; anything unknown fails closed. */
function writeFailureCategory(value: unknown): WriteFailureCategory | null {
  return typeof value === 'string' && (WRITE_FAILURE_CATEGORIES as readonly string[]).includes(value)
    ? (value as WriteFailureCategory)
    : null
}

const SUBMIT_MESSAGES: Record<SubmitWriteState, string> = {
  IN_FLIGHT: '正在提交到 Auto Bangumi，请稍候…',
  ACTIVE: '提交成功：已在 Auto Bangumi 创建外部订阅。',
  // Issue #98/#99: a one-time acceptance — no subscription, no media promise.
  ADDED_TO_DOWNLOAD: '已加入下载：Auto Bangumi 已接受本次下载现有资源的请求，不代表资源已下载完成。',
  SUBMIT_FAILED: '提交明确失败，尚未创建外部订阅；可在确认后显式重试。',
  NEEDS_RECONFIRM: '本地方案已变化，本次尚未创建外部订阅；请返回修改方案后重新确认。',
  VERIFYING_EXTERNAL: '外部提交结果待确认，正在只读回查；请勿重复提交。',
  RECOVERY_REQUIRED: '本地结果未完成落盘，需要恢复；请勿重复提交。',
  CONFLICT: '追番记录已变化或当前状态不允许提交，本次未提交到 Auto Bangumi；正在刷新最新详情，请重新确认后再提交。',
  // A structured non-409 4xx is decided before the external boundary, so the
  // copy states plainly that nothing was created; the raw error_type/status is
  // deliberately never rendered.
  REJECTED: '服务端明确拒绝了本次请求，本次未创建 Auto Bangumi 外部订阅；正在刷新最新详情，请重新确认后再提交。',
  UNKNOWN: '提交结果待确认，正在只读回查；未确认生效前不会再次提交。',
}

/** Issue #101 AC 1: a one-time failure never claims an external effect either way. */
const ONE_TIME_SUBMIT_FAILED_MESSAGE = '提交失败，可重新提交。'

const KNOWN_SUBMIT_OUTCOMES = new Set<string>(SUBMIT_OUTCOMES)

function isSubmitOutcome(value: unknown): value is SubmitWriteState {
  return typeof value === 'string' && KNOWN_SUBMIT_OUTCOMES.has(value)
}

const WRITE_CONFLICT_TYPES = [
  'tracking_revision_conflict', 'tracking_idempotency_conflict',
  'tracking_state_conflict', 'tracking_operation_in_progress',
] as const

const WRITE_CONFLICT_FALLBACK_MESSAGE = SUBMIT_MESSAGES.CONFLICT

const WRITE_CONFLICT_MESSAGES: Record<(typeof WRITE_CONFLICT_TYPES)[number], string> = {
  tracking_revision_conflict:
    '追番记录已变化，本次未提交到 Auto Bangumi；正在刷新最新详情，请重新确认后再提交。',
  tracking_idempotency_conflict:
    '本次提交标识已失效，未提交到 Auto Bangumi；正在刷新最新详情，请重新确认后再提交。',
  tracking_state_conflict:
    '当前追番状态不允许本次提交，未提交到 Auto Bangumi；正在刷新最新详情，请按最新状态重新确认。',
  tracking_operation_in_progress:
    '存在尚未完成的提交操作，本次未提交到 Auto Bangumi；正在刷新最新详情，请先完成恢复后再提交。',
}

/** Fixed next step for one documented conflict; unknown types fail closed. */
function writeConflictMessage(errorType: unknown): string {
  return typeof errorType === 'string' && (WRITE_CONFLICT_TYPES as readonly string[]).includes(errorType)
    ? WRITE_CONFLICT_MESSAGES[errorType as (typeof WRITE_CONFLICT_TYPES)[number]]
    : WRITE_CONFLICT_FALLBACK_MESSAGE
}

function projectWriteDiagnostics(value: unknown): TrackingWriteDiagnostics {
  const empty: TrackingWriteDiagnostics = { httpStatus: null, messageZh: null, messageEn: null }
  if (!value || typeof value !== 'object') return empty
  const source = value as Record<string, unknown>
  const status = source.http_status
  const zh = source.message_zh
  const en = source.message_en
  return {
    httpStatus: typeof status === 'number' && Number.isInteger(status) ? status : null,
    messageZh: typeof zh === 'string' && zh.trim() ? zh.trim() : null,
    messageEn: typeof en === 'string' && en.trim() ? en.trim() : null,
  }
}

/**
 * True only for a structured JSON 400/404 pre-boundary refusal (D38-08.5).
 *
 * Only the documented 400/404 JSON envelope is known to be raised before the
 * external boundary. A network failure, timeout, non-JSON body, 5xx, 408/429,
 * or another status stays ``UNKNOWN`` because it may already have reached it.
 */
function isDefiniteWriteRejection(error: TrackingWriteError): boolean {
  return error.httpError === true
    && error.nonJson !== true
    && error.network !== true
    && error.cancelled !== true
    && (error.status === 400 || error.status === 404)
}

/** Create one in-memory submit intent; callers must keep it local to the action. */
function createTrackingActionIntent(
  item: TrackingItem,
  action: TrackingAction,
  targetScope?: TrackingScope,
): TrackingWriteIntent | null {
  const executable = executableTrackingActions(item)
  const projected = executable.find((candidate) => candidate === action || (
    candidate.code === action.code && candidate.label === action.label && candidate.style === action.style &&
    candidate.requires_confirmation === action.requires_confirmation &&
    JSON.stringify(candidate.target_scopes ?? []) === JSON.stringify(action.target_scopes ?? [])
  ))
  if (!projected) return null
  if (targetScope !== undefined && !(projected.target_scopes ?? []).includes(targetScope)) return null
  if (!Number.isInteger(item.revision) || item.revision < 1) return null
  return {
    action: projected.code,
    ...(targetScope ? { targetScope } : {}),
    expectedRevision: item.revision,
    confirm: true,
    idempotencyKey: makeOpaqueKey(),
  }
}

// ---------------------------------------------------------------------------
// Recovery family (US-312).
// ---------------------------------------------------------------------------

/**
 * One recovery action's whole family wiring, declared once (issue #193).
 *
 * ``body`` is the request body value the recover endpoint accepts and
 * ``confirmation`` is the impact confirmation the page must answer first (or
 * ``null`` when the click alone confirms it), so an action's body value and its
 * copy can never be declared in two places that drift apart.
 *
 * A manual conclusion is a user assertion about the external world, so it is
 * always confirmed a second time and the confirmation tells the user to check
 * Auto Bangumi first. ``VERIFY_EXTERNAL`` is confirmed too because it spends the
 * page credential on one external read. ``RECOVER_AUTO`` contacts nothing, so it
 * needs no confirmation at all.
 */
const RECOVERY_ACTION_SPECS = {
  RECOVER_AUTO: { body: 'AUTO', confirmation: null },
  MARK_SUCCEEDED: {
    body: 'MARK_SUCCEEDED',
    confirmation: {
      title: '标记为提交成功',
      message: '请先在 Auto Bangumi 中独立核对该追番的实际状态。标记为成功只更新 MiGuOrca 本地追番状态，不会创建、修改或删除任何外部订阅，是否继续？',
      confirmLabel: '确认标记成功',
    },
  },
  MARK_FAILED: {
    body: 'MARK_FAILED',
    confirmation: {
      title: '标记为提交失败',
      message: '请先在 Auto Bangumi 中独立核对该追番的实际状态。标记为失败只更新 MiGuOrca 本地追番状态，不会删除任何外部订阅，是否继续？',
      confirmLabel: '确认标记失败',
      danger: true,
    },
  },
  VERIFY_EXTERNAL: {
    body: 'VERIFY_EXTERNAL',
    confirmation: {
      title: '只读核验外部状态',
      message: '将使用已保存的 Auto Bangumi 连接，只读核对该追番在 Auto Bangumi 中的当前状态；不会创建、修改或删除任何外部订阅，是否继续？',
      confirmLabel: '确认只读核验',
    },
  },
} as const satisfies Record<TrackingRecoveryActionCode, {
  readonly body: TrackingRecoverBody['action']
  readonly confirmation: TrackingWriteConfirmation | null
}>

function isRecoveryActionCode(value: unknown): value is TrackingRecoveryActionCode {
  return isOperationOfFamily('RECOVERY', value)
}

/** Null for ``RECOVER_AUTO``: the local recovery is confirmed by its click alone. */
function recoveryConfirmation(
  action: TrackingRecoveryActionCode,
): TrackingWriteConfirmation | null {
  return RECOVERY_ACTION_SPECS[action].confirmation
}

interface TrackingRecoveryIntent {
  readonly action: TrackingRecoveryActionCode
  readonly expectedRevision: number
}

/**
 * Build the one recovery request body for a validated action.
 *
 * ``VERIFY_EXTERNAL`` is the only credential-bearing recovery and returns null
 * without the page session, so it can never be sent credential-free; the two
 * manual conclusions are the only bodies that carry ``confirm: true``; ``AUTO``
 * is explicitly credential-free and confirmation-free. The body shape itself
 * cannot express an external id, URL, raw response or free-text note.
 */
function createTrackingRecoverBody(
  action: TrackingRecoveryActionCode,
  expectedRevision: number,
  connection: TrackingWriteConfig | null,
  storageDir?: string,
): TrackingRecoverBody | null {
  const storage = storageDir ? { storage_dir: storageDir } : {}
  if (action === 'VERIFY_EXTERNAL') {
    if (!connection) return null
    return {
      expected_revision: expectedRevision,
      action: RECOVERY_ACTION_SPECS[action].body,
      connection_ref: connection.connection_ref,
      configuration_revision: connection.configuration_revision,
      ...storage,
    }
  }
  const manual = action === 'MARK_SUCCEEDED' || action === 'MARK_FAILED'
  return {
    expected_revision: expectedRevision,
    action: RECOVERY_ACTION_SPECS[action].body,
    ...(manual ? { confirm: true as const } : {}),
    ...storage,
  }
}

/**
 * Validate one recovery action against the current server-observed record.
 *
 * The three local actions must be in the server's projected action list, so a
 * stale or hand-made action can never be sent. ``VERIFY_EXTERNAL`` is accepted
 * only for a record the server says is recoverable (``RECOVER_AUTO`` is the
 * server's marker for exactly those statuses) and only with a proven
 * ``external_verify`` capability from the live page session.
 */
function createTrackingRecoveryIntent(
  item: TrackingItem,
  action: TrackingRecoveryActionCode,
  capabilities?: CapabilityResult | null,
): TrackingRecoveryIntent | null {
  if (!isRecoveryActionCode(action)) return null
  if (!Number.isInteger(item.revision) || item.revision < 1) return null
  const offered = executableTrackingActions(item).map((candidate) => candidate.code)
  if (action === 'VERIFY_EXTERNAL') {
    if (!offered.includes('RECOVER_AUTO') || !canVerifyExternally(capabilities)) return null
  } else if (!offered.includes(action)) {
    return null
  }
  return { action, expectedRevision: item.revision }
}

const RECOVERY_OUTCOMES = [
  'ACTIVE', 'SUBMIT_FAILED', 'RECOVERY_REQUIRED',
] as const satisfies readonly TrackingRecoverResult['outcome'][]

const RECOVERY_MESSAGES: Record<RecoveryWriteState, string> = {
  IN_FLIGHT: '正在恢复该追番的结果，请稍候…',
  ACTIVE: '恢复完成：已确认该追番在 Auto Bangumi 中存在外部订阅。',
  SUBMIT_FAILED: '恢复完成：已确认本次未创建外部订阅，可在确认后显式重试提交。',
  RECOVERY_REQUIRED: '结果仍无法确认，保持恢复状态；未确认前不会自动提交。',
  CONFLICT: '追番记录已变化或当前状态不允许恢复，本次未执行恢复；正在刷新最新详情，请重新确认。',
  REJECTED: '服务端明确拒绝了本次恢复请求，本次未执行任何外部操作；正在刷新最新详情，请重新确认。',
  UNKNOWN: '恢复结果待确认，正在只读回查；未确认前不会自动重发。',
}

/** Shown whenever a recovery could not be concluded without a human verdict. */
const RECOVERY_NEEDS_MANUAL_NOTICE =
  '需要人工核验：请先在 Auto Bangumi 中独立核对该追番的实际状态，再选择“标记为成功”或“标记为失败”；本页不会代替你判断，也不会自动提交。'

// ---------------------------------------------------------------------------
// Management family (US-313, US-314, US-315).
// ---------------------------------------------------------------------------

/** The enable/disable direction implied by the record's own server status. */
function managementEnableDirection(status: unknown): boolean | null {
  if (status === 'DISABLED') return true
  if (status === 'ACTIVE' || status === 'EXTERNAL_ONLY') return false
  return null
}

/** The one sendable judgment: the management actions ``TRACKING_WRITE_ACTIONS`` declares. */
export function isSendableManagementAction(value: string): value is TrackingManagementActionCode {
  return isOperationOfFamily('MANAGEMENT', value)
}

/**
 * The target scopes this page may request for one projected management action.
 *
 * This is the same intersection ``executableTrackingActions`` already applied,
 * narrowed to a requested scope: a scope is requestable only when the server
 * offered it *and* the live session proves the matching capability.  An unknown
 * action, style or scope therefore never yields a requestable scope — the page
 * can use this to re-validate an emitted request instead of trusting the emit.
 */
export function projectTrackingActionScopes(
  item: TrackingItem,
  actionCode: TrackingActionCode,
  targetScope: TrackingScope,
): TrackingManagementScope[] {
  if (!isTrackingManagementScope(targetScope)) return []
  const requested = executableTrackingActions(item)
    .filter((candidate) => candidate.code === actionCode)
    .flatMap((candidate) => candidate.target_scopes ?? [])
    .filter((scope): scope is TrackingManagementScope => scope === targetScope)
  return requested.length === 1 ? requested : []
}

interface TrackingManagementIntentBase {
  readonly expectedRevision: number
  readonly confirm: true
  readonly idempotencyKey: string
}

/**
 * One validated management request.
 *
 * The union is discriminated by the action code, so the compiler — not a
 * runtime check — guarantees that only a ``MODIFY`` intent carries a patch, that
 * only a ``SET_ENABLED`` intent carries a direction, and that a ``REFRESH_RSS``
 * intent can only ever target the current record's associated RSS.
 */
type TrackingManagementIntent =
  | (TrackingManagementIntentBase & {
      readonly action: 'MODIFY'
      readonly targetScope: TrackingManagementScope
      readonly patch: TrackingSubscriptionPatch | TrackingRssPatch
      /** Local plan values the server raises only after a confirmed write. */
      readonly localPlan?: TrackingSubscriptionPatch | null
      readonly enabled: null
    })
  | (TrackingManagementIntentBase & {
      readonly action: 'SET_ENABLED'
      readonly targetScope: TrackingManagementScope
      readonly patch: null
      readonly enabled: boolean
    })
  | (TrackingManagementIntentBase & {
      readonly action: 'REFRESH_RSS'
      readonly targetScope: 'ASSOCIATED_RSS'
      readonly patch: null
      readonly enabled: null
    })
  | (TrackingManagementIntentBase & {
      readonly action: 'DELETE_EXTERNAL'
      readonly targetScope: TrackingManagementScope
      readonly patch: null
      readonly enabled: null
    })

function validRevision(item: TrackingItem): boolean {
  return Number.isInteger(item.revision) && item.revision >= 1
}

/**
 * Validate one modify action against the current server-observed record.
 *
 * The action and the scope must both be projected by ``available_actions`` for
 * the record's current status and the live session's capability, and the patch
 * must be a well-formed, non-empty patch for that very scope.  A stale or
 * hand-made combination therefore never becomes a request.
 */
function createTrackingModifyIntent(
  item: TrackingItem,
  action: TrackingManagementActionCode,
  targetScope: TrackingManagementScope,
  patch: unknown,
  localPlan?: unknown,
): TrackingManagementIntent | null {
  if (action !== 'MODIFY') return null
  if (!validRevision(item) || !managementPatchPresent(targetScope, patch)) return null
  // The page re-checks the server projection itself instead of trusting the
  // emit: the action must still be offered for this record's current revision
  // and the live session must still prove the capability for this very scope.
  if (!projectTrackingActionScopes(item, action, targetScope).length) return null
  return {
    action: 'MODIFY',
    targetScope,
    ...(localPlan && Object.keys(localPlan as object).length
      ? { localPlan: localPlan as TrackingSubscriptionPatch }
      : {}),
    patch: patch as TrackingSubscriptionPatch | TrackingRssPatch,
    enabled: null,
    expectedRevision: item.revision,
    confirm: true,
    idempotencyKey: makeOpaqueKey(),
  }
}

/**
 * Validate one enable/disable against the record's own server status.
 *
 * The direction is never taken from the emit: it is derived from the status the
 * server just returned, and only the three statuses that name a direction yield
 * one.  An unknown status therefore fails closed instead of guessing whether the
 * user meant "启用" or "停用".
 */
function createTrackingSetEnabledIntent(
  item: TrackingItem,
  targetScope: TrackingManagementScope,
): TrackingManagementIntent | null {
  if (!validRevision(item)) return null
  const enabled = managementEnableDirection(item.status)
  if (enabled === null) return null
  if (!projectTrackingActionScopes(item, 'SET_ENABLED', targetScope).length) return null
  return {
    action: 'SET_ENABLED',
    targetScope,
    patch: null,
    enabled,
    expectedRevision: item.revision,
    confirm: true,
    idempotencyKey: makeOpaqueKey(),
  }
}

/**
 * Validate one associated-RSS refresh.
 *
 * The scope is not a parameter: a refresh can only ever address the current
 * tracking record's own associated RSS (the server refuses any other scope, and
 * there is no global refresh route to fall back to).
 */
function createTrackingRefreshRssIntent(item: TrackingItem): TrackingManagementIntent | null {
  if (!validRevision(item)) return null
  if (!projectTrackingActionScopes(item, 'REFRESH_RSS', 'ASSOCIATED_RSS').length) return null
  return {
    action: 'REFRESH_RSS',
    targetScope: 'ASSOCIATED_RSS',
    patch: null,
    enabled: null,
    expectedRevision: item.revision,
    confirm: true,
    idempotencyKey: makeOpaqueKey(),
  }
}

/**
 * Validate one per-record external delete against the server's own projection.
 *
 * The scope is the user's explicit choice (which external object disappears) and
 * is re-validated here: the server must still offer ``DELETE_EXTERNAL`` for that
 * very scope at this revision and the live session must still prove the matching
 * delete capability, so neither a stale form nor a hand-made request can become
 * a delete.  There is no patch and no direction: a delete removes one object.
 */
function createTrackingDeleteExternalIntent(
  item: TrackingItem,
  targetScope: TrackingManagementScope,
): TrackingManagementIntent | null {
  if (!validRevision(item)) return null
  if (!projectTrackingActionScopes(item, 'DELETE_EXTERNAL', targetScope).length) return null
  return {
    action: 'DELETE_EXTERNAL',
    targetScope,
    patch: null,
    enabled: null,
    expectedRevision: item.revision,
    confirm: true,
    idempotencyKey: makeOpaqueKey(),
  }
}

/**
 * Build one intent for whichever management action the user requested.
 *
 * This is the page's single entry point: an action the page does not send yields
 * ``null`` rather than a request, so an action code without a builder below can
 * never leave the page however the server projects it.
 */
function createTrackingManagementActionIntent(
  item: TrackingItem,
  action: TrackingManagementActionCode,
  targetScope: TrackingManagementScope,
  patch: unknown,
  localPlan?: unknown,
): TrackingManagementIntent | null {
  if (action === 'MODIFY') return createTrackingModifyIntent(item, action, targetScope, patch, localPlan)
  if (action === 'SET_ENABLED') return createTrackingSetEnabledIntent(item, targetScope)
  if (action === 'REFRESH_RSS') return createTrackingRefreshRssIntent(item)
  if (action === 'DELETE_EXTERNAL') return createTrackingDeleteExternalIntent(item, targetScope)
  return null
}

/**
 * True when two intents describe the very same management request.
 *
 * ``expectedRevision`` and the opaque key are deliberately **not** compared: a
 * locked intent keeps its own revision binding, so an explicit transport retry
 * must replay the whole locked intent (the server judges a replay by
 * key + revision and rejects a same-key/different-binding request).
 */
function sameManagementRequest(
  left: TrackingManagementIntent,
  right: TrackingManagementIntent,
): boolean {
  return left.action === right.action
    && left.targetScope === right.targetScope
    && left.enabled === right.enabled
    && JSON.stringify(left.patch) === JSON.stringify(right.patch)
}

/**
 * Build the one request body for a validated management intent.
 *
 * The body is assembled in exactly one place and the action decides the shape,
 * so a subscription patch can never be sent to the enable route, a scope can
 * never be sent to the refresh route, and the body shape itself cannot express
 * an external id, URL, raw response or free-text note.
 */
function createTrackingManagementBody(
  intent: TrackingManagementIntent,
  connection: SavedConnectionGeneration | null | undefined,
  storageDir?: string,
): TrackingModifyBody | TrackingSetEnabledBody | TrackingRefreshRssBody | TrackingDeleteExternalBody | null {
  if (!connection || !connection.connection_ref || connection.configuration_revision === undefined) return null
  const common = {
    expected_revision: intent.expectedRevision,
    idempotency_key: intent.idempotencyKey,
    confirm: true as const,
    connection_ref: connection.connection_ref,
    configuration_revision: connection.configuration_revision,
    ...(storageDir ? { storage_dir: storageDir } : {}),
  }
  if (intent.action === 'SET_ENABLED') {
    return { ...common, target_scope: intent.targetScope, enabled: intent.enabled }
  }
  if (intent.action === 'REFRESH_RSS') {
    return { ...common, target_scope: 'ASSOCIATED_RSS' }
  }
  if (intent.action === 'DELETE_EXTERNAL') {
    // The generated shape has no ``file`` field at all, so this body can only
    // ever ask Auto Bangumi to drop the external object.
    return { ...common, target_scope: intent.targetScope }
  }
  if (intent.targetScope === 'SUBSCRIPTION') {
    if (!managementPatchPresent('SUBSCRIPTION', intent.patch)) return null
    const localPlan = intent.localPlan
    return {
      ...common,
      target_scope: 'SUBSCRIPTION',
      patch: intent.patch as TrackingSubscriptionPatch,
      ...(localPlan && Object.keys(localPlan).length ? { local_plan: localPlan } : {}),
    }
  }
  if (!managementPatchPresent('ASSOCIATED_RSS', intent.patch)) return null
  return { ...common, target_scope: 'ASSOCIATED_RSS', patch: intent.patch as TrackingRssPatch }
}

const MANAGEMENT_STATUSES = [
  'PREPARED', 'IN_PROGRESS', 'SUCCEEDED', 'FAILED', 'OUTCOME_UNKNOWN', 'RECOVERY_REQUIRED',
] as const

type TrackingManagementStatus = (typeof MANAGEMENT_STATUSES)[number]

const KNOWN_MANAGEMENT_STATUSES = new Set<string>(MANAGEMENT_STATUSES)

function isManagementStatus(value: unknown): value is TrackingManagementStatus {
  return typeof value === 'string' && KNOWN_MANAGEMENT_STATUSES.has(value)
}

/**
 * Every 409 a management endpoint can raise (US-225) happens before the
 * external boundary: the management operation is refused while it is being
 * prepared, so Auto Bangumi was never called with it.  An unrecognized type
 * falls back to generic copy that also claims exactly that.
 */
const MANAGEMENT_CONFLICT_TYPES = [
  'tracking_revision_conflict', 'tracking_idempotency_conflict',
  'tracking_management_state_conflict', 'tracking_management_patch_invalid',
  'tracking_target_missing', 'tracking_target_drift', 'tracking_target_ambiguous',
  'tracking_mapping_missing',
] as const

const MANAGEMENT_CONFLICT_MESSAGES: Record<(typeof MANAGEMENT_CONFLICT_TYPES)[number], string> = {
  tracking_revision_conflict:
    '追番记录已变化，本次未提交到 Auto Bangumi；正在刷新最新详情，请重新确认。',
  tracking_idempotency_conflict:
    '本次管理请求标识已失效，未提交到 Auto Bangumi；正在刷新最新详情，请重新确认。',
  tracking_management_state_conflict:
    '存在尚未完成的管理操作，本次未提交到 Auto Bangumi；正在刷新最新详情，请先完成恢复。',
  tracking_management_patch_invalid:
    '本次修改内容未通过服务端校验，未提交到 Auto Bangumi；正在刷新最新详情，请重新确认后再修改。',
  tracking_target_missing:
    '该记录当前没有对应的外部对象，本次未提交到 Auto Bangumi；正在刷新最新详情。',
  tracking_target_drift:
    '外部对象已变化，本次未提交到 Auto Bangumi；正在刷新最新详情，请重新确认。',
  tracking_target_ambiguous:
    '匹配到多个外部对象，本次未提交到 Auto Bangumi；正在刷新最新详情，请重新确认。',
  tracking_mapping_missing:
    '该记录缺少外部关联信息，本次未提交到 Auto Bangumi；正在刷新最新详情。',
}

/**
 * The few conflicts whose next step names the request itself (US-314).
 *
 * Every other management conflict is action-agnostic (revision/idempotency/
 * state/target), so only the validation conflict gets per-action copy — it is
 * the one whose wording would otherwise describe an enable or a refresh as a
 * "修改".
 */
const MANAGEMENT_CONFLICT_ACTION_MESSAGES: Partial<
  Record<TrackingManagementActionCode, Partial<Record<(typeof MANAGEMENT_CONFLICT_TYPES)[number], string>>>
> = {
  SET_ENABLED: {
    tracking_management_patch_invalid:
      '本次启停请求未通过服务端校验，未提交到 Auto Bangumi；正在刷新最新详情，请重新确认。',
  },
  REFRESH_RSS: {
    tracking_management_patch_invalid:
      '本次刷新请求未通过服务端校验，未提交到 Auto Bangumi；正在刷新最新详情，请重新确认。',
  },
  DELETE_EXTERNAL: {
    // The one delete conflict whose generic wording would misdescribe it: the
    // target the user chose simply does not exist any more, so nothing was
    // deleted and there is nothing to re-confirm.
    tracking_target_missing:
      '该记录当前没有对应的外部对象，本次未删除任何外部对象；正在刷新最新详情。',
  },
}

/** Fixed next step for one documented management conflict; unknown types fail closed. */
function managementConflictMessage(
  errorType: unknown,
  action?: TrackingManagementActionCode,
): string {
  if (typeof errorType !== 'string' || !(MANAGEMENT_CONFLICT_TYPES as readonly string[]).includes(errorType)) {
    return MANAGEMENT_ACTION_SPECS.MODIFY.messages.CONFLICT
  }
  const conflict = errorType as (typeof MANAGEMENT_CONFLICT_TYPES)[number]
  return (action && MANAGEMENT_CONFLICT_ACTION_MESSAGES[action]?.[conflict])
    ?? MANAGEMENT_CONFLICT_MESSAGES[conflict]
}

/**
 * Fixed copy for a management request the page itself refuses to build.
 *
 * ``createTrackingManagementBody`` returns ``null`` when an intent cannot be
 * turned into a safe request.  That is a definite page-side refusal — nothing
 * was sent — so it must converge on a decided state instead of leaving the
 * panel on ``IN_FLIGHT`` ("正在提交外部修改，请稍候…") forever.
 */
const MANAGEMENT_UNBUILDABLE_MESSAGE =
  '本次管理请求缺少可安全发送的必要信息，未向 Auto Bangumi 发送任何请求；已重新读取最新详情，请重新确认后再试。'

const MODIFY_SCOPE_CONFIRMATIONS = {
  SUBSCRIPTION: {
    title: '修改 Auto Bangumi 番剧订阅',
    message: '将在 Auto Bangumi 中修改该追番的外部番剧订阅，并可能改变后续下载；只影响 Auto Bangumi 外部订阅，不修改 MiGuOrca 本地方案。是否继续？',
    confirmLabel: '确认修改订阅',
  },
  ASSOCIATED_RSS: {
    title: '修改 Auto Bangumi 关联 RSS',
    message: '将在 Auto Bangumi 中修改该追番的关联 RSS，只影响 Auto Bangumi 外部 RSS，不修改 MiGuOrca 本地方案。是否继续？',
    confirmLabel: '确认修改 RSS',
  },
} as const satisfies Record<TrackingManagementScope, TrackingWriteConfirmation>

type EnableDirection = 'enable' | 'disable'

/**
 * Enable/disable copy, per scope and per direction.
 *
 * The record's own status decides the direction, and each direction names what
 * it does to future downloads, so an "启用" confirmation can never be shown for
 * a request that disables.
 */
const SET_ENABLED_CONFIRMATIONS = {
  SUBSCRIPTION: {
    enable: {
      title: '启用 Auto Bangumi 番剧订阅',
      message: '将在 Auto Bangumi 中启用该追番的外部番剧订阅，之后可能恢复或触发下载；只影响 Auto Bangumi 外部订阅，不修改 MiGuOrca 本地方案。是否继续？',
      confirmLabel: '确认启用订阅',
    },
    disable: {
      title: '停用 Auto Bangumi 番剧订阅',
      message: '将在 Auto Bangumi 中停用该追番的外部番剧订阅，之后不再按该订阅下载；只影响 Auto Bangumi 外部订阅，不修改 MiGuOrca 本地方案。是否继续？',
      confirmLabel: '确认停用订阅',
    },
  },
  ASSOCIATED_RSS: {
    enable: {
      title: '启用 Auto Bangumi 关联 RSS',
      message: '将在 Auto Bangumi 中启用该追番的关联 RSS，之后可能恢复或触发下载；只影响 Auto Bangumi 外部 RSS，不修改 MiGuOrca 本地方案。是否继续？',
      confirmLabel: '确认启用 RSS',
    },
    disable: {
      title: '停用 Auto Bangumi 关联 RSS',
      message: '将在 Auto Bangumi 中停用该追番的关联 RSS，之后不再按该 RSS 下载；只影响 Auto Bangumi 外部 RSS，不修改 MiGuOrca 本地方案。是否继续？',
      confirmLabel: '确认停用 RSS',
    },
  },
} as const satisfies Record<TrackingManagementScope, Record<EnableDirection, TrackingWriteConfirmation>>

/**
 * The external delete confirmation (US-315).
 *
 * It is the only danger-styled management dialog, and it names every local
 * record that survives: the request has no ``file`` field, so the delete can only
 * remove the external object and never the downloaded media.  ``danger`` makes
 * the dialog announce and style the confirm button as destructive.
 */
const DELETE_EXTERNAL_CONFIRMATION: TrackingWriteConfirmation = {
  title: '删除 Auto Bangumi 外部对象',
  message: '将在 Auto Bangumi 中删除该追番对应的外部对象；只影响 Auto Bangumi 外部对象，MiGuOrca 本地订阅方案、追番记录、审计记录、下载任务和已下载媒体文件都会保留，本操作也不会删除任何媒体文件。是否继续？',
  confirmLabel: '确认删除外部对象',
  danger: true,
}

/**
 * The refresh confirmation says explicitly that only this record's own RSS is
 * refreshed: there is no global refresh behind this button.
 */
const REFRESH_RSS_CONFIRMATION: TrackingWriteConfirmation = {
  title: '刷新 Auto Bangumi 关联 RSS',
  message: '将让 Auto Bangumi 重新拉取该追番当前关联的 RSS 内容；只刷新当前追番的关联 RSS，不会刷新全局 RSS，也不修改 MiGuOrca 本地方案。是否继续？',
  confirmLabel: '确认立即刷新资源',
}

/**
 * One management action's whole family wiring, declared once (issue #193).
 *
 * Every management action must state exactly what it did or did not do, so the
 * copy is bound to the action code the page sent rather than shared: an RSS
 * refresh never claims a subscription was changed, and an enable/disable never
 * claims a field was modified.  Each action's six-state message table and the
 * impact confirmation it may be sent under live in the same entry, so a new
 * action declares its copy and its confirmation in one place instead of two
 * parallel tables (the four scope/direction confirmation tables above are this
 * entry's own building blocks).
 *
 * The confirmation is resolved from the validated intent, so it always
 * describes the action, the scope and (for enable/disable) the direction that is
 * actually about to be sent — never one the user did not choose.
 */
const MANAGEMENT_ACTION_SPECS = {
  MODIFY: {
    messages: {
      IN_FLIGHT: '正在提交外部修改，请稍候…',
      SUCCEEDED: '外部修改已完成：Auto Bangumi 已应用本次修改。',
      FAILED: '外部修改明确失败，Auto Bangumi 未应用本次修改；可核对后重新发起。',
      CONFLICT: '追番记录已变化或当前状态不允许本次管理操作，本次未提交到 Auto Bangumi；正在刷新最新详情，请重新确认。',
      REJECTED: '服务端明确拒绝了本次管理请求，本次未修改 Auto Bangumi 外部订阅；正在刷新最新详情，请重新确认。',
      UNKNOWN: '外部修改结果待确认，正在只读回查；未确认生效前不会自动重试。',
    },
    confirmation: (intent: TrackingManagementIntent): TrackingWriteConfirmation =>
      MODIFY_SCOPE_CONFIRMATIONS[intent.targetScope],
  },
  SET_ENABLED: {
    messages: {
      IN_FLIGHT: '正在提交外部启停，请稍候…',
      SUCCEEDED: '外部启停已完成：Auto Bangumi 已应用本次启用或停用。',
      FAILED: '外部启停明确失败，Auto Bangumi 未应用本次启用或停用；可核对后重新发起。',
      CONFLICT: '追番记录已变化或当前状态不允许本次启停，本次未提交到 Auto Bangumi；正在刷新最新详情，请重新确认。',
      REJECTED: '服务端明确拒绝了本次启停请求，本次未改变 Auto Bangumi 的启用状态；正在刷新最新详情，请重新确认。',
      UNKNOWN: '外部启停结果待确认，正在只读回查；未确认生效前不会自动重试。',
    },
    confirmation: (intent: TrackingManagementIntent): TrackingWriteConfirmation =>
      SET_ENABLED_CONFIRMATIONS[intent.targetScope][intent.enabled ? 'enable' : 'disable'],
  },
  REFRESH_RSS: {
    messages: {
      IN_FLIGHT: '正在请求立即刷新资源，请稍候…',
      SUCCEEDED: '关联 RSS 刷新已完成：Auto Bangumi 已接受本次刷新请求。',
      FAILED: '关联 RSS 刷新明确失败，Auto Bangumi 未接受本次刷新；可核对后重新发起。',
      CONFLICT: '追番记录已变化或当前状态不允许立即刷新资源，本次未提交到 Auto Bangumi；正在刷新最新详情，请重新确认。',
      REJECTED: '服务端明确拒绝了本次刷新请求，本次未刷新 Auto Bangumi 关联 RSS；正在刷新最新详情，请重新确认。',
      UNKNOWN: '关联 RSS 刷新结果待确认，正在只读回查；未确认完成前不会自动重试。',
    },
    confirmation: (): TrackingWriteConfirmation => REFRESH_RSS_CONFIRMATION,
  },
  DELETE_EXTERNAL: {
    messages: {
      IN_FLIGHT: '正在提交外部删除，请稍候…',
      SUCCEEDED: '外部删除已完成：Auto Bangumi 已删除该外部对象；MiGuOrca 本地订阅方案、追番记录、审计记录、下载任务和已下载媒体文件均保留。',
      FAILED: '外部删除明确失败，Auto Bangumi 未删除该外部对象；本地方案与已下载媒体未受影响，可核对后重新发起。',
      CONFLICT: '追番记录已变化或当前状态不允许本次删除，本次未提交到 Auto Bangumi；正在刷新最新详情，请重新确认。',
      REJECTED: '服务端明确拒绝了本次删除请求，本次未删除 Auto Bangumi 外部对象；正在刷新最新详情，请重新确认。',
      UNKNOWN: '外部删除结果待确认，正在只读回查；未确认删除前不会自动重试，本地方案与已下载媒体未受影响。',
    },
    confirmation: (): TrackingWriteConfirmation => DELETE_EXTERNAL_CONFIRMATION,
  },
} as const satisfies Record<TrackingManagementActionCode, {
  readonly messages: Record<ManagementWriteState, string>
  readonly confirmation: (intent: TrackingManagementIntent) => TrackingWriteConfirmation
}>

/** The one fixed message for one management action and state. */
function managementActionMessage(
  action: TrackingManagementActionCode,
  state: ManagementWriteState,
): string {
  return MANAGEMENT_ACTION_SPECS[action].messages[state]
}

/**
 * Impact confirmation for one validated management intent, from the action's own
 * declaration above.
 */
function managementConfirmation(intent: TrackingManagementIntent): TrackingWriteConfirmation {
  return MANAGEMENT_ACTION_SPECS[intent.action].confirmation(intent)
}

/** Shown whenever a management result needs a human verdict before continuing. */
const MANAGEMENT_NEEDS_MANUAL_NOTICE =
  '需要人工核验：请先在 Auto Bangumi 中独立核对该追番的实际状态，再决定是否重新发起修改；本页不会代替你判断，也不会自动重试。'

// ---------------------------------------------------------------------------
// Session construction: one model, one message source.
// ---------------------------------------------------------------------------

interface SessionFields {
  readonly trackingId: string
  readonly operation: TrackingWriteOperation
  readonly targetScope: TrackingManagementScope | null
  readonly state: TrackingWriteState
  readonly message: string
  readonly issues: readonly TrackingRevalidateIssueView[]
  readonly failureCategory: WriteFailureCategory | null
  readonly diagnostics: TrackingWriteDiagnostics
  readonly needsManual: boolean
}

const NO_DIAGNOSTICS: TrackingWriteDiagnostics = { httpStatus: null, messageZh: null, messageEn: null }

function makeSession(fields: SessionFields): TrackingWriteSession {
  const family = operationFamily(fields.operation)
  return {
    ...fields,
    family,
    manualNotice: fields.needsManual
      ? (family === 'RECOVERY' ? RECOVERY_NEEDS_MANUAL_NOTICE : MANAGEMENT_NEEDS_MANUAL_NOTICE)
      : null,
    keepsIntent: keepsIntent(fields.state),
  }
}

/**
 * The one submit-family session.
 *
 * A published failure class owns the copy for its own channel; otherwise the
 * fixed per-state sentence stays authoritative.  A one-time attempt has no
 * external subscription to reason about, so its failure copy is the plain
 * retryable sentence (issue #101 AC 1) — which is why the one-time branch comes
 * first.
 */
function createSubmitSession(
  trackingId: string,
  action: TrackingWriteActionCode,
  state: SubmitWriteState,
  options: {
    issues?: readonly TrackingRevalidateIssueView[]
    failureCategory?: WriteFailureCategory | null
    submissionMode?: TrackingSubmissionMode | null
    diagnostics?: TrackingWriteDiagnostics
    /** The conflict's own fixed next step, when one was published. */
    message?: string
  } = {},
): TrackingWriteSession {
  const failureCategory = options.failureCategory ?? null
  const message = options.message ?? (
    state === 'SUBMIT_FAILED' && options.submissionMode === 'DOWNLOAD_EXISTING'
      ? ONE_TIME_SUBMIT_FAILED_MESSAGE
      : failureCategory
        ? WRITE_FAILURE_PRESENTATIONS[failureCategory].message
        : SUBMIT_MESSAGES[state]
  )
  return makeSession({
    trackingId,
    operation: action,
    targetScope: null,
    state,
    message,
    issues: options.issues ?? [],
    failureCategory,
    diagnostics: options.diagnostics ?? NO_DIAGNOSTICS,
    needsManual: false,
  })
}

/**
 * A 409 refuses the request before the external boundary, so this session is
 * released immediately (``keepsIntent === false``) and the page re-reads the
 * server tracking before asking for a new confirmation.
 */
function createSubmitConflictSession(
  trackingId: string,
  action: TrackingWriteActionCode,
  errorType: unknown,
): TrackingWriteSession {
  return createSubmitSession(trackingId, action, 'CONFLICT', { message: writeConflictMessage(errorType) })
}

function createRecoverySession(
  trackingId: string,
  action: TrackingRecoveryActionCode,
  state: RecoveryWriteState,
  needsManual = false,
): TrackingWriteSession {
  return makeSession({
    trackingId,
    operation: action,
    targetScope: null,
    state,
    message: RECOVERY_MESSAGES[state],
    issues: [],
    failureCategory: null,
    diagnostics: NO_DIAGNOSTICS,
    needsManual,
  })
}

/** A 409 refuses the recovery before anything is persisted; ask again. */
function createRecoveryConflictSession(
  trackingId: string,
  action: TrackingRecoveryActionCode,
): TrackingWriteSession {
  return createRecoverySession(trackingId, action, 'CONFLICT')
}

/**
 * The server's own flag wins; when it is missing an unresolved state is still
 * treated as requiring a human verdict rather than being read as decided.
 */
function managementNeedsManual(state: ManagementWriteState, serverFlag: unknown): boolean {
  if (state === 'SUCCEEDED' || state === 'FAILED' || state === 'CONFLICT' || state === 'REJECTED') {
    return false
  }
  return serverFlag === undefined ? true : serverFlag === true
}

/**
 * Create one management write session.
 *
 * ``message`` is always built from the fixed table unless a caller passes a
 * conflict's own next step, so the raw server enum and the server's
 * ``safe_message`` never reach the DOM.  ``needsManual`` means the external
 * result cannot be concluded without a human verdict, and it always keeps the
 * page's single intent (D38-09.4).
 */
function createManagementSession(
  trackingId: string,
  action: TrackingManagementActionCode,
  targetScope: TrackingManagementScope,
  state: ManagementWriteState,
  needsManual = false,
  message?: string,
): TrackingWriteSession {
  return makeSession({
    trackingId,
    operation: action,
    targetScope,
    state,
    message: message ?? managementActionMessage(action, state),
    issues: [],
    failureCategory: null,
    diagnostics: NO_DIAGNOSTICS,
    needsManual,
  })
}

/**
 * Project one HTTP 200 submit-family result. An outcome we do not recognize is
 * treated exactly like an unreadable transport result: read back, never
 * resubmit blind.
 */
function projectSubmitOutcome(
  trackingId: string,
  action: TrackingWriteActionCode,
  result: TrackingWriteResult | TrackingResubmitResult,
  submissionMode: TrackingSubmissionMode | null,
): TrackingWriteSession {
  const outcome: SubmitWriteState = isSubmitOutcome(result.outcome) ? result.outcome : 'UNKNOWN'
  return createSubmitSession(trackingId, action, outcome, {
    issues: projectRevalidateIssues(result.issues),
    failureCategory: writeFailureCategory(result.failure_category),
    submissionMode,
    diagnostics: projectWriteDiagnostics((result as { diagnostics?: unknown }).diagnostics),
  })
}

/**
 * Project one HTTP 200 recovery result.
 *
 * ``needs_manual`` is the server's own verdict that only a human conclusion can
 * progress, so it always keeps the recovery state — including a
 * ``RECOVERY_REQUIRED`` outcome that arrives without the flag. An outcome value
 * outside the documented enum stays indeterminate rather than being read as a
 * success.
 */
function isRecoveryOutcome(value: unknown): value is (typeof RECOVERY_OUTCOMES)[number] {
  return typeof value === 'string' && (RECOVERY_OUTCOMES as readonly string[]).includes(value)
}

function projectRecoveryOutcome(
  trackingId: string,
  action: TrackingRecoveryActionCode,
  result: TrackingRecoverResult,
): TrackingWriteSession {
  if (result.needs_manual === true) {
    return createRecoverySession(trackingId, action, 'RECOVERY_REQUIRED', true)
  }
  const outcome: unknown = result.outcome
  if (isRecoveryOutcome(outcome) && outcome !== 'RECOVERY_REQUIRED') {
    return createRecoverySession(trackingId, action, outcome)
  }
  if (outcome === 'RECOVERY_REQUIRED') {
    return createRecoverySession(trackingId, action, 'RECOVERY_REQUIRED', true)
  }
  return createRecoverySession(trackingId, action, 'UNKNOWN')
}

/**
 * Project one HTTP 200 management result.
 *
 * ``management_status`` is the server's own verdict and the only thing that may
 * be reported as success: ``SUCCEEDED``.  ``FAILED`` is a definite failure and
 * everything else — an in-flight status, a partial batch, an explicit
 * recovery-required verdict or an undocumented value — stays indeterminate, so
 * the page reads back and never claims the external change was applied.
 */
function projectManagementOutcome(
  trackingId: string,
  action: TrackingManagementActionCode,
  targetScope: TrackingManagementScope,
  result: TrackingManagementResult,
): TrackingWriteSession {
  const status: unknown = result.management_status
  if (isManagementStatus(status) && (status === 'SUCCEEDED' || status === 'FAILED')) {
    return createManagementSession(
      trackingId, action, targetScope, status, managementNeedsManual(status, result.needs_manual),
    )
  }
  return createManagementSession(trackingId, action, targetScope, 'UNKNOWN', true)
}

// ---------------------------------------------------------------------------
// Plan delete (issue #92) — one local delete, optionally with its external object.
// ---------------------------------------------------------------------------

export interface TrackingPlanDeleteSession {
  readonly trackingId: string
  readonly state: 'IN_FLIGHT' | 'DELETED' | 'EXTERNAL_FAILED' | 'EXTERNAL_UNKNOWN'
  readonly message: string
}

const PLAN_DELETE_ENDPOINT = '/api/v1/tracking/items/{tracking_id}/delete-plan' as const satisfies ApiPath

/**
 * ``DELETED`` is the only state where the local plan and its tracking record are
 * gone; the two external states mean nothing local was removed and the user must
 * retry or recover deliberately.
 */
const PLAN_DELETE_MESSAGES: Record<TrackingPlanDeleteSession['state'], string> = {
  IN_FLIGHT: '正在删除追番方案，请稍候…',
  DELETED: '追番方案已删除。',
  EXTERNAL_FAILED: 'Auto Bangumi 未删除该受控外部订阅，本地方案与追番记录均已保留；请核对后重试。',
  EXTERNAL_UNKNOWN: '外部删除结果待确认，本地方案与追番记录均已保留；请先恢复核验后再决定。',
}

function createPlanDeleteSession(
  trackingId: string,
  state: TrackingPlanDeleteSession['state'],
): TrackingPlanDeleteSession {
  return { trackingId, state, message: PLAN_DELETE_MESSAGES[state] }
}

// ---------------------------------------------------------------------------
// Explicit batch submit (issue #87) — one session for one confirmed batch.
// ---------------------------------------------------------------------------

interface TrackingBatchSelection {
  /** Selected tracking ids, in the order the user added them. */
  readonly selected: readonly string[]
  /** Selected-or-skipped ids with a fixed reason, for the batch notice. */
  readonly skipped: Readonly<Record<string, string>>
}

interface TrackingBatchEntry {
  readonly tracking_id: string
  readonly expected_revision: number
  readonly idempotency_key: string
}

interface TrackingBatchSubmitBody {
  readonly items: readonly TrackingBatchEntry[]
  readonly confirm: true
  readonly connection_ref: string
  readonly configuration_revision: number
  readonly storage_dir?: string
}

const EMPTY_BATCH_SELECTION: TrackingBatchSelection = { selected: [], skipped: {} }

/** The only server-projected actions a batch may carry. */
const BATCH_ACTIONS = new Set(['SUBMIT', 'RETRY'])

/**
 * Fixed reason this row cannot join a batch right now, or ``null`` when it can.
 * Unknown/processing states fail closed: they are never silently submitted.
 */
function batchSkipReason(item: TrackingItem): string | null {
  if (item.status_group === 'PROCESSING') return '正在处理中，请等待当前操作完成'
  const actions = item.available_actions ?? []
  if (!actions.some((action) => BATCH_ACTIONS.has(String(action.code)))) {
    return '当前状态不可提交'
  }
  return null
}

interface SkippedBatchEntry {
  readonly trackingId: string
  readonly title: string
  /** Fixed safe reason from the local pre-check — never raw text. */
  readonly reason: string
}

/**
 * The selected plans this batch will not send (issue #100).
 *
 * The batch pre-check uses only the saved plan evidence the list already holds
 * (status + server-advertised actions); it never re-runs the server's state
 * machine and never contacts Auto Bangumi.
 */
function skippedBatchEntries(
  selection: TrackingBatchSelection,
  items: readonly TrackingItem[],
): SkippedBatchEntry[] {
  const byId = new Map(items.map((item) => [item.tracking_id, item]))
  const skipped: SkippedBatchEntry[] = []
  for (const trackingId of selection.selected) {
    const item = byId.get(trackingId)
    if (!item) {
      skipped.push({ trackingId, title: '未命名番剧', reason: '不在当前列表中，请刷新后重试' })
      continue
    }
    const reason = batchSkipReason(item)
    if (reason) skipped.push({ trackingId, title: item.title || '未命名番剧', reason })
  }
  return skipped
}

function isBatchSelected(selection: TrackingBatchSelection, trackingId: string): boolean {
  return selection.selected.includes(trackingId)
}

/** Add or remove one row; selection order is preserved. */
function toggleBatchSelection(
  selection: TrackingBatchSelection,
  trackingId: string,
): TrackingBatchSelection {
  if (isBatchSelected(selection, trackingId)) {
    return { ...selection, selected: selection.selected.filter((id) => id !== trackingId) }
  }
  return { ...selection, selected: [...selection.selected, trackingId] }
}

/**
 * Select every submittable row in the current result set, replacing the
 * selection. Non-submittable rows are recorded with their fixed reason so the
 * page can state exactly what was skipped and why.
 */
function selectAllBatch(items: readonly TrackingItem[]): TrackingBatchSelection {
  const selected: string[] = []
  const skipped: Record<string, string> = {}
  for (const item of items) {
    const reason = batchSkipReason(item)
    if (reason) skipped[item.tracking_id] = reason
    else selected.push(item.tracking_id)
  }
  return { selected, skipped }
}

interface TrackingBatchSelectionSummary {
  readonly selected: number
  /** Selected rows that the current filter/search hides. */
  readonly hidden: number
}

/**
 * Counts for the selection banner. Filtering never clears a selection, so the
 * page must always state how many selected rows are currently invisible.
 */
function batchSelectionSummary(
  selection: TrackingBatchSelection,
  visible: readonly TrackingItem[],
): TrackingBatchSelectionSummary {
  const visibleIds = new Set(visible.map((item) => item.tracking_id))
  return {
    selected: selection.selected.length,
    hidden: selection.selected.filter((id) => !visibleIds.has(id)).length,
  }
}

/**
 * Build the strict batch body from the current selection.
 *
 * Every entry binds the row's *current* revision and a fresh opaque key, so a
 * re-confirmation is a new operation while a transport retry must reuse the
 * locked body. A selection whose row disappeared (filtered away *and* deleted)
 * is dropped rather than silently sent with a stale revision.
 */
function buildBatchSubmitBody(
  selection: TrackingBatchSelection,
  items: readonly TrackingItem[],
  connection: { connection_ref: string; configuration_revision: number },
  storageDir?: string,
  submissionMode?: TrackingSubmissionMode,
): TrackingBatchSubmitBody | null {
  const byId = new Map(items.map((item) => [item.tracking_id, item]))
  const entries: TrackingBatchEntry[] = []
  for (const trackingId of selection.selected) {
    const item = byId.get(trackingId)
    if (!item) continue
    if (batchSkipReason(item)) continue
    if (!Number.isInteger(item.revision) || item.revision < 1) continue
    entries.push({
      tracking_id: item.tracking_id,
      expected_revision: item.revision,
      idempotency_key: makeOpaqueKey(),
    })
  }
  if (!entries.length) return null
  return {
    items: entries,
    confirm: true,
    // Issue #100: exactly one mode applies to every selected plan.
    ...(submissionMode ? { submission_mode: submissionMode } : {}),
    connection_ref: connection.connection_ref,
    configuration_revision: connection.configuration_revision,
    ...(storageDir ? { storage_dir: storageDir } : {}),
  }
}

interface TrackingBatchEntryOutcome {
  readonly trackingId: string
  readonly ok: boolean
  /** Published failure category of the entry's business result, when any. */
  readonly failureCategory: string | null
  /** Stable pre-boundary refusal code, when the entry never reached Auto Bangumi. */
  readonly errorType: string | null
  readonly message: string
}

interface TrackingBatchOutcome {
  readonly entries: readonly TrackingBatchEntryOutcome[]
  readonly succeeded: number
  readonly failed: number
  /** Entries still unresolved: they keep their selection and must be recovered. */
  readonly unresolved: readonly string[]
}

/**
 * Project one accepted batch response into per-entry outcomes.
 *
 * A succeeded entry leaves the selection; a failed or unresolved entry stays
 * selected so the user can act on it again. Unknown server values fail closed:
 * an unrecognized outcome is treated as unresolved, never as success.
 */
function projectBatchOutcome(result: {
  items?: readonly {
    tracking_id?: string
    ok?: boolean
    error_type?: string | null
    result?: { outcome?: string; failure_category?: string | null } | null
  }[]
}): TrackingBatchOutcome {
  const entries: TrackingBatchEntryOutcome[] = []
  const unresolved: string[] = []
  let succeeded = 0
  let failed = 0
  for (const item of result.items ?? []) {
    const trackingId = typeof item.tracking_id === 'string' ? item.tracking_id : ''
    if (!trackingId) continue
    const outcome = item.result?.outcome
    const isSuccess = item.ok === true && outcome === 'ACTIVE'
    if (isSuccess) {
      succeeded += 1
      entries.push({
        trackingId, ok: true, failureCategory: null, errorType: null,
        message: '提交成功：已在 Auto Bangumi 创建外部订阅。',
      })
      continue
    }
    const indeterminate = outcome === 'VERIFYING_EXTERNAL' || outcome === 'RECOVERY_REQUIRED' || !item.result
    if (indeterminate) {
      unresolved.push(trackingId)
      failed += 1
      entries.push({
        trackingId, ok: false,
        failureCategory: item.result?.failure_category ?? null,
        errorType: item.error_type ?? null,
        message: item.result
          ? '提交结果待确认，请先恢复核验；本次不会自动重发。'
          : '服务端在外部提交前拒绝了该条目，正在刷新最新详情，请重新确认。',
      })
      continue
    }
    failed += 1
    entries.push({
      trackingId, ok: false,
      failureCategory: item.result?.failure_category ?? null,
      errorType: item.error_type ?? null,
      message: '提交明确失败，尚未创建外部订阅。',
    })
  }
  return { entries, succeeded, failed, unresolved }
}

/** Keep only the entries that still need the user's attention. */
function selectionAfterBatch(
  selection: TrackingBatchSelection,
  outcome: TrackingBatchOutcome,
): TrackingBatchSelection {
  const done = new Set(outcome.entries.filter((entry) => entry.ok).map((entry) => entry.trackingId))
  return { ...selection, selected: selection.selected.filter((id) => !done.has(id)) }
}

const TRACKING_BATCH_SUBMIT_ENDPOINT = '/api/v1/tracking/batch-submit' as const satisfies ApiPath

// ---------------------------------------------------------------------------
// The session composable.
// ---------------------------------------------------------------------------

/** The transport that is currently in flight; one write runs at a time. */
type ActiveTransport =
  | { readonly family: 'SUBMIT'; readonly trackingId: string; readonly action: TrackingWriteActionCode; readonly mode: TrackingSubmissionMode | null }
  /**
   * One risk-confirmed resubmission: a submit-family outcome, one new operation.
   * It repeats a persistent submission, so its mode is always 持续追番.
   */
  | {
      readonly family: 'RESUBMIT'
      readonly trackingId: string
      readonly action: 'SUBMIT'
      readonly mode: TrackingSubmissionMode
    }
  | { readonly family: 'RECOVERY'; readonly trackingId: string; readonly action: TrackingRecoveryActionCode }
  | { readonly family: 'MANAGEMENT'; readonly trackingId: string; readonly action: TrackingManagementActionCode; readonly targetScope: TrackingManagementScope }

/**
 * The composable's own assembled surface (issue #193).
 *
 * It is deliberately *not* exported: its only consumer is the returned object of
 * ``useTrackingWriteSession()`` below, and the page consumes that value rather
 * than the type.  An exported interface with no producer-side consumer invites a
 * second, drifting description of the same surface — the one export the #168
 * review found unused.
 */
interface TrackingWriteSessionApi {
  // -- snapshots ------------------------------------------------------------
  /** The three panels' latest session, one per write family. */
  readonly sessions: ComputedRef<TrackingWriteSessionSet>
  /** True while a single-write transport is in flight. */
  readonly loading: Ref<boolean>
  /** True while an impact confirmation is open. */
  readonly pending: Ref<boolean>
  readonly planDelete: Ref<TrackingPlanDeleteSession | null>
  /** The page's bounded read-only check of a pending submission (issue #183). */
  readonly check: Ref<TrackingCheckSession | null>
  readonly checkLoading: Ref<boolean>
  /** True while the page still owes this item one automatic check (issue #183). */
  readonly autoCheckArmed: Ref<boolean>
  /**
   * Issue #184: the read-only phase of one risk-confirmed resubmission — the
   * proven reason, its refusal, or the exact binding a confirmation must echo.
   * It is its own slot like the check's; the confirmation itself then reports
   * through the ordinary submit session.
   */
  readonly resubmit: Ref<TrackingResubmitSession | null>
  readonly resubmitLoading: Ref<boolean>
  readonly batchSelection: Ref<TrackingBatchSelection>
  readonly batchOutcome: Ref<TrackingBatchOutcome | null>
  readonly batchLoading: Ref<boolean>
  readonly batchNotice: Ref<string>
  readonly batchSkippedNotice: ComputedRef<string>

  // -- lock queries (page-owned notices and disabled states) ----------------
  readonly hasUnresolvedLock: ComputedRef<boolean>
  /** The record whose still-unresolved intent refuses this request, or ''. */
  unresolvedOwner: (trackingId: string) => string
  /** The single page intent is in flight or spent on another record. */
  busyFor: (trackingId: string) => boolean
  /**
   * The fixed refusal notice shown on the selected record: the stored reason a
   * locked intent refused this record's request, the generic locked-intent
   * reason while another record owns it, or ''.
   */
  noticeFor: (trackingId: string) => string

  // -- session lifecycle ----------------------------------------------------
  /** Forget every session and intent (unmount / hard reset). */
  reset: () => void
  /**
   * The page session is being cleared.  An unresolved result survives as a
   * non-replayable tombstone (its key is never rebindable to a new connection);
   * a decided one is simply forgotten.
   */
  preserveAfterClear: () => void
  /** The page owns the impact dialog; it reports the dialog's open state here. */
  setPending: (pending: boolean) => void

  // -- submit family --------------------------------------------------------
  beginSubmit: (payload: TrackingWriteTarget, options?: TrackingWriteBeginOptions) => TrackingWriteStart
  /** Settles an ordinary submit/retry or the write phase of a resubmission (#184). */
  finishSubmit: (result: TrackingWriteResult | TrackingResubmitResult) => readonly TrackingWriteEffect[]
  failSubmit: (error: TrackingWriteError) => readonly TrackingWriteEffect[]
  /** The transport ended (successfully, with a failure, or dropped). */
  finishAttempt: () => void

  // -- recovery family ------------------------------------------------------
  beginRecovery: (
    payload: { readonly action: TrackingRecoveryActionCode; readonly item: TrackingItem },
    options?: TrackingWriteBeginOptions & { readonly capabilities?: CapabilityResult | null },
  ) => TrackingWriteStart
  finishRecovery: (result: TrackingRecoverResult) => readonly TrackingWriteEffect[]
  failRecovery: (error: TrackingWriteError) => readonly TrackingWriteEffect[]

  // -- management family ----------------------------------------------------
  beginManagement: (
    payload: {
      readonly action: TrackingAction
      readonly item: TrackingItem
      readonly targetScope: TrackingManagementScope
      readonly patch: unknown
      readonly localPlan?: unknown
    },
    options?: TrackingWriteBeginOptions,
  ) => TrackingWriteStart
  finishManagement: (result: TrackingManagementResult) => readonly TrackingWriteEffect[]
  failManagement: (error: TrackingWriteError) => readonly TrackingWriteEffect[]

  // -- unified plan delete --------------------------------------------------
  beginPlanDelete: (payload: {
    readonly item: TrackingItem
    readonly deleteExternal: boolean
  }, options?: TrackingWriteBeginOptions) => TrackingWriteStart
  finishPlanDelete: (result: TrackingPlanDeleteResult) => readonly TrackingWriteEffect[]
  failPlanDelete: (error: TrackingWriteError) => readonly TrackingWriteEffect[]
  resetPlanDelete: () => void

  // -- bounded read-only check (issue #183) ---------------------------------
  /**
   * Arm/disarm the one automatic read-only check a reopened 结果待确认
   * submission is owed.  A started check consumes the flag; a refused one
   * leaves it armed so it is retried instead of silently dropped.
   */
  setAutoCheck: (armed: boolean) => void
  beginCheck: (
    payload: { readonly item: TrackingItem; readonly automatic: boolean },
    options?: TrackingWriteBeginOptions,
  ) => TrackingWriteStart
  finishCheck: (result: TrackingCheckResult) => readonly TrackingWriteEffect[]
  failCheck: (error: TrackingWriteError) => readonly TrackingWriteEffect[]

  // -- risk-confirmed resubmission (issue #184) -----------------------------
  /**
   * Start the read-only phase, or replay the exact body of an unresolved earlier
   * confirmation of the same item (never a second operation for the same one).
   */
  beginResubmit: (
    payload: { readonly item: TrackingItem },
    options?: TrackingWriteBeginOptions,
  ) => TrackingWriteStart
  finishResubmitOffer: (result: TrackingResubmitResult) => readonly TrackingWriteEffect[]
  failResubmitOffer: (error: TrackingWriteError) => readonly TrackingWriteEffect[]
  /** The user cancelled the risk confirmation: no request and no new operation. */
  cancelResubmit: (trackingId: string) => void
  /** Send the one confirmation of the binding the read-only phase published. */
  beginResubmitConfirmation: (
    binding: TrackingResubmitBinding,
    options?: TrackingWriteBeginOptions,
  ) => TrackingWriteStart


  // -- batch submit ---------------------------------------------------------
  isBatchSelected: (trackingId: string) => boolean
  toggleBatchRow: (trackingId: string) => void
  selectAllBatch: (items: readonly TrackingItem[]) => void
  clearBatchSelection: () => void
  batchSkipReason: (item: TrackingItem) => string | null
  batchSummary: (visible: readonly TrackingItem[]) => TrackingBatchSelectionSummary
  resetBatch: () => void
  beginBatchSubmit: (
    payload: { readonly items: readonly TrackingItem[]; readonly mode: TrackingSubmissionMode | null },
    options?: TrackingWriteBeginOptions,
  ) => TrackingBatchStart
  finishBatchSubmit: (result: TrackingBatchResult) => readonly TrackingWriteEffect[]
  failBatchSubmit: (error: TrackingWriteError) => void
}

/**
 * The one mutable state of the page's single external write (issue #193).
 *
 * Everything the families below share lives here and nowhere else: the reactive
 * snapshots the page renders, the locked intents with their opaque keys and
 * connection generations, the one in-flight transport, and the queries/commands
 * that more than one family answers (the page-level lock model, the refusal
 * notice, the convergence effect, the hard reset).
 *
 * It is an implementation detail of this module: nothing outside the file names
 * it, so a family can only reach shared state through this one declaration
 * instead of closing over whatever happened to be in scope.
 */
interface TrackingWriteCore {
  // -- page-visible reactive state -----------------------------------------
  readonly sessions: ComputedRef<TrackingWriteSessionSet>
  readonly hasUnresolvedLock: ComputedRef<boolean>
  readonly batchSkippedNotice: ComputedRef<string>
  readonly submitSession: Ref<TrackingWriteSession | null>
  readonly recoverySession: Ref<TrackingWriteSession | null>
  readonly managementSession: Ref<TrackingWriteSession | null>
  readonly loading: Ref<boolean>
  readonly pending: Ref<boolean>
  readonly planDelete: Ref<TrackingPlanDeleteSession | null>
  readonly check: Ref<TrackingCheckSession | null>
  readonly checkLoading: Ref<boolean>
  readonly autoCheckArmed: Ref<boolean>
  readonly resubmit: Ref<TrackingResubmitSession | null>
  readonly resubmitLoading: Ref<boolean>
  readonly batchSelection: Ref<TrackingBatchSelection>
  readonly batchOutcome: Ref<TrackingBatchOutcome | null>
  readonly batchLoading: Ref<boolean>
  readonly batchNotice: Ref<string>
  readonly refusalNotice: Ref<{ readonly trackingId: string; readonly message: string } | null>

  // -- the one locked intent per family ------------------------------------
  submitIntent: TrackingWriteIntent | null
  resubmitIntent: TrackingResubmitIntent | null
  managementIntent: TrackingManagementIntent | null
  submitReplayBlocked: boolean
  managementReplayBlocked: boolean
  submitConfigSnapshot: TrackingWriteConfig | null
  managementConfigSnapshot: TrackingWriteConfig | null
  active: ActiveTransport | null
  planDeleteExternal: boolean
  checkAttempt: { readonly trackingId: string; readonly revision: number } | null
  resubmitAttempt: { readonly trackingId: string; readonly revision: number } | null

  // -- shared queries and commands -----------------------------------------
  readonly unresolvedOwner: (trackingId: string) => string
  readonly busyFor: (trackingId: string) => boolean
  readonly refuseAndStart: (
    trackingId: string,
    reason: TrackingWriteRefusal['reason'],
  ) => TrackingWriteStart
  readonly unbuildableStart: (trackingId: string) => TrackingWriteStart
  readonly noticeFor: (trackingId: string) => string
  readonly releaseSubmitIntent: () => void
  readonly releaseFor: (trackingId: string) => void
  readonly releaseSettledSubmission: (trackingId: string) => void
  readonly resetCheck: () => void
  readonly resetResubmit: () => void
  readonly reset: () => void
  readonly preserveAfterClear: () => void
  readonly setPending: (pending: boolean) => void
  readonly finishAttempt: () => void
  readonly recheck: (trackingId: string | null, refreshList: boolean) => TrackingWriteEffect
}

/**
 * Build the shared core, then hand it to one factory per family below.
 *
 * Issue #193: ``useTrackingWriteSession()`` is only the assembly point now.  It
 * used to be one ~1100-line function holding every family, which made "where
 * does a submit touch management state" a question you answered by reading the
 * whole thing.  Each family now takes a ``Pick`` of this core naming exactly the
 * state it may use, so the answer is its signature.
 */
function createTrackingWriteCore(): TrackingWriteCore {
  const submitSession = ref<TrackingWriteSession | null>(null)
  const recoverySession = ref<TrackingWriteSession | null>(null)
  const managementSession = ref<TrackingWriteSession | null>(null)
  const loading = ref(false)
  const pending = ref(false)
  const planDelete = ref<TrackingPlanDeleteSession | null>(null)
  const check = ref<TrackingCheckSession | null>(null)
  const checkLoading = ref(false)
  const autoCheckArmed = ref(false)
  /** Issue #184: the read-only phase of a risk-confirmed resubmission. */
  const resubmit = ref<TrackingResubmitSession | null>(null)
  const resubmitLoading = ref(false)
  const batchSelection = ref<TrackingBatchSelection>(EMPTY_BATCH_SELECTION)
  const batchOutcome = ref<TrackingBatchOutcome | null>(null)
  const batchLoading = ref(false)
  const batchNotice = ref('')
  /** The last fixed refusal reason, scoped to the record the user acted on. */
  const refusalNotice = ref<{ readonly trackingId: string; readonly message: string } | null>(null)

  const sessions = computed<TrackingWriteSessionSet>(() => ({
    submit: submitSession.value,
    recovery: recoverySession.value,
    management: managementSession.value,
  }))

  function currentSessions(): TrackingWriteSession[] {
    return [submitSession.value, recoverySession.value, managementSession.value]
      .filter((session): session is TrackingWriteSession => session !== null)
  }

  const hasUnresolvedLock = computed(() => (
    currentSessions().some((session) => session.keepsIntent)
  ))

  const batchSkippedNotice = computed(() => {
    const reasons = Object.values(batchSelection.value.skipped)
    if (!reasons.length) return ''
    const counts = new Map<string, number>()
    for (const reason of reasons) counts.set(reason, (counts.get(reason) ?? 0) + 1)
    const detail = [...counts].map(([reason, count]) => `${reason}（${count} 条）`).join('；')
    return `已跳过 ${reasons.length} 条不可提交记录：${detail}。`
  })


  // The locked intents and the connection generation each one was confirmed
  // with.  Only one write runs at a time, but the submit and management families
  // each keep their own tombstone so a clear can never rebind one family's
  // pending operation to another's connection.  They are the core's own fields
  // (and not closure variables) so a family factory can only reach them here.
  const core: TrackingWriteCore = {
    submitSession,
    recoverySession,
    managementSession,
    loading,
    pending,
    planDelete,
    check,
    checkLoading,
    autoCheckArmed,
    resubmit,
    resubmitLoading,
    batchSelection,
    batchOutcome,
    batchLoading,
    batchNotice,
    refusalNotice,
    sessions,
    hasUnresolvedLock,
    batchSkippedNotice,
    submitIntent: null,
    resubmitIntent: null,
    managementIntent: null,
    submitReplayBlocked: false,
    managementReplayBlocked: false,
    submitConfigSnapshot: null,
    managementConfigSnapshot: null,
    active: null,
    planDeleteExternal: false,
    checkAttempt: null,
    resubmitAttempt: null,
    unresolvedOwner,
    busyFor,
    refuseAndStart,
    unbuildableStart,
    noticeFor,
    releaseSubmitIntent,
    releaseFor,
    releaseSettledSubmission,
    resetCheck,
    resetResubmit,
    reset,
    preserveAfterClear,
    setPending,
    finishAttempt,
    recheck,
  }
  function unresolvedOwner(trackingId: string): string {
    for (const session of currentSessions()) {
      if (session.trackingId !== trackingId && session.keepsIntent) return session.trackingId
    }
    return ''
  }

  function busyFor(trackingId: string): boolean {
    if (loading.value) return true
    return currentSessions().some((session) => session.keepsIntent && session.trackingId !== trackingId)
  }

  /** State the fixed reason a locked intent refused a different request. */
  function refuse(trackingId: string, reason: TrackingWriteRefusal['reason']): void {
    refusalNotice.value = {
      trackingId,
      message: reason === 'REPLAY' ? REPLAY_BLOCKED_MESSAGE : INTENT_BLOCKED_MESSAGE,
    }
  }

  /** Refuse one command and state why on the record the user acted on. */
  function refuseAndStart(trackingId: string, reason: TrackingWriteRefusal['reason']): TrackingWriteStart {
    refuse(trackingId, reason)
    return refusedStart(trackingId, reason)
  }

  function noticeFor(trackingId: string): string {
    const notice = refusalNotice.value
    if (notice && notice.trackingId === trackingId) return notice.message
    return unresolvedOwner(trackingId) ? INTENT_BLOCKED_MESSAGE : ''
  }

  // A refusal notice only explains a still-pending intent: once every write,
  // recovery and management lock is released (a definite result, a 409, a 4xx
  // refusal, a manual recovery verdict or a cleared connection) it must vanish.
  watch(sessions, () => {
    if (refusalNotice.value && !hasUnresolvedLock.value) refusalNotice.value = null
  })

  /**
   * Spend the one submit-family intent.  A risk-confirmed resubmission keeps its
   * confirmation in the same slot, so a definite outcome releases both.
   */
  function releaseSubmitIntent(): void {
    core.submitIntent = null
    core.resubmitIntent = null
  }

  function resetResubmit(): void {
    core.resubmitAttempt = null
    resubmitLoading.value = false
    resubmit.value = null
  }

  function reset(): void {
    submitSession.value = null
    recoverySession.value = null
    managementSession.value = null
    planDelete.value = null
    resetCheck()
    resetResubmit()
    core.submitIntent = null
    core.resubmitIntent = null
    core.managementIntent = null
    core.submitReplayBlocked = false
    core.managementReplayBlocked = false
    core.submitConfigSnapshot = null
    core.managementConfigSnapshot = null
    core.active = null
    refusalNotice.value = null
    loading.value = false
    pending.value = false
  }

  /**
   * A cleared page session destroys the credentials while preserving unresolved
   * intents as non-replayable tombstones.  The server record stays authoritative
   * and can only be settled through read-only verification or recovery.
   */
  function preserveAfterClear(): void {
    pending.value = false
    loading.value = false
    core.active = null

    const submit = submitSession.value
    if (submit && (submit.state === 'IN_FLIGHT' || submit.keepsIntent) && (core.submitIntent || core.resubmitIntent)) {
      // A cleared connection never rebinds a locked intent to the new one: the
      // unresolved submit keeps its body as a non-replayable tombstone (issue
      // #184 keeps the resubmit confirmation under exactly the same rule).
      core.submitReplayBlocked = true
      core.submitConfigSnapshot = null
      submitSession.value = createSubmitSession(
        submit.trackingId, submit.operation as TrackingWriteActionCode, 'UNKNOWN',
      )
    } else {
      submitSession.value = null
      releaseSubmitIntent()
      core.submitReplayBlocked = false
      core.submitConfigSnapshot = null
    }
    resetResubmit()

    const recovery = recoverySession.value
    if (recovery && (recovery.state === 'IN_FLIGHT' || recovery.keepsIntent)) {
      recoverySession.value = createRecoverySession(
        recovery.trackingId, recovery.operation as TrackingRecoveryActionCode, 'UNKNOWN',
      )
      // Issue #183: the same clear invalidates the read-only check this page
      // owed (its result would describe a connection that is gone).
      resetCheck()
    } else {
      recoverySession.value = null
    }

    const management = managementSession.value
    if (management && (management.state === 'IN_FLIGHT' || management.keepsIntent) && core.managementIntent) {
      core.managementReplayBlocked = true
      core.managementConfigSnapshot = null
      managementSession.value = createManagementSession(
        management.trackingId,
        management.operation as TrackingManagementActionCode,
        management.targetScope ?? 'SUBSCRIPTION',
        'UNKNOWN',
        true,
      )
    } else {
      managementSession.value = null
      core.managementIntent = null
      core.managementReplayBlocked = false
      core.managementConfigSnapshot = null
    }
  }

  /** A clear/reconnect never releases an old write; only a confirmed recovery does. */
  function releaseFor(trackingId: string): void {
    const submit = submitSession.value
    if (submit?.trackingId === trackingId && submit.keepsIntent) {
      submitSession.value = null
      releaseSubmitIntent()
      core.submitReplayBlocked = false
      core.submitConfigSnapshot = null
    }
    const management = managementSession.value
    if (management?.trackingId === trackingId && management.keepsIntent) {
      managementSession.value = null
      core.managementIntent = null
      core.managementReplayBlocked = false
      core.managementConfigSnapshot = null
    }
  }

  function finishAttempt(): void {
    loading.value = false
  }

  function recheck(trackingId: string | null, refreshList: boolean): TrackingWriteEffect {
    return { kind: 'recheck', trackingId, refreshList }
  }

  /**
   * Refuse one command whose request the page session can no longer build, and
   * converge on the server.
   *
   * Issue #193: the three families reach the same *precondition* — an action
   * whose declared credential (the locked intent's saved generation, or the
   * generation a read-only ``VERIFY_EXTERNAL`` spends) is no longer on the page —
   * and none of them may answer it with a silent no-op, which is exactly what
   * ``beginRecovery`` used to do: a dead button with no stated next step.
   *
   * What differs per family is whether it may *also* converge, and that is not a
   * style choice (independent re-audit N-1):
   *
   * - ``beginRecovery`` is the silent arm and the only user of this helper.  It is
   *   unreachable from the UI (``TrackingView`` always reads the capability and the
   *   connection from the same ``savedState``), so refusing *and* handing back the
   *   converging re-read adds no request the page ever sent.
   * - The submit and management arms keep their baseline refusal *without* the
   *   extra effect, because the submit one is reachable: the risk-confirmed
   *   resubmission clears the ordinary submit generation, so a later submit for
   *   that record would otherwise acquire an HTTP request the page never made
   *   (AC1).  Both are pinned by the session test.
   *
   * The reason is the replay reason because it is the one fixed sentence that
   * describes this precondition ("the connection this operation was bound to has
   * been cleared or replaced"), and it is deliberately the same sentence every
   * family already states for it.
   *
   * The reachable sibling — a generation that *exists* but cannot be turned into a
   * safe body (``beginManagement``'s own unbuildable check) — keeps its own
   * definite-failure session instead: there the page owes the user a statement of
   * what it refused to send, and it already carries the same converging re-read.
   * Routing it through the refusal channel would be wrong in kind, not just in
   * wording: that channel means "a still-unresolved intent refused a *different*
   * request", which is not what happened.
   */
  function unbuildableStart(trackingId: string): TrackingWriteStart {
    return {
      ...refuseAndStart(trackingId, 'REPLAY'),
      effects: [recheck(trackingId, true)],
    }
  }

  /**
   * A read-only check that proved the exact external object settles the pending
   * *submission*: only that family's intent is released, so a recovery or
   * management lock that is still unresolved stays locked and the server's
   * operation/audit history is untouched.
   *
   * Issue #190 released only the session and the intent; this also clears the
   * replay tombstone flag and the cached generation (issue #193: deliberate, and
   * kept).  The extra clearing is unreachable from the page, so it cannot change
   * what the page sends:
   *
   * - reaching it needs a *still unresolved* submit tombstone for this very
   *   record, and a tombstone only carries ``submitReplayBlocked`` after
   *   ``preserveAfterClear`` turned it into a non-replayable ``UNKNOWN`` one;
   * - both callers settle on a server-proven *existence*
   *   (``projectCheckResult``'s ``ACTIVE``/``DISABLED`` or
   *   ``projectResubmitOffer``'s ``CONFIRMED``), i.e. the record now has an
   *   external subscription and the server no longer projects ``SUBMIT`` for it,
   *   so no fresh confirmation can follow the release;
   * - and even if one did, releasing the tombstone only *permits* a brand-new
   *   confirmation (new key, new revision); it never rebinds the discarded key to
   *   the new connection, so no duplicate external write is possible.
   *
   * Keeping it is the safer option: "release a settled intent" then has exactly
   * one implementation instead of one that leaves a stale tombstone behind for
   * the very record it just settled.
   */
  function releaseSettledSubmission(trackingId: string): void {
    const submit = submitSession.value
    if (submit?.trackingId !== trackingId || !submit.keepsIntent) return
    submitSession.value = null
    releaseSubmitIntent()
    core.submitReplayBlocked = false
    core.submitConfigSnapshot = null
  }

  function resetCheck(): void {
    core.checkAttempt = null
    checkLoading.value = false
    check.value = null
    autoCheckArmed.value = false
  }

  /** The page owns the impact dialog; it reports the dialog's open state here. */
  function setPending(value: boolean): void {
    core.pending.value = value
  }

  return core
}

/**
 * The submit family (US-310, US-311): 提交 and 重试, plus the write phase of the
 * one risk-confirmed resubmission (issue #184), which reports through this slot.
 */
/**
 * The shared state the submit family uses, and nothing else.
 *
 * Issue #193: narrowing the core per family is what makes the split a real
 * boundary rather than a relocation — this family cannot read, let alone
 * write, another family's locked intent or generation.
 */
type SubmitFamilyCore = Pick<
  TrackingWriteCore,
  | 'active'
  | 'autoCheckArmed'
  | 'loading'
  | 'managementSession'
  | 'pending'
  | 'recheck'
  | 'recoverySession'
  | 'refusalNotice'
  | 'refuseAndStart'
  | 'releaseSubmitIntent'
  | 'submitConfigSnapshot'
  | 'submitIntent'
  | 'submitReplayBlocked'
  | 'submitSession'
  | 'unbuildableStart'
  | 'unresolvedOwner'
>

function createSubmitFamily(core: SubmitFamilyCore) {
  /**
   * The page's fixed presentation of one decided submit-family session: a
   * success notice, a blocking dialog with a settings deep link, or nothing the
   * user must be interrupted with.
   */
  function submitFeedback(session: TrackingWriteSession): TrackingWriteEffect[] {
    if (session.state === 'ACTIVE') {
      return [{
        kind: 'notify',
        feedback: { channel: 'success', title: '提交成功', message: '已在 Auto Bangumi 创建外部订阅。' },
      }]
    }
    const category = session.failureCategory
    if (!category || !(WRITE_FAILURE_CATEGORIES as readonly string[]).includes(category)) return []
    const presentation = WRITE_FAILURE_PRESENTATIONS[category as WriteFailureCategory]
    if (presentation.channel !== 'dialog') return []
    return [{
      kind: 'notify',
      feedback: { channel: 'dialog', title: presentation.title, message: presentation.message },
    }]
  }

  // -- submit family --------------------------------------------------------

  function beginSubmit(
    payload: TrackingWriteTarget,
    options: TrackingWriteBeginOptions = {},
  ): TrackingWriteStart {
    const trackingId = payload.item.tracking_id
    // One page-level intent at a time: a confirmation is already open, or an
    // external write/recovery is already running.
    if (core.pending.value || core.loading.value) return ignoredStart()
    if (core.submitReplayBlocked) return core.refuseAndStart(trackingId, 'REPLAY')
    // Issue #86: a saved Auto Bangumi connection is all an external write needs.
    // The server re-validates connection, credentials, exact version and write
    // capability inside the same request and fails closed.
    if (!options.connection) return ignoredStart()
    const sameItemRecovery = core.recoverySession.value?.trackingId === trackingId
      && core.recoverySession.value.keepsIntent
    const sameItemManagement = core.managementSession.value?.trackingId === trackingId
      && core.managementSession.value.keepsIntent
    if (sameItemRecovery || sameItemManagement) return core.refuseAndStart(trackingId, 'INTENT')
    // Any *other* record still holding the page's single unresolved intent
    // refuses this request — with a stated next step instead of a silent no-op.
    if (core.unresolvedOwner(trackingId)) return core.refuseAndStart(trackingId, 'INTENT')
    const requested = payload.action.code
    if (!isWriteActionCode(requested)) return ignoredStart()
    // A locked intent still owns the single opaque key for this item. Replaying
    // it under a different action would send something the user did not ask for.
    const locked = core.submitIntent && core.submitSession.value?.trackingId === trackingId ? core.submitIntent : null
    if (locked && locked.action !== requested) return core.refuseAndStart(trackingId, 'INTENT')
    // Issue #98 AC 2: the entry only opens the mode choice for the submit family.
    if (!options.mode) {
      return { ...ignoredStart(), ask: 'SUBMISSION_MODE' }
    }
    // This item's own next step is legitimate: the earlier refusal notice has
    // served its purpose.
    core.refusalNotice.value = null
    if (options.confirmed !== true) {
      return {
        ...ignoredStart(),
        ask: 'IMPACT',
        confirmation: WRITE_ACTION_CONFIRMATIONS[requested],
      }
    }

    const intent = locked ?? createTrackingActionIntent(payload.item, payload.action)
    if (!intent) return ignoredStart()
    const requestConfig = locked ? core.submitConfigSnapshot : options.connection
    // A locked intent can legitimately have no generation left (independent
    // re-audit N-1): ``beginResubmitConfirmation`` clears this very snapshot for
    // the one risk-confirmed resubmission without releasing the ordinary submit
    // intent, so an ordinary submit for the same record reaches here afterwards.
    // That is a *reachable* command, so it keeps exactly the baseline answer — the
    // fixed refusal and zero requests.  The converging re-read the recovery arm
    // owes would add an HTTP request on a path the page never sent one on (AC1);
    // "keeps the cleared-connection refusal at its gate" and "refuses a locked
    // submit whose generation the resubmission flow dropped" in the session test
    // pin this arm and that reachability.
    if (!requestConfig) return core.refuseAndStart(trackingId, 'REPLAY')
    core.submitIntent = intent
    if (!locked) core.submitConfigSnapshot = { ...requestConfig }
    const storageDir = options.storageDir
    const body: TrackingWriteBody = {
      expected_revision: intent.expectedRevision,
      idempotency_key: intent.idempotencyKey,
      confirm: true,
      ...(options.mode ? { submission_mode: options.mode } : {}),
      connection_ref: requestConfig.connection_ref!,
      configuration_revision: requestConfig.configuration_revision!,
      ...(storageDir ? { storage_dir: storageDir } : {}),
    }
    core.active = { family: 'SUBMIT', trackingId, action: requested, mode: options.mode ?? null }
    core.loading.value = true
    core.submitSession.value = createSubmitSession(trackingId, requested, 'IN_FLIGHT')
    return {
      accepted: true,
      refusal: null,
      ask: null,
      confirmation: null,
      request: {
        endpoint: operationEndpoint(requested),
        path: { tracking_id: trackingId },
        body,
      },
      effects: [],
    }
  }

  function finishSubmit(
    result: TrackingWriteResult | TrackingResubmitResult,
  ): readonly TrackingWriteEffect[] {
    const transport = core.active
    if (!transport || (transport.family !== 'SUBMIT' && transport.family !== 'RESUBMIT')) return []
    core.active = null
    const session = projectSubmitOutcome(
      transport.trackingId, transport.action, result, transport.mode,
    )
    core.submitSession.value = session
    if (!session.keepsIntent) {
      core.releaseSubmitIntent()
    } else {
      // Issue #183: a submit whose result is still unproven owes one automatic
      // bounded read-only check, which is exactly what the submit area shows.
      core.autoCheckArmed.value = true
    }
    return [core.recheck(transport.trackingId, false), ...submitFeedback(session)]
  }

  function failSubmit(error: TrackingWriteError): readonly TrackingWriteEffect[] {
    const transport = core.active
    if (!transport || (transport.family !== 'SUBMIT' && transport.family !== 'RESUBMIT')) return []
    // A cancellation that cannot have crossed the external boundary is not a
    // result: the session and its intent stay exactly as they were.
    if (error.cancelled === true && error.httpError !== true) return []
    core.active = null
    const { trackingId, action } = transport
    if (error.status === 409) {
      // Every documented 409 is raised before the external boundary, so nothing
      // was submitted. The locked intent is spent and the error body carries no
      // authoritative tracking, so re-read both and require a new confirmation.
      core.releaseSubmitIntent()
      core.submitSession.value = transport.family === 'RESUBMIT'
        ? createSubmitSession(trackingId, action, 'CONFLICT', {
            message: resubmitConflictMessage(error.type),
          })
        : createSubmitConflictSession(trackingId, action, error.type)
      return [core.recheck(trackingId, true)]
    }
    if (isDefiniteWriteRejection(error)) {
      // D38-08.5: a documented JSON 400/404 is a definite refusal raised before
      // the external boundary — Auto Bangumi was never written. This is *not*
      // "结果待确认": the intent is released and the page only reads back.
      core.releaseSubmitIntent()
      core.submitSession.value = createSubmitSession(trackingId, action, 'REJECTED')
      return [core.recheck(trackingId, true)]
    }
    // Network, timeout, non-JSON, 5xx — anything we cannot read as a definite
    // outcome: the external result is unknown. Keeping the locked intent can
    // never duplicate a subscription, so this path fails closed and only reads
    // back; it never mints a new key and never resends by itself.
    core.submitSession.value = createSubmitSession(trackingId, action, 'UNKNOWN')
    return [core.recheck(trackingId, true)]
  }

  return { beginSubmit, finishSubmit, failSubmit }
}

/**
 * The recovery family (US-312): the three local conclusions and the one
 * credential-bearing read-only ``VERIFY_EXTERNAL``.
 */
/**
 * The shared state the recovery family uses, and nothing else.
 *
 * Issue #193: narrowing the core per family is what makes the split a real
 * boundary rather than a relocation — this family cannot read, let alone
 * write, another family's locked intent or generation.
 */
type RecoveryFamilyCore = Pick<
  TrackingWriteCore,
  | 'active'
  | 'loading'
  | 'pending'
  | 'recheck'
  | 'recoverySession'
  | 'refusalNotice'
  | 'refuseAndStart'
  | 'releaseFor'
  | 'unbuildableStart'
  | 'unresolvedOwner'
>

function createRecoveryFamily(core: RecoveryFamilyCore) {
  // -- recovery family ------------------------------------------------------

  function beginRecovery(
    payload: { readonly action: TrackingRecoveryActionCode; readonly item: TrackingItem },
    options: TrackingWriteBeginOptions & { readonly capabilities?: CapabilityResult | null } = {},
  ): TrackingWriteStart {
    // One page-level intent at a time: a confirmation is open, or a write or
    // recovery is already running.
    if (core.pending.value || core.loading.value) return ignoredStart()
    const requested = payload.action
    if (!isRecoveryActionCode(requested)) return ignoredStart()
    const trackingId = payload.item.tracking_id
    // Another record's unresolved write or recovery keeps the page's single
    // intent, so this recovery is refused before it can race it (D38-09.4).
    if (core.unresolvedOwner(trackingId)) return core.refuseAndStart(trackingId, 'INTENT')
    // This record's own next step is legitimate: drop the earlier refusal notice.
    core.refusalNotice.value = null
    const confirmation = recoveryConfirmation(requested)
    if (confirmation && options.confirmed !== true) {
      return { ...ignoredStart(), ask: 'IMPACT', confirmation }
    }
    // Read the live session *after* the confirmation: a session cleared while
    // the dialog was open must not be used (the local actions never need one).
    const intent = createTrackingRecoveryIntent(
      payload.item, requested, options.capabilities ?? null,
    )
    if (!intent) return ignoredStart()
    const body = createTrackingRecoverBody(
      intent.action, intent.expectedRevision, options.connection ?? null, options.storageDir,
    )
    // A body the page cannot build safely (external verification without the
    // live session) is not sent at all, and is refused exactly like the other
    // two families' unbuildable sessions (issue #193).
    if (!body) return core.unbuildableStart(trackingId)
    core.active = { family: 'RECOVERY', trackingId, action: intent.action }
    core.loading.value = true
    core.recoverySession.value = createRecoverySession(trackingId, intent.action, 'IN_FLIGHT')
    return {
      accepted: true,
      refusal: null,
      ask: null,
      confirmation: null,
      request: {
        endpoint: operationEndpoint(intent.action),
        path: { tracking_id: trackingId },
        body,
      },
      effects: [],
    }
  }

  function finishRecovery(result: TrackingRecoverResult): readonly TrackingWriteEffect[] {
    const transport = core.active
    if (!transport || transport.family !== 'RECOVERY') return []
    core.active = null
    const { trackingId, action } = transport
    const session = projectRecoveryOutcome(trackingId, action, result)
    core.recoverySession.value = session
    // A decided recovery settles the record: every unresolved write intent it
    // was recovering from is released.
    if (session.state === 'ACTIVE' || session.state === 'SUBMIT_FAILED') core.releaseFor(trackingId)
    return [core.recheck(trackingId, false)]
  }

  function failRecovery(error: TrackingWriteError): readonly TrackingWriteEffect[] {
    const transport = core.active
    if (!transport || transport.family !== 'RECOVERY') return []
    if (error.cancelled === true && error.httpError !== true) return []
    core.active = null
    const { trackingId, action } = transport
    if (error.status === 409) {
      // Revision/state conflict: the recovery was refused before anything was
      // persisted, so re-read the server state and let the user confirm again.
      core.recoverySession.value = createRecoveryConflictSession(trackingId, action)
      return [core.recheck(trackingId, true)]
    }
    if (isDefiniteWriteRejection(error)) {
      // A documented JSON 400/404 is decided before any state change.
      core.recoverySession.value = createRecoverySession(trackingId, action, 'REJECTED')
      return [core.recheck(trackingId, true)]
    }
    // Anything unreadable stays indeterminate: read back, keep the recovery
    // state and never resend on the user's behalf.
    core.recoverySession.value = createRecoverySession(trackingId, action, 'UNKNOWN')
    return [core.recheck(trackingId, true)]
  }

  return { beginRecovery, finishRecovery, failRecovery }
}

/**
 * The management family (US-313, US-314, US-315): 修改 / 启停 / 立即刷新 /
 * 删除外部对象, each routed by the validated intent's own declaration.
 */
/**
 * The shared state the management family uses, and nothing else.
 *
 * Issue #193: narrowing the core per family is what makes the split a real
 * boundary rather than a relocation — this family cannot read, let alone
 * write, another family's locked intent or generation.
 */
type ManagementFamilyCore = Pick<
  TrackingWriteCore,
  | 'active'
  | 'loading'
  | 'managementConfigSnapshot'
  | 'managementIntent'
  | 'managementReplayBlocked'
  | 'managementSession'
  | 'pending'
  | 'recheck'
  | 'recoverySession'
  | 'refusalNotice'
  | 'refuseAndStart'
  | 'submitSession'
  | 'unbuildableStart'
  | 'unresolvedOwner'
>

function createManagementFamily(core: ManagementFamilyCore) {
  // -- management family ----------------------------------------------------

  function beginManagement(
    payload: {
      readonly action: TrackingAction
      readonly item: TrackingItem
      readonly targetScope: TrackingManagementScope
      readonly patch: unknown
      readonly localPlan?: unknown
    },
    options: TrackingWriteBeginOptions = {},
  ): TrackingWriteStart {
    const trackingId = payload.item.tracking_id
    if (core.pending.value || core.loading.value) return ignoredStart()
    if (core.managementReplayBlocked) return core.refuseAndStart(trackingId, 'REPLAY')
    // Issue #89: a saved Auto Bangumi connection is all an external management
    // write needs. The server re-validates connection, credentials, exact
    // version and write capability in the same request and fails closed.
    if (!options.connection) return ignoredStart()
    const requested = payload.action.code
    // Only the management actions this page can actually send are accepted.
    if (!isSendableManagementAction(requested)) return ignoredStart()
    const targetScope = payload.targetScope
    if (!isTrackingManagementScope(targetScope)) return ignoredStart()
    const sameItemWrite = core.submitSession.value?.trackingId === trackingId
      && core.submitSession.value.keepsIntent
    const sameItemRecovery = core.recoverySession.value?.trackingId === trackingId
      && core.recoverySession.value.keepsIntent
    if (sameItemWrite || sameItemRecovery) return core.refuseAndStart(trackingId, 'INTENT')
    // Any other record still holding the page's single unresolved intent refuses
    // this management request — with a stated reason, not a silent no-op.
    if (core.unresolvedOwner(trackingId)) return core.refuseAndStart(trackingId, 'INTENT')

    // The page re-validates the emitted request against the current server
    // projection: the action and scope must still be offered for this revision,
    // the patch must belong to the chosen scope and the enable direction must
    // still be the one the record's own status implies.
    const projectedIntent = createTrackingManagementActionIntent(
      payload.item, requested, targetScope, payload.patch, payload.localPlan,
    )
    if (!projectedIntent) return ignoredStart()
    // A locked intent still owns the single opaque key *and* the request it was
    // confirmed with. Replaying it for a different scope, patch or direction
    // would send something the user did not ask for, and minting a new key while
    // the external result is unresolved could apply the change twice.
    const locked = core.managementIntent && core.managementSession.value?.trackingId === trackingId
      ? core.managementIntent
      : null
    if (locked && !sameManagementRequest(locked, projectedIntent)) {
      return core.refuseAndStart(trackingId, 'INTENT')
    }
    const intent = locked ?? projectedIntent
    // The user is replaying the one locked request (or starting a fresh one):
    // the refusal notice has served its purpose.
    core.refusalNotice.value = null
    if (options.confirmed !== true) {
      return { ...ignoredStart(), ask: 'IMPACT', confirmation: managementConfirmation(intent) }
    }
    const requestConfig = locked ? core.managementConfigSnapshot : options.connection
    // No public-surface sequence reaches this arm today (independent re-audit E3:
    // mutating it to either alternative changes nothing any test or probe can
    // observe), but it is kept at exactly the baseline zero-request refusal: the
    // submit family's sibling *is* reachable through the resubmission flow (see
    // there), so this arm must not become a way to add an HTTP request if a future
    // change ever makes a management generation disappear the same way.  The
    // reachable sibling just below — a generation that exists but cannot become a
    // body — is the one that owes the user a statement, and it keeps its own
    // definite-failure session.
    if (!requestConfig) return core.refuseAndStart(trackingId, 'REPLAY')
    core.managementIntent = intent
    if (!locked) core.managementConfigSnapshot = { ...requestConfig }
    // A body the page cannot build safely (no server address, missing scope
    // patch, no known enable direction) is refused here, before any in-flight
    // session exists: it sends zero requests and converges on a definite failure
    // instead of leaving the panel stuck on "正在提交外部修改，请稍候…".
    const body = createTrackingManagementBody(intent, requestConfig, options.storageDir)
    if (!body) {
      core.managementIntent = null
      core.managementSession.value = createManagementSession(
        trackingId, intent.action, targetScope, 'REJECTED', false, MANAGEMENT_UNBUILDABLE_MESSAGE,
      )
      return { ...ignoredStart(), effects: [core.recheck(trackingId, true)] }
    }
    core.active = { family: 'MANAGEMENT', trackingId, action: intent.action, targetScope }
    core.loading.value = true
    core.managementSession.value = createManagementSession(trackingId, intent.action, targetScope, 'IN_FLIGHT')
    return {
      accepted: true,
      refusal: null,
      ask: null,
      confirmation: null,
      request: {
        endpoint: operationEndpoint(intent.action),
        path: { tracking_id: trackingId },
        body,
      },
      effects: [],
    }
  }

  function finishManagement(result: TrackingManagementResult): readonly TrackingWriteEffect[] {
    const transport = core.active
    if (!transport || transport.family !== 'MANAGEMENT') return []
    core.active = null
    const { trackingId, action, targetScope } = transport
    const session = projectManagementOutcome(trackingId, action, targetScope, result)
    core.managementSession.value = session
    if (!session.keepsIntent) core.managementIntent = null
    return [core.recheck(trackingId, false)]
  }

  function failManagement(error: TrackingWriteError): readonly TrackingWriteEffect[] {
    const transport = core.active
    if (!transport || transport.family !== 'MANAGEMENT') return []
    if (error.cancelled === true && error.httpError !== true) return []
    core.active = null
    const { trackingId, action, targetScope } = transport
    if (error.status === 409) {
      // Every documented management 409 is raised while the operation is being
      // prepared, i.e. before the external boundary: nothing was submitted. The
      // locked intent is spent, so re-read both and require a new confirmation.
      core.managementIntent = null
      core.managementSession.value = createManagementSession(
        trackingId, action, targetScope, 'CONFLICT', false,
        managementConflictMessage(error.type, action),
      )
      return [core.recheck(trackingId, true)]
    }
    if (isDefiniteWriteRejection(error)) {
      // A structured non-409 4xx is a definite refusal raised before the
      // external boundary, so Auto Bangumi was never touched. The intent is
      // released and the page only reads the latest state back.
      core.managementIntent = null
      core.managementSession.value = createManagementSession(trackingId, action, targetScope, 'REJECTED')
      return [core.recheck(trackingId, true)]
    }
    // Network, timeout, non-JSON, 5xx — anything we cannot read as a definite
    // verdict: the external result is unknown. Keeping the locked intent can
    // never apply the change twice, so this path fails closed and only reads
    // back; it never mints a new key and never resends by itself.
    core.managementSession.value = createManagementSession(trackingId, action, targetScope, 'UNKNOWN', true)
    return [core.recheck(trackingId, true)]
  }

  return { beginManagement, finishManagement, failManagement }
}

/**
 * The unified plan delete (issue #92): a local delete that optionally asks Auto
 * Bangumi to drop the external object as well.
 */
/**
 * The shared state the plan delete family uses, and nothing else.
 *
 * Issue #193: narrowing the core per family is what makes the split a real
 * boundary rather than a relocation — this family cannot read, let alone
 * write, another family's locked intent or generation.
 */
type PlanDeleteFamilyCore = Pick<
  TrackingWriteCore,
  | 'planDelete'
  | 'planDeleteExternal'
  | 'recheck'
>

function createPlanDeleteFamily(core: PlanDeleteFamilyCore) {
  // -- unified plan delete (issue #92) --------------------------------------

  function beginPlanDelete(
    payload: { readonly item: TrackingItem; readonly deleteExternal: boolean },
    options: TrackingWriteBeginOptions = {},
  ): TrackingWriteStart {
    const connection = options.connection ?? null
    // Issue #96: a purely local delete needs no Auto Bangumi connection at all;
    // only the optional external delete requires the saved connection.
    if (payload.deleteExternal && !connection?.connection_ref) return ignoredStart()
    const trackingId = payload.item.tracking_id
    core.planDeleteExternal = payload.deleteExternal
    core.planDelete.value = createPlanDeleteSession(trackingId, 'IN_FLIGHT')
    const storageDir = options.storageDir
    // The generated body declares ``connection_ref`` unconditionally, but a
    // purely local delete deliberately carries no credential at all (issue #96).
    const body = {
      confirm: true as const,
      delete_external: payload.deleteExternal,
      idempotency_key: makeOpaqueKey(),
      ...(payload.deleteExternal && connection?.connection_ref
        ? {
            connection_ref: connection.connection_ref,
            configuration_revision: connection.configuration_revision,
          }
        : {}),
      ...(storageDir ? { storage_dir: storageDir } : {}),
    }
    return {
      accepted: true,
      refusal: null,
      ask: null,
      confirmation: null,
      request: {
        endpoint: PLAN_DELETE_ENDPOINT,
        path: { tracking_id: trackingId },
        body,
      },
      effects: [],
    }
  }

  function finishPlanDelete(result: TrackingPlanDeleteResult): readonly TrackingWriteEffect[] {
    const current = core.planDelete.value
    if (!current) return []
    const trackingId = current.trackingId
    const state = result?.outcome === 'DELETED'
      ? 'DELETED'
      : result?.outcome === 'EXTERNAL_FAILED' ? 'EXTERNAL_FAILED' : 'EXTERNAL_UNKNOWN'
    core.planDelete.value = createPlanDeleteSession(trackingId, state)
    if (state === 'DELETED') {
      return [
        {
          kind: 'notify',
          feedback: {
            channel: 'success',
            title: '追番方案已删除',
            message: core.planDeleteExternal
              ? '已同时删除受控外部订阅；已下载媒体保留。'
              : 'Auto Bangumi 中的订阅继续运行，MiGuOrca 不再管理它。',
          },
        },
        core.recheck(null, true),
      ]
    }
    return [core.recheck(trackingId, true)]
  }

  function failPlanDelete(error: TrackingWriteError): readonly TrackingWriteEffect[] {
    const current = core.planDelete.value
    if (!current) return []
    if (error.cancelled === true && error.httpError !== true) return []
    const trackingId = current.trackingId
    core.planDelete.value = createPlanDeleteSession(
      trackingId, error.status === 409 ? 'EXTERNAL_FAILED' : 'EXTERNAL_UNKNOWN',
    )
    return [core.recheck(trackingId, true)]
  }

  function resetPlanDelete(): void {
    core.planDelete.value = null
  }

  return {
    beginPlanDelete,
    finishPlanDelete,
    failPlanDelete,
    resetPlanDelete,
  }
}

/**
 * The bounded read-only check of a pending submission (issue #183): its own slot
 * and its own attempt, holding no page-level intent.
 */
/**
 * The shared state the read-only check uses, and nothing else.
 *
 * Issue #193: narrowing the core per family is what makes the split a real
 * boundary rather than a relocation — this family cannot read, let alone
 * write, another family's locked intent or generation.
 */
type CheckFamilyCore = Pick<
  TrackingWriteCore,
  | 'autoCheckArmed'
  | 'check'
  | 'checkAttempt'
  | 'checkLoading'
  | 'recheck'
  | 'refusalNotice'
  | 'refuseAndStart'
  | 'releaseSettledSubmission'
  | 'unresolvedOwner'
>

function createCheckFamily(core: CheckFamilyCore) {
  function setAutoCheck(armed: boolean): void {
    core.autoCheckArmed.value = armed
  }

  /**
   * Begin one bounded read-only confirmation of a pending submission.
   *
   * The request carries only the revision the user is looking at; the server
   * resolves the original operation's saved connection, so nothing here can
   * rebind it.  A stale revision is a 409 before any read.  A check holds no
   * page-level intent: another record's unresolved intent refuses a manual
   * attempt (with the fixed reason) and leaves the owed automatic one armed, so
   * it is retried instead of being silently dropped.
   */
  function beginCheck(
    payload: { readonly item: TrackingItem; readonly automatic: boolean },
    options: TrackingWriteBeginOptions = {},
  ): TrackingWriteStart {
    const trackingId = payload.item.tracking_id
    const revision = payload.item.revision
    if (typeof revision !== 'number') return ignoredStart()
    if (payload.automatic && !core.autoCheckArmed.value) return ignoredStart()
    if (core.checkLoading.value) return ignoredStart()
    if (core.unresolvedOwner(trackingId)) {
      if (payload.automatic) return ignoredStart()
      return core.refuseAndStart(trackingId, 'INTENT')
    }
    if (payload.automatic) core.autoCheckArmed.value = false
    core.refusalNotice.value = null
    const storageDir = options.storageDir
    const body: TrackingCheckBody = {
      expected_revision: revision,
      ...(storageDir ? { storage_dir: storageDir } : {}),
    }
    core.checkAttempt = { trackingId, revision }
    core.checkLoading.value = true
    core.check.value = createCheckSession(trackingId, 'IN_FLIGHT', null, revision)
    return {
      accepted: true,
      refusal: null,
      ask: null,
      confirmation: null,
      request: {
        endpoint: TRACKING_CHECK_ENDPOINT,
        path: { tracking_id: trackingId },
        body,
      },
      effects: [],
    }
  }

  function finishCheck(result: TrackingCheckResult): readonly TrackingWriteEffect[] {
    const attempt = core.checkAttempt
    if (!attempt) return []
    core.checkAttempt = null
    core.checkLoading.value = false
    const session = projectCheckResult(attempt.trackingId, result, attempt.revision)
    core.check.value = session
    if (session.state === 'CONFIRMED') core.releaseSettledSubmission(attempt.trackingId)
    return [core.recheck(attempt.trackingId, true)]
  }

  function failCheck(error: TrackingWriteError): readonly TrackingWriteEffect[] {
    const attempt = core.checkAttempt
    if (!attempt) return []
    core.checkAttempt = null
    core.checkLoading.value = false
    // A cancellation that cannot have reached the server is not a result: the
    // in-flight session stays as it is, exactly as the write families do.
    if (error.cancelled === true && error.httpError !== true) return []
    core.check.value = error.status === 409
      ? createCheckSession(attempt.trackingId, 'CONFLICT', null, attempt.revision)
      : createCheckSession(attempt.trackingId, 'UNKNOWN', null, attempt.revision)
    return [core.recheck(attempt.trackingId, true)]
  }

  return { setAutoCheck, beginCheck, finishCheck, failCheck }
}

/**
 * The risk-confirmed single manual resubmission (issue #184): its own read-only
 * offer slot, then one new operation reported through the submit family's slot.
 */
/**
 * The shared state the resubmission family uses, and nothing else.
 *
 * Issue #193: narrowing the core per family is what makes the split a real
 * boundary rather than a relocation — this family cannot read, let alone
 * write, another family's locked intent or generation.
 */
type ResubmitFamilyCore = Pick<
  TrackingWriteCore,
  | 'active'
  | 'loading'
  | 'pending'
  | 'recheck'
  | 'refusalNotice'
  | 'refuseAndStart'
  | 'releaseSettledSubmission'
  | 'resubmit'
  | 'resubmitAttempt'
  | 'resubmitIntent'
  | 'resubmitLoading'
  | 'submitConfigSnapshot'
  | 'submitReplayBlocked'
  | 'submitSession'
  | 'unresolvedOwner'
>

function createResubmitFamily(core: ResubmitFamilyCore) {
  // -- risk-confirmed resubmission (issue #184) -----------------------------

  /** The one confirmation body of a resubmit, rebuilt from its exact binding. */
  function resubmitRequest(
    trackingId: string,
    binding: TrackingResubmitBinding,
    storageDir: string | undefined,
  ): TrackingWriteRequest {
    return {
      endpoint: TRACKING_RESUBMIT_ENDPOINT,
      path: { tracking_id: trackingId },
      body: createResubmitConfirmationBody(binding, storageDir),
    }
  }

  /**
   * Start (or replay) the one manual resubmission of a pending submission.
   *
   * The first call is the read-only phase: it carries the revision and nothing
   * else, so a proven subscription converges with zero external writes.  While a
   * previous confirmation of the same item is still unproven, this call instead
   * replays that exact body — re-checking or re-minting could create a second
   * subscription.
   */
  function beginResubmit(
    payload: { readonly item: TrackingItem },
    options: TrackingWriteBeginOptions = {},
  ): TrackingWriteStart {
    const trackingId = payload.item.tracking_id
    if (core.pending.value || core.loading.value || core.resubmitLoading.value) return ignoredStart()
    const locked = core.resubmitIntent?.trackingId === trackingId ? core.resubmitIntent : null
    if (locked) {
      if (core.submitReplayBlocked) return core.refuseAndStart(trackingId, 'REPLAY')
      core.refusalNotice.value = null
      core.active = {
        family: 'RESUBMIT', trackingId, action: 'SUBMIT', mode: 'CONTINUE_TRACKING',
      }
      core.loading.value = true
      core.submitSession.value = createSubmitSession(trackingId, 'SUBMIT', 'IN_FLIGHT')
      return {
        ...acceptedStart(resubmitRequest(trackingId, locked.binding, options.storageDir)),
        resubmitPhase: 'CONFIRMATION',
      }
    }
    if (core.unresolvedOwner(trackingId)) return core.refuseAndStart(trackingId, 'INTENT')
    const revision = payload.item.revision
    if (typeof revision !== 'number') return ignoredStart()
    core.refusalNotice.value = null
    const body: TrackingResubmitBody = {
      expected_revision: revision,
      confirm: false,
      ...(options.storageDir ? { storage_dir: options.storageDir } : {}),
    }
    core.resubmitAttempt = { trackingId, revision }
    core.resubmitLoading.value = true
    core.resubmit.value = createResubmitSession(trackingId, 'IN_FLIGHT', null, revision)
    return {
      ...acceptedStart({
        endpoint: TRACKING_RESUBMIT_ENDPOINT,
        path: { tracking_id: trackingId },
        body,
      }),
      resubmitPhase: 'OFFER',
    }
  }

  /**
   * Settle the read-only phase.  A proven subscription releases the pending
   * submission intent; a refusal is stated as its own reason; only an offered,
   * still-unresolved result asks the page for the explicit risk confirmation.
   */
  function finishResubmitOffer(result: TrackingResubmitResult): readonly TrackingWriteEffect[] {
    const attempt = core.resubmitAttempt
    if (!attempt) return []
    core.resubmitAttempt = null
    core.resubmitLoading.value = false
    const session = projectResubmitOffer(attempt.trackingId, result, attempt.revision)
    core.resubmit.value = session
    if (session.state === 'CONFIRMED') core.releaseSettledSubmission(attempt.trackingId)
    if (session.state !== 'UNKNOWN' || !session.binding) {
      return [core.recheck(attempt.trackingId, true)]
    }
    return [
      core.recheck(attempt.trackingId, true),
      { kind: 'confirmResubmitRisk', trackingId: attempt.trackingId, binding: session.binding },
    ]
  }

  function failResubmitOffer(error: TrackingWriteError): readonly TrackingWriteEffect[] {
    const attempt = core.resubmitAttempt
    if (!attempt) return []
    core.resubmitAttempt = null
    core.resubmitLoading.value = false
    if (error.cancelled === true && error.httpError !== true) return []
    // Every documented 409 is raised before the external boundary, so the proven
    // reason is stated and the page re-reads instead of guessing a cause.
    core.resubmit.value = error.status === 409
      ? createResubmitSession(
          attempt.trackingId, 'CONFLICT', null, attempt.revision, resubmitConflictMessage(error.type),
        )
      : createResubmitSession(attempt.trackingId, 'UNKNOWN', null, attempt.revision)
    return [core.recheck(attempt.trackingId, true)]
  }

  /** The user cancelled the risk confirmation: no request, no new operation. */
  function cancelResubmit(trackingId: string): void {
    const session = core.resubmit.value
    if (!session || session.trackingId !== trackingId || !session.binding) return
    core.resubmit.value = createResubmitSession(
      trackingId, 'CANCELLED', session.reason, session.revision,
    )
  }

  /**
   * Send the one confirmation of a risk-confirmed resubmission.
   *
   * The body is the exact binding the server published; while its result is
   * unproven the page replays that very body (``beginResubmit``) instead of
   * starting a new read-only phase.
   */
  function beginResubmitConfirmation(
    binding: TrackingResubmitBinding,
    options: TrackingWriteBeginOptions = {},
  ): TrackingWriteStart {
    if (core.pending.value || core.loading.value) return ignoredStart()
    const offer = core.resubmit.value
    if (
      !offer
      || !offer.binding
      || offer.binding.previous_operation_id !== binding.previous_operation_id
      || offer.binding.expected_revision !== binding.expected_revision
      || offer.binding.connection_ref !== binding.connection_ref
    ) {
      return ignoredStart()
    }
    const trackingId = offer.trackingId
    if (core.unresolvedOwner(trackingId)) return core.refuseAndStart(trackingId, 'INTENT')
    core.refusalNotice.value = null
    core.resubmitIntent = { trackingId, binding: offer.binding }
    core.resubmit.value = null
    // The confirmation is a submit-family external write: one new operation and
    // the ordinary submit result panel.
    //
    // The ordinary submit's generation is dropped here on purpose (independent
    // re-audit N-3): the one new operation carries its own server-published
    // binding (previous operation + connection), so keeping the snapshot would
    // invite a replay of the *old* key against the new operation.  ``submitIntent``
    // is deliberately not released here — this confirmation is not a fresh
    // ordinary submit, and its own result still has to settle the page's single
    // intent.  The consequence is recorded and tested: until that result is
    // decided, an ordinary submit for this record finds a locked intent with no
    // generation and gets the fixed refusal with zero requests.
    core.submitConfigSnapshot = null
    core.active = { family: 'RESUBMIT', trackingId, action: 'SUBMIT', mode: 'CONTINUE_TRACKING' }
    core.loading.value = true
    core.submitSession.value = createSubmitSession(trackingId, 'SUBMIT', 'IN_FLIGHT')
    return {
      ...acceptedStart(resubmitRequest(trackingId, offer.binding, options.storageDir)),
      resubmitPhase: 'CONFIRMATION',
    }
  }

  return {
    beginResubmit,
    finishResubmitOffer,
    failResubmitOffer,
    cancelResubmit,
    beginResubmitConfirmation,
  }
}

/**
 * The explicit batch submit (issue #87, #100): one request for one confirmed
 * selection, projected into per-entry outcomes.
 *
 * Where the deleted ``batchSelection.ts`` (issue #168) went — every export of
 * that module now lives in this file, and only the commands the page calls stay
 * on the session's public surface:
 *
 * | old export | new home |
 * | --- | --- |
 * | ``TrackingBatchSelection`` / ``TrackingBatchEntry`` / ``TrackingBatchSubmitBody`` | internal interfaces here |
 * | ``TrackingBatchSelectionSummary`` / ``SkippedBatchEntry`` | internal interfaces here |
 * | ``TrackingBatchEntryOutcome`` / ``TrackingBatchOutcome`` | internal interfaces here (the ``batchOutcome`` ref's type) |
 * | ``EMPTY_BATCH_SELECTION`` | internal constant here |
 * | ``batchSkipReason`` | internal function, re-exposed unchanged by the page API |
 * | ``skippedBatchEntries`` | internal function here, unchanged (called by ``beginBatchSubmit``) |
 * | ``isBatchSelected`` / ``toggleBatchSelection`` / ``selectAllBatch`` | internal functions; the API keeps ``isBatchSelected`` / ``toggleBatchRow`` / ``selectAllBatch`` |
 * | ``clearBatchSelection`` | the API's ``clearBatchSelection`` writes the ref directly (the old pure function returned the empty selection) |
 * | ``batchSelectionSummary`` | internal function, exposed as the API's ``batchSummary`` |
 * | ``buildBatchSubmitBody`` / ``projectBatchOutcome`` / ``selectionAfterBatch`` | internal functions here, unchanged |
 * | ``BATCH_ACTIONS`` (private) | internal constant here, unchanged |
 */
/**
 * The shared state the batch family uses, and nothing else.
 *
 * Issue #193: narrowing the core per family is what makes the split a real
 * boundary rather than a relocation — this family cannot read, let alone
 * write, another family's locked intent or generation.
 */
type BatchFamilyCore = Pick<
  TrackingWriteCore,
  | 'batchLoading'
  | 'batchNotice'
  | 'batchOutcome'
  | 'batchSelection'
  | 'recheck'
>

function createBatchFamily(core: BatchFamilyCore) {
  function resetBatch(): void {
    core.batchSelection.value = EMPTY_BATCH_SELECTION
    core.batchOutcome.value = null
    core.batchNotice.value = ''
  }

  // -- explicit batch submit (issue #87) -----------------------------------

  function beginBatchSubmit(
    payload: { readonly items: readonly TrackingItem[]; readonly mode: TrackingSubmissionMode | null },
    options: TrackingWriteBeginOptions = {},
  ): TrackingBatchStart {
    const connection = options.connection ?? null
    if (!connection?.connection_ref) return { ...ignoredStart(), skipped: [], skippedTitle: '' }
    // AC 5/6/9: the local pre-check result is stated before (and separately from)
    // any external result, and a fully skipped batch sends nothing at all.
    const skipped = skippedBatchEntries(core.batchSelection.value, payload.items)
    const body = buildBatchSubmitBody(
      core.batchSelection.value,
      payload.items,
      { connection_ref: connection.connection_ref, configuration_revision: connection.configuration_revision! },
      options.storageDir,
      payload.mode ?? undefined,
    )
    if (!body) {
      // AC 6: a fully skipped batch proves zero Auto Bangumi requests.
      core.batchOutcome.value = null
      core.batchNotice.value = '没有可提交的方案'
      return { ...ignoredStart(), skipped, skippedTitle: '没有可提交的方案' }
    }
    // AC 4: the information dialog never gates the run — the submittable plans
    // start immediately, with no second confirmation.  The banner is cleared for
    // the new attempt; the dialog's title is returned instead of being shown.
    core.batchOutcome.value = null
    core.batchNotice.value = ''
    core.batchLoading.value = true
    return {
      accepted: true,
      refusal: null,
      ask: null,
      confirmation: null,
      request: { endpoint: TRACKING_BATCH_SUBMIT_ENDPOINT, path: {}, body },
      effects: [],
      skipped,
      skippedTitle: skipped.length ? '部分方案未提交' : '',
    }
  }

  function finishBatchSubmit(result: TrackingBatchResult): readonly TrackingWriteEffect[] {
    const outcome = projectBatchOutcome(result)
    core.batchOutcome.value = outcome
    core.batchSelection.value = selectionAfterBatch(core.batchSelection.value, outcome)
    const unknown = outcome.unresolved.length
    core.batchNotice.value = `本次批量提交：成功 ${outcome.succeeded} 条，失败 ${outcome.failed} 条${unknown ? `，其中 ${unknown} 条结果待确认需先恢复` : ''}。`
    core.batchLoading.value = false
    const effects: TrackingWriteEffect[] = [core.recheck(null, true)]
    if (outcome.succeeded) {
      effects.unshift({
        kind: 'notify',
        feedback: {
          channel: 'success',
          title: '批量提交完成',
          message: `已在 Auto Bangumi 创建 ${outcome.succeeded} 条外部订阅。`,
        },
      })
    }
    return effects
  }

  function failBatchSubmit(error: TrackingWriteError): void {
    core.batchLoading.value = false
    // A cancellation that cannot have crossed the external boundary keeps the
    // previous copy: nothing was resolved and nothing is resent.
    if (error.cancelled === true && error.httpError !== true) return
    // Nothing was resolved: keep the selection and never resend on our own.
    core.batchNotice.value = '批量提交请求未能确认送达，已保留当前选择；请核对连接后重新确认。'
  }

  return {
    isBatchSelected: (trackingId: string) => isBatchSelected(core.batchSelection.value, trackingId),
    toggleBatchRow(trackingId: string) {
      core.batchSelection.value = toggleBatchSelection(core.batchSelection.value, trackingId)
    },
    selectAllBatch(items: readonly TrackingItem[]) {
      core.batchSelection.value = selectAllBatch(items)
    },
    clearBatchSelection() {
      core.batchSelection.value = EMPTY_BATCH_SELECTION
    },
    batchSkipReason,
    batchSummary: (visible: readonly TrackingItem[]) => (
      batchSelectionSummary(core.batchSelection.value, visible)
    ),
    resetBatch,
    beginBatchSubmit,
    finishBatchSubmit,
    failBatchSubmit,
  }
}

/**
 * The page's one write session: the assembly of the core and its families.
 *
 * Every family factory above returns only its own commands, and this function is
 * the single place that knows they all belong to one surface.  It performs no
 * policy itself: the snapshots, the lock queries and the hard reset come from the
 * core, and each family's commands come from that family.
 */
export function useTrackingWriteSession(): TrackingWriteSessionApi {
  const core = createTrackingWriteCore()
  const submitFamily = createSubmitFamily(core)
  const recoveryFamily = createRecoveryFamily(core)
  const managementFamily = createManagementFamily(core)
  const planDeleteFamily = createPlanDeleteFamily(core)
  const checkFamily = createCheckFamily(core)
  const resubmitFamily = createResubmitFamily(core)
  const batchFamily = createBatchFamily(core)
  return {
    // -- snapshots and lock queries, all from the one core ------------------
    sessions: core.sessions,
    loading: core.loading,
    pending: core.pending,
    planDelete: core.planDelete,
    check: core.check,
    checkLoading: core.checkLoading,
    autoCheckArmed: core.autoCheckArmed,
    resubmit: core.resubmit,
    resubmitLoading: core.resubmitLoading,
    batchSelection: core.batchSelection,
    batchOutcome: core.batchOutcome,
    batchLoading: core.batchLoading,
    batchNotice: core.batchNotice,
    batchSkippedNotice: core.batchSkippedNotice,
    hasUnresolvedLock: core.hasUnresolvedLock,
    unresolvedOwner: core.unresolvedOwner,
    busyFor: core.busyFor,
    noticeFor: core.noticeFor,
    reset: core.reset,
    preserveAfterClear: core.preserveAfterClear,
    setPending: core.setPending,
    finishAttempt: core.finishAttempt,
    // -- one command set per family -----------------------------------------
    ...submitFamily,
    ...recoveryFamily,
    ...managementFamily,
    ...planDeleteFamily,
    ...checkFamily,
    ...resubmitFamily,
    ...batchFamily,
  }
}
