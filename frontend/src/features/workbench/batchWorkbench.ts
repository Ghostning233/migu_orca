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

/** One label/value pair of the card's on-demand auxiliary layer. */
export interface BatchCardFact {
  label: string
  value: string
}

/**
 * US-355: the auxiliary card facts (aliases, queries, season hint, preference
 * resolution, candidate count and episode placeholder).
 *
 * These are the facts a reviewer only needs while investigating a card, so the
 * default layer stays compact. Everything that decides whether an item is
 * blocked — status, blockers, failures, unknown results and recovery actions —
 * is rendered outside this list and is therefore never hidden by it.
 */
export function batchCardAuxiliaryFacts(item: BatchItem): BatchCardFact[] {
  const facts: BatchCardFact[] = []
  const title = batchCardTitle(item)
  const aliases = (item.canonical_title_candidates ?? [])
    .filter((alias): alias is string => typeof alias === 'string' && Boolean(alias.trim()) && alias !== title)
  if (aliases.length) facts.push({ label: '别名', value: aliases.join('、') })
  const queries = (item.search_queries ?? []).filter((query): query is string => typeof query === 'string' && Boolean(query.trim()))
  if (queries.length) facts.push({ label: '检索关键词', value: queries.join('、') })
  if (item.season_hint) facts.push({ label: '季数提示', value: String(item.season_hint) })
  const candidates = item.candidates?.length ?? 0
  if (candidates) facts.push({ label: '候选合集', value: `${candidates} 个` })
  facts.push({ label: '偏好', value: batchCardPreferenceSummary(item) })
  facts.push({ label: '总集数', value: batchEpisodeProgressText(undefined).replace('总集数：', '') })
  return facts
}

/** Public, decision-relevant inputs of one card's single next step. */
export interface BatchCardGuidance {
  status: string | null | undefined
  /** The card is still at the real-collection step and has choices to show. */
  hasCandidates: boolean
  /** The card owns a server-authoritative draft that can still be confirmed. */
  hasDraft: boolean
  /** First blocker of the shared confirmability gate, when the card is blocked. */
  blocker: string | null
  /** The last save result still has to be verified against the frozen request. */
  resultUnknown: boolean
  /** The plan is saved locally and its confirmation is still open. */
  savedPendingConfirm: boolean
  /** The confirmed plan is already bound to a real tracking record. */
  trackingLocated: boolean
  /** A draft generation for this card is in flight. */
  generating: boolean
}

/**
 * US-355: the one action the reviewer should take for this card.
 *
 * Pure copy over public state only: recovery and terminal states win over the
 * generic branches so the card never suggests regenerating a draft that is
 * actually waiting for a retry of an already-frozen request.
 */
