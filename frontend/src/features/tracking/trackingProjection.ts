/**
 * API-free tracking page *display projection* (US-304, US-307, US-309).
 *
 * This module only consumes generated OpenAPI operation types and projects what
 * the page renders: status groups and counts, labels, formatting, filtering and
 * sorting, and the read-only capability/revalidation matrices.  It performs no
 * transport and stores no session, intent, key or request state — every local
 * session of an external write lives in ``useTrackingWriteSession`` (issue #168).
 */
import type { operations, paths } from '@/api/generated/api'

// Issue #193 (A.2): the *request* scope vocabulary is owned by the write session,
// which is the only module that turns a scope into a request.  This display
// module borrows the type alone to keep its label map exhaustive — a type-only
// import, so no runtime dependency (let alone a cycle) is introduced.
import type { TrackingManagementActionCode, TrackingManagementScope } from './useTrackingWriteSession'

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
export type TrackingRevalidateResult = NonNullable<
  operations['revalidateTrackingItem']['responses']['200']['content']['application/json']['result']
>
export type TrackingRevalidateIssue = NonNullable<TrackingRevalidateResult['issues']>[number]

export const TRACKING_STATUS_GROUPS = [
  'PENDING', 'PROCESSING', 'ACTIVE', 'ATTENTION', 'INACTIVE',
] as const satisfies readonly TrackingItem['status_group'][]

export type TrackingStatusGroup = (typeof TRACKING_STATUS_GROUPS)[number]

/**
 * Issue #224 A4: a retired, read-only state kept only for historical archives.
 * It shows its real label but joins no overview card and no group filter.
 */
export const TRACKING_EXTERNAL_ONLY_STATUS = 'EXTERNAL_ONLY'

/** Server-published group metadata (issue #224 A7). */
export type TrackingStatusGroupMeta = TrackingListResult['status_groups'][number]

/** One renderable status group: server-owned label plus authoritative count. */
export interface TrackingStatusGroupView {
  group: TrackingStatusGroup
  label: string
  count: number
  /** True for the four groups 状态总览 renders as cards; PROCESSING never is. */
  isCard: boolean
}

