/**
 * Request list helpers (US-202).
 *
 * Pure functions shared by the RequestsView and its unit tests: status
 * labels, searchable text, filtering and sorting. They mirror the legacy
 * `app.js` behavior exactly so the old `/index` list and the new
 * `/app/plans` list stay parity (same API result, same empty state, same
 * search/filter/sort semantics).
 *
 * Security boundary: these helpers operate on public `summary` DTOs only
 * (the generated OpenAPI client type); they never receive raw request
 * snapshots, URLs, credentials or absolute paths, and no value here is ever
 * written to storage, URL or logs.
 */
import type { operations } from '@/api/generated/api'

/** Public summary shape produced by `GET /api/v1/requests` (US-202 DTO). */
export type RequestSummary = NonNullable<
  operations['listRequests']['responses']['200']['content']['application/json']['result']['requests']
>[number]

/** User-facing Chinese label for a Request status code (US-202). */
export const STATUS_LABELS: Record<string, string> = {
  PENDING_CONFIRM: '待确认',
  ACCEPTED: '已确认',
  CANCELLED: '已取消',
}

/** Stable internal status codes, in display order for the filter. */
export const KNOWN_STATUSES = ['PENDING_CONFIRM', 'ACCEPTED', 'CANCELLED'] as const

/** Sort modes offered by the list controls. */
export const SORT_MODES = ['default', 'title_asc', 'request_id_asc'] as const
export type SortMode = (typeof SORT_MODES)[number]

/** Render a field value the way the legacy list did (未设置/无/join). */
export function fieldValue(value: string | null | undefined): string {
  if (value === null || value === undefined || value === '') {
    return '未设置'
  }
  return String(value)
}

/** Chinese business label for a status code; unknown codes render as-is. */
export function statusLabel(status: string | null | undefined): string {
  const value = fieldValue(status)
  return STATUS_LABELS[value] ?? value
}

/** Display title for a summary (same fallback chain as legacy requestLabel). */
export function requestLabel(summary: RequestSummary): string {
  return (
    summary.bangumi_title ||
    summary.request_id ||
    summary.selected_subtitle_group ||
    '未命名订阅方案'
  )
}

/** Lowercased searchable text over the public summary fields (US-202). */
export function searchableText(summary: RequestSummary): string {
  return [
    summary.bangumi_title,
    summary.request_id,
    summary.selected_subtitle_group,
    summary.expected_folder_name,
  ]
    .map((value) => fieldValue(value).toLowerCase())
    .join(' ')
}

/** Normalize a status value for filtering ('' means 全部). */
export function summaryStatus(summary: RequestSummary): string {
  return fieldValue(summary.status)
}

/** Filter a list by search term and status ('' status = 全部). */
export function filterRequests(
  requests: readonly RequestSummary[],
  searchTerm: string,
  status: string,
): RequestSummary[] {
  const term = searchTerm.trim().toLowerCase()
  return requests.filter((summary) => {
    const matchesSearch = !term || searchableText(summary).includes(term)
    const matchesStatus = !status || summaryStatus(summary) === status
    return matchesSearch && matchesStatus
  })
}

/** Sort a list by the given mode (default keeps server order). */
export function sortRequests(
  requests: readonly RequestSummary[],
  mode: SortMode,
): RequestSummary[] {
  if (mode === 'title_asc') {
    return requests.slice().sort((a, b) =>
      requestLabel(a).localeCompare(requestLabel(b), 'zh-CN'),
    )
  }
  if (mode === 'request_id_asc') {
    return requests.slice().sort((a, b) =>
      fieldValue(a.request_id).localeCompare(fieldValue(b.request_id), 'zh-CN'),
    )
  }
  return requests.slice()
}

/** Distinct statuses present in the loaded list, sorted by display order. */
export function availableStatuses(
  requests: readonly RequestSummary[],
): string[] {
  const present = new Set(requests.map(summaryStatus))
  const ordered = KNOWN_STATUSES.filter((code) => present.has(code))
  const others = Array.from(present)
    .filter((code) => !KNOWN_STATUSES.includes(code as (typeof KNOWN_STATUSES)[number]))
    .sort((a, b) => a.localeCompare(b, 'zh-CN'))
  return [...ordered, ...others]
}
