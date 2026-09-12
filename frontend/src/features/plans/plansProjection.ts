/**
 * API-free projection helpers for the Stage 37 plans list (US-295).
 *
 * This module only consumes public result types generated from OpenAPI.  It
 * does not know about transport, stores, tracking actions, or Request
 * snapshots, so list filtering and association rules remain testable without
 * a component or API mock.
 */
import type { operations } from '@/api/generated/api'
import {
  requestLabel,
  statusLabel,
  type RequestSummary,
} from '@/features/requests/requestsList'

export type RequestListResult = NonNullable<
  operations['listRequests']['responses']['200']['content']['application/json']['result']
>

export type TrackingListResult = NonNullable<
  operations['listTrackingItems']['responses']['200']['content']['application/json']['result']
>

export type TrackingItem = TrackingListResult['items'][number]

/** The one safe tracking association rendered alongside a Request summary. */
export interface PlanTrackingAssociation {
  item: TrackingItem
  status: string
  statusLabel: string
  trackingId: string
}

/** A row keeps the generated summary as its only Request source of truth. */
export interface PlanRow {
  request: RequestSummary
  tracking: PlanTrackingAssociation | null
}

export const TRACKING_UNAVAILABLE_LABEL = '追番状态暂不可用'
export const TRACKING_NOT_LINKED_LABEL = '未进入追番管理'

const TRACKING_STATUS_LABELS: Record<string, string> = {
  PENDING_SUBMIT: '待提交',
  REVALIDATING: '复核中',
  NEEDS_RECONFIRM: '待重新确认',
  SUBMITTING: '提交中',
  VERIFYING_EXTERNAL: '核验中',
  ACTIVE: '追番中',
  SUBMIT_FAILED: '提交失败',
  RECOVERY_REQUIRED: '待恢复',
  UNKNOWN: '状态未知',
  DISABLED: '已停用',
  EXTERNAL_DELETED: '外部已删除',
}

/** A tracking id is navigable only when it is a non-empty public id token. */
export function isValidTrackingId(value: string | null | undefined): value is string {
  return typeof value === 'string' && /^[A-Za-z0-9][A-Za-z0-9_.-]*$/.test(value)
}

function isLinkableTrackingItem(item: TrackingItem): boolean {
  return item.status !== 'EXTERNAL_ONLY' && isValidTrackingId(item.tracking_id)
}

/** Return the server label, with a fixed Chinese fallback for unknown values. */
export function trackingStatusLabel(item: TrackingItem): string {
  if (typeof item.status_label === 'string' && item.status_label.trim()) {
    return item.status_label
  }
  return TRACKING_STATUS_LABELS[item.status] ?? TRACKING_UNAVAILABLE_LABEL
}

/**
 * Build a unique request_id → tracking item index.
 *
 * A request is linked only when exactly one eligible item has a non-empty,
 * exactly equal request_id.  Duplicate eligible items intentionally remove the
 * association instead of picking one or deriving an id from another field.
 */
export function joinTrackingItems(
  items: readonly TrackingItem[],
): Map<string, PlanTrackingAssociation> {
  const grouped = new Map<string, TrackingItem[]>()
  for (const item of items) {
    if (!isLinkableTrackingItem(item) || typeof item.request_id !== 'string' || !item.request_id.trim()) {
      continue
    }
    const group = grouped.get(item.request_id) ?? []
    group.push(item)
    grouped.set(item.request_id, group)
  }

  const associations = new Map<string, PlanTrackingAssociation>()
  for (const [requestId, matches] of grouped) {
    const item = matches.length === 1 ? matches[0] : undefined
    if (!item) continue
    associations.set(requestId, {
      item,
      status: item.status,
      statusLabel: trackingStatusLabel(item),
      trackingId: item.tracking_id,
    })
  }
  return associations
}

/** Project summaries and a tracking result into user-facing plan rows. */
export function projectPlanRows(
  requests: readonly RequestSummary[],
  trackingItems: readonly TrackingItem[] = [],
): PlanRow[] {
  const associations = joinTrackingItems(trackingItems)
  return requests.map((request) => ({
    request,
    tracking: request.request_id ? associations.get(request.request_id) ?? null : null,
  }))
}

/** Parse only a valid persisted ISO timestamp; invalid values sort last. */
export function planTimestamp(value: string | null | undefined): number | null {
  if (typeof value !== 'string' || !value.trim()) return null
  const parsed = Date.parse(value)
  return Number.isFinite(parsed) ? parsed : null
}

/** Stable recent-first ordering; missing/invalid timestamps retain server order at the end. */
export function sortPlanRows(rows: readonly PlanRow[]): PlanRow[] {
  return rows
    .map((row, index) => ({ row, index, timestamp: planTimestamp(row.request.updated_at) }))
    .sort((a, b) => {
      if (a.timestamp === null && b.timestamp === null) return a.index - b.index
      if (a.timestamp === null) return 1
      if (b.timestamp === null) return -1
      return b.timestamp - a.timestamp || a.index - b.index
    })
    .map(({ row }) => row)
}

/** Public text used by title/subtitle-group search; request_id is excluded. */
export function planSearchableText(row: PlanRow): string {
  const summary = row.request
  const groups = summary.candidate_subtitle_groups
    .map((group) => group.subtitle_group ?? '')
    .join(' ')
  return [summary.bangumi_title, summary.selected_subtitle_group, summary.expected_folder_name, groups]
    .filter((value): value is string => typeof value === 'string')
    .join(' ')
    .toLocaleLowerCase()
}

/** Derive title/status filters without changing the source rows. */
export function filterPlanRows(
  rows: readonly PlanRow[],
  searchTerm: string,
  requestStatus: string,
): PlanRow[] {
  const term = searchTerm.trim().toLocaleLowerCase()
  return rows.filter((row) => {
    const matchesSearch = !term || planSearchableText(row).includes(term)
    const matchesStatus = !requestStatus || (row.request.status ?? '') === requestStatus
    return matchesSearch && matchesStatus
  })
}

/** Complete derived pipeline used by PlansView and unit tests. */
export function buildPlanRows(
  requests: readonly RequestSummary[],
  trackingItems: readonly TrackingItem[] = [],
  searchTerm = '',
  requestStatus = '',
): PlanRow[] {
  return filterPlanRows(sortPlanRows(projectPlanRows(requests, trackingItems)), searchTerm, requestStatus)
}

/** Fixed status label for a row with no safe unique tracking association. */
export function planTrackingLabel(row: PlanRow): string {
  return row.tracking?.statusLabel ?? TRACKING_NOT_LINKED_LABEL
}

/** Public request status label; kept here so consumers need no API details. */
export function planRequestStatusLabel(row: PlanRow): string {
  return statusLabel(row.request.status)
}

/** Public title helper for cards. */
export function planTitle(row: PlanRow): string {
  return requestLabel(row.request)
}
