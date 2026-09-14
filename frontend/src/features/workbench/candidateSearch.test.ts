import { describe, expect, it } from 'vitest'

import {
  buildCandidateCreatePayload,
  buildFallbackCreatePayload,
  candidateSelectionIsBlocked,
  collectPreviewEditPatch,
  episodeProgressText,
  needsSeasonConfirmation,
  parseSeasonNumber,
  parseSourceLabel,
  validateCandidateQuery,
  validateFallbackValue,
  type MikanCandidate,
  type PreviewEditState,
} from '@/features/workbench/candidateSearch'

// US-204: pure helpers for the workbench single-search flow. They mirror the
// legacy app.js functions (buildCandidateSearchPayload / renderCandidateCard /
// candidateSelectionIsBlocked / renderTitleParseSummary / collectPreviewEditPatch)
// so `/index` and `/app/workbench` stay parity. The helpers only operate on
// public whitelisted candidate fields; `mikan_url` is never rendered by the
// card and `candidate_context` is a one-time in-memory capability.

function candidate(overrides: Partial<Record<string, unknown>> = {}): MikanCandidate {
  return {
    bangumi_id: '2353',
    title: '葬送的芙莉莲',
    mikan_url: 'https://mikan.example/Home/Bangumi/2353',
    poster_url: null,
    source_query: '芙莉莲',
    aliases: [],
    recommendation: null,
    total_episodes: null,
    season_evidence: null,
    candidate_context: null,
    ...overrides,
  } as never
}

describe('candidateSearch validation helpers', () => {
  it('rejects an empty candidate query with the legacy Chinese message', () => {
    expect(validateCandidateQuery('')).toBe('搜索 MiKan 候选前必须填写番剧标题。')
    expect(validateCandidateQuery('   ')).toBe('搜索 MiKan 候选前必须填写番剧标题。')
    expect(validateCandidateQuery('芙莉莲')).toBeNull()
  })

  it('validates the direct-fallback value like the legacy page', () => {
    expect(validateFallbackValue('')).toBe('生成前必须填写 MiKan 合集 URL 或 ID。')
    expect(validateFallbackValue('not a url or id')).toBe('必须是数字 ID 或 HTTP(S) URL。')
    expect(validateFallbackValue('2353')).toBeNull()
    expect(validateFallbackValue('https://mikan.example/Home/Bangumi/2353')).toBeNull()
    expect(validateFallbackValue('http://mikan.example/42')).toBeNull()
  })

  it('formats episode progress with explicit or unknown totals', () => {
    expect(episodeProgressText(28)).toBe('播出进度：待开发 / 28 集')
    expect(episodeProgressText(null)).toBe('播出进度：待开发 / 未知')
    expect(episodeProgressText('invalid' as never)).toBe('播出进度：待开发 / 未知')
    expect(episodeProgressText(0)).toBe('播出进度：待开发 / 未知')
  })
})

describe('candidateSearch parse summary helpers', () => {
  it('maps parse source codes to Chinese labels and falls back', () => {
    expect(parseSourceLabel('alias')).toBe('别名匹配')
    expect(parseSourceLabel('rule')).toBe('规则识别')
    expect(parseSourceLabel('correction')).toBe('用户修正')
    expect(parseSourceLabel('fallback')).toBe('原始标题回退')
    expect(parseSourceLabel('unknown-code')).toBe('原始标题回退')
    expect(parseSourceLabel(null)).toBe('原始标题回退')
  })

  it('extracts a valid season number from the parse result', () => {
    expect(parseSeasonNumber({ season: { number: 4, raw: 's4', normalized: '第四季', source: 'title_marker' } } as never)).toBe(4)
    expect(parseSeasonNumber({ season: { number: null } } as never)).toBeNull()
    expect(parseSeasonNumber(null)).toBeNull()
    expect(parseSeasonNumber({ season: { number: 'invalid' } } as never)).toBeNull()
    expect(parseSeasonNumber({} as never)).toBeNull()
  })
})

