/**
 * Batch workbench helpers (US-205).
 *
 * Pure display/validation helpers shared by the BatchWorkbenchView and its
 * unit tests. They mirror the legacy `app.js` batch flow
 * (batchStatusLabel / buildBatchParsePayload / batchCardTitle /
 * batchCardPreferenceSummary / batchCardSeedSummary / canExpandBatchCard /
 * batchCardRequest / renderBatchCandidateChoices / resolveBatchAcceptDescriptors
 * / applyBatchAcceptResult / showBatchAcceptNotification / batchQueueStatusLabel
 * / batchQueueItemSummary / batchQueueSummaryMessage / recordUserCorrection) so
 * the old `/index` batch tab and the new `/app/add` batch section stay
 * parity for the same API result.
 *
 * Security boundary: these helpers operate on the generated OpenAPI batch
 * types only (public parse items, candidate whitelists and sanitized queue
 * items). They never receive credentials, raw bodies or local absolute paths,
 * and they actively redact URL-looking values at display time. No value here
 * is ever persisted or logged.
 */
import { api } from '@/api/client'
import type { operations } from '@/api/generated/api'
import { displayValue, type RequestSnapshot } from '@/features/requests/requestDetail'

/** Public batch parse result produced by `POST /api/v1/batches/parse`. */
export type BatchParseResult = NonNullable<
  operations['parseBatchTitles']['responses']['200']['content']['application/json']['result']
>

/** One typed batch card (public parse item + client draft state). */
export type BatchItem = NonNullable<BatchParseResult['items']>[number]

/** The typed Mikan candidate inside a batch card (strict whitelist). */
export type BatchCandidate = NonNullable<BatchItem['candidates']>[number]

/** Public accept-result item produced by `POST /api/v1/batches/{id}/accept`. */
export type BatchAcceptResult = NonNullable<
  operations['acceptBatchItems']['responses']['200']['content']['application/json']['result']
>

/** Public submit-result item (submit/retry/recover share the accept shape). */
export type BatchSubmitResult = NonNullable<
  operations['submitBatchQueue']['responses']['200']['content']['application/json']['result']
>

/** Public queue item (sanitized summaries only). */
export type QueueItem = NonNullable<
  NonNullable<
    operations['getBatchQueue']['responses']['200']['content']['application/json']['result']['queue']
  >['items']
>[number]

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

/** Chinese label for a queue item status code. */
export const QUEUE_STATUS_LABELS: Record<string, string> = {
  READY_TO_SUBMIT: '待提交',
  SUBMITTING: '提交中',
  SUCCEEDED: '提交成功',
  FAILED: '提交失败',
  RETRYABLE: '可重试',
  RESULT_PERSIST_FAILED: '结果保存失败',
}

/** Chinese label for a queue status; unknown codes render as-is. */
export function queueStatusLabel(status: string | null | undefined): string {
  const value = String(status ?? '')
  return QUEUE_STATUS_LABELS[value] ?? value
}

/** One-line queue item summary (result summary > last error > none). */
export function queueItemSummary(item: QueueItem): string {
  if (item.ab_result_summary) {
    return `结果：${item.ab_result_summary}`
  }
  if (item.last_error) {
    return `错误：${item.last_error}`
  }
  return '尚无结果摘要'
}

/** Validate the batch raw input before calling the parse API. */
export function validateBatchRawInput(rawInput: string): string | null {
  if (!rawInput.trim()) {
    return '批量获取前必须输入至少一个番剧名称。'
  }
  return null
}

/** Count the non-empty lines of a batch input (used in the loading message). */
export function batchItemCount(rawInput: string): number {
  return rawInput.split(/\r?\n/).filter((line) => line.trim()).length
}

/** Build the batch parse request payload (only user input + storage context). */
export function buildBatchParsePayload(rawInput: string, storageDir: string | null): Record<string, unknown> {
  return { raw_input: rawInput, storage_dir: storageDir || null }
}

/** True when a batch card is FOUND with a selectable candidate list. */
export function canChooseBatchCandidate(item: BatchItem): boolean {
  return String(item.status ?? '') === 'FOUND' && (item.candidates?.length ?? 0) > 0
}

/** True when a batch card is in the explicit "candidate choices" popover. */
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
    source: 'mikan',
    mikan_bangumi: candidate.mikan_url,
    storage_dir: options.storageDir || null,
    save_request: false,
  }
  if (typeof candidate.candidate_context === 'string' && candidate.candidate_context) {
    payload.candidate_context = candidate.candidate_context
  }
  if (Number.isInteger(options.confirmedSeason)) {
    payload.season_confirmation = options.confirmedSeason
  }
  return payload
}

/** One descriptor for the batch accept endpoint (public fields only). */
export interface BatchAcceptDescriptor {
  item_id: string
  request_id: string | null
  title: string
}

/** Collect the accept descriptors for the given cards (saved or preview). */
export function collectBatchAcceptDescriptors(items: readonly BatchItem[]): BatchAcceptDescriptor[] {
  return items.map((item) => ({
    item_id: item.item_id ?? '',
    request_id: (item.preview_request as RequestSnapshot | null)?.request_id ?? null,
    title: batchCardTitle(item),
  }))
}

/** Build the batch accept payload (item_ids omitted for accept-all). */
export function buildBatchAcceptPayload(
  descriptors: readonly BatchAcceptDescriptor[],
  itemIds: readonly string[] | null,
  storageDir: string | null,
): Record<string, unknown> {
  const payload: Record<string, unknown> = {
    items: descriptors.map(({ item_id, request_id, title }) => ({ item_id, request_id, title })),
    storage_dir: storageDir || null,
  }
  if (itemIds) {
    payload.item_ids = [...itemIds]
  }
  return payload
}

/** Post the batch accept request through the shared transport. */
export async function postBatchAccept(
  batchId: string,
  payload: Record<string, unknown>,
): Promise<BatchAcceptResult> {
  return api.post<BatchAcceptResult>(`/api/v1/batches/{batch_id}/accept`, {
    path: { batch_id: batchId },
    body: payload,
  })
}

/** True when an accept result item was accepted (or already accepted). */
export function acceptOutcomeAccepted(item: { status?: string | null }): boolean {
  return item.status === 'accepted' || item.status === 'already_accepted'
}

/** Chinese label for an accept-feedback status code. */
export function acceptFeedbackLabel(status: string | null | undefined): string {
  return String(status ?? '') === 'failed' ? '接受失败：' : '无法接受：'
}

/** Build the batch accept notification copy (legacy showBatchAcceptNotification). */
export function batchAcceptNotification(summary: Record<string, number | undefined>, isSingle: boolean): { kind: 'success' | 'error'; title: string; message: string } {
  const accepted = summary.accepted ?? 0
  const already = summary.already_accepted ?? 0
  const bad = (summary.unacceptable ?? 0) + (summary.failed ?? 0)
  let message = `已接受 ${accepted} 项`
  if (already) {
    message += `；已确认跳过 ${already} 项`
  }
  if (bad) {
    message += `；${bad} 项无法接受`
  }
  if (isSingle) {
    if (bad > 0 && accepted === 0) {
      return { kind: 'error', title: '接受失败', message }
    }
    return { kind: 'success', title: '接受成功', message: '当前批量卡片已标记为已接受并待提交，其他卡片保持不变。' }
  }
  if (bad > 0 && accepted === 0) {
    return { kind: 'error', title: '批量接受失败', message }
  }
  if (bad > 0) {
    return { kind: 'success', title: '批量接受完成', message }
  }
  return { kind: 'success', title: '批量接受成功', message }
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
