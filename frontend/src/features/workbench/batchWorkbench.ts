/**
 * Batch workbench helpers (US-205).
 *
 * Pure display/validation helpers shared by the BatchWorkbenchView and its
 * unit tests. They mirror the legacy `app.js` batch flow
 * (batchStatusLabel / buildBatchParsePayload / batchCardTitle /
 * batchCardPreferenceSummary / batchCardSeedSummary / canExpandBatchCard /
 * batchCardRequest / renderBatchCandidateChoices / batchQueueStatusLabel
 * / batchQueueItemSummary / batchQueueSummaryMessage / recordUserCorrection) so
 * the `/app/add` batch section stays consistent with the generated API result.
 *
 * Security boundary: these helpers operate on the generated OpenAPI batch
 * types only (public parse items, candidate whitelists and sanitized queue
 * items). They never receive credentials, raw bodies or local absolute paths,
 * and they actively redact URL-looking values at display time. No value here
 * is ever persisted or logged.
 */
import type { operations } from '@/api/generated/api'
import { isPublicRouteIdentifier } from '@/app/router/catalog'
import { displayValue, type RequestSnapshot } from '@/features/requests/requestDetail'
import type { SaveConfirmBatchItemsBody, SaveConfirmBatchItemsResult, TrackingItemsResult } from '@/app/composables/useBatchReviewJourney'

/** Public batch parse result produced by `POST /api/v1/batches/parse`. */
export type BatchParseResult = NonNullable<
  operations['parseBatchTitles']['responses']['200']['content']['application/json']['result']
>

/** One typed batch card (public parse item + client draft state). */
export type BatchItem = NonNullable<BatchParseResult['items']>[number]

/** The typed Mikan candidate inside a batch card (strict whitelist). */
export type BatchCandidate = NonNullable<BatchItem['candidates']>[number]

export type BatchSaveConfirmResult = SaveConfirmBatchItemsResult
export type BatchSaveConfirmItem = BatchSaveConfirmResult['results'][number]
export type BatchTrackingItem = TrackingItemsResult['items'][number]

/** User-facing Chinese label for a batch card status code. */
export const BATCH_STATUS_LABELS: Record<string, string> = {
  RAW: '待解析',
  PARSED: '已解析',
  FOUND: '找到候选',
  EMPTY: '未找到候选',
  FAILED: '搜索失败',
  NEEDS_REVIEW: '待确认',
  DRAFT: '草案',
  READY: '待接受',
  ACCEPTED: '已接受',
  CONFIRMED: '已确认待提交',
  SAVED_PENDING_CONFIRM: '已保存待确认',
  RESPONSE_UNKNOWN: '结果待核验',
}

/** Chinese label for a batch status; unknown codes render as-is. */
export function batchStatusLabel(status: string | null | undefined): string {
  const value = String(status ?? '')
  return BATCH_STATUS_LABELS[value] ?? value
}

/** True when a batch card can expand into the candidate choices / draft. */
export function canExpandBatchCard(item: BatchItem): boolean {
  const status = String(item.status ?? '')
  return status === 'DRAFT' || status === 'READY'
}

/** The client-held Request snapshot for a card (saved, preview or draft). */
export function batchCardRequest(item: BatchItem): RequestSnapshot | null {
  return (item.preview_request as RequestSnapshot | null) ?? null
}

/** True when a batch card can be accepted (has a reviewable draft). */
export function canAcceptBatchCard(item: BatchItem): boolean {
  return canExpandBatchCard(item) && Boolean(batchCardRequest(item))
}

/** True when a batch card can be modified (has a reviewable draft). */
export function canModifyBatchCard(item: BatchItem): boolean {
  return canExpandBatchCard(item) && Boolean(batchCardRequest(item))
}

/** Display title for a batch card (canonical candidate > raw title). */
export function batchCardTitle(item: BatchItem): string {
  const canonical = Array.isArray(item.canonical_title_candidates)
    ? item.canonical_title_candidates
    : []
  if (canonical.length && canonical[0]) {
    return canonical[0] || '未命名条目'
  }
  return item.raw_title || '未命名条目'
}

/** Chinese label for a preference-hit field code (legacy helper). */
export function batchCardPreferenceHitLabel(field: string | null | undefined): string {
  const labels: Record<string, string> = {
    subtitle_groups: '字幕组',
    filter_rule: '筛选',
    naming: '命名',
  }
  const value = String(field ?? '')
  return labels[value] ?? value
}

