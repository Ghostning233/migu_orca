import { describe, expect, it } from 'vitest'

import {
  actionLabel,
  combinedSeedNames,
  completeSeedGroups,
  displayValue,
  effectiveSeeds,
  excludedSeeds,
  isPreview,
  scrubConfig,
  selectedRssSource,
  totalCompleteSeedCount,
  type RequestDetailResult,
  type RequestSnapshot,
} from '@/features/requests/requestDetail'

// US-203: pure detail display helpers mirror the legacy app.js
// (renderDetailPayload / selectedRssSource / combinedSeedNames /
// displayValue / actionLabel / scrubConfig). They are shared between the
// detail panel and its tests; no second implementation lives in the feature.

function snapshot(overrides: Partial<Record<string, unknown>> = {}): RequestSnapshot {
  return {
    request_id: 'req-detail-1',
    status: 'PENDING_CONFIRM',
    input: { raw_title: '葬送的芙莉莲' },
    source_info: {
      matched_bangumi: {
        title: '葬送的芙莉莲',
        aliases: ['Frieren'],
        mikan_url: 'https://example.invalid/bangumi/frieren',
        match_score: 1,
        poster_url: null,
      },
      rss_sources: [
        {
          subtitle_group: '喵萌奶茶屋',
          rss_url: 'https://example.invalid/rss/moe.xml',
          source_type: 'mikan',
          total_seed_count: 3,
          seed_names: ['[喵萌] 葬送的芙莉莲 01.mkv', '[喵萌] 葬送的芙莉莲 02.mkv'],
          valid_seed_count: 2,
          invalid_seed_count: 1,
          valid_seed_names: ['[喵萌] 葬送的芙莉莲 01.mkv', '[喵萌] 葬送的芙莉莲 02.mkv'],
          excluded_seed_names: [
            { name: '[喵萌] 葬送的芙莉莲 SP.mkv', reason: '命中排除规则：SP', rule: 'must_not_contain' },
          ],
          warnings: [],
        },
        {
          subtitle_group: 'Loli',
          rss_url: 'https://example.invalid/rss/loli.xml',
          source_type: 'mikan',
          total_seed_count: 1,
          seed_names: ['[Loli] 葬送的芙莉莲 01.mkv'],
          valid_seed_count: 1,
          invalid_seed_count: 0,
          valid_seed_names: ['[Loli] 葬送的芙莉莲 01.mkv'],
          excluded_seed_names: [],
          warnings: [],
        },
      ],
    },
    confirmable_config: {
      selected_subtitle_group: '喵萌奶茶屋',
      selected_rss_url: 'https://example.invalid/rss/moe.xml',
      filter_rule: {
        must_contain: '',
        must_not_contain: '',
        use_regex: false,
        case_sensitive: false,
      },
      effective_seed_names: ['[喵萌] 葬送的芙莉莲 01.mkv', '[喵萌] 葬送的芙莉莲 02.mkv'],
      expected_folder_name: '葬送的芙莉莲',
      warnings: [],
    },
    ab_submit_result: null,
    created_at: '2026-08-31T00:00:00+00:00',
    updated_at: '2026-08-31T00:00:00+00:00',
    user_action: null,
    ...overrides,
  }
}

function detailResult(overrides: Partial<Record<string, unknown>> = {}): RequestDetailResult {
  return {
    request: snapshot(),
    history: { available: true, events: [], error: null },
    ab_result: { available: false, record: null, error: null },
    ...overrides,
  } as RequestDetailResult
}

describe('displayValue / actionLabel (US-203)', () => {
  it('renders null/empty as 未设置', () => {
    expect(displayValue(null)).toBe('未设置')
    expect(displayValue('')).toBe('未设置')
    expect(displayValue(undefined)).toBe('未设置')
  })

  it('renders arrays joined with ，', () => {
    expect(displayValue(['a', 'b'])).toBe('a，b')
  })

  it('redacts URL-looking strings', () => {
    expect(displayValue('https://secret.example.invalid/x')).toBe('[redacted_url]')
    expect(displayValue('http://x')).toBe('[redacted_url]')
  })

  it('maps history action codes to Chinese labels and keeps unknown as-is', () => {
    expect(actionLabel('ACCEPT')).toBe('确认')
    expect(actionLabel('CANCEL')).toBe('取消')
    expect(actionLabel('MODIFY')).toBe('修改')
    expect(actionLabel('FUTURE_ACTION')).toBe('FUTURE_ACTION')
    expect(actionLabel(null)).toBe('未设置')
  })
})

