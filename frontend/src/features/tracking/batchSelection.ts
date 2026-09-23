/**
 * Explicit batch submit selection (issue #87).
 *
 * A batch is a user-visible selection of *independent* reliable submissions.
 * This module owns the pure rules only — which rows can be submitted, what a
 * "select all current results" actually selects, what it skipped and why, and
 * how a selection survives filtering. The page owns the request, the single
 * confirmation and the per-entry results.
 *
 * Nothing here reads or writes storage, credentials or the network.
 */
import type { TrackingItem } from './trackingProjection'
import { makeOpaqueKey } from './trackingProjection'

/** The only server-projected actions a batch may carry. */
const BATCH_ACTIONS = new Set(['SUBMIT', 'RETRY'])

export interface TrackingBatchSelection {
  /** Selected tracking ids, in the order the user added them. */
  readonly selected: readonly string[]
  /** Selected-or-skipped ids with a fixed reason, for the batch notice. */
  readonly skipped: Readonly<Record<string, string>>
}

export interface TrackingBatchEntry {
  readonly tracking_id: string
  readonly expected_revision: number
  readonly idempotency_key: string
}

export interface TrackingBatchSubmitBody {
  readonly items: readonly TrackingBatchEntry[]
  readonly confirm: true
  readonly connection_ref: string
  readonly configuration_revision: number
  readonly storage_dir?: string
}

export const EMPTY_BATCH_SELECTION: TrackingBatchSelection = { selected: [], skipped: {} }

/**
 * Fixed reason this row cannot join a batch right now, or ``null`` when it can.
 * Unknown/processing states fail closed: they are never silently submitted.
 */
export function batchSkipReason(item: TrackingItem): string | null {
  if (item.status_group === 'PROCESSING') return '正在处理中，请等待当前操作完成'
  const actions = item.available_actions ?? []
  if (!actions.some((action) => BATCH_ACTIONS.has(String(action.code)))) {
    return '当前状态不可提交'
  }
  return null
}

export interface SkippedBatchEntry {
  readonly trackingId: string
  readonly title: string
  /** Fixed safe reason from the local pre-check — never raw text. */
  readonly reason: string
}

/**
 * The selected plans this batch will not send (issue #100).
 *
 * The batch pre-check uses only the saved plan evidence the list already holds
 * (status + server-advertised actions); it never re-runs the server's state
 * machine and never contacts Auto Bangumi.
 */
export function skippedBatchEntries(
  selection: TrackingBatchSelection,
  items: readonly TrackingItem[],
): SkippedBatchEntry[] {
  const byId = new Map(items.map((item) => [item.tracking_id, item]))
  const skipped: SkippedBatchEntry[] = []
  for (const trackingId of selection.selected) {
    const item = byId.get(trackingId)
    if (!item) {
      skipped.push({ trackingId, title: '未命名番剧', reason: '不在当前列表中，请刷新后重试' })
      continue
    }
    const reason = batchSkipReason(item)
    if (reason) skipped.push({ trackingId, title: item.title || '未命名番剧', reason })
  }
  return skipped
}

export function isBatchSelected(selection: TrackingBatchSelection, trackingId: string): boolean {
  return selection.selected.includes(trackingId)
}

/** Add or remove one row; selection order is preserved. */
export function toggleBatchSelection(
  selection: TrackingBatchSelection,
  trackingId: string,
): TrackingBatchSelection {
  if (isBatchSelected(selection, trackingId)) {
    return { ...selection, selected: selection.selected.filter((id) => id !== trackingId) }
  }
  return { ...selection, selected: [...selection.selected, trackingId] }
}

/**
 * Select every submittable row in the current result set, replacing the
 * selection. Non-submittable rows are recorded with their fixed reason so the
 * page can state exactly what was skipped and why.
 */
export function selectAllBatch(items: readonly TrackingItem[]): TrackingBatchSelection {
  const selected: string[] = []
  const skipped: Record<string, string> = {}
  for (const item of items) {
    const reason = batchSkipReason(item)
    if (reason) skipped[item.tracking_id] = reason
    else selected.push(item.tracking_id)
  }
  return { selected, skipped }
}

export function clearBatchSelection(): TrackingBatchSelection {
  return EMPTY_BATCH_SELECTION
}

export interface TrackingBatchSelectionSummary {
  readonly selected: number
  /** Selected rows that the current filter/search hides. */
  readonly hidden: number
}

/**
 * Counts for the selection banner. Filtering never clears a selection, so the
 * page must always state how many selected rows are currently invisible.
 */
export function batchSelectionSummary(
  selection: TrackingBatchSelection,
  visible: readonly TrackingItem[],
): TrackingBatchSelectionSummary {
  const visibleIds = new Set(visible.map((item) => item.tracking_id))
  return {
    selected: selection.selected.length,
    hidden: selection.selected.filter((id) => !visibleIds.has(id)).length,
  }
}

