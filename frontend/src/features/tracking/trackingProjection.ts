/**
 * API-free tracking page projection and intent helpers (US-304, US-309, US-310,
 * US-311, US-312).
 *
 * This module only consumes generated OpenAPI operation types. It never
 * performs transport, reconstructs server state, or stores an intent/key.
 */
import type { paths } from '@/api/generated/api'
import type { operations } from '@/api/generated/api'

type ApiPath = Extract<keyof paths, string>

export type TrackingListResult = NonNullable<
  operations['listTrackingItems']['responses']['200']['content']['application/json']['result']
>
export type TrackingItem = TrackingListResult['items'][number]
export type TrackingAction = NonNullable<TrackingItem['available_actions']>[number]
export type TrackingActionCode = TrackingAction['code']
export type TrackingActionStyle = TrackingAction['style']
export type TrackingScope = NonNullable<TrackingAction['target_scopes']>[number]
export type CapabilityResult = NonNullable<
  operations['probeSavedAutoBangumiCapabilities']['responses']['200']['content']['application/json']['result']
>
export type CapabilityState = CapabilityResult['subscription_modify']
export type TrackingRevalidateBody = NonNullable<
  operations['revalidateTrackingItem']['requestBody']['content']['application/json']
>
export type TrackingRevalidateResult = NonNullable<
  operations['revalidateTrackingItem']['responses']['200']['content']['application/json']['result']
>
export type TrackingRevalidateIssue = NonNullable<TrackingRevalidateResult['issues']>[number]
export type TrackingSubmitBody = NonNullable<
  operations['submitTrackingItem']['requestBody']['content']['application/json']
>
export type TrackingSubmitResult = NonNullable<
  operations['submitTrackingItem']['responses']['200']['content']['application/json']['result']
>
export type TrackingRetryBody = NonNullable<
  operations['retryTrackingItem']['requestBody']['content']['application/json']
>
export type TrackingRetryResult = NonNullable<
  operations['retryTrackingItem']['responses']['200']['content']['application/json']['result']
>
/**
 * ``submit`` and ``retry`` are the two submit-family external writes (US-226):
 * the retry endpoint accepts exactly the same revision/key/confirm/credential
 * body and answers with the same persisted-outcome result.
 */
export type TrackingWriteBody = TrackingSubmitBody | TrackingRetryBody
export type TrackingWriteResult = TrackingSubmitResult | TrackingRetryResult
export type TrackingRecoverBody = NonNullable<
  operations['recoverTrackingItem']['requestBody']['content']['application/json']
>
export type TrackingResubmitBody = NonNullable<
  operations['resubmitTrackingItem']['requestBody']['content']['application/json']
>
export type TrackingResubmitResult = NonNullable<
  operations['resubmitTrackingItem']['responses']['200']['content']['application/json']['result']
>
export type TrackingRecoverResult = NonNullable<
  operations['recoverTrackingItem']['responses']['200']['content']['application/json']['result']
>
/**
 * The request-scoped Auto Bangumi connection the page holds after one successful
 * probe.  The generated probe body keeps ``base_url`` optional, so the recovery
 * body builder normalizes it into the strict recover shape and refuses to send a
 * credential that has no server address at all.
 */
export interface TrackingSessionAbConfig {
  connection_ref?: string | null
  configuration_revision?: number
}

export const TRACKING_STATUS_GROUPS = [
  'PENDING', 'PROCESSING', 'ACTIVE', 'ATTENTION', 'INACTIVE',
] as const satisfies readonly TrackingItem['status_group'][]

export type TrackingStatusGroup = (typeof TRACKING_STATUS_GROUPS)[number]

/**
 * Overview cards (issue #85). PROCESSING is a transient per-row state and
 * deliberately has no category of its own — those rows stay visible in the list
 * and inside the server total.
 */
/**
 * Issue #99: the overview is fixed at five categories. 已加入下载 is not a status
 * group of its own — it is counted separately from 追番中 — so this list is its
 * own union rather than the server's status groups.
 */
export const TRACKING_OVERVIEW_GROUPS = [
  'PENDING', 'ACTIVE', 'INACTIVE', 'ADDED_TO_DOWNLOAD', 'ATTENTION',
] as const

export type TrackingOverviewGroup = (typeof TRACKING_OVERVIEW_GROUPS)[number]

export interface TrackingOverview {
  total: number
  byGroup: Record<TrackingOverviewGroup, number>
  unreadable: number
}

/** Server-authoritative list counts from ``GET /api/v1/tracking/items``. */
export interface TrackingListSummary {
  total: number
  pending: number
  processing: number
  active: number
  /** Issue #99: one-time acceptances, counted separately from 追番中. */
  added_to_download: number
  inactive: number
  needs_attention: number
  unreadable: number
}

export interface TrackingFilter {
  query?: string
  statusGroup?: TrackingStatusGroup | ''
}

export interface TrackingActionIntent {
  readonly action: TrackingActionCode
  readonly targetScope?: TrackingScope
  readonly expectedRevision: number
  readonly confirm: true
  readonly idempotencyKey: string
}

const KNOWN_ACTIONS = new Set<TrackingActionCode>([
  'REVALIDATE', 'SUBMIT', 'RETRY', 'RECOVER_AUTO', 'MARK_SUCCEEDED',
  'MARK_FAILED', 'MODIFY', 'SET_ENABLED', 'REFRESH_RSS', 'DELETE_EXTERNAL',
])
const KNOWN_STYLES = new Set<TrackingActionStyle>(['PRIMARY', 'SECONDARY', 'DANGER'])
const KNOWN_SCOPES = new Set<TrackingScope>(['SUBSCRIPTION', 'ASSOCIATED_RSS'])
export const MANAGEMENT_CAPABILITY: Partial<Record<TrackingActionCode, Partial<Record<TrackingScope, keyof CapabilityResult>>>> = {
  MODIFY: { SUBSCRIPTION: 'subscription_modify', ASSOCIATED_RSS: 'rss_modify' },
  SET_ENABLED: { SUBSCRIPTION: 'subscription_enable', ASSOCIATED_RSS: 'rss_enable' },
  REFRESH_RSS: { ASSOCIATED_RSS: 'rss_refresh' },
  DELETE_EXTERNAL: { SUBSCRIPTION: 'subscription_delete', ASSOCIATED_RSS: 'rss_delete' },
}

/**
 * The scope of a management action *as it is being requested* (US-313).
 *
 * ``TrackingScope`` is the generated public scope enum, but the requested scope
 * is only real if this page has a builder for it: a scope without a request body
 * shape can never be sent, so it fails closed here rather than at the boundary.
 */
export const TRACKING_MANAGEMENT_SCOPES = ['SUBSCRIPTION', 'ASSOCIATED_RSS'] as const

export type TrackingManagementScope = (typeof TRACKING_MANAGEMENT_SCOPES)[number]

export function isTrackingManagementScope(value: unknown): value is TrackingManagementScope {
  return value === 'SUBSCRIPTION' || value === 'ASSOCIATED_RSS'
}

/** Fixed Chinese labels for the two management scopes; the raw enum never renders. */
export const MANAGEMENT_SCOPE_LABELS = {
  SUBSCRIPTION: '外部番剧订阅',
  ASSOCIATED_RSS: '关联 RSS',
} as const satisfies Record<TrackingManagementScope, string>

/** The enable/disable direction implied by the record's own server status. */
export function managementEnableDirection(status: unknown): boolean | null {
  if (status === 'DISABLED') return true
  if (status === 'ACTIVE' || status === 'EXTERNAL_ONLY') return false
  return null
}

const MANAGEMENT_ACTION_CODES = new Set<TrackingActionCode>(['MODIFY', 'SET_ENABLED', 'REFRESH_RSS', 'DELETE_EXTERNAL'])

/**
 * The management family as a set, so the page can route one action code to the
 * management write path without re-deriving it from the scope list.
 */
export function isManagementActionCode(value: TrackingActionCode): value is TrackingManagementActionCode {
  return MANAGEMENT_ACTION_CODES.has(value)
}

export type TrackingManagementActionCode =
  'MODIFY' | 'SET_ENABLED' | 'REFRESH_RSS' | 'DELETE_EXTERNAL'

function isKnownStatusGroup(value: unknown): value is TrackingStatusGroup {
  return typeof value === 'string' && TRACKING_STATUS_GROUPS.includes(value as TrackingStatusGroup)
}

function isKnownAction(value: unknown): value is TrackingActionCode {
  return typeof value === 'string' && KNOWN_ACTIONS.has(value as TrackingActionCode)
}

function isKnownStyle(value: unknown): value is TrackingActionStyle {
  return typeof value === 'string' && KNOWN_STYLES.has(value as TrackingActionStyle)
}