describe('candidateSearch season evidence helpers', () => {
  it('detects NEEDS_CONFIRMATION candidates', () => {
    expect(
      needsSeasonConfirmation(
        candidate({ season_evidence: { status: 'NEEDS_CONFIRMATION', season: 4, requires_review: true } }),
      ),
    ).toBe(true)
    expect(needsSeasonConfirmation(candidate())).toBe(false)
    expect(needsSeasonConfirmation(candidate({ season_evidence: { status: 'PROVEN', season: 4, requires_review: false } }))).toBe(false)
  })

  it('blocks CONFLICT candidates regardless of confirmation', () => {
    const conflict = candidate({ season_evidence: { status: 'CONFLICT', season: null, requires_review: true } })
    expect(candidateSelectionIsBlocked(conflict, null)).toBe(true)
    expect(candidateSelectionIsBlocked(conflict, 4)).toBe(true)
  })

  it('blocks NEEDS_CONFIRMATION until the season is explicitly confirmed', () => {
    const needs = candidate({ season_evidence: { status: 'NEEDS_CONFIRMATION', season: 4, requires_review: true } })
    expect(candidateSelectionIsBlocked(needs, null)).toBe(true)
    expect(candidateSelectionIsBlocked(needs, 4)).toBe(false)
  })

  it('never blocks candidates without season evidence', () => {
    expect(candidateSelectionIsBlocked(candidate(), null)).toBe(false)
  })
})

describe('candidateSearch payload builders', () => {
  it('builds the create payload with public candidate metadata only', () => {
    const payload = buildCandidateCreatePayload(
      candidate({ candidate_context: 'opaque-context', season_evidence: { status: 'NEEDS_CONFIRMATION', season: 4, requires_review: true } }),
      { storageDir: 'backups', confirmedSeason: 4 },
    )
    expect(payload).toEqual({
      title: '葬送的芙莉莲',
      source: 'mikan',
      mikan_bangumi: 'https://mikan.example/Home/Bangumi/2353',
      storage_dir: 'backups',
      candidate_context: 'opaque-context',
      season_confirmation: 4,
    })
  })

  it('omits candidate_context and season_confirmation when absent', () => {
    const payload = buildCandidateCreatePayload(candidate(), { storageDir: '', confirmedSeason: null })
    expect(payload).toEqual({
      title: '葬送的芙莉莲',
      source: 'mikan',
      mikan_bangumi: 'https://mikan.example/Home/Bangumi/2353',
      storage_dir: null,
    })
    expect('candidate_context' in payload).toBe(false)
    expect('season_confirmation' in payload).toBe(false)
  })

  it('builds the fallback payload without a user-supplied endpoint', () => {
    const payload = buildFallbackCreatePayload(' 2353 ', { storageDir: 'backups', title: '芙莉莲' })
    expect(payload).toEqual({
      title: '芙莉莲',
      source: 'mikan',
      mikan_bangumi: '2353',
      storage_dir: 'backups',
    })
    expect('mikan_config' in payload).toBe(false)
  })

  it('uses the MiKan 直连合集 title fallback for an empty query', () => {
    const payload = buildFallbackCreatePayload('42', { storageDir: '', title: '' })
    expect(payload.title).toBe('MiKan 直连合集')
  })
})

describe('candidateSearch collectPreviewEditPatch', () => {
  const original: PreviewEditState = {
    selectedSubtitleGroup: '喵萌奶茶屋',
    mustContain: '1080p',
    mustNotContain: '',
    useRegex: false,
    caseSensitive: false,
    expectedFolderName: '葬送的芙莉莲',
  }

  it('returns an empty patch when nothing changed', () => {
    expect(collectPreviewEditPatch(original, { ...original })).toEqual({})
  })

  it('includes only changed fields', () => {
    const patch = collectPreviewEditPatch(original, {
      ...original,
      mustNotContain: 'V2',
      expectedFolderName: 'MyCustomFolder',
    })
    expect(patch).toEqual({
      filter_rule: { must_not_contain: 'V2', use_regex: false, case_sensitive: false },
      expected_folder_name: 'MyCustomFolder',
    })
    expect('selected_subtitle_group' in patch).toBe(false)
  })

  it('includes the selected subtitle group when changed', () => {
    const patch = collectPreviewEditPatch(original, { ...original, selectedSubtitleGroup: 'Loli' })
    expect(patch.selected_subtitle_group).toBe('Loli')
  })

  it('includes the filter rule booleans when any filter field changes', () => {
    const patch = collectPreviewEditPatch(original, { ...original, useRegex: true })
    expect(patch.filter_rule).toEqual({ use_regex: true, case_sensitive: false })
  })
})