describe('selectedRssSource (US-203)', () => {
  it('prefers the source matching the selected subtitle group', () => {
    const source = selectedRssSource(snapshot())
    expect(source?.subtitle_group).toBe('喵萌奶茶屋')
  })

  it('falls back to the first source when no group matches', () => {
    const req = snapshot({ confirmable_config: { ...snapshot().confirmable_config, selected_subtitle_group: '不存在' } })
    const source = selectedRssSource(req)
    expect(source?.subtitle_group).toBe('喵萌奶茶屋')
  })

  it('returns null for an empty source list', () => {
    const req = snapshot({ source_info: { matched_bangumi: {}, rss_sources: [] } })
    expect(selectedRssSource(req)).toBeNull()
  })
})

describe('seed helpers (US-203)', () => {
  it('combines unique valid + excluded names', () => {
    expect(combinedSeedNames(['a', 'b'], ['b', 'c'])).toEqual(['a', 'b', 'c'])
    expect(combinedSeedNames([], [])).toEqual([])
  })

  it('computes effective seeds from the selected source', () => {
    expect(effectiveSeeds(snapshot())).toEqual(['[喵萌] 葬送的芙莉莲 01.mkv', '[喵萌] 葬送的芙莉莲 02.mkv'])
  })

  it('falls back to confirmable_config.effective_seed_names when valid_seed_names is absent', () => {
    const req = snapshot({
      source_info: {
        matched_bangumi: {},
        rss_sources: [{ subtitle_group: '喵萌奶茶屋', rss_url: null, valid_seed_names: null }],
      },
    })
    expect(effectiveSeeds(req)).toEqual(['[喵萌] 葬送的芙莉莲 01.mkv', '[喵萌] 葬送的芙莉莲 02.mkv'])
  })

  it('extracts excluded seed name/reason pairs', () => {
    const seeds = excludedSeeds(snapshot())
    expect(seeds).toEqual([
      { name: '[喵萌] 葬送的芙莉莲 SP.mkv', reason: '命中排除规则：SP' },
    ])
  })

  it('handles bare-string excluded entries', () => {
    const req = snapshot({
      source_info: {
        matched_bangumi: {},
        rss_sources: [{ subtitle_group: '喵萌奶茶屋', excluded_seed_names: ['旧种子'] }],
      },
    })
    expect(excludedSeeds(req)).toEqual([{ name: '旧种子', reason: '' }])
  })

  it('groups complete seeds by subtitle group with per-group names', () => {
    const groups = completeSeedGroups(snapshot())
    expect(groups).toHaveLength(2)
    expect(groups[0]!.subtitleGroup).toBe('喵萌奶茶屋')
    expect(groups[0]!.seedNames).toEqual([
      '[喵萌] 葬送的芙莉莲 01.mkv',
      '[喵萌] 葬送的芙莉莲 02.mkv',
      '[喵萌] 葬送的芙莉莲 SP.mkv',
    ])
    expect(groups[1]!.seedNames).toEqual(['[Loli] 葬送的芙莉莲 01.mkv'])
  })

  it('counts complete seeds across all groups', () => {
    expect(totalCompleteSeedCount(snapshot())).toBe(4)
  })
})

describe('scrubConfig (US-203)', () => {
  it('redacts sensitive keys and URL values recursively', () => {
    const cleaned = scrubConfig({
      token: 'secret',
      endpoint: 'https://x.example.invalid',
      fallback_config: { rss_url: 'https://y.example.invalid', plain: 'ok' },
      nested: [{ password: 'pw', value: 'keep' }],
    }) as Record<string, unknown>
    // Sensitive *keys* are redacted wholesale (legacy behavior), even when the
    // value is a URL — the key check wins over the value URL check.
    expect(cleaned.token).toBe('[redacted]')
    expect(cleaned.endpoint).toBe('[redacted]')
    expect((cleaned.nested as Array<Record<string, unknown>>)[0]!.password).toBe('[redacted]')
    expect((cleaned.nested as Array<Record<string, unknown>>)[0]!.value).toBe('keep')
    // Non-sensitive keys keep their values; URL-looking string *values* are
    // redacted to [redacted_url].
    const fallback = cleaned.fallback_config as Record<string, unknown>
    expect(fallback.rss_url).toBe('[redacted]')
    expect(fallback.plain).toBe('ok')
    expect(
      scrubConfig({ plain_link: 'https://z.example.invalid', plain: 'ok' }),
    ).toEqual({ plain_link: '[redacted_url]', plain: 'ok' })
  })
})

describe('isPreview (US-203)', () => {
  it('detects an unsaved preview by the saved_request flag', () => {
    expect(isPreview(detailResult())).toBe(false)
    expect(isPreview({ ...detailResult(), saved_request: null } as unknown as RequestDetailResult)).toBe(true)
  })
})