function isKnownScope(value: unknown): value is TrackingScope {
  return typeof value === 'string' && KNOWN_SCOPES.has(value as TrackingScope)
}

/**
 * Project the overview strictly from the server summary (issue #85).
 *
 * The page never rebuilds the server state machine: counts come from the
 * authoritative projection, and any missing or malformed value renders 0
 * instead of being guessed from whichever rows happen to be loaded/filtered.
 */
export function projectTrackingOverview(
  summary: TrackingListSummary | null | undefined,
): TrackingOverview {
  return {
    total: _safeCount(summary?.total),
    byGroup: {
      PENDING: _safeCount(summary?.pending),
      ACTIVE: _safeCount(summary?.active),
      INACTIVE: _safeCount(summary?.inactive),
      ADDED_TO_DOWNLOAD: _safeCount(summary?.added_to_download),
      ATTENTION: _safeCount(summary?.needs_attention),
    },
    unreadable: _safeCount(summary?.unreadable),
  }
}

/**
 * Issue #99 AC 6/7: the visible label for an operation-level submission mode.
 *
 * 待提交/需修改 carry no mode (the server sends ``null``), and any unknown or
 * unreadable value fails closed to ``null`` so the page never fabricates one.
 */
export function formatSubmissionMode(value: unknown): string | null {
  if (value === 'CONTINUE_TRACKING') return '持续追番'
  if (value === 'DOWNLOAD_EXISTING') return '下载现有资源'
  return null
}

function _safeCount(value: unknown): number {
  return typeof value === 'number' && Number.isFinite(value) && value > 0 ? Math.trunc(value) : 0
}

/** Format a server timestamp for the list's "最近更新时间" column (issue #85). */
export function formatTrackingUpdatedAt(value: string | null | undefined): string {
  if (typeof value !== 'string' || !value.trim()) return '更新时间不可用'
  const parsed = new Date(value)
  if (Number.isNaN(parsed.getTime())) return '更新时间不可用'
  return new Intl.DateTimeFormat('zh-CN', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
  }).format(parsed)
}

/** Search only public title/subtitle fields and apply a server status group. */
export function filterTrackingItems(
  items: readonly TrackingItem[],
  filter: TrackingFilter = {},
): TrackingItem[] {
  const query = filter.query?.trim().toLocaleLowerCase('zh-CN') ?? ''
  const group = filter.statusGroup ?? ''
  return items.filter((item) => {
    const matchesQuery = !query || [item.title, item.subtitle_group]
      .filter((value): value is string => typeof value === 'string')
      .some((value) => value.toLocaleLowerCase('zh-CN').includes(query))
    const matchesGroup = !group || (isKnownStatusGroup(item.status_group) && item.status_group === group)
    return matchesQuery && matchesGroup
  })
}

/** Sort valid timestamps in real time; invalid/missing values stay at the end. */
export function sortTrackingItems(items: readonly TrackingItem[]): TrackingItem[] {
  return items.slice().sort((left, right) => {
    const leftTime = parseUpdatedAt(left.updated_at)
    const rightTime = parseUpdatedAt(right.updated_at)
    if (leftTime === null && rightTime === null) return 0
    if (leftTime === null) return 1
    if (rightTime === null) return -1
    return rightTime - leftTime
  })
}

function parseUpdatedAt(value: TrackingItem['updated_at']): number | null {
  if (typeof value !== 'string' || !value.trim()) return null
  const timestamp = Date.parse(value)
  return Number.isNaN(timestamp) ? null : timestamp
}

function supported(capabilities: CapabilityResult | null | undefined, field: keyof CapabilityResult): boolean {
  return capabilities?.probe_status === 'VERIFIED' && capabilities[field] === 'SUPPORTED'
}

/**
 * Filter server actions by strict known values only.
 *
 * Issue #86/#89: a settings-page probe is diagnostic, never an authorization
 * gate. Every external write re-validates the saved connection, credentials,
 * exact version and write capability inside the same server request and fails
 * closed, so unknown action/scope values still fail closed here while a
 * diagnostic "unsupported" probe no longer hides an action.
 */
