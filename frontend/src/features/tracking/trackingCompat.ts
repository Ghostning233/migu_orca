/**
 * One-time compatibility location for the retired queue entry (US-316).
 *
 * Stage 38 replaced `/app/tracking` (the old `QueueView` queue workflow) with
 * the formal tracking management screen, and `/app/queue?batch_id=...` is now a
 * redirect into it. The legacy batch link still has to land somewhere useful,
 * but it must never become a second source of truth: the only thing this module
 * reads from the old surface is each queue item's *public* `request_id`, which it
 * maps onto the local tracking list. Status, actions, selection and every
 * external decision continue to come from the generated tracking DTO.
 *
 * Nothing here guesses by title, season, filename or ordering heuristics, and
 * nothing renders an identifier: a request id that matches no selectable local
 * record simply does not locate, and the page states a fixed next step instead.
 */
import type { operations } from '@/api/generated/api'

import type { TrackingItem } from './trackingProjection'

type BatchQueueResult = NonNullable<
  operations['getBatchQueue']['responses']['200']['content']['application/json']['result']
>

/**
 * Fixed Chinese next step when a legacy batch link cannot be located (US-316).
 *
 * The batch id itself is a public identifier, but it is deliberately not echoed
 * here: the notice only ever states what the user can do next, so no legacy
 * identifier, error type or raw server text can reach the DOM.
 */
export const BATCH_COMPAT_NOT_LOCATED =
  '旧的批量入口已退出：本批次没有可定位的本地追番记录，请在列表中选择记录，或到追番方案查看该批次。'

/** Fixed Chinese next step when the legacy batch read itself fails (US-316). */
export const BATCH_COMPAT_READ_FAILED =
  '旧的批量入口已退出：暂时无法读取该批次，请在列表中选择记录，或稍后重试。'

/**
 * Collect the public request ids the legacy queue projection publishes.
 *
 * Unknown shapes fail closed to an empty list: a queue payload the page cannot
 * read must not locate anything (and must never fall back to another field).
 */
export function projectQueueRequestIds(result: BatchQueueResult | null | undefined): string[] {
  const items = result?.queue?.items
  if (!Array.isArray(items)) return []
  const requestIds: string[] = []
  for (const item of items) {
    const requestId: unknown = item?.request_id
    if (typeof requestId === 'string' && requestId) requestIds.push(requestId)
  }
  return requestIds
}

/**
 * Map legacy queue request ids onto local tracking records, in queue order.
 *
 * The tracking DTO stays authoritative: only `request_id` equality is used, and
 * a record the tracking list no longer offers as a selectable destination (an
 * externally deleted one) is not located either.
 */
export function locateTrackingIdForBatch(
  requestIds: readonly string[],
  items: readonly TrackingItem[],
): string | null {
  for (const requestId of requestIds) {
    const match = items.find(
      (item) => item.request_id === requestId && item.status !== 'EXTERNAL_DELETED',
    )
    if (match) return match.tracking_id
  }
  return null
}