/** True when the card fell back to the default flow (preference failure). */
export function batchCardPreferenceFallback(item: BatchItem): string | null {
  for (const warning of item.preference_warnings ?? []) {
    const text = String(warning ?? '')
    if (text.includes('偏好读取失败') || text.includes('偏好应用失败')) {
      return text
    }
  }
  return null
}

/** One-line preference summary for the card footer (legacy helper). */
export function batchCardPreferenceSummary(item: BatchItem): string {
  if (batchCardPreferenceFallback(item)) {
    return '偏好不可用，已回退默认流程'
  }
  const hits = item.preference_hits ?? []
  const appliedFields = hits
    .filter((hit) => hit?.applied === true)
    .map((hit) => batchCardPreferenceHitLabel(typeof hit?.field === 'string' ? hit.field : null))
  if (appliedFields.length) {
    return `偏好命中：${appliedFields.join('、')}`
  }
  return '未配置偏好，使用默认流程'
}

/** Chinese label for a preference fallback code (legacy helper). */
export function batchCardFallbackLabel(fallback: string | null | undefined): string {
  const labels: Record<string, string> = {
    next_preferred: '偏好字幕组优先',
    none: '不自动选择',
  }
  const value = String(fallback ?? '')
  return labels[value] ?? value
}

/** Chinese label for a naming strategy code (legacy helper). */
export function batchCardNamingStrategyLabel(strategy: string | null | undefined): string {
  const labels: Record<string, string> = {
    official_title_season: '官方标题+季',
    official_title: '官方标题',
    raw_title: '原始标题',
  }
  const value = String(strategy ?? '')
  return labels[value] ?? value
}

/** Seed count summary for the card footer (effective seeds or 待展开). */
export function batchCardSeedSummary(item: BatchItem): string {
  const request = batchCardRequest(item)
  const effective = request?.confirmable_config?.effective_seed_names ?? []
  if (effective.length) {
    return String(effective.length)
  }
  return '待展开'
}

/** True when the card is flagged for human review (never for ACCEPTED). */
export function batchCardNeedsReview(item: BatchItem): boolean {
  return item.needs_user_review === true && String(item.status ?? '') !== 'ACCEPTED'
}

/** Validate the batch raw input before calling the parse API. */
export function validateBatchRawInput(rawInput: string): string | null {
  const count = batchItemCount(rawInput)
  if (count === 0) {
    return '批量获取前必须输入至少一个番剧名称；当前为 0 部，请输入 1～36 部后再获取。'
  }
  if (count > 36) {
    return `批量输入包含 ${count} 部番剧，超过单批上限 36 部；请减少后再获取。`
  }
  return null
}

/** Count the non-empty lines of a batch input (used in the loading message). */
export function batchItemCount(rawInput: string): number {
  return rawInput.split(/\r?\n/).filter((line) => line.trim()).length
}

/** Keep blocking failures first, then review items, then normal items. */
export function orderBatchItemsForReview(items: BatchItem[]): BatchItem[] {
  const groups: BatchItem[][] = [[], [], []]
  for (const item of items) {
    const status = String(item.status ?? '')
    const group = status === 'FAILED' || status === 'EMPTY' ? 0 : item.needs_user_review === true ? 1 : 2
    groups[group]!.push(item)
  }
  return groups.flat()
}

/** Whether a batch item is an exception that should be surfaced for review. */
export function batchItemIsException(item: BatchItem): boolean {
  return String(item.status ?? '') === 'FAILED' || String(item.status ?? '') === 'EMPTY' || batchCardNeedsReview(item)
}

/** Find the next exception after the current item, wrapping at the end. */
export function nextBatchException(items: BatchItem[], currentItemId: string | null): BatchItem | null {
  const exceptions = items.filter(batchItemIsException)
  if (!exceptions.length) return null
  const currentIndex = items.findIndex((item) => item.item_id === currentItemId)
  const start = currentIndex < 0 ? 0 : currentIndex + 1
  return exceptions.find((item) => items.indexOf(item) >= start) ?? exceptions[0] ?? null
}

/** Match one item against the additive workbench search/filter controls. */
export function batchItemMatchesReviewFilters(
  item: BatchItem,
  filters: { query: string; status: string; exceptionsOnly: boolean },
): boolean {
  const query = filters.query.trim().toLocaleLowerCase()
  const title = `${item.raw_title ?? ''} ${batchCardTitle(item)}`.toLocaleLowerCase()
  if (query && !title.includes(query)) return false
  if (filters.status && String(item.status ?? '') !== filters.status) return false
  if (filters.exceptionsOnly && !batchItemIsException(item)) return false
  return true
}

/** Build the batch parse request payload (only user input + storage context). */
export function buildBatchParsePayload(rawInput: string, storageDir: string | null): Record<string, unknown> {
  return { raw_input: rawInput, storage_dir: storageDir || null }
}

