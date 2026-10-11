/**
 * API-free tracking page *display projection* (US-304, US-307, US-309).
 *
 * This module only consumes generated OpenAPI operation types and projects what
 * the page renders: status groups and counts, labels, formatting, filtering and
 * sorting, and the read-only capability/revalidation matrices.  It performs no
 * transport and stores no session, intent, key or request state — every local
 * session of an external write lives in ``useTrackingWriteSession`` (issue #168).
 */
import type { operations } from '@/api/generated/api'

import type { TrackingManagementScope } from './useTrackingWriteSession'

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

/** Fixed copy for the per-record external delete section (US-315). */
export const DELETE_EXTERNAL_HELP =
  '删除按当前追番逐条执行：没有勾选、批量或全局删除，也只会删除你明确选择的那一个 Auto Bangumi 外部对象；MiGuOrca 本地订阅方案、追番记录、审计记录、下载任务和已下载媒体文件都会保留，且不会删除任何媒体文件。'