export function batchCardNextStep(guidance: BatchCardGuidance): string {
  const status = String(guidance.status ?? '')
  if (guidance.generating) return '等待当前候选的订阅草案生成完成。'
  if (guidance.resultUnknown || status === 'RESPONSE_UNKNOWN') {
    return '用「使用相同操作重试」或「重试定位」核验本条结果。'
  }
  if (guidance.savedPendingConfirm || status === 'SAVED_PENDING_CONFIRM') {
    return '点「重试确认」完成确认；不会重复保存。'
  }
  if (status === 'CONFIRMED') {
    return guidance.trackingLocated
      ? '在我的追番中再次确认后提交外部订阅。'
      : '点「重试定位」找回追番记录后继续。'
  }
  if (status === 'FAILED') return '删除该条目，或调整名称后重新获取批量草案。'
  if (status === 'EMPTY') return '删除该条目，或改用更完整的名称后重新获取。'
  if (guidance.hasCandidates) return '在右栏选择真实 MiKan 合集生成草案。'
  if (guidance.blocker) return `先解决：${guidance.blocker}。`
  if (guidance.hasDraft) return '勾选加入待确认，或用「保存并确认全部」。'
  return '重新获取批量草案以生成可审核条目。'
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
  return Number.isInteger(total) && total > 0 ? `总集数：${total} 集` : '总集数：未知'
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

/**
 * US-356: the one count model both save entries are described by.
 *
 * `confirmable`/`hidden` describe the complete batch's 保存并确认全部 scope;
 * `selected`/`selectedHidden`/`selectedExcluded` describe the D-02 scope of
 * 保存并确认 N 部 (manually checked *and* currently eligible items of the
 * complete batch — a review filter never removes a manual intent, and a checked
 * item that is not currently eligible never enters the request).
 */
export interface BatchConfirmScopeCounts extends BatchAcceptAllCounts {
  /** Items the active review filter currently shows. */
  visible: number
  /** Complete-batch items that are checked and currently eligible (N). */
  selected: number
  /** Of `selected`, those the active review filter hides but that still travel. */
  selectedHidden: number
  /** Checked items that are currently not eligible, so excluded from N. */
  selectedExcluded: number
  /** Complete-batch items that still need processing before they can confirm. */
  needsProcessing: number
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

/** Clamp every scope count to the set it is derived from. */
function normalizeConfirmScopeCounts(counts: BatchConfirmScopeCounts): {
  total: number
  visible: number
  selected: number
  selectedHidden: number
  selectedExcluded: number
  confirmable: number
  hidden: number
  excluded: number
  needsProcessing: number
} {
  const base = normalizeAcceptAllCounts(counts)
  const visible = Math.max(0, Math.min(Math.trunc(counts.visible), base.total))
  const selected = Math.max(0, Math.min(Math.trunc(counts.selected), base.total))
  const selectedExcluded = Math.max(0, Math.min(Math.trunc(counts.selectedExcluded), base.total - selected))
  const selectedHidden = Math.max(0, Math.min(Math.trunc(counts.selectedHidden), selected))
  return { ...base, visible, selected, selectedHidden, selectedExcluded, needsProcessing: base.excluded }
}

/**
 * US-356: visible scope line for the 保存并确认 N 部 entry.
 *
 * N is the complete batch's manually checked *and* currently eligible set
 * (D-02): a review filter only changes what the user browses, so it never drops
 * a manual intent, and a checked item that is currently blocked keeps its check
 * but is excluded from the request. The copy states the batch total, that same
 * N, how many of the N items the filter hides, and how many checked items are
 * excluded, so the entry is described by visible copy and not only by a title.
 */
export function batchSelectedScopeText(counts: BatchConfirmScopeCounts): string {
  const { total, selected, selectedHidden, selectedExcluded } = normalizeConfirmScopeCounts(counts)
  if (total === 0) return ''
  if (selected === 0) {
    const excluded = selectedExcluded
      ? `已勾选但当前不可确认的 ${selectedExcluded} 部被排除：请先解决各自的阻断原因。`
      : ''
    return `完整批次 ${total} 部中没有已勾选且可确认的条目：请先在卡片上勾选当前可确认的条目。${excluded}`
  }
  const details = [`保存并确认 ${selected} 部来自完整批次 ${total} 部中已勾选且当前可确认的条目`]
  if (selectedHidden) details.push(`其中 ${selectedHidden} 部当前被筛选隐藏、仍会一并保存`)
  if (selectedExcluded) details.push(`已勾选但当前不可确认的 ${selectedExcluded} 部被排除`)
  return `${details.join('，')}；筛选与可见全选不改变本集合。`
}

export interface BatchConfirmDialogCopy {
  title: string
  message: string
  confirmLabel: string
  /** Heading for the safety title list; empty when there is no list. */
  itemsLabel: string
  /** The frozen, display-safe titles of exactly the items that will be sent. */
  items: string[]
}

export type BatchAcceptAllConfirmCopy = BatchConfirmDialogCopy

/**
 * US-356: dialog copy for one frozen N-part intent.
 *
 * The title and the confirm button both state N so the number the user saw on
 * the entry is the number the button promises; the body states that the set
 * comes from the complete batch, the hidden participants that still travel with
 * the request, the checked items that were excluded, and that this only saves a
 * local plan — the external Auto Bangumi submit is a separate, later
 * confirmation. The title list is exactly the frozen participant set.
 */
export function batchSelectedConfirmCopy(
  counts: BatchConfirmScopeCounts,
  titles: readonly string[] = [],
): BatchConfirmDialogCopy {
  const { total, selected, selectedHidden, selectedExcluded } = normalizeConfirmScopeCounts(counts)
  const clauses = [`本次保存并确认完整批次 ${total} 部中已勾选且当前可确认的 ${selected} 部`]
  if (selectedHidden) clauses.push(`其中 ${selectedHidden} 部被筛选隐藏，仍会一并保存并确认`)
  const exclusion = selectedExcluded ? `已勾选但当前不可确认的 ${selectedExcluded} 部被排除。` : ''
  const label = `保存并确认 ${selected} 部`
  return {
    title: label,
    confirmLabel: label,
    itemsLabel: titles.length ? `本次将保存并确认的 ${titles.length} 部` : '',
    items: [...titles],
    message: `${clauses.join('，')}。${exclusion}仅保存本地订阅方案，不会提交到 Auto Bangumi；外部提交需在我的追番再次确认。`,
  }
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

/**
 * US-348 / US-356: dialog copy for one frozen confirm-all intent.
 *
 * The title and the confirm button both state M so the number the user saw is
 * the number the button promises; the body states the complete batch, the
 * hidden participants that still travel with the request, the excluded items,
 * and that this only saves a local plan — the external Auto Bangumi submit is
 * a separate, later confirmation.
 */
export function batchAcceptAllConfirmCopy(
  counts: BatchAcceptAllCounts,
  titles: readonly string[] = [],
): BatchConfirmDialogCopy {
  const { total, confirmable, hidden, excluded } = normalizeAcceptAllCounts(counts)
  const clauses = [`完整批次 ${total} 部中当前可确认 ${confirmable} 部`]
  if (hidden) clauses.push(`其中 ${hidden} 部被筛选隐藏，仍会一并保存并确认`)
  const exclusion = excluded ? `已排除 ${excluded} 部未就绪、已确认或结果待核验的条目。` : ''
  const label = `保存并确认全部 ${confirmable} 部`
  return {
    title: label,
    confirmLabel: label,
    itemsLabel: titles.length ? `本次将保存并确认的 ${titles.length} 部` : '',
    items: [...titles],
    message: `${clauses.join('，')}。${exclusion}仅保存本地订阅方案，不会提交到 Auto Bangumi；外部提交需在我的追番再次确认。`,
  }
}

/**
 * US-356: the persistent, visible reason both save entries are disabled by.
 *
 * A disabled entry must always carry this copy in the business area; the
 * `title` attribute is never the only explanation. It returns an empty string
 * exactly when no transport-level block applies — an empty scope is explained
 * by that entry's own scope line instead.
 */
export function batchConfirmDisabledReason(state: { saving: boolean; pendingVerification: boolean }): string {
  if (state.pendingVerification) {
    return '上一次批量保存结果待核验：请先用「使用相同操作重试」核验后再发起新的确认，不会重复保存。'
  }
  if (state.saving) return '正在保存确认：请等待本次请求完成后再次提交。'
  return ''
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

export interface BatchSaveConfirmOutcomeSummary {
  requested: number
  confirmed: number
  failed: number
  /** Items in the complete batch that still need work after this response. */
  remaining: number
  total: number
}

export function batchSaveConfirmOutcomeSummaryText(summary: BatchSaveConfirmOutcomeSummary): string {
  return `本次结果：已确认 ${summary.confirmed} 项；失败 ${summary.failed} 项；完整批次剩余 ${summary.remaining} 项。`
}

/**
 * US-357: derive the persistent batch summary from the server's result rows.
 * The response summary is useful as transport metadata, but it is not the
 * authority for item state and must not be used to infer partial success.
 */
export function batchSaveConfirmOutcomeSummary(
  results: readonly BatchSaveConfirmItem[],
  items: readonly BatchItem[],
): BatchSaveConfirmOutcomeSummary {
  const confirmedIds = new Set(
    items.filter((item) => String(item.status ?? '') === 'CONFIRMED').map((item) => item.item_id ?? ''),
  )
  let confirmed = 0
  for (const result of results) {
    if (!batchSaveConfirmSucceeded(result)) continue
    confirmed += 1
    if (result.item_id) confirmedIds.add(result.item_id)
  }
  return {
    requested: results.length,
    confirmed,
    failed: Math.max(0, results.length - confirmed),
    remaining: Math.max(0, items.length - confirmedIds.size),
    total: items.length,
  }
}

export type BatchSaveConfirmNextFocus = { kind: 'failed' | 'remaining'; itemId: string } | null

/** Choose the first recoverable target without ever inventing a hidden node. */
export function batchSaveConfirmNextFocus(
  results: readonly BatchSaveConfirmItem[],
  items: readonly BatchItem[],
): BatchSaveConfirmNextFocus {
  const resultById = new Map(results.map((result) => [result.item_id, result]))
  for (const item of items) {
    const result = resultById.get(item.item_id ?? '')
    if (result && !batchSaveConfirmSucceeded(result) && item.item_id) {
      return { kind: 'failed', itemId: item.item_id }
    }
  }
  const confirmedIds = new Set(
    items.filter((item) => String(item.status ?? '') === 'CONFIRMED').map((item) => item.item_id ?? ''),
  )
  for (const result of results) {
    if (batchSaveConfirmSucceeded(result) && result.item_id) confirmedIds.add(result.item_id)
  }
  const remaining = items.find((item) => item.item_id && !confirmedIds.has(item.item_id))
  return remaining?.item_id ? { kind: 'remaining', itemId: remaining.item_id } : null
}

/** Return a real public tracking id for D-04 completion navigation only. */
export function batchSaveConfirmTrackingId(results: readonly BatchSaveConfirmItem[]): string | null {
  const result = results.find((candidate) => batchSaveConfirmSucceeded(candidate) && isPublicRouteIdentifier(candidate.tracking_id))
  return result?.tracking_id ?? null
}

/** Issue 114: 每条失败只能得到一种最小安全恢复动作。 */
export type BatchSaveRecoveryAction =
  | 'RETRY_CONFIRM'
  | 'REGENERATE_DRAFT'
  | 'RETRY_SAVE'
  | 'VERIFY_RESULT'
  | 'NONE'

export interface BatchSaveRecoveryInput {
  status?: string | null
  /** 最近一次保存确认针对该条目的失败类型（若有）。 */
  errorType?: string | null
  /** 已确认条目是否已经定位到真实追番记录。 */
  trackingLocated?: boolean
}

const DRAFT_INVALID_ERROR_TYPES = [
  'draft_expired',
  'draft_evicted',
  'draft_replayed',
  'draft_revision_conflict',
] as const

/**
 * 把条目状态与最近一次失败原因投影成唯一恢复动作。
 *
 * - 已保存但确认未完成：只允许「重试确认」，不会重复保存；
 * - 草案失效／版本冲突：只允许「重新生成草案」；
 * - 响应未知：只允许核验（重试定位）或按冻结请求同键重放；
 * - 其他可再次保存的普通失败：只允许「重试保存」（新的明确操作 → 新幂等键）。
 *
 * 未知输入 fail closed：返回 NONE，不给出可能造成重复外部写的动作。
 */
export function batchSaveRecoveryAction(input: BatchSaveRecoveryInput): BatchSaveRecoveryAction {
  const status = String(input.status ?? '')
  const errorType = String(input.errorType ?? '')
  if (status === 'RESPONSE_UNKNOWN') return 'VERIFY_RESULT'
  if (status === 'SAVED_PENDING_CONFIRM') return 'RETRY_CONFIRM'
  if (status === 'CONFIRMED') return input.trackingLocated ? 'NONE' : 'VERIFY_RESULT'
  if ((DRAFT_INVALID_ERROR_TYPES as readonly string[]).includes(errorType)) return 'REGENERATE_DRAFT'
  if (status === 'DRAFT' && errorType) return 'RETRY_SAVE'
  return 'NONE'
}

/** 恢复动作的固定中文文案；空动作没有按钮文案。 */
export function batchSaveRecoveryLabel(action: BatchSaveRecoveryAction): string {
  return {
    RETRY_CONFIRM: '重试确认',
    REGENERATE_DRAFT: '重新生成草案',
    RETRY_SAVE: '重试保存',
    VERIFY_RESULT: '重试定位',
    NONE: '',
  }[action]
}

/** True when the failure type means the draft can never be replayed as-is. */
export function batchSaveErrorInvalidatesDraft(errorType: string | null | undefined): boolean {
  return (DRAFT_INVALID_ERROR_TYPES as readonly string[]).includes(String(errorType ?? ''))
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