/** True when a batch card is FOUND with a selectable candidate list. */
export function canChooseBatchCandidate(item: BatchItem): boolean {
  return String(item.status ?? '') === 'FOUND' && (item.candidates?.length ?? 0) > 0
}

/** True when a batch card is the active right-hand candidate detail. */
export function isCandidateActive(item: BatchItem, activeItemId: string | null): boolean {
  return activeItemId !== null && item.item_id === activeItemId
}

/** True when the candidate selection is blocked (conflict / unconfirmed season). */
export function batchCandidateSelectionIsBlocked(candidate: BatchCandidate, confirmedSeason: number | null): boolean {
  const evidence = candidate.season_evidence
  if (!evidence) return false
  if (evidence.status === 'CONFLICT') return true
  return evidence.status === 'NEEDS_CONFIRMATION' && !Number.isInteger(confirmedSeason)
}

/** True when the candidate needs the explicit season-confirmation checkbox. */
export function batchCandidateNeedsConfirmation(candidate: BatchCandidate): boolean {
  return candidate.season_evidence?.status === 'NEEDS_CONFIRMATION'
}

/** Episode-progress display text for a batch card (same as single-search). */
export function batchEpisodeProgressText(totalEpisodes: number | null | undefined): string {
  const total = Number(totalEpisodes)
  return Number.isInteger(total) && total > 0 ? `播出进度：待开发 / ${total} 集` : '播出进度：待开发 / 未知'
}

/** Build the create-request payload for a selected batch candidate. */
export function buildBatchCandidateCreatePayload(
  candidate: BatchCandidate,
  options: { storageDir: string; confirmedSeason: number | null },
): Record<string, unknown> {
  const payload: Record<string, unknown> = {
    title: candidate.title || '未命名合集',
    mikan_bangumi: candidate.mikan_url,
    storage_dir: options.storageDir || null,
  }
  if (typeof candidate.candidate_context === 'string' && candidate.candidate_context) {
    payload.candidate_context = candidate.candidate_context
  }
  if (Number.isInteger(options.confirmedSeason)) {
    payload.season_confirmation = options.confirmedSeason
  }
  return payload
}

export interface BatchSaveConfirmDescriptor {
  item_id: string
  draft_id: string
  base_revision: number
  idempotency_key: string
}

export interface BatchAcceptAllCounts {
  /** Every item of the parsed batch. */
  total: number
  /** Items currently passing the shared confirmability gate. */
  confirmable: number
  /** Confirmable items the active review filter hides. */
  hidden: number
}

/** Clamp the confirm-all counts to the batch they describe. */
function normalizeAcceptAllCounts(counts: BatchAcceptAllCounts): {
  total: number
  confirmable: number
  hidden: number
  excluded: number
} {
  const total = Math.max(0, Math.trunc(counts.total))
  const confirmable = Math.max(0, Math.min(Math.trunc(counts.confirmable), total))
  const hidden = Math.max(0, Math.min(Math.trunc(counts.hidden), confirmable))
  return { total, confirmable, hidden, excluded: total - confirmable }
}

/**
 * US-347: visible scope line for the 保存并确认全部 entry.
 *
 * The confirm-all scope is the complete batch's confirmable set — review
 * filters and checkbox selection only change what the user browses, never what
 * 全部 saves. The text therefore states the batch total, the confirmable count
 * (M), how many of them the current filter hides, and how many are excluded,
 * so the entry is described by visible copy and not only by a hover title.
 */
export function batchAcceptAllScopeText(counts: BatchAcceptAllCounts): string {
  const { total, confirmable, hidden, excluded } = normalizeAcceptAllCounts(counts)
  if (total === 0) return ''
  if (confirmable === 0) {
    return `完整批次 ${total} 项均不可确认：请先为条目生成可审核草案，并处理待应用编辑、重算、失败、已确认或结果待核验的条目。`
  }
  const details = [`保存并确认全部覆盖完整批次 ${total} 项中的 ${confirmable} 项可确认条目`]
  if (hidden) details.push(`其中 ${hidden} 项当前被筛选隐藏`)
  if (excluded) details.push(`排除 ${excluded} 项未就绪、已确认或结果待核验条目`)
  return `${details.join('，')}；不受筛选或勾选影响。`
}

export interface BatchAcceptAllConfirmCopy {
  title: string
  message: string
  confirmLabel: string
}

