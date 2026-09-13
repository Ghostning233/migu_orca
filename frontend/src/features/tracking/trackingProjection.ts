/**
 * API-free tracking page projection and intent helpers (US-304, US-309).
 *
 * This module only consumes generated OpenAPI operation types. It never
 * performs transport, reconstructs server state, or stores an intent/key.
 */
import type { operations } from '@/api/generated/api'

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