export interface TrackingOverview {
  total: number
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

/**
 * The action codes this page is willing to read.  Issue #228 (T5a) retired
 * ``REVALIDATE``/``RECOVER_AUTO``/``MARK_SUCCEEDED``/``MARK_FAILED`` and the
 * standalone ``DELETE_EXTERNAL`` from the published enum, so the projection can
 * no longer receive them.
 */
const KNOWN_ACTIONS = new Set<TrackingActionCode>([
  'SUBMIT', 'RETRY', 'MODIFY', 'SET_ENABLED', 'REFRESH_RSS',
])
const KNOWN_STYLES = new Set<TrackingActionStyle>(['PRIMARY', 'SECONDARY', 'DANGER'])
/**
 * The generated ``TrackingScope`` values this page is willing to *read*.
 *
 * It deliberately does not reuse the write session's sendable-scope guard
 * (issue #193): this is input validation over the server-published enum, where
 * the safe direction is to keep knowing a scope the page cannot request (so it
 * can still be displayed and filtered) — collapsing the two would silently drop
 * a future server scope from the projection instead of from the request.
 */
const KNOWN_SCOPES = new Set<TrackingScope>(['SUBSCRIPTION', 'ASSOCIATED_RSS'])

/**
 * Which live capability each management action needs for a given scope.
 *
 * Issue #193: total over the management family, so a management action added to
 * the write session's operation table fails the build here until its capability
 * mapping is stated, instead of silently dropping out of the projection.
 */
export const MANAGEMENT_CAPABILITY: Partial<
  Record<TrackingActionCode, Partial<Record<TrackingScope, keyof CapabilityResult>>>
> & Record<TrackingManagementActionCode, Partial<Record<TrackingScope, keyof CapabilityResult>>> = {
  MODIFY: { SUBSCRIPTION: 'subscription_modify', ASSOCIATED_RSS: 'rss_modify' },
  SET_ENABLED: { SUBSCRIPTION: 'subscription_enable', ASSOCIATED_RSS: 'rss_enable' },
  REFRESH_RSS: { ASSOCIATED_RSS: 'rss_refresh' },
}

/** Fixed Chinese labels for the two management scopes; the raw enum never renders. */
export const MANAGEMENT_SCOPE_LABELS = {
  SUBSCRIPTION: '外部番剧订阅',
  ASSOCIATED_RSS: '关联 RSS',
} as const satisfies Record<TrackingManagementScope, string>

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
 * Project the list total strictly from the server summary (issue #85).
 *
 * The page never rebuilds the server state machine: the total comes from the
 * authoritative projection, and a missing or malformed value renders 0 instead
 * of being guessed from whichever rows happen to be loaded/filtered.
 */
export function projectTrackingOverview(
  summary: TrackingListSummary | null | undefined,
): TrackingOverview {
  return {
    total: _safeCount(summary?.total),
    unreadable: _safeCount(summary?.unreadable),
  }
}

/**
 * Project the server-owned status-group metadata (issue #224 A7).
 *
 * The server publishes every group — including zero-count groups on an empty
 * list — together with the labels and the four card memberships, so this module
 * owns no label table and no card list. An entry with an unknown group or no
 * usable label is dropped instead of being rendered with an invented name; a
 * duplicated group keeps its first server entry so the order stays the server's.
 */
export function projectStatusGroups(
  groups: readonly TrackingStatusGroupMeta[] | null | undefined,
): TrackingStatusGroupView[] {
  if (!Array.isArray(groups)) return []
  const views: TrackingStatusGroupView[] = []
  const seen = new Set<TrackingStatusGroup>()
  for (const entry of groups) {
    const candidate = entry as Partial<TrackingStatusGroupMeta> | null
    if (!candidate || !isKnownStatusGroup(candidate.group)) continue
    const label = typeof candidate.label === 'string' ? candidate.label.trim() : ''
    if (!label || seen.has(candidate.group)) continue
    seen.add(candidate.group)
    views.push({
      group: candidate.group,
      label,
      count: _safeCount(candidate.count),
      isCard: candidate.has_overview_card === true,
    })
  }
  return views
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

/** Parse a server timestamp, or null when it is absent/unreadable. */
function parseServerTimestamp(value: string | null | undefined): Date | null {
  if (typeof value !== 'string' || !value.trim()) return null
  const parsed = new Date(value)
  return Number.isNaN(parsed.getTime()) ? null : parsed
}

/** Format a server timestamp for the list's "最近更新时间" column (issue #85). */
export function formatTrackingUpdatedAt(value: string | null | undefined): string {
  const parsed = parseServerTimestamp(value)
  if (!parsed) return '更新时间不可用'
  return formatTimestamp(parsed)
}

/** The one timestamp shape the tracking surface uses (YYYY/MM/DD HH:mm). */
function formatTimestamp(parsed: Date): string {
  return new Intl.DateTimeFormat('zh-CN', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
  }).format(parsed)
}

/**
 * Format a server timestamp for the detail's 创建时间 value (issue #227 D2).
 *
 * The 2026-10-20 revision replaced 「最近更新」(updated_at) with 创建时间
 * (created_at): updated_at moves on every submit/modify/enable/sync, so it never
 * described resource freshness.  A missing or unreadable value uses the same
 * "未设置" wording the rest of the summary uses for absent metadata.
 */
export function formatTrackingCreatedAt(value: string | null | undefined): string {
  const parsed = parseServerTimestamp(value)
  if (!parsed) return '未设置'
  return formatTimestamp(parsed)
}

/**
 * Chinese wording for the record's current operation and its state (issue #227
 * D6).  The values are the server's public enums; an unrecognized value is
 * returned verbatim so the operational record never hides evidence behind a
 * made-up label.
 */
const OPERATION_LABELS: Record<string, string> = {
  SUBMIT: '提交',
  MODIFY: '修改',
  SET_ENABLED: '启停',
  DELETE_EXTERNAL: '删除外部订阅',
  REFRESH_RSS: '刷新资源',
}

const OPERATION_STATE_LABELS: Record<string, string> = {
  PREPARED: '已准备',
  IN_PROGRESS: '进行中',
  SUCCEEDED: '成功',
  FAILED: '失败',
  OUTCOME_UNKNOWN: '结果待确认',
  RECOVERY_REQUIRED: '需要恢复',
}

const AUDIT_ACTION_LABELS: Record<string, string> = {
  TRACKING_CREATED: '已创建追番记录',
  TRACKING_BACKFILLED: '已回填历史记录',
  PLAN_CHANGE_DETECTED: '检测到方案变化',
  REVALIDATION_PASSED: '提交前复核通过',
  REVALIDATION_FAILED: '提交前复核未通过',
  SUBMIT_STARTED: '开始提交',
  SUBMIT_SUCCEEDED: '提交成功',
  SUBMIT_FAILED: '提交失败',
  SUBMIT_OUTCOME_UNKNOWN: '提交结果待确认',
  MANAGEMENT_STARTED: '开始外部管理操作',
  MANAGEMENT_SUCCEEDED: '外部管理操作成功',
  MANAGEMENT_FAILED: '外部管理操作失败',
  MANAGEMENT_UNKNOWN: '外部管理结果待确认',
  RESULT_PERSIST_FAILED: '结果落盘失败',
  RECOVERY_AUTO_SUCCEEDED: '本地恢复成功',
  RECOVERY_AUTO_FAILED: '本地恢复确认失败',
  RECOVERY_NEEDS_MANUAL: '需要人工核验',
  RECOVERY_MANUAL_SUCCEEDED: '人工核验标记成功',
  RECOVERY_MANUAL_FAILED: '人工核验标记失败',
  RESUBMIT_RISK_CONFIRMED: '已确认主动重发风险',
  RECOVERY_EXTERNAL_VERIFIED: '只读核验外部状态',
  COMPAT_QUEUE_UPDATED: '兼容队列已更新',
  COMPAT_QUEUE_UPDATE_FAILED: '兼容队列更新失败',
}

function pickLabel(value: unknown, labels: Record<string, string>, fallback: string): string {
  if (typeof value !== 'string' || !value) return fallback
  return labels[value] ?? value
}

/** Chinese name of one operation kind; unknown codes stay visible. */
export function formatTrackingOperation(value: unknown): string {
  return pickLabel(value, OPERATION_LABELS, '未知操作')
}

/** Chinese name of one operation state; unknown codes stay visible. */
export function formatTrackingOperationState(value: unknown): string {
  return pickLabel(value, OPERATION_STATE_LABELS, '未知状态')
}

/** Chinese name of one audit action; unknown codes stay visible. */
export function formatTrackingAuditAction(value: unknown): string {
  return pickLabel(value, AUDIT_ACTION_LABELS, '未知操作记录')
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
    // Issue #224 A4: the retired read-only archive stays visible in 全部 only,
    // so a group/card filter never returns it even though it maps to INACTIVE.
    const matchesGroup = !group || (
      isKnownStatusGroup(item.status_group)
      && item.status_group === group
      && item.status !== TRACKING_EXTERNAL_ONLY_STATUS
    )
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

/** True only while the current probe proves the read-only external check. */
export function canVerifyExternally(capabilities?: CapabilityResult | null): boolean {
  return supported(capabilities, 'external_verify')
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

// -- fixed management-section copy -------------------------------------------

/** Fixed copy explaining why the form is a write-only field set. */
export const MODIFY_FORM_HELP =
  '本表单不读取 Auto Bangumi 的当前值，只提交你明确勾选并填写的字段；未勾选的字段保持 Auto Bangumi 现有值。清空已勾选的文本字段会将该字段设为空。'

/** Fixed copy shown next to the enable/disable and refresh actions (US-314). */
export const MANAGEMENT_ACTIONS_HELP =
  '启停与刷新只作用于 Auto Bangumi 中的外部对象，不修改 MiGuOrca 本地方案；每次操作都需要单独确认。'

/**
 * The record statuses only the server can settle (issue #228).
 *
 * These are the statuses a read-only external verification may be offered for.
 * The set lives here — the one projection module — so the page and the write
 * session cannot drift from each other or lose the status type.
 */
export const RECOVERABLE_STATUSES: ReadonlySet<TrackingItem['status']> = new Set([
  'VERIFYING_EXTERNAL',
  'RECOVERY_REQUIRED',
  'UNKNOWN',
])

/** True when the record's exact status is one only the server can settle. */
export function isRecoverableStatus(status: unknown): status is TrackingItem['status'] {
  return typeof status === 'string'
    && RECOVERABLE_STATUSES.has(status as TrackingItem['status'])
}

/**
 * Bounded read-only confirmation of a pending submission (issue #183).
 *
 * A persistent ``提交`` whose outcome could not be proven shows 结果待确认. The
 * page explains it from the server's *proven* reason class and offers exactly
 * one next step: a read-only 核验 (button label「核验结果」). The page never supplies a connection —
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
 * 结果待确认 is not a safe retry (ADR-0001/ADR-0002). The server owns the two
 * phases: a read-only check the page already has (#183), then — only if the
 * result is still unproven and the server explicitly offered it — one new
 * operation after the user accepts the duplicate/resource risk. Nothing in this
 * module performs IO or invents a cause the server did not prove.
 */
export type TrackingResubmitBody = NonNullable<
  operations['resubmitTrackingItem']['requestBody']['content']['application/json']
>
export type TrackingResubmitResult = NonNullable<
  operations['resubmitTrackingItem']['responses']['200']['content']['application/json']['result']
>
export type TrackingResubmitBinding = NonNullable<TrackingResubmitResult['binding']>

export const TRACKING_RESUBMIT_ENDPOINT =
  '/api/v1/tracking/items/{tracking_id}/resubmit' as const satisfies ApiPath

/** Operation states a pending submission may be resubmitted from. */
export const RESUBMIT_OPERATION_STATES = ['OUTCOME_UNKNOWN', 'RECOVERY_REQUIRED'] as const

/**
 * Fixed risk copy for the three proven reasons the server can still offer a
 * resubmit for (``NOT_FOUND``/``AMBIGUOUS``/``UNREADABLE``). Every other reason
 * is a refusal and is presented by ``trackingResubmitBlockedMessage``; an
 * unproven reason yields the honest generic sentence instead of an invented
 * duplication event or a safety promise.
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
 * (AC 6), including its own plan/connection/scope codes. Anything unrecognized
 * fails closed to the honest generic sentence.
 */
export const RESUBMIT_BLOCKED_REASONS = [
  'EXTERNAL_WRITE_IN_PROGRESS', 'PLAN_NOT_SUBMITTABLE', 'CONFIG_ERROR',
  'RESULT_UNPROVEN', 'ONE_TIME_SUBMISSION', 'CONNECTION_CHANGED',
  'AUTHENTICATION', 'VERSION', 'CAPABILITY', 'CONNECTION',
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
  ONE_TIME_SUBMISSION:
    '本次提交方式是「下载现有资源」，不属于持续追番的待确认结果，本次不会重新提交；请按既有提交流程处理。',
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
  /** The exact binding the server published, while a risk confirmation is owed. */
  readonly binding: TrackingResubmitBinding | null
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
  binding: TrackingResubmitBinding | null = null,
): TrackingResubmitSession {
  return {
    trackingId,
    revision,
    state,
    reason,
    blockedReason,
    binding,
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
    case 'CONFLICT': return RESUBMIT_CONFLICT_FALLBACK_MESSAGE
    default: return trackingCheckReasonMessage(reason)
  }
}

/** Parse the server's published blocked reason; anything unknown fails closed. */
export function trackingResubmitBlockedReason(value: unknown): TrackingResubmitBlockedReason | null {
  return typeof value === 'string' && (RESUBMIT_BLOCKED_REASONS as readonly string[]).includes(value)
    ? (value as TrackingResubmitBlockedReason)
    : null
}

/**
 * Project the read-only phase. ``CONFIRMED``/``BLOCKED`` are decided outcomes;
 * an offered ``UNRESOLVED`` result carries the exact binding a later explicit
 * confirmation must echo, and never authorizes a write by itself.
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
    return createResubmitSession(
      trackingId,
      'BLOCKED',
      reason,
      checkedRevision,
      undefined,
      trackingResubmitBlockedReason(result.blocked_reason),
    )
  }
  return createResubmitSession(
    trackingId,
    'UNKNOWN',
    reason,
    checkedRevision,
    undefined,
    null,
    resubmitBindingFrom(result),
  )
}

/**
 * True only when the server offered the resubmit and published the exact binding
 * the confirmation must echo; a check failure can never authorize the write.
 */
export function resubmitBindingFrom(result: TrackingResubmitResult): TrackingResubmitBinding | null {
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
  binding: TrackingResubmitBinding,
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
 * It never decides the outcome: the server re-validates every precondition
 * (including the submission mode), and this only avoids offering a step the
 * server has already proven impossible (a write that may still be running, a
 * one-time request, or an operation that is not a checkable pending submit).
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
