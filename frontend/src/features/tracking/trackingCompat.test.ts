import { describe, expect, it } from 'vitest'

import {
  BATCH_COMPAT_NOT_LOCATED,
  BATCH_COMPAT_READ_FAILED,
  locateTrackingIdForBatch,
  projectQueueRequestIds,
} from './trackingCompat'
import type { TrackingItem } from './trackingProjection'

function item(overrides: Partial<TrackingItem> = {}): TrackingItem {
  return {
    tracking_id: 'tracking-1', request_id: 'request-1', title: '葬送的芙莉莲', season: 1,
    subtitle_group: '喵萌奶茶屋', poster_path: null, status: 'ACTIVE', status_label: '追番中',
    status_group: 'ACTIVE', available_actions: [], valid_resource_count: 2,
    updated_episode: null, updated_episode_status: 'NOT_IMPLEMENTED', total_episodes: null,
    revision: 3, updated_at: '2026-09-13T00:00:00Z', ...overrides,
  }
}

function queue(items: readonly unknown[]): never {
  return { batch_id: 'batch-legacy', queue: { queue_id: 'queue-legacy', batch_id: 'batch-legacy', items } } as never
}

describe('legacy batch compatibility location (US-316)', () => {
  it('reads only the public request ids the queue projection publishes', () => {
    expect(projectQueueRequestIds(queue([
      { item_id: 'item-1', request_id: 'request-1', title: '示例' },
      { item_id: 'item-2', request_id: 'request-2' },
    ]))).toEqual(['request-1', 'request-2'])
  })

  it('fails closed when the queue payload cannot be read', () => {
    expect(projectQueueRequestIds(null)).toEqual([])
    expect(projectQueueRequestIds(undefined)).toEqual([])
    expect(projectQueueRequestIds({ batch_id: 'batch-legacy', queue: null } as never)).toEqual([])
    expect(projectQueueRequestIds({ batch_id: 'batch-legacy', queue: { items: 'nope' } } as never)).toEqual([])
    expect(projectQueueRequestIds(queue([
      { item_id: 'item-1' },
      { item_id: 'item-2', request_id: '' },
      { item_id: 'item-3', request_id: 42 },
      { item_id: 'item-4', request_id: 'request-4' },
    ]))).toEqual(['request-4'])
  })

  it('locates a local tracking record by public request_id in queue order', () => {
    const items = [item({ tracking_id: 'tracking-a', request_id: 'request-a' }),
      item({ tracking_id: 'tracking-b', request_id: 'request-b' })]
    expect(locateTrackingIdForBatch(['request-b', 'request-a'], items)).toBe('tracking-b')
  })

  it('never guesses: an unmatched or unknown identifier does not locate', () => {
    const items = [item({ tracking_id: 'tracking-a', request_id: 'request-a' })]
    expect(locateTrackingIdForBatch([], items)).toBeNull()
    expect(locateTrackingIdForBatch(['request-missing'], items)).toBeNull()
    // A title/season match is not an identity match — only request_id counts.
    expect(locateTrackingIdForBatch(['葬送的芙莉莲'], items)).toBeNull()
    expect(locateTrackingIdForBatch(['request-a'], [item({ request_id: null })])).toBeNull()
  })

  it('does not locate a record the tracking list no longer offers as a destination', () => {
    const items = [
      item({ tracking_id: 'tracking-gone', request_id: 'request-gone', status: 'EXTERNAL_DELETED' }),
      item({ tracking_id: 'tracking-live', request_id: 'request-live' }),
    ]
    expect(locateTrackingIdForBatch(['request-gone'], items)).toBeNull()
    expect(locateTrackingIdForBatch(['request-gone', 'request-live'], items)).toBe('tracking-live')
  })

  it('states a fixed Chinese next step that carries no identifier or server text', () => {
    for (const copy of [BATCH_COMPAT_NOT_LOCATED, BATCH_COMPAT_READ_FAILED]) {
      expect(copy).toContain('旧的批量入口已退出')
      expect(copy).not.toMatch(/batch|request|trk_|http|error_type/i)
    }
  })
})
