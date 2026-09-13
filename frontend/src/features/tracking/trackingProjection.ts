/**
 * API-free tracking page projection and intent helpers (US-304, US-309, US-310,
 * US-311).
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
  operations['probeAutoBangumiCapabilities']['responses']['200']['content']['application/json']['result']
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

export const TRACKING_STATUS_GROUPS = [
  'PENDING', 'PROCESSING', 'ACTIVE', 'ATTENTION', 'INACTIVE',
] as const satisfies readonly TrackingItem['status_group'][]

export type TrackingStatusGroup = (typeof TRACKING_STATUS_GROUPS)[number]

export interface TrackingOverview {
  total: number
  byGroup: Record<TrackingStatusGroup, number>
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
const MANAGEMENT_CAPABILITY: Partial<Record<TrackingActionCode, Partial<Record<TrackingScope, keyof CapabilityResult>>>> = {
  MODIFY: { SUBSCRIPTION: 'subscription_modify', ASSOCIATED_RSS: 'rss_modify' },
  SET_ENABLED: { SUBSCRIPTION: 'subscription_enable', ASSOCIATED_RSS: 'rss_enable' },
  REFRESH_RSS: { ASSOCIATED_RSS: 'rss_refresh' },
  DELETE_EXTERNAL: { SUBSCRIPTION: 'subscription_delete', ASSOCIATED_RSS: 'rss_delete' },
}

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

/** Count only server-provided known status groups; unknown data is unreadable. */
export function projectTrackingOverview(items: readonly TrackingItem[]): TrackingOverview {
  const byGroup = Object.fromEntries(TRACKING_STATUS_GROUPS.map((group) => [group, 0])) as Record<TrackingStatusGroup, number>
  let unreadable = 0
  for (const item of items) {
    if (!isKnownStatusGroup(item.status_group)) {
      unreadable += 1
      continue
    }
    byGroup[item.status_group] += 1
  }
  return { total: items.length, byGroup, unreadable }
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

/** Filter server actions by strict known values and current proven capability. */
export function executableTrackingActions(
  item: TrackingItem,
  capabilities?: CapabilityResult | null,
): TrackingAction[] {
  const result: TrackingAction[] = []
  for (const action of item.available_actions ?? []) {
    if (!isKnownAction(action.code) || !isKnownStyle(action.style)) continue
    const rawScopes = Array.isArray(action.target_scopes) ? action.target_scopes : []
    const scopes = rawScopes.filter(isKnownScope)
    if (scopes.length !== rawScopes.length || new Set(scopes).size !== scopes.length) continue
    const capability = MANAGEMENT_CAPABILITY[action.code]
    if (capability) {
      if (!capabilities || scopes.length === 0) continue
      const supportedScopes = scopes.filter((scope) => {
        let field: keyof CapabilityResult | undefined = capability[scope]
        if (action.code === 'SET_ENABLED') {
          if (item.status === 'DISABLED') {
            field = scope === 'SUBSCRIPTION' ? 'subscription_enable' : 'rss_enable'
          } else if (item.status === 'ACTIVE' || item.status === 'EXTERNAL_ONLY') {
            field = scope === 'SUBSCRIPTION' ? 'subscription_disable' : 'rss_disable'
          } else {
            field = undefined
          }
        }
        return field !== undefined && supported(capabilities, field)
      })
      if (!supportedScopes.length) continue
      result.push({ ...action, target_scopes: supportedScopes })
      continue
    }
    if (action.code === 'SUBMIT' || action.code === 'RETRY') {
      if (scopes.length > 0 || !supported(capabilities, 'subscription_submit')) continue
    } else if (scopes.length > 0) {
      continue
    }
    result.push(action)
  }
  return result
}

function makeOpaqueKey(): string {
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
  capabilities?: CapabilityResult | null,
): TrackingActionIntent | null {
  const executable = executableTrackingActions(item, capabilities)
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
  return CAPABILITY_STATE_LABELS[capabilityState(value)]
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
    message: '将在 Auto Bangumi 创建该追番的外部订阅，并可能触发下载。提交只使用本页面已探测的连接，是否继续？',
    confirmLabel: '确认提交',
  },
  RETRY: {
    title: '重试 Auto Bangumi 提交',
    message: '该追番上次提交明确失败。重试会使用本页面已探测的连接重新创建外部订阅，并可能触发下载，是否继续？',
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
] as const satisfies readonly TrackingSubmitResult['outcome'][]

export type TrackingSubmitOutcome = (typeof SUBMIT_OUTCOMES)[number]

/**
 * ``UNKNOWN`` also covers a transport result we could not read at all.
 * ``REJECTED`` is the definite counterpart: a structured non-409 HTTP 4xx the
 * server returned *before* the external boundary (D38-08.5), so Auto Bangumi
 * was provably never written.
 */
export type TrackingWriteState = 'IN_FLIGHT' | TrackingSubmitOutcome | 'CONFLICT' | 'REJECTED' | 'UNKNOWN'

export interface TrackingWriteSession {
  readonly trackingId: string
  readonly action: TrackingActionCode
  readonly state: TrackingWriteState
  readonly message: string
  readonly issues: TrackingRevalidateIssueView[]
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
): TrackingWriteSession {
  return { trackingId, action, state, message: WRITE_MESSAGES[state], issues }
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
  return { trackingId, action, state: 'CONFLICT', message: writeConflictMessage(errorType), issues: [] }
}

/**
 * True only for a structured, non-409 HTTP 4xx (D38-08.5).
 *
 * Every documented submit-family 4xx other than 409 is raised before the
 * external boundary, so Auto Bangumi was never called with the request: that is
 * a definite refusal ("本次未创建外部订阅"), not the indeterminate ``UNKNOWN``
 * result. A network failure, timeout, non-JSON body, 5xx, or a status we cannot
 * read stays ``UNKNOWN`` because it may already have reached the boundary.
 */
export function isDefiniteWriteRejection(error: { status: number; httpError: boolean }): boolean {
  return error.httpError === true && error.status >= 400 && error.status < 500 && error.status !== 409
}

/**
 * Project one HTTP 200 submit-family result. An outcome we do not recognize is
 * treated exactly like an unreadable transport result: read back, never
 * resubmit blind.
 */
export function projectWriteOutcome(
  trackingId: string,
  action: TrackingActionCode,
  result: TrackingWriteResult,
): TrackingWriteSession {
  const outcome: TrackingWriteState = isSubmitOutcome(result.outcome) ? result.outcome : 'UNKNOWN'
  return createWriteSession(trackingId, action, outcome, projectRevalidateIssues(result.issues))
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