/**
 * US-348: dialog copy for one frozen confirm-all intent.
 *
 * The title and the confirm button both state M so the number the user saw is
 * the number the button promises; the body states the complete batch, the
 * hidden participants that still travel with the request, the excluded items,
 * and that this only saves a local plan — the external Auto Bangumi submit is
 * a separate, later confirmation.
 */
export function batchAcceptAllConfirmCopy(counts: BatchAcceptAllCounts): BatchAcceptAllConfirmCopy {
  const { total, confirmable, hidden, excluded } = normalizeAcceptAllCounts(counts)
  const clauses = [`完整批次 ${total} 部中当前可确认 ${confirmable} 部`]
  if (hidden) clauses.push(`其中 ${hidden} 部被筛选隐藏，仍会一并保存并确认`)
  const exclusion = excluded ? `已排除 ${excluded} 部未就绪、已确认或结果待核验的条目。` : ''
  const label = `保存并确认全部 ${confirmable} 部`
  return {
    title: label,
    message: `${clauses.join('，')}。${exclusion}仅保存本地订阅方案，不会提交到 Auto Bangumi；外部提交需在追番管理再次确认。`,
    confirmLabel: label,
  }
}

/** Build the generated save-confirm body; capabilities never leave this payload. */
export function buildBatchSaveConfirmPayload(
  descriptors: readonly BatchSaveConfirmDescriptor[],
  itemIds: readonly string[] | null,
  storageDir: string | null,
): SaveConfirmBatchItemsBody {
  return {
    items: descriptors.map((item) => ({ ...item })),
    ...(itemIds ? { item_ids: [...itemIds] } : {}),
    storage_dir: storageDir || null,
  }
}

export function batchSaveConfirmSucceeded(item: BatchSaveConfirmItem): boolean {
  return String(item.outcome ?? '').toUpperCase() === 'CONFIRMED' && isPublicRouteIdentifier(item.request_id) &&
    (!item.tracking_id || isPublicRouteIdentifier(item.tracking_id))
}

export function batchSaveConfirmErrorLabel(item: BatchSaveConfirmItem): string {
  const labels: Record<string, string> = {
    draft_expired: '订阅草案已失效，请重新生成。',
    draft_revision_conflict: '草案已更新，请基于最新版本重试。',
    idempotency_conflict: '本次操作与已有操作冲突，请重新开始。',
    save_confirm_failed: '订阅方案已保存，但确认未完成。可重试确认。',
    draft_reserved: '订阅草案正在处理中，请稍后重试。',
  }
  return labels[item.error_type ?? ''] ?? '保存确认失败，请重试。'
}

export function batchSaveConfirmRecoveryAllowed(item: BatchSaveConfirmItem): boolean {
  return item.error_type === 'save_confirm_failed' &&
    String(item.outcome ?? '').toUpperCase() === 'FAILED' &&
    isPublicRouteIdentifier(item.request_id)
}

/** Locate a public tracking row only by the confirmed request identity. */
export function findBatchTrackingItem(result: TrackingItemsResult, requestId: string): BatchTrackingItem | null {
  if (!isPublicRouteIdentifier(requestId) || !Array.isArray(result.items)) return null
  const match = result.items.find((item) => item.request_id === requestId)
  return match && isPublicRouteIdentifier(match.request_id) && match.request_id === requestId && isPublicRouteIdentifier(match.tracking_id)
    ? match
    : null
}

/** Build the batch submit summary message (legacy batchQueueSummaryMessage). */
export function batchSubmitSummaryMessage(summary: Record<string, number | undefined>): string {
  const succeeded = summary.succeeded ?? 0
  const failed = summary.failed ?? 0
  const retryable = summary.retryable ?? 0
  const skipped = summary.skipped ?? 0
  let message = `提交成功 ${succeeded} 项`
  if (failed) {
    message += `；提交失败 ${failed} 项`
  }
  if (retryable) {
    message += `；可重试 ${retryable} 项`
  }
  if (skipped) {
    message += `；跳过 ${skipped} 项`
  }
  return message
}

/** Build the batch submit notification kind/title from the summary. */
export function batchSubmitNotification(summary: Record<string, number | undefined>): { kind: 'success' | 'error'; title: string; message: string } {
  const message = batchSubmitSummaryMessage(summary)
  const succeeded = summary.succeeded ?? 0
  const failed = summary.failed ?? 0
  const retryable = summary.retryable ?? 0
  if (succeeded === 0 && (failed > 0 || retryable > 0)) {
    return { kind: 'error', title: '批量提交失败', message }
  }
  if (failed > 0 || retryable > 0) {
    return { kind: 'success', title: '批量提交完成', message }
  }
  return { kind: 'success', title: '批量提交成功', message }
}

export { displayValue }