/**
 * Build the strict batch body from the current selection.
 *
 * Every entry binds the row's *current* revision and a fresh opaque key, so a
 * re-confirmation is a new operation while a transport retry must reuse the
 * locked body. A selection whose row disappeared (filtered away *and* deleted)
 * is dropped rather than silently sent with a stale revision.
 */
export function buildBatchSubmitBody(
  selection: TrackingBatchSelection,
  items: readonly TrackingItem[],
  connection: { connection_ref: string; configuration_revision: number },
  storageDir?: string,
  submissionMode?: 'CONTINUE_TRACKING' | 'DOWNLOAD_EXISTING',
): TrackingBatchSubmitBody | null {
  const byId = new Map(items.map((item) => [item.tracking_id, item]))
  const entries: TrackingBatchEntry[] = []
  for (const trackingId of selection.selected) {
    const item = byId.get(trackingId)
    if (!item) continue
    if (batchSkipReason(item)) continue
    if (!Number.isInteger(item.revision) || item.revision < 1) continue
    entries.push({
      tracking_id: item.tracking_id,
      expected_revision: item.revision,
      idempotency_key: makeOpaqueKey(),
    })
  }
  if (!entries.length) return null
  return {
    items: entries,
    confirm: true,
    // Issue #100: exactly one mode applies to every selected plan.
    ...(submissionMode ? { submission_mode: submissionMode } : {}),
    connection_ref: connection.connection_ref,
    configuration_revision: connection.configuration_revision,
    ...(storageDir ? { storage_dir: storageDir } : {}),
  }
}

export interface TrackingBatchEntryOutcome {
  readonly trackingId: string
  readonly ok: boolean
  /** Published failure category of the entry's business result, when any. */
  readonly failureCategory: string | null
  /** Stable pre-boundary refusal code, when the entry never reached Auto Bangumi. */
  readonly errorType: string | null
  readonly message: string
}

export interface TrackingBatchOutcome {
  readonly entries: readonly TrackingBatchEntryOutcome[]
  readonly succeeded: number
  readonly failed: number
  /** Entries still unresolved: they keep their selection and must be recovered. */
  readonly unresolved: readonly string[]
}

/**
 * Project one accepted batch response into per-entry outcomes.
 *
 * A succeeded entry leaves the selection; a failed or unresolved entry stays
 * selected so the user can act on it again. Unknown server values fail closed:
 * an unrecognized outcome is treated as unresolved, never as success.
 */
export function projectBatchOutcome(result: {
  items?: readonly {
    tracking_id?: string
    ok?: boolean
    error_type?: string | null
    result?: { outcome?: string; failure_category?: string | null } | null
  }[]
}): TrackingBatchOutcome {
  const entries: TrackingBatchEntryOutcome[] = []
  const unresolved: string[] = []
  let succeeded = 0
  let failed = 0
  for (const item of result.items ?? []) {
    const trackingId = typeof item.tracking_id === 'string' ? item.tracking_id : ''
    if (!trackingId) continue
    const outcome = item.result?.outcome
    const isSuccess = item.ok === true && outcome === 'ACTIVE'
    if (isSuccess) {
      succeeded += 1
      entries.push({
        trackingId, ok: true, failureCategory: null, errorType: null,
        message: '提交成功：已在 Auto Bangumi 创建外部订阅。',
      })
      continue
    }
    const indeterminate = outcome === 'VERIFYING_EXTERNAL' || outcome === 'RECOVERY_REQUIRED' || !item.result
    if (indeterminate) {
      unresolved.push(trackingId)
      failed += 1
      entries.push({
        trackingId, ok: false,
        failureCategory: item.result?.failure_category ?? null,
        errorType: item.error_type ?? null,
        message: item.result
          ? '提交结果未知，请先恢复核验；本次不会自动重发。'
          : '服务端在外部提交前拒绝了该条目，正在刷新最新详情，请重新确认。',
      })
      continue
    }
    failed += 1
    entries.push({
      trackingId, ok: false,
      failureCategory: item.result?.failure_category ?? null,
      errorType: item.error_type ?? null,
      message: '提交明确失败，尚未创建外部订阅。',
    })
  }
  return { entries, succeeded, failed, unresolved }
}

/** Keep only the entries that still need the user's attention. */
export function selectionAfterBatch(
  selection: TrackingBatchSelection,
  outcome: TrackingBatchOutcome,
): TrackingBatchSelection {
  const done = new Set(outcome.entries.filter((entry) => entry.ok).map((entry) => entry.trackingId))
  return { ...selection, selected: selection.selected.filter((id) => !done.has(id)) }
}