export function executableTrackingActions(item: TrackingItem): TrackingAction[] {
  const result: TrackingAction[] = []
  for (const action of item.available_actions ?? []) {
    if (!isKnownAction(action.code) || !isKnownStyle(action.style)) continue
    const rawScopes = Array.isArray(action.target_scopes) ? action.target_scopes : []
    const scopes = rawScopes.filter(isKnownScope)
    if (scopes.length !== rawScopes.length || new Set(scopes).size !== scopes.length) continue
    const capability = MANAGEMENT_CAPABILITY[action.code]
    if (capability) {
      // A management action needs a real, known target scope; the server owns
      // whether this connection can actually perform it (issue #89).
      if (scopes.length === 0) continue
      result.push({ ...action, target_scopes: scopes })
      continue
    }
    if (action.code === 'SUBMIT' || action.code === 'RETRY') {
      // Issue #86: submission is offered whenever the server projects the
      // action. The server re-validates the saved connection, authentication,
      // exact version and write capability inside the same request and fails
      // closed, so a settings-page probe is diagnostic only — never a gate.
      if (scopes.length > 0) continue
    } else if (scopes.length > 0) {
      continue
    }
    result.push(action)
  }
  return result
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

/**
 * Page-owned result of one unified plan delete (issue #92).
 *
 * ``DELETED`` is the only state where the local plan and its tracking record are
 * gone; the two external states mean nothing local was removed and the user must
 * retry or recover deliberately.
 */
export type TrackingPlanDeleteState = 'IN_FLIGHT' | 'DELETED' | 'EXTERNAL_FAILED' | 'EXTERNAL_UNKNOWN'

export interface TrackingPlanDeleteSession {
  readonly trackingId: string
  readonly state: TrackingPlanDeleteState
  readonly message: string
}

const PLAN_DELETE_MESSAGES: Record<TrackingPlanDeleteState, string> = {
  IN_FLIGHT: '正在删除追番方案，请稍候…',
  DELETED: '追番方案已删除。',
  EXTERNAL_FAILED: 'Auto Bangumi 未删除该受控外部订阅，本地方案与追番记录均已保留；请核对后重试。',
  EXTERNAL_UNKNOWN: '外部删除结果未知，本地方案与追番记录均已保留；请先恢复核验后再决定。',
}

export function createPlanDeleteSession(
  trackingId: string,
  state: TrackingPlanDeleteState,
): TrackingPlanDeleteSession {
  return { trackingId, state, message: PLAN_DELETE_MESSAGES[state] }
}

export function makeOpaqueKey(): string {
  const candidate = globalThis.crypto?.randomUUID?.()
  return candidate && /^[A-Za-z0-9-]{8,128}$/.test(candidate)
    ? candidate
    : `intent-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 14)}`
}

/** Create one in-memory intent; callers must keep it local to the action. */
export function createTrackingActionIntent(
  item: TrackingItem,
  action: TrackingAction,
  targetScope?: TrackingScope,
): TrackingActionIntent | null {
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

/** Transport retries reuse exactly the same intent/key; no new key is made. */
export function reuseTrackingActionIntent(intent: TrackingActionIntent): TrackingActionIntent {
  return intent
}

/**
 * Capability display projection (US-307 review fix).
 *
 * The generated probe result is the only source. These helpers turn whitelisted
 * enum fields into fixed Chinese labels; they never accept or render endpoint,
 * account, credential, adapter or any other free-form server value.
 */
export const CAPABILITY_SUMMARY_FIELDS = [
  { key: 'subscription_list', label: '读取订阅列表' },
  { key: 'subscription_detail', label: '读取订阅详情' },
  { key: 'subscription_submit', label: '新增订阅' },
  { key: 'subscription_modify', label: '修改订阅' },
  { key: 'subscription_enable', label: '启用订阅' },
  { key: 'subscription_disable', label: '停用订阅' },
  { key: 'subscription_delete', label: '删除订阅' },
  { key: 'rss_list', label: '读取 RSS 列表' },
  { key: 'rss_modify', label: '修改 RSS' },
  { key: 'rss_enable', label: '启用 RSS' },
  { key: 'rss_disable', label: '停用 RSS' },
  { key: 'rss_delete', label: '删除 RSS' },
  { key: 'rss_refresh', label: '刷新 RSS' },
  { key: 'external_verify', label: '外部核验' },
] as const satisfies ReadonlyArray<{ key: keyof CapabilityResult; label: string }>

export interface CapabilitySummaryEntry {
  key: (typeof CAPABILITY_SUMMARY_FIELDS)[number]['key']
  label: string
  state: CapabilityState
}

const CAPABILITY_STATE_LABELS: Record<CapabilityState, string> = {
  SUPPORTED: '支持', UNSUPPORTED: '不支持', UNKNOWN: '未知',
}
const PROBE_STATUS_LABELS: Record<string, string> = {
  VERIFIED: '已验证', PARTIAL: '部分验证', FAILED: '探测失败',
}
// Version is the only free-form value rendered; keep it to a plain version token
// so a hostile server value can never smuggle an endpoint or URL into the DOM.
const SAFE_VERSION_PATTERN = /^[A-Za-z0-9][A-Za-z0-9._+-]{0,31}$/

/** Unknown or unexpected server values always fail closed to 未知. */
export function capabilityState(value: unknown): CapabilityState {
  return value === 'SUPPORTED' || value === 'UNSUPPORTED' ? value : 'UNKNOWN'
}

export function capabilityStateLabel(value: unknown): string {
  return CAPABILITY_STATE_LABELS[capabilityState(value)] ?? '未知'
}

export function probeStatusLabel(status: string): string {
  return PROBE_STATUS_LABELS[status] ?? '未确认'
}

/** Version is the only free-form field shown, and only as a plain version token. */
export function capabilityVersionLabel(capabilities: CapabilityResult): string {
  const version = typeof capabilities.version === 'string' ? capabilities.version.trim() : ''
  return SAFE_VERSION_PATTERN.test(version) ? version : '未确认'
}

export function projectCapabilitySummary(capabilities: CapabilityResult): CapabilitySummaryEntry[] {
  return CAPABILITY_SUMMARY_FIELDS.map((field) => ({
    key: field.key,
    label: field.label,
    state: capabilityState(capabilities[field.key]),
  }))
}

/**
 * Revalidation issue projection (US-309).
 *
 * ``ready=false`` is an HTTP 200 business result, so the server's fixed §11.5
 * issue list is the only explanation of why no external subscription exists.
 * Only the documented code enum is renderable: an unrecognized code is dropped
 * rather than echoing an unvetted server string into the DOM, and a known code
 * whose message is missing falls back to fixed Chinese copy.
 */
export const REVALIDATE_ISSUE_CODES = [
  'REQUEST_MISSING', 'REQUEST_NOT_ACCEPTED', 'REQUEST_CHANGED', 'TITLE_MISSING',
  'SEASON_REVIEW_REQUIRED', 'MIKAN_SELECTION_MISSING', 'SUBTITLE_GROUP_MISSING',
  'NO_VALID_RESOURCES', 'EXTERNAL_ALREADY_LINKED', 'OPERATION_IN_PROGRESS',
  'TRACKING_STATE_INVALID',
] as const satisfies readonly TrackingRevalidateIssue['code'][]

export interface TrackingRevalidateIssueView {
  code: TrackingRevalidateIssue['code']
  message: string
}

const KNOWN_REVALIDATE_ISSUE_CODES = new Set<string>(REVALIDATE_ISSUE_CODES)

/** Fixed copy used when a known code arrives without a usable message. */
export const REVALIDATE_ISSUE_FALLBACK_MESSAGE = '本地方案尚未通过提交前复核。'

/** True only for the documented §11.5 issue code enum. */
export function isKnownRevalidateIssueCode(value: unknown): value is TrackingRevalidateIssue['code'] {
  return typeof value === 'string' && KNOWN_REVALIDATE_ISSUE_CODES.has(value)
}

/** Project the §11.5 issue list, keeping server order and dropping unknown codes. */
export function projectRevalidateIssues(issues: unknown): TrackingRevalidateIssueView[] {
  if (!Array.isArray(issues)) return []
  const views: TrackingRevalidateIssueView[] = []
  const seen = new Set<string>()
  for (const issue of issues) {
    const candidate = issue as { code?: unknown; message?: unknown } | null
    if (!candidate || !isKnownRevalidateIssueCode(candidate.code) || seen.has(candidate.code)) continue
    seen.add(candidate.code)
    const message = typeof candidate.message === 'string' ? candidate.message.trim() : ''
    views.push({ code: candidate.code, message: message || REVALIDATE_ISSUE_FALLBACK_MESSAGE })
  }
  return views
}

/**
 * Submit-family external writes (US-310, US-311).
 *
 * The generated path template and the impact confirmation are bound to the
 * server-computed action code, so the page can never send one action's request
 * with another action's copy. Both need a live page credential session, the
 * latest revision and an explicit confirmation.
 */
export const WRITE_ACTION_ENDPOINTS = {
  SUBMIT: '/api/v1/tracking/items/{tracking_id}/submit',
  RETRY: '/api/v1/tracking/items/{tracking_id}/retry',
} as const satisfies Record<string, ApiPath>

export type TrackingWriteActionCode = keyof typeof WRITE_ACTION_ENDPOINTS

export interface TrackingWriteConfirmation {
  title: string
  message: string
  confirmLabel: string
}

export const WRITE_ACTION_CONFIRMATIONS: Record<TrackingWriteActionCode, TrackingWriteConfirmation> = {
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

/** True only for the submit-family actions this page knows how to send. */
export function isWriteActionCode(value: TrackingActionCode): value is TrackingWriteActionCode {
  return value === 'SUBMIT' || value === 'RETRY'
}

/**
 * Explicit external submission and retry (US-310, US-311).
 *
 * The page-level write session below describes one item-scoped external write:
 * ``state`` is either the persisted business outcome the server returned, the
 * in-flight marker, or one of the three client-side states that describe what
 * the server refused/told us (a conflict, a definite pre-write HTTP rejection,
 * or an unreadable result). Fixed Chinese copy only — the raw server enum never
 * reaches the DOM.
 */
export const SUBMIT_OUTCOMES = [
  'ACTIVE', 'SUBMIT_FAILED', 'NEEDS_RECONFIRM', 'VERIFYING_EXTERNAL', 'RECOVERY_REQUIRED',
  // Issue #98/#99: a one-time "download existing resources" request Auto
  // Bangumi accepted. It is local history, not an external subscription.
  'ADDED_TO_DOWNLOAD',
] as const satisfies readonly TrackingSubmitResult['outcome'][]

export type TrackingSubmitOutcome = (typeof SUBMIT_OUTCOMES)[number]

/**
 * ``UNKNOWN`` also covers a transport result we could not read at all.
 * ``REJECTED`` is the definite counterpart: a structured non-409 HTTP 4xx the
 * server returned *before* the external boundary (D38-08.5), so Auto Bangumi
 * was provably never written.
 */
export type TrackingWriteState = 'IN_FLIGHT' | TrackingSubmitOutcome | 'CONFLICT' | 'REJECTED' | 'UNKNOWN'

/**
 * Published, non-sensitive failure classification (issue #86). The server sends
 * only this code; every user-facing sentence lives here so an upstream response
 * can never reach the UI.
 */
export const WRITE_FAILURE_CATEGORIES = [
  'CONNECTION', 'AUTHENTICATION', 'VERSION', 'DUPLICATE_SUBSCRIPTION',
  'VALIDATION', 'REJECTED', 'OUTCOME_UNKNOWN',
] as const

export type WriteFailureCategory = (typeof WRITE_FAILURE_CATEGORIES)[number]

export interface WriteFailurePresentation {
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

export const WRITE_FAILURE_PRESENTATIONS: Readonly<Record<WriteFailureCategory, WriteFailurePresentation>> = {
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
    title: '提交结果未知',
    message: '无法确认 Auto Bangumi 是否已创建订阅。请先使用恢复核验，未确认前不会再次提交。',
    channel: 'recovery',
  },
}

/** Parse the server's published category; anything unknown fails closed. */
export function writeFailureCategory(value: unknown): WriteFailureCategory | null {
  return typeof value === 'string' && (WRITE_FAILURE_CATEGORIES as readonly string[]).includes(value)
    ? (value as WriteFailureCategory)
    : null
}

export interface TrackingWriteSession {
  readonly trackingId: string
  readonly action: TrackingActionCode
  readonly state: TrackingWriteState
  readonly message: string
  readonly issues: TrackingRevalidateIssueView[]
  /** Published failure class of a failed/indeterminate result, when provided. */
  readonly failureCategory: WriteFailureCategory | null
  /**
   * Issue #101: the bounded, sanitized Auto Bangumi reason for a failure. Empty
   * means Auto Bangumi gave none, and the page then says 未提供具体原因.
   */
  readonly diagnostics: TrackingWriteDiagnostics
}

export interface TrackingWriteDiagnostics {
  readonly httpStatus: number | null
  readonly messageZh: string | null
  readonly messageEn: string | null
}

/** Issue #101 AC 1: a one-time failure never claims an external effect either way. */
export const ONE_TIME_SUBMIT_FAILED_MESSAGE = '提交失败，可重新提交。'

export function projectWriteDiagnostics(value: unknown): TrackingWriteDiagnostics {
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
 * Every 409 the submit-family endpoints document (US-225/US-226) means the
 * request was refused *before* the external boundary: Auto Bangumi was never
 * called with it. The record summary in the error body is not authoritative, so
 * the page converges by re-reading the server tracking and asks the user to
 * confirm again — never by resending. Each documented type gets its own fixed
 * Chinese next step; an unrecognized one falls back to the generic copy.
 */
export const WRITE_CONFLICT_TYPES = [
  'tracking_revision_conflict', 'tracking_idempotency_conflict',
  'tracking_state_conflict', 'tracking_operation_in_progress',
] as const

export type TrackingWriteConflictType = (typeof WRITE_CONFLICT_TYPES)[number]

export const WRITE_CONFLICT_FALLBACK_MESSAGE =
  '追番记录已变化或当前状态不允许提交，本次未提交到 Auto Bangumi；正在刷新最新详情，请重新确认后再提交。'

const WRITE_CONFLICT_MESSAGES: Record<TrackingWriteConflictType, string> = {
  tracking_revision_conflict:
    '追番记录已变化，本次未提交到 Auto Bangumi；正在刷新最新详情，请重新确认后再提交。',
  tracking_idempotency_conflict:
    '本次提交标识已失效，未提交到 Auto Bangumi；正在刷新最新详情，请重新确认后再提交。',
  tracking_state_conflict:
    '当前追番状态不允许本次提交，未提交到 Auto Bangumi；正在刷新最新详情，请按最新状态重新确认。',
  tracking_operation_in_progress:
    '存在尚未完成的提交操作，本次未提交到 Auto Bangumi；正在刷新最新详情，请先完成恢复后再提交。',
}

const WRITE_MESSAGES: Record<TrackingWriteState, string> = {
  IN_FLIGHT: '正在提交到 Auto Bangumi，请稍候…',
  ACTIVE: '提交成功：已在 Auto Bangumi 创建外部订阅。',
  // Issue #98/#99: a one-time acceptance — no subscription, no media promise.
  ADDED_TO_DOWNLOAD: '已加入下载：Auto Bangumi 已接受本次下载现有资源的请求，不代表资源已下载完成。',
  SUBMIT_FAILED: '提交明确失败，尚未创建外部订阅；可在确认后显式重试。',
  NEEDS_RECONFIRM: '本地方案已变化，本次尚未创建外部订阅；请返回修改方案后重新确认。',
  VERIFYING_EXTERNAL: '外部提交结果未知，正在只读回查；请勿重复提交。',
  RECOVERY_REQUIRED: '本地结果未完成落盘，需要恢复；请勿重复提交。',
  CONFLICT: WRITE_CONFLICT_FALLBACK_MESSAGE,
  // A structured non-409 4xx is decided before the external boundary, so the
  // copy states plainly that nothing was created; the raw error_type/status is
  // deliberately never rendered.
  REJECTED: '服务端明确拒绝了本次请求，本次未创建 Auto Bangumi 外部订阅；正在刷新最新详情，请重新确认后再提交。',
  UNKNOWN: '提交结果未知，正在只读回查；未确认生效前不会再次提交。',
}

const KNOWN_SUBMIT_OUTCOMES = new Set<string>(SUBMIT_OUTCOMES)

function isSubmitOutcome(value: unknown): value is TrackingSubmitOutcome {
  return typeof value === 'string' && KNOWN_SUBMIT_OUTCOMES.has(value)
}

export function writeSessionMessage(state: TrackingWriteState): string {
  return WRITE_MESSAGES[state]
}

export function createWriteSession(
  trackingId: string,
  action: TrackingActionCode,
  state: TrackingWriteState,
  issues: TrackingRevalidateIssueView[] = [],
  failureCategory: WriteFailureCategory | null = null,
  submissionMode: 'CONTINUE_TRACKING' | 'DOWNLOAD_EXISTING' | null = null,
  diagnostics: TrackingWriteDiagnostics = { httpStatus: null, messageZh: null, messageEn: null },
): TrackingWriteSession {
  // A published failure class owns the copy for its own channel; otherwise the
  // fixed per-state sentence stays authoritative. A one-time attempt has no
  // external subscription to reason about, so its failure copy is the plain
  // retryable sentence (issue #101 AC 1).
  const message = state === 'SUBMIT_FAILED' && submissionMode === 'DOWNLOAD_EXISTING'
    ? ONE_TIME_SUBMIT_FAILED_MESSAGE
    : failureCategory
      ? WRITE_FAILURE_PRESENTATIONS[failureCategory].message
      : WRITE_MESSAGES[state]
  return { trackingId, action, state, message, issues, failureCategory, diagnostics }
}

/** Fixed next step for one documented conflict; unknown types fail closed. */
export function writeConflictMessage(errorType: unknown): string {
  return typeof errorType === 'string' && (WRITE_CONFLICT_TYPES as readonly string[]).includes(errorType)
    ? WRITE_CONFLICT_MESSAGES[errorType as TrackingWriteConflictType]
    : WRITE_CONFLICT_FALLBACK_MESSAGE
}

/**
 * A 409 refuses the request before the external boundary, so this session is
 * released immediately (`writeSessionKeepsIntent('CONFLICT') === false`) and the
 * page re-reads the server tracking before asking for a new confirmation.
 */
export function createWriteConflictSession(
  trackingId: string,
  action: TrackingActionCode,
  errorType: unknown,
): TrackingWriteSession {
  return {
    trackingId, action, state: 'CONFLICT',
    message: writeConflictMessage(errorType), issues: [], failureCategory: null,
    diagnostics: { httpStatus: null, messageZh: null, messageEn: null },
  }
}

/**
 * True only for a structured JSON 400/404 pre-boundary refusal (D38-08.5).
 *
 * Only the documented 400/404 JSON envelope is known to be raised before the
 * external boundary. A network failure, timeout, non-JSON body, 5xx, 408/429,
 * or another status stays ``UNKNOWN`` because it may already have reached it.
 */
export function isDefiniteWriteRejection(error: {
  status: number
  httpError: boolean
  nonJson?: boolean
  network?: boolean
  cancelled?: boolean
}): boolean {
  // Only documented JSON pre-boundary refusals release an intent. Proxy HTML,
  // cancellation/network failures, and statuses such as 408/429 may have
  // crossed the external boundary and therefore remain UNKNOWN.
  return error.httpError === true
    && error.nonJson !== true
    && error.network !== true
    && error.cancelled !== true
    && (error.status === 400 || error.status === 404)
}

/**
 * Project one HTTP 200 submit-family result. Issue #184's resubmit answers with
 * the same generated write fields plus its own two-phase metadata, so both
 * contracts project through one function; an outcome we do not recognize is
 * treated exactly like an unreadable transport result — read back, never
 * resubmit blind.
 */
export function projectWriteOutcome(
  trackingId: string,
  action: TrackingActionCode,
  result: TrackingWriteResult | TrackingResubmitResult,
  submissionMode: 'CONTINUE_TRACKING' | 'DOWNLOAD_EXISTING' | null = null,
): TrackingWriteSession {
  const outcome: TrackingWriteState = isSubmitOutcome(result.outcome) ? result.outcome : 'UNKNOWN'
  return createWriteSession(
    trackingId,
    action,
    outcome,
    projectRevalidateIssues(result.issues),
    writeFailureCategory(result.failure_category),
    submissionMode,
    projectWriteDiagnostics((result as { diagnostics?: unknown }).diagnostics),
  )
}

/**
 * True only while the external result is still indeterminate.
 *
 * These are the states where a transport retry must reuse the *same* opaque key:
 * the external call may already have happened, so minting a new key could create
 * a second subscription.  Every definite result (an explicit business failure
 * and a pre-write HTTP rejection alike) releases the intent so the next user
 * confirmation gets a fresh key.
 */
export function writeSessionKeepsIntent(state: TrackingWriteState): boolean {
  return state === 'UNKNOWN' || state === 'VERIFYING_EXTERNAL' || state === 'RECOVERY_REQUIRED'
}

/**
 * Unknown-result recovery (US-312).
 *
 * The page never guesses a recovery action. ``RECOVER_AUTO``, ``MARK_SUCCEEDED``
 * and ``MARK_FAILED`` are rendered only when the server's ``available_actions``
 * offers them for the current status (they are pure-local: no capability, no
 * credential, no external call). ``VERIFY_EXTERNAL`` is *never* in
 * ``available_actions`` — it is the recovery flow's own read-only choice, offered
 * only while the page holds a live credential session that proves
 * ``external_verify``; it re-reads the record's current operation and can never
 * create, modify or delete an external subscription.
 */
export const RECOVERY_ACTIONS = [
  'RECOVER_AUTO', 'MARK_SUCCEEDED', 'MARK_FAILED', 'VERIFY_EXTERNAL',
] as const

export type TrackingRecoveryActionCode = (typeof RECOVERY_ACTIONS)[number]

/**
 * The single recover endpoint. Every action is bound to exactly one request
 * body value below, so the button the user pressed can never send another
 * action's request.
 */
export const TRACKING_RECOVER_ENDPOINT =
  '/api/v1/tracking/items/{tracking_id}/recover' as const satisfies ApiPath

export const RECOVERY_ACTION_BODIES = {
  RECOVER_AUTO: 'AUTO',
  MARK_SUCCEEDED: 'MARK_SUCCEEDED',
  MARK_FAILED: 'MARK_FAILED',
  VERIFY_EXTERNAL: 'VERIFY_EXTERNAL',
} as const satisfies Record<TrackingRecoveryActionCode, TrackingRecoverBody['action']>

export interface TrackingRecoveryConfirmation {
  title: string
  message: string
  confirmLabel: string
  /** Only the manual "mark as failed" conclusion is styled as a danger. */
  danger?: boolean
}

/**
 * A manual conclusion is a user assertion about the external world, so it is
 * always confirmed a second time and the confirmation tells the user to check
 * Auto Bangumi first. ``VERIFY_EXTERNAL`` is confirmed too because it spends the
 * page credential on one external read. ``RECOVER_AUTO`` has no entry at all:
 * it contacts nothing and needs no confirmation.
 */
export const RECOVERY_ACTION_CONFIRMATIONS = {
  MARK_SUCCEEDED: {
    title: '标记为提交成功',
    message: '请先在 Auto Bangumi 中独立核对该追番的实际状态。标记为成功只更新 MiGuOrca 本地追番状态，不会创建、修改或删除任何外部订阅，是否继续？',
    confirmLabel: '确认标记成功',
  },
  MARK_FAILED: {
    title: '标记为提交失败',
    message: '请先在 Auto Bangumi 中独立核对该追番的实际状态。标记为失败只更新 MiGuOrca 本地追番状态，不会删除任何外部订阅，是否继续？',
    confirmLabel: '确认标记失败',
    danger: true,
  },
  VERIFY_EXTERNAL: {
    title: '只读核验外部状态',
    message: '将使用已保存的 Auto Bangumi 连接，只读核对该追番在 Auto Bangumi 中的当前状态；不会创建、修改或删除任何外部订阅，是否继续？',
    confirmLabel: '确认只读核验',
  },
} as const satisfies Record<Exclude<TrackingRecoveryActionCode, 'RECOVER_AUTO'>, TrackingRecoveryConfirmation>

export function isRecoveryActionCode(value: unknown): value is TrackingRecoveryActionCode {
  return typeof value === 'string' && (RECOVERY_ACTIONS as readonly string[]).includes(value)
}

/** Null for ``RECOVER_AUTO``: the local recovery is confirmed by its click alone. */
export function recoveryConfirmation(
  action: TrackingRecoveryActionCode,
): TrackingRecoveryConfirmation | null {
  return action === 'RECOVER_AUTO' ? null : RECOVERY_ACTION_CONFIRMATIONS[action]
}

/** True only while the current probe proves the read-only external check. */
export function canVerifyExternally(capabilities?: CapabilityResult | null): boolean {
  return supported(capabilities, 'external_verify')
}

export interface TrackingRecoveryIntent {
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
export function createTrackingRecoverBody(
  action: TrackingRecoveryActionCode,
  expectedRevision: number,
  connection: TrackingSessionAbConfig | null,
  storageDir?: string,
): TrackingRecoverBody | null {
  const storage = storageDir ? { storage_dir: storageDir } : {}
  if (action === 'VERIFY_EXTERNAL') {
    if (!connection) return null
    return {
      expected_revision: expectedRevision,
      action: RECOVERY_ACTION_BODIES[action],
      connection_ref: connection.connection_ref,
      configuration_revision: connection.configuration_revision,
      ...storage,
    }
  }
  const manual = action === 'MARK_SUCCEEDED' || action === 'MARK_FAILED'
  return {
    expected_revision: expectedRevision,
    action: RECOVERY_ACTION_BODIES[action],
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
export function createTrackingRecoveryIntent(
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

/**
 * ``IN_FLIGHT``/``CONFLICT``/``REJECTED`` are page-level facts about one
 * request; the three outcome values are the persisted server verdicts a
 * recovery may produce. ``UNKNOWN`` also covers an outcome value outside the
 * documented enum, which is never interpreted as success.
 */
export const RECOVERY_OUTCOMES = [
  'ACTIVE', 'SUBMIT_FAILED', 'RECOVERY_REQUIRED',
] as const satisfies readonly TrackingRecoverResult['outcome'][]

export type TrackingRecoveryState =
  | 'IN_FLIGHT' | (typeof RECOVERY_OUTCOMES)[number] | 'CONFLICT' | 'REJECTED' | 'UNKNOWN'

export interface TrackingRecoverySession {
  readonly trackingId: string
  readonly action: TrackingRecoveryActionCode
  readonly state: TrackingRecoveryState
  readonly needsManual: boolean
  readonly message: string
}

const RECOVERY_MESSAGES: Record<TrackingRecoveryState, string> = {
  IN_FLIGHT: '正在恢复该追番的结果，请稍候…',
  ACTIVE: '恢复完成：已确认该追番在 Auto Bangumi 中存在外部订阅。',
  SUBMIT_FAILED: '恢复完成：已确认本次未创建外部订阅，可在确认后显式重试提交。',
  RECOVERY_REQUIRED: '结果仍无法确认，保持恢复状态；未确认前不会自动提交。',
  CONFLICT: '追番记录已变化或当前状态不允许恢复，本次未执行恢复；正在刷新最新详情，请重新确认。',
  REJECTED: '服务端明确拒绝了本次恢复请求，本次未执行任何外部操作；正在刷新最新详情，请重新确认。',
  UNKNOWN: '恢复结果未知，正在只读回查；未确认前不会自动重发。',
}

/** Shown whenever a recovery could not be concluded without a human verdict. */
export const RECOVERY_NEEDS_MANUAL_NOTICE =
  '需要人工核验：请先在 Auto Bangumi 中独立核对该追番的实际状态，再选择“标记为成功”或“标记为失败”；本页不会代替你判断，也不会自动提交。'

export function createRecoverySession(
  trackingId: string,
  action: TrackingRecoveryActionCode,
  state: TrackingRecoveryState,
  needsManual = false,
): TrackingRecoverySession {
  return { trackingId, action, state, needsManual, message: RECOVERY_MESSAGES[state] }
}

/** A 409 refuses the recovery before anything is persisted; ask again. */
export function createRecoveryConflictSession(
  trackingId: string,
  action: TrackingRecoveryActionCode,
): TrackingRecoverySession {
  return createRecoverySession(trackingId, action, 'CONFLICT')
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
export function projectRecoveryOutcome(
  trackingId: string,
  action: TrackingRecoveryActionCode,
  result: TrackingRecoverResult,
): TrackingRecoverySession {
  if (result.needs_manual === true) {
    return createRecoverySession(trackingId, action, 'RECOVERY_REQUIRED', true)
  }
  const outcome: unknown = result.outcome
  if (outcome === 'ACTIVE' || outcome === 'SUBMIT_FAILED') {
    return createRecoverySession(trackingId, action, outcome)
  }
  if (outcome === 'RECOVERY_REQUIRED') {
    return createRecoverySession(trackingId, action, 'RECOVERY_REQUIRED', true)
  }
  return createRecoverySession(trackingId, action, 'UNKNOWN')
}

/**
 * True while the recovery still owns the page's single intent.
 *
 * An unresolved recovery keeps every other item's submit/retry locked (D38-09.4)
 * until the user concludes it; a resolved verdict, a conflict or a definite
 * refusal releases it immediately.
 */
export function recoverySessionKeepsLock(state: TrackingRecoveryState): boolean {
  return state === 'UNKNOWN' || state === 'RECOVERY_REQUIRED'
}

/**
 * External management writes (US-313).
 *
 * Management writes (``MODIFY``, ``SET_ENABLED``, ``REFRESH_RSS``,
 * ``DELETE_EXTERNAL``) are the second external write family.  They share the
 * page's credential session, the impact confirmation, the latest revision and
 * the single page-level intent with the submit family, but their server verdict
 * is ``management_status`` rather than ``outcome`` and ``safe_message`` is not
 * authoritative — a truncated or unrecognized status must never be read as
 * success, so the page states only what it can prove.
 *
 * ``TrackingActionCode`` (not the narrower management union) is used here so the
 * scope-bound request shape stays the only thing that decides whether a request
 * can be sent at all.
 */
export type TrackingManagementState =
  | 'IN_FLIGHT' | 'SUCCEEDED' | 'FAILED' | 'CONFLICT' | 'REJECTED' | 'UNKNOWN'

export interface TrackingManagementSession {
  readonly trackingId: string
  readonly action: TrackingManagementActionCode
  readonly targetScope: TrackingManagementScope
  readonly state: TrackingManagementState
  readonly needsManual: boolean
  readonly message: string
}

/**
 * One fixed message table per action (US-314).
 *
 * Every management action must state exactly what it did or did not do, so the
 * copy is bound to the action code the page sent rather than shared: an RSS
 * refresh never claims a subscription was changed, and an enable/disable never
 * claims a field was modified.  The action is a management code, so the table is
 * total over the whole family.
 */
const MANAGEMENT_ACTION_MESSAGES: Record<
  TrackingManagementActionCode,
  Record<TrackingManagementState, string>
> = {
  MODIFY: {
    IN_FLIGHT: '正在提交外部修改，请稍候…',
    SUCCEEDED: '外部修改已完成：Auto Bangumi 已应用本次修改。',
    FAILED: '外部修改明确失败，Auto Bangumi 未应用本次修改；可核对后重新发起。',
    CONFLICT: '追番记录已变化或当前状态不允许本次管理操作，本次未提交到 Auto Bangumi；正在刷新最新详情，请重新确认。',
    REJECTED: '服务端明确拒绝了本次管理请求，本次未修改 Auto Bangumi 外部订阅；正在刷新最新详情，请重新确认。',
    UNKNOWN: '外部修改结果未知，正在只读回查；未确认生效前不会自动重试。',
  },
  SET_ENABLED: {
    IN_FLIGHT: '正在提交外部启停，请稍候…',
    SUCCEEDED: '外部启停已完成：Auto Bangumi 已应用本次启用或停用。',
    FAILED: '外部启停明确失败，Auto Bangumi 未应用本次启用或停用；可核对后重新发起。',
    CONFLICT: '追番记录已变化或当前状态不允许本次启停，本次未提交到 Auto Bangumi；正在刷新最新详情，请重新确认。',
    REJECTED: '服务端明确拒绝了本次启停请求，本次未改变 Auto Bangumi 的启用状态；正在刷新最新详情，请重新确认。',
    UNKNOWN: '外部启停结果未知，正在只读回查；未确认生效前不会自动重试。',
  },
  REFRESH_RSS: {
    IN_FLIGHT: '正在请求立即刷新资源，请稍候…',
    SUCCEEDED: '关联 RSS 刷新已完成：Auto Bangumi 已接受本次刷新请求。',
    FAILED: '关联 RSS 刷新明确失败，Auto Bangumi 未接受本次刷新；可核对后重新发起。',
    CONFLICT: '追番记录已变化或当前状态不允许立即刷新资源，本次未提交到 Auto Bangumi；正在刷新最新详情，请重新确认。',
    REJECTED: '服务端明确拒绝了本次刷新请求，本次未刷新 Auto Bangumi 关联 RSS；正在刷新最新详情，请重新确认。',
    UNKNOWN: '关联 RSS 刷新结果未知，正在只读回查；未确认完成前不会自动重试。',
  },
  DELETE_EXTERNAL: {
    IN_FLIGHT: '正在提交外部删除，请稍候…',
    SUCCEEDED: '外部删除已完成：Auto Bangumi 已删除该外部对象；MiGuOrca 本地订阅方案、追番记录、审计记录、下载任务和已下载媒体文件均保留。',
    FAILED: '外部删除明确失败，Auto Bangumi 未删除该外部对象；本地方案与已下载媒体未受影响，可核对后重新发起。',
    CONFLICT: '追番记录已变化或当前状态不允许本次删除，本次未提交到 Auto Bangumi；正在刷新最新详情，请重新确认。',
    REJECTED: '服务端明确拒绝了本次删除请求，本次未删除 Auto Bangumi 外部对象；正在刷新最新详情，请重新确认。',
    UNKNOWN: '外部删除结果未知，正在只读回查；未确认删除前不会自动重试，本地方案与已下载媒体未受影响。',
  },
}

/**
 * Every 409 a management endpoint can raise (US-225) happens before the
 * external boundary: the management operation is refused while it is being
 * prepared, so Auto Bangumi was never called with it.  An unrecognized type
 * falls back to generic copy that also claims exactly that.
 */
export const MANAGEMENT_CONFLICT_TYPES = [
  'tracking_revision_conflict', 'tracking_idempotency_conflict',
  'tracking_management_state_conflict', 'tracking_management_patch_invalid',
  'tracking_target_missing', 'tracking_target_drift', 'tracking_target_ambiguous',
  'tracking_mapping_missing',
] as const

export type TrackingManagementConflictType = (typeof MANAGEMENT_CONFLICT_TYPES)[number]

export const MANAGEMENT_CONFLICT_FALLBACK_MESSAGE =
  '追番记录已变化或当前状态不允许本次管理操作，本次未提交到 Auto Bangumi；正在刷新最新详情，请重新确认。'

const MANAGEMENT_CONFLICT_MESSAGES: Record<TrackingManagementConflictType, string> = {
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
  Record<TrackingManagementActionCode, Partial<Record<TrackingManagementConflictType, string>>>
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
export function managementConflictMessage(
  errorType: unknown,
  action?: TrackingManagementActionCode,
): string {
  if (typeof errorType !== 'string' || !(MANAGEMENT_CONFLICT_TYPES as readonly string[]).includes(errorType)) {
    return MANAGEMENT_CONFLICT_FALLBACK_MESSAGE
  }
  const conflict = errorType as TrackingManagementConflictType
  return (action && MANAGEMENT_CONFLICT_ACTION_MESSAGES[action]?.[conflict])
    ?? MANAGEMENT_CONFLICT_MESSAGES[conflict]
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
export function createManagementSession(
  trackingId: string,
  action: TrackingManagementActionCode,
  targetScope: TrackingManagementScope,
  state: TrackingManagementState,
  needsManual = false,
  message?: string,
): TrackingManagementSession {
  return {
    trackingId, action, targetScope, state,
    needsManual,
    message: message ?? MANAGEMENT_ACTION_MESSAGES[action][state],
  }
}

/**
 * The server's own flag wins; when it is missing an unresolved state is still
 * treated as requiring a human verdict rather than being read as decided.
 */
export function managementSessionNeedsManual(state: TrackingManagementState, serverFlag: unknown): boolean {
  if (state === 'SUCCEEDED' || state === 'FAILED' || state === 'CONFLICT' || state === 'REJECTED') {
    return false
  }
  return serverFlag === undefined ? true : serverFlag === true
}

/**
 * True only while a management result is still indeterminate: those are the
 * states where a transport retry must reuse the very same intent (key, scope and
 * patch), because the external change may already have been applied.
 */
export function managementSessionKeepsIntent(session: TrackingManagementSession): boolean {
  return session.state === 'UNKNOWN'
}

/** Shown whenever a management result needs a human verdict before continuing. */
export const MANAGEMENT_NEEDS_MANUAL_NOTICE =
  '需要人工核验：请先在 Auto Bangumi 中独立核对该追番的实际状态，再决定是否重新发起修改；本页不会代替你判断，也不会自动重试。'

/**
 * Bounded read-only confirmation of a pending submission (issue #183).
 *
 * A persistent ``提交`` whose outcome could not be proven shows 结果待确认. The
 * page explains it from the server's *proven* reason class and offers exactly
 * one next step: a read-only 重新检查. The page never supplies a connection —
 * the server resolves the original submit operation's bound Auto Bangumi
 * instance — and it can never rebind, create or resubmit anything.
 */
export type TrackingCheckBody = NonNullable<
  operations['checkTrackingItem']['requestBody']
>['content']['application/json']
export type TrackingCheckResult = NonNullable<
  operations['checkTrackingItem']['responses']['200']['content']['application/json']['result']
>

export const TRACKING_CHECK_ENDPOINT =
  '/api/v1/tracking/items/{tracking_id}/check' as const satisfies ApiPath

/** Every proven reason class the server may publish for an unresolved check. */
export const TRACKING_CHECK_REASONS = [
  'NOT_FOUND', 'AMBIGUOUS', 'UNREADABLE',
  'CONNECTION', 'AUTHENTICATION', 'VERSION', 'CAPABILITY',
  'CONNECTION_CHANGED',
] as const

export type TrackingCheckReason = (typeof TRACKING_CHECK_REASONS)[number]

/** Parse the server's published reason; anything unknown fails closed to null. */
export function trackingCheckReason(value: unknown): TrackingCheckReason | null {
  return typeof value === 'string' && (TRACKING_CHECK_REASONS as readonly string[]).includes(value)
    ? (value as TrackingCheckReason)
    : null
}

/**
 * Fixed copy per proven reason. A reason we cannot prove yields the honest
 * generic sentence, never an invented cause.
 */
const CHECK_REASON_MESSAGES: Readonly<Record<TrackingCheckReason, string>> = {
  NOT_FOUND: '暂时没有在 Auto Bangumi 中找到该订阅。订阅可能仍在处理，也可能尚未建立；未确认前不会再次提交。',
  AMBIGUOUS: '在 Auto Bangumi 中找到多个相同身份的订阅，无法确认哪一条属于本方案；未确认前不会再次提交。',
  UNREADABLE: '无法读取 Auto Bangumi 的当前状态，暂时无法确认；未确认前不会再次提交。',
  CONNECTION: '保存的 Auto Bangumi 连接当前无法访问，暂时无法确认；请检查网络或设置后重新检查。',
  AUTHENTICATION: 'Auto Bangumi 拒绝了保存的连接凭据，暂时无法确认；请前往设置更新账号或密码后重新检查。',
  VERSION: '当前 Auto Bangumi 版本不在已验证范围内，暂时无法确认；请前往设置确认版本后重新检查。',
  CAPABILITY: '保存的连接不支持只读核验，暂时无法确认；请前往设置检查连接类型。',
  CONNECTION_CHANGED: '保存的连接已被更换，原提交绑定的实例不再可用；不会用新连接认领旧结果。',
}

export const CHECK_PENDING_UNKNOWN_MESSAGE =
  '尚未确认 Auto Bangumi 是否已建立该订阅；未确认前不会再次提交。'

export function trackingCheckReasonMessage(reason: TrackingCheckReason | null): string {
  return reason ? CHECK_REASON_MESSAGES[reason] : CHECK_PENDING_UNKNOWN_MESSAGE
}

/**
 * The tracking statuses whose persistent-submit result is still unproven.
 * ``ACTIVE``/``SUBMIT_FAILED``/``ADDED_TO_DOWNLOAD`` are decided outcomes.
 */
export const PENDING_SUBMISSION_STATUSES = [
  'VERIFYING_EXTERNAL', 'RECOVERY_REQUIRED', 'UNKNOWN',
] as const

export type PendingSubmissionStatus = (typeof PENDING_SUBMISSION_STATUSES)[number]

export function isPendingSubmissionStatus(value: unknown): value is PendingSubmissionStatus {
  return typeof value === 'string'
    && (PENDING_SUBMISSION_STATUSES as readonly string[]).includes(value)
}

/**
 * True only for a *persistent submit* whose result is still unproven.
 *
 * Both facts come from the server (the record status and the current
 * operation's own kind); this routes the item to the read-only check flow
 * instead of the management/recovery controls — it grants nothing, because the
 * check endpoint re-validates every precondition server-side.
 */
export function isPendingSubmission(
  status: unknown,
  operationKind: unknown,
  submissionMode: unknown,
): boolean {
  if (!isPendingSubmissionStatus(status)) return false
  if (operationKind !== 'SUBMIT') return false
  // A one-time "download existing resources" request never establishes an
  // external subscription, so it is never a pending persistent submission.
  return submissionMode !== 'DOWNLOAD_EXISTING'
}

export type TrackingCheckState = 'IN_FLIGHT' | 'CONFIRMED' | 'PENDING' | 'CONFLICT' | 'UNKNOWN'

export interface TrackingCheckSession {
  readonly trackingId: string
  /** The revision this check acted on; a stale one never overwrites a newer result. */
  readonly revision: number | null
  readonly state: TrackingCheckState
  readonly message: string
  readonly reason: TrackingCheckReason | null
}

export function createCheckSession(
  trackingId: string,
  state: TrackingCheckState,
  reason: TrackingCheckReason | null = null,
  revision: number | null = null,
  message?: string,
): TrackingCheckSession {
  return {
    trackingId,
    revision,
    state,
    reason,
    message: message ?? (state === 'PENDING' ? trackingCheckReasonMessage(reason) : checkStateMessage(state)),
  }
}

function checkStateMessage(state: TrackingCheckState): string {
  switch (state) {
    case 'IN_FLIGHT': return '正在只读核验 Auto Bangumi 的当前状态…'
    case 'CONFIRMED': return '已确认订阅存在，追番状态已更新。'
    case 'CONFLICT': return '追番记录已变化，本次检查未生效；正在读取最新详情，请重新检查。'
    default: return '暂时无法完成只读核验；未确认前不会再次提交。'
  }
}

/**
 * Project one successful check response. The server's ``outcome`` decides the
 * session state; ``verification_reason`` is only trusted for an unresolved one.
 */
export function projectCheckResult(
  trackingId: string,
  result: TrackingCheckResult,
  checkedRevision: number,
): TrackingCheckSession {
  const reason = trackingCheckReason(result.verification_reason)
  if (result.outcome === 'ACTIVE' || result.outcome === 'DISABLED') {
    return createCheckSession(trackingId, 'CONFIRMED', null, checkedRevision)
  }
  return createCheckSession(trackingId, 'PENDING', reason, checkedRevision)
}

/**
 * A stale check result must never overwrite a newer one: the session is only
 * accepted when it acts on the revision currently displayed.
 */
export function checkSessionIsCurrent(
  session: TrackingCheckSession | null | undefined,
  trackingId: string,
  revision: number | null,
): boolean {
  return Boolean(session) && session!.trackingId === trackingId && session!.revision === revision
}

/**
 * Risk-confirmed single manual resubmission of a pending submission (issue #184).
 *
 * 结果待确认 is not a safe retry (ADR-0001/ADR-0002). The page therefore has two
 * steps: the read-only check the server already owns, and only then an explicit
 * risk confirmation whose fixed copy comes from the server's *proven* reason. A
 * cancelled confirmation sends no write request, and a confirmed one reuses the
 * ordinary submit result panel — the page never invents a second submit contract.
 */
export const TRACKING_RESUBMIT_ENDPOINT =
  '/api/v1/tracking/items/{tracking_id}/resubmit' as const satisfies ApiPath

/** Operation states a pending submission may be resubmitted from. */
export const RESUBMIT_OPERATION_STATES = ['OUTCOME_UNKNOWN', 'RECOVERY_REQUIRED'] as const

/**
 * Fixed risk copy for the three proven reasons the server can still offer a
 * resubmit for (``NOT_FOUND``/``AMBIGUOUS``/``UNREADABLE``). Every other reason
 * is a refusal, so it is presented by ``trackingResubmitBlockedMessage`` and is
 * never reachable as a risk dialog; anything unproven yields the honest generic
 * sentence instead of an invented duplication event or a safety promise.
 */
const RESUBMIT_RISK_MESSAGES: Readonly<Partial<Record<TrackingCheckReason, string>>> = {
  NOT_FOUND:
    '重新提交会在 Auto Bangumi 中再次创建该订阅：如果原提交其实已经成功、只是暂时没有出现在列表里，就会产生重复订阅并重复处理资源。',
  AMBIGUOUS:
    'Auto Bangumi 中存在多条相同身份的订阅，重新提交会再创建一条并重复处理资源。',
  UNREADABLE:
    '无法读取 Auto Bangumi 的当前状态：原提交可能已经创建订阅并开始处理资源，重新提交可能造成重复订阅或重复下载。',
}

export const RESUBMIT_PENDING_UNKNOWN_RISK_MESSAGE =
  '原提交的结果仍未确认；重新提交可能创建重复订阅或重复处理资源。'

export function resubmitRiskMessage(reason: TrackingCheckReason | null): string {
  return (reason ? RESUBMIT_RISK_MESSAGES[reason] : undefined)
    ?? RESUBMIT_PENDING_UNKNOWN_RISK_MESSAGE
}

/**
 * Every published reason the server may use to refuse a resubmit outright
 * (AC 6), plus its own plan/connection refusals. Anything unrecognized fails
 * closed to the honest generic sentence.
 */
export const RESUBMIT_BLOCKED_REASONS = [
  'EXTERNAL_WRITE_IN_PROGRESS', 'PLAN_NOT_SUBMITTABLE', 'CONFIG_ERROR',
  'RESULT_UNPROVEN', 'CONNECTION_CHANGED', 'AUTHENTICATION', 'VERSION',
  'CAPABILITY', 'CONNECTION',
] as const

export type TrackingResubmitBlockedReason = (typeof RESUBMIT_BLOCKED_REASONS)[number]

const RESUBMIT_BLOCKED_MESSAGES: Readonly<Record<TrackingResubmitBlockedReason, string>> = {
  EXTERNAL_WRITE_IN_PROGRESS:
    '上一次提交可能仍在执行，本次不会重新提交；请先完成恢复核验。',
  PLAN_NOT_SUBMITTABLE:
    '本地方案未通过提交前检查，本次不会重新提交；请按提示修改追番方案后再试。',
  CONFIG_ERROR:
    '保存的 Auto Bangumi 连接当前不可用，本次不会重新提交；请前往设置检查连接。',
  RESULT_UNPROVEN:
    '无法用已证实的原因判定当前待确认结果，本次不会重新提交；请稍后重新检查。',
  CONNECTION_CHANGED:
    '保存的连接已被更换，原提交绑定的实例不再可用；不会用新连接重新提交旧结果。',
  AUTHENTICATION:
    'Auto Bangumi 拒绝了保存的连接凭据，本次不会重新提交；请前往设置更新账号或密码。',
  VERSION:
    '当前 Auto Bangumi 版本不在已验证范围内，本次不会重新提交；请前往设置确认版本。',
  CAPABILITY:
    '保存的连接不支持所需的只读核验能力，本次不会重新提交；请前往设置检查连接类型。',
  CONNECTION:
    '保存的 Auto Bangumi 连接当前无法访问，本次不会重新提交；请检查网络或设置后重新检查。',
}

export const RESUBMIT_BLOCKED_FALLBACK_MESSAGE =
  '暂时无法重新提交；未确认绑定与方案之前不会向 Auto Bangumi 发起新的提交。'

export function trackingResubmitBlockedMessage(value: unknown): string {
  return typeof value === 'string' && (RESUBMIT_BLOCKED_REASONS as readonly string[]).includes(value)
    ? RESUBMIT_BLOCKED_MESSAGES[value as TrackingResubmitBlockedReason]
    : RESUBMIT_BLOCKED_FALLBACK_MESSAGE
}

/**
 * Fixed next step for every 409 the resubmit endpoint documents. A 409 is always
 * raised before the external boundary, so the copy states plainly that nothing
 * was resubmitted and which proven condition refused it; an unrecognized type
 * fails closed to the generic sentence.
 */
const RESUBMIT_CONFLICT_MESSAGES: Readonly<Record<string, string>> = {
  tracking_revision_conflict:
    '追番记录已变化，本次未重新提交；正在读取最新详情，请重新检查后再确认。',
  tracking_state_conflict:
    '当前追番状态没有可核验的待确认提交（例如上一次提交仍可能在进行），本次未重新提交；请先完成恢复核验。',
  tracking_check_in_progress:
    '该追番记录的只读检查正在进行，本次未重新提交；请稍候再试。',
  tracking_operation_in_progress:
    '存在尚未完成的提交操作，本次未重新提交；请先完成恢复核验。',
  tracking_resubmit_binding_conflict:
    '本次重新提交绑定的操作或连接已变化，未重新提交；请重新检查后再确认。',
  tracking_idempotency_conflict:
    '本次重新提交标识已失效，未重新提交；请重新检查后再确认。',
}

export const RESUBMIT_CONFLICT_FALLBACK_MESSAGE =
  '追番记录或绑定已变化，本次未重新提交；正在读取最新详情，请重新检查后再确认。'

export function resubmitConflictMessage(errorType: unknown): string {
  return typeof errorType === 'string' && errorType in RESUBMIT_CONFLICT_MESSAGES
    ? RESUBMIT_CONFLICT_MESSAGES[errorType]!
    : RESUBMIT_CONFLICT_FALLBACK_MESSAGE
}

export type TrackingResubmitState =
  | 'IN_FLIGHT' | 'CONFIRMED' | 'BLOCKED' | 'CANCELLED' | 'CONFLICT' | 'UNKNOWN'

export interface TrackingResubmitSession {
  readonly trackingId: string
  /** The revision this interaction acted on; a stale one never overwrites a newer result. */
  readonly revision: number | null
  readonly state: TrackingResubmitState
  readonly message: string
  readonly reason: TrackingCheckReason | null
  readonly blockedReason: TrackingResubmitBlockedReason | null
}

export const RESUBMIT_CANCELLED_MESSAGE =
  '已取消重新提交；本次没有向 Auto Bangumi 发起新的提交。'

export function createResubmitSession(
  trackingId: string,
  state: TrackingResubmitState,
  reason: TrackingCheckReason | null = null,
  revision: number | null = null,
  message?: string,
  blockedReason: TrackingResubmitBlockedReason | null = null,
): TrackingResubmitSession {
  return {
    trackingId,
    revision,
    state,
    reason,
    blockedReason,
    message: message ?? resubmitStateMessage(state, reason, blockedReason),
  }
}

function resubmitStateMessage(
  state: TrackingResubmitState,
  reason: TrackingCheckReason | null,
  blockedReason: TrackingResubmitBlockedReason | null,
): string {
  switch (state) {
    case 'IN_FLIGHT': return '正在只读核验 Auto Bangumi 的当前状态…'
    case 'CONFIRMED': return '已确认订阅存在，追番状态已更新；本次没有重新提交。'
    case 'BLOCKED': return trackingResubmitBlockedMessage(blockedReason)
    case 'CANCELLED': return RESUBMIT_CANCELLED_MESSAGE
    case 'CONFLICT':
      return RESUBMIT_CONFLICT_FALLBACK_MESSAGE
    default: return trackingCheckReasonMessage(reason)
  }
}

/**
 * Project the read-only phase. ``CONFIRMED``/``BLOCKED`` are decided outcomes;
 * an unresolved check is only ever presented as the *risk* the user must accept,
 * never as an automatic resubmission.
 */
export function projectResubmitOffer(
  trackingId: string,
  result: TrackingResubmitResult,
  checkedRevision: number,
): TrackingResubmitSession {
  const reason = trackingCheckReason(result.verification_reason)
  if (result.check_status === 'CONFIRMED') {
    return createResubmitSession(trackingId, 'CONFIRMED', null, checkedRevision)
  }
  if (result.check_status === 'BLOCKED') {
    const blocked = typeof result.blocked_reason === 'string'
      && (RESUBMIT_BLOCKED_REASONS as readonly string[]).includes(result.blocked_reason)
      ? (result.blocked_reason as TrackingResubmitBlockedReason)
      : null
    return createResubmitSession(trackingId, 'BLOCKED', reason, checkedRevision, undefined, blocked)
  }
  return createResubmitSession(trackingId, 'UNKNOWN', reason, checkedRevision)
}

/**
 * True only when the server offered the resubmit and published the exact binding
 * the confirmation must echo; a check failure can never authorize the write.
 */
export function resubmitBindingFrom(
  result: TrackingResubmitResult,
): TrackingResubmitResult['binding'] | null {
  if (result.check_status !== 'UNRESOLVED' || result.requires_risk_confirmation !== true) return null
  const binding = result.binding
  if (!binding) return null
  if (typeof binding.expected_revision !== 'number') return null
  if (typeof binding.previous_operation_id !== 'string' || !binding.previous_operation_id) return null
  if (typeof binding.connection_ref !== 'string' || !binding.connection_ref) return null
  return binding
}

/** The confirmation body: the exact binding the server published, nothing else. */
export function createResubmitConfirmationBody(
  binding: NonNullable<TrackingResubmitResult['binding']>,
  storageDir: string | undefined,
): TrackingResubmitBody {
  return {
    expected_revision: binding.expected_revision,
    confirm: true,
    previous_operation_id: binding.previous_operation_id,
    connection_ref: binding.connection_ref,
    ...(storageDir ? { storage_dir: storageDir } : {}),
  }
}

/** The page's decision for the 重新提交 entry of one pending submission. */
export interface TrackingResubmitOfferState {
  readonly available: boolean
  /** The proven next step when the entry cannot be offered ('' while available). */
  readonly hint: string
}

/**
 * Whether the page offers 重新提交 for a pending submission, in one place.
 *
 * It never decides the outcome: the server re-validates every precondition, and
 * this only avoids offering a step the server has already proven impossible (a
 * write that may still be running, or an operation that is not a checkable
 * pending submit).
 */
export function resubmitOfferState(
  status: unknown,
  operationKind: unknown,
  operationState: unknown,
  submissionMode: unknown,
): TrackingResubmitOfferState {
  if (!isPendingSubmission(status, operationKind, submissionMode)) {
    return { available: false, hint: '' }
  }
  if (
    typeof operationState === 'string'
    && (RESUBMIT_OPERATION_STATES as readonly string[]).includes(operationState)
  ) {
    return { available: true, hint: '' }
  }
  if (operationState === 'IN_PROGRESS') {
    return {
      available: false,
      hint: '上一次提交可能仍在执行，请先完成恢复核验后再重新提交。',
    }
  }
  return {
    available: false,
    hint: '当前待确认提交的绑定状态不支持重新提交，请先完成恢复核验。',
  }
}
