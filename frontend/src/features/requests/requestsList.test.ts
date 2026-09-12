import { describe, expect, it } from 'vitest'

import {
  availableStatuses,
  fieldValue,
  filterRequests,
  requestLabel,
  searchableText,
  sortRequests,
  statusLabel,
  summaryStatus,
  type RequestSummary,
} from '@/features/requests/requestsList'

// Public summary fixtures (no sensitive values — summaries are the public
// DTO shape, never raw request snapshots).
function summary(overrides: Partial<RequestSummary> = {}): RequestSummary {
  return {
    request_id: 'req-a',
    status: 'PENDING_CONFIRM',
    bangumi_title: '葬送的芙莉莲',
    season: null,
    updated_at: '2026-08-31T00:00:00+00:00',
    candidate_subtitle_groups: [],
    selected_subtitle_group: '喵萌奶茶屋',
    effective_seed_count: 5,
    expected_folder_name: '葬送的芙莉莲 (2023)',
    warnings: [],
    ...overrides,
  }
}

const FIXTURES: RequestSummary[] = [
  summary({
    request_id: 'req-a',
    status: 'PENDING_CONFIRM',
    bangumi_title: '葬送的芙莉莲',
    selected_subtitle_group: '喵萌奶茶屋',
    expected_folder_name: '葬送的芙莉莲 (2023)',
  }),
  summary({
    request_id: 'req-b',
    status: 'ACCEPTED',
    bangumi_title: '咒术回战第三季',
    selected_subtitle_group: 'LoliHouse',
    expected_folder_name: '咒术回战第三季',
  }),
  summary({
    request_id: 'req-c',
    status: 'CANCELLED',
    bangumi_title: '葬送的芙莉莲',
    selected_subtitle_group: '北宇治字幕组',
    expected_folder_name: '葬送的芙莉莲 (2023) S2',
  }),
]

describe('fieldValue / statusLabel (US-202)', () => {
  it('renders empty values as 未设置', () => {
    expect(fieldValue(null)).toBe('未设置')
    expect(fieldValue(undefined)).toBe('未设置')
    expect(fieldValue('')).toBe('未设置')
    expect(fieldValue('req-a')).toBe('req-a')
  })

  it('maps status codes to Chinese business labels', () => {
    expect(statusLabel('PENDING_CONFIRM')).toBe('待确认')
    expect(statusLabel('ACCEPTED')).toBe('已确认')
    expect(statusLabel('CANCELLED')).toBe('已取消')
  })

  it('renders unknown status codes as-is (internal value, never a leak)', () => {
    expect(statusLabel('UNKNOWN_STATUS')).toBe('UNKNOWN_STATUS')
    expect(statusLabel(null)).toBe('未设置')
  })
})

describe('requestLabel / searchableText (US-202)', () => {
  it('falls back through title, request_id, subtitle group', () => {
    expect(requestLabel(FIXTURES[0]!)).toBe('葬送的芙莉莲')
    expect(requestLabel(summary({ bangumi_title: null, request_id: 'req-x' }))).toBe('req-x')
    expect(
      requestLabel(summary({ bangumi_title: null, request_id: null, selected_subtitle_group: '喵萌' })),
    ).toBe('喵萌')
    expect(
      requestLabel(
        summary({ bangumi_title: null, request_id: null, selected_subtitle_group: null }),
      ),
    ).toBe('未命名订阅方案')
  })

  it('lowercases and joins the searchable fields', () => {
    const text = searchableText(FIXTURES[0]!)
    expect(text).toContain('葬送的芙莉莲')
    expect(text).toContain('req-a')
    expect(text).toContain('喵萌奶茶屋')
    expect(text).toContain('葬送的芙莉莲 (2023)')
  })
})

describe('filterRequests (US-202)', () => {
  it('returns all when no term/status given', () => {
    expect(filterRequests(FIXTURES, '', '')).toHaveLength(3)
  })

  it('filters by title search term', () => {
    const result = filterRequests(FIXTURES, '芙莉莲', '')
    expect(result.map((item) => item.request_id)).toEqual(['req-a', 'req-c'])
  })

  it('filters by request_id search term (case-insensitive)', () => {
    const result = filterRequests(FIXTURES, 'REQ-A', '')
    expect(result.map((item) => item.request_id)).toEqual(['req-a'])
  })

  it('filters by status code', () => {
    const result = filterRequests(FIXTURES, '', 'ACCEPTED')
    expect(result.map((item) => item.request_id)).toEqual(['req-b'])
  })

  it('combines search and status filters', () => {
    const result = filterRequests(FIXTURES, '芙莉莲', 'CANCELLED')
    expect(result.map((item) => item.request_id)).toEqual(['req-c'])
  })

  it('returns empty for a non-matching term', () => {
    expect(filterRequests(FIXTURES, '不存在的番剧', '')).toEqual([])
  })
})

describe('sortRequests (US-202)', () => {
  it('keeps server order for the default mode', () => {
    const result = sortRequests(FIXTURES, 'default')
    expect(result.map((item) => item.request_id)).toEqual(['req-a', 'req-b', 'req-c'])
  })

  it('sorts by title ascending with zh-CN locale', () => {
    const result = sortRequests(FIXTURES, 'title_asc')
    const titles = result.map(requestLabel)
    expect(titles).toEqual([...titles].sort((a, b) => a.localeCompare(b, 'zh-CN')))
  })

  it('sorts by request_id ascending', () => {
    const result = sortRequests(FIXTURES, 'request_id_asc')
    expect(result.map((item) => item.request_id)).toEqual(['req-a', 'req-b', 'req-c'])
  })

  it('does not mutate the input array', () => {
    const input = [...FIXTURES]
    sortRequests(input, 'title_asc')
    expect(input.map((item) => item.request_id)).toEqual(['req-a', 'req-b', 'req-c'])
  })
})

describe('summaryStatus / availableStatuses (US-202)', () => {
  it('normalizes a missing status for filtering', () => {
    expect(summaryStatus(summary({ status: null }))).toBe('未设置')
  })

  it('returns distinct statuses in the canonical display order', () => {
    expect(availableStatuses(FIXTURES)).toEqual(['PENDING_CONFIRM', 'ACCEPTED', 'CANCELLED'])
  })

  it('appends unknown statuses after the canonical ones', () => {
    const result = availableStatuses([...FIXTURES, summary({ status: 'WEIRD' })])
    expect(result).toEqual(['PENDING_CONFIRM', 'ACCEPTED', 'CANCELLED', 'WEIRD'])
  })
})
