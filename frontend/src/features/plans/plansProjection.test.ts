import { describe, expect, it } from 'vitest'

import type { RequestSummary } from '@/features/requests/requestsList'
import {
  TRACKING_NOT_LINKED_LABEL,
  TRACKING_UNAVAILABLE_LABEL,
  buildPlanRows,
  filterPlanRows,
  joinTrackingItems,
  planTrackingLabel,
  projectPlanRows,
  sortPlanRows,
  type TrackingItem,
} from '@/features/plans/plansProjection'

function request(overrides: Partial<RequestSummary> = {}): RequestSummary {
  return {
    request_id: 'req-a',
    status: 'PENDING_CONFIRM',
    bangumi_title: '葬送的芙莉莲',
    season: null,
    updated_at: '2026-09-01T00:00:00Z',
    candidate_subtitle_groups: [
      {
        subtitle_group: '喵萌奶茶屋',
        total_resource_count: 2,
        valid_resource_count: 2,
        invalid_resource_count: 0,
      },
    ],
    selected_subtitle_group: '喵萌奶茶屋',
    effective_seed_count: 2,
    expected_folder_name: '葬送的芙莉莲',
    warnings: [],
    ...overrides,
  }
}

function tracking(overrides: Partial<TrackingItem> = {}): TrackingItem {
  return {
    tracking_id: 'tracking-a',
    request_id: 'req-a',
    title: '葬送的芙莉莲',
    season: 1,
    subtitle_group: '喵萌奶茶屋',
    poster_path: null,
    status: 'ACTIVE',
    status_label: '追番中',
    status_group: 'ACTIVE',
    valid_resource_count: 2,
    updated_episode: null,
    updated_episode_status: 'NOT_IMPLEMENTED',
    total_episodes: null,
    revision: 1,
    updated_at: '2026-09-01T00:00:00Z',
    ...overrides,
  }
}

describe('plans projection (US-295)', () => {
  it('joins one exact request_id match and never exposes tracking actions', () => {
    const row = projectPlanRows([request()], [tracking()])[0]!
    expect(row.tracking?.trackingId).toBe('tracking-a')
    expect(row.tracking?.statusLabel).toBe('追番中')
    expect(planTrackingLabel(row)).toBe('追番中')
  })

  it('drops duplicate, missing, external-only, and invalid tracking associations', () => {
    const rows = projectPlanRows(
      [request(), request({ request_id: 'req-b' })],
      [
        tracking(),
        tracking({ tracking_id: 'tracking-b' }),
        tracking({ request_id: 'req-b', status: 'EXTERNAL_ONLY' }),
        tracking({ request_id: 'req-c' }),
        tracking({ request_id: 'req-b', tracking_id: '/private/path' }),
      ],
    )
    expect(rows[0]!.tracking).toBeNull()
    expect(rows[1]!.tracking).toBeNull()
    expect(planTrackingLabel(rows[1]!)).toBe(TRACKING_NOT_LINKED_LABEL)
    expect(joinTrackingItems([tracking({ status_label: '' })]).get('req-a')?.statusLabel).toBe(
      '追番中',
    )
    expect(TRACKING_UNAVAILABLE_LABEL).toBe('追番状态暂不可用')
  })

  it('sorts valid timestamps descending and keeps invalid/missing values stable at the end', () => {
    const rows = projectPlanRows([
      request({ request_id: 'old', updated_at: '2026-01-01T00:00:00Z' }),
      request({ request_id: 'invalid', updated_at: 'not-a-time' }),
      request({ request_id: 'new', updated_at: '2026-09-10T00:00:00Z' }),
      request({ request_id: 'missing', updated_at: null }),
      request({ request_id: 'invalid-2', updated_at: 'still-invalid' }),
    ])
    expect(sortPlanRows(rows).map((row) => row.request.request_id)).toEqual([
      'new',
      'old',
      'invalid',
      'missing',
      'invalid-2',
    ])
  })

  it('searches public title and subtitle fields but not request_id', () => {
    const rows = projectPlanRows([request({ request_id: 'private-looking-id' })])
    expect(filterPlanRows(rows, '芙莉莲', '')).toHaveLength(1)
    expect(filterPlanRows(rows, '喵萌', '')).toHaveLength(1)
    expect(filterPlanRows(rows, 'private-looking-id', '')).toHaveLength(0)
    expect(filterPlanRows(rows, '', 'ACCEPTED')).toHaveLength(0)
  })

  it('composes stable sorting, title filtering, and Request-only status filtering', () => {
    const result = buildPlanRows(
      [
        request({ request_id: 'pending', updated_at: '2026-09-01T00:00:00Z' }),
        request({ request_id: 'accepted', status: 'ACCEPTED', updated_at: '2026-09-02T00:00:00Z' }),
      ],
      [tracking({ request_id: 'accepted', status: 'SUBMIT_FAILED', status_label: '提交失败' })],
      '芙莉莲',
      'ACCEPTED',
    )
    expect(result.map((row) => row.request.request_id)).toEqual(['accepted'])
    expect(result[0]!.tracking?.status).toBe('SUBMIT_FAILED')
  })
})
