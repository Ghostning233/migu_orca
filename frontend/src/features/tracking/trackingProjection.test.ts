import { describe, expect, it } from 'vitest'

import {
  createTrackingActionIntent,
  executableTrackingActions,
  filterTrackingItems,
  projectTrackingOverview,
  reuseTrackingActionIntent,
  sortTrackingItems,
  type CapabilityResult,
  type TrackingItem,
} from './trackingProjection'

type ItemAction = NonNullable<TrackingItem['available_actions']>[number]

function item(overrides: Partial<TrackingItem> = {}): TrackingItem {
  return {
    tracking_id: 'tracking-1', request_id: 'request-1', title: '葬送的芙莉莲', season: 1,
    subtitle_group: '喵萌奶茶屋', poster_path: null, status: 'ACTIVE', status_label: '追番中',
    status_group: 'ACTIVE', available_actions: [], valid_resource_count: 2,
    updated_episode: null, updated_episode_status: 'NOT_IMPLEMENTED', total_episodes: null,
    revision: 3, updated_at: '2026-09-13T00:00:00Z', ...overrides,
  }
}

function capabilities(overrides: Partial<CapabilityResult> = {}): CapabilityResult {
  return {
    probe_status: 'VERIFIED', version: '3.1.18', adapter: 'legacy_3_1',
    subscription_list: 'SUPPORTED', subscription_detail: 'SUPPORTED', subscription_modify: 'SUPPORTED',
    subscription_enable: 'SUPPORTED', subscription_disable: 'SUPPORTED', subscription_delete: 'SUPPORTED',
    rss_list: 'SUPPORTED', rss_modify: 'SUPPORTED', rss_enable: 'SUPPORTED', rss_disable: 'SUPPORTED',
    rss_delete: 'SUPPORTED', rss_refresh: 'SUPPORTED', external_verify: 'SUPPORTED',
    checked_at: null, safe_message: null, ...overrides,
  }
}

function action(overrides: Partial<ItemAction> = {}): ItemAction {
  return {
    code: 'MODIFY', label: '修改', style: 'SECONDARY', requires_confirmation: true,
    target_scopes: ['SUBSCRIPTION'], ...overrides,
  }
}

describe('tracking projection (US-304)', () => {
  it('counts known server status groups and isolates unknown values', () => {
    const result = projectTrackingOverview([
      item(), item({ tracking_id: 'tracking-2', status_group: 'PENDING' }),
      item({ tracking_id: 'tracking-3', status_group: 'UNTRUSTED' as never }),
    ])
    expect(result.total).toBe(3)
    expect(result.byGroup.ACTIVE).toBe(1)
    expect(result.byGroup.PENDING).toBe(1)
    expect(result.unreadable).toBe(1)
  })

  it('searches only public title/subtitle and applies server group filter', () => {
    const rows = [item(), item({ tracking_id: 'tracking-2', title: '咒术回战', subtitle_group: '风之圣殿', status_group: 'ATTENTION' })]
    expect(filterTrackingItems(rows, { query: '喵萌' })).toHaveLength(1)
    expect(filterTrackingItems(rows, { statusGroup: 'ATTENTION' })[0]?.tracking_id).toBe('tracking-2')
    expect(filterTrackingItems(rows, { query: 'tracking-1' })).toHaveLength(0)
  })

  it('sorts deterministically without mutating server order', () => {
    const rows = [item({ tracking_id: 'b' }), item({ tracking_id: 'a' })]
    expect(sortTrackingItems(rows).map((row) => row.tracking_id)).toEqual(['a', 'b'])
    expect(rows.map((row) => row.tracking_id)).toEqual(['b', 'a'])
  })

  it('fails closed for unknown action/style/scope and unsupported capability', () => {
    const rows = item({ available_actions: [
      action(),
      action({ code: 'NOT_KNOWN' as never }),
      action({ style: 'NOT_KNOWN' as never }),
      action({ target_scopes: ['NOT_KNOWN'] as never }),
    ] })
    expect(executableTrackingActions(rows, capabilities())).toHaveLength(1)
    expect(executableTrackingActions(rows, capabilities({ subscription_modify: 'UNKNOWN' }))).toHaveLength(0)
    expect(executableTrackingActions(item({ available_actions: [action({ code: 'SUBMIT', target_scopes: [] })] }))).toHaveLength(1)
  })

  it('creates one revision-bound opaque intent and reuses its key on transport retry', () => {
    const current = item({ available_actions: [action()] })
    const candidate = executableTrackingActions(current, capabilities())[0]!
    const intent = createTrackingActionIntent(current, candidate, 'SUBSCRIPTION', capabilities())
    expect(intent).toMatchObject({ action: 'MODIFY', targetScope: 'SUBSCRIPTION', expectedRevision: 3, confirm: true })
    expect(intent?.idempotencyKey).toMatch(/^[A-Za-z0-9-]{8,128}$/)
    expect(reuseTrackingActionIntent(intent!)).toBe(intent)
    expect(createTrackingActionIntent(current, candidate, 'ASSOCIATED_RSS', capabilities())).toBeNull()
  })
})
