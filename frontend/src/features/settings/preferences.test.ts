import { describe, expect, it } from 'vitest'

import {
  DEFAULT_PREFERENCES,
  listToText,
  textToList,
} from '@/features/settings/preferences'

// US-201: the Settings page only ever carries non-sensitive preference
// defaults (subtitle groups / filter rules / naming / search reuse). These
// tests pin the shape used to build the POST /api/v1/preferences payload and
// the line-list normalization shared with the legacy page.

describe('DEFAULT_PREFERENCES (US-201)', () => {
  it('provides the same defaults as the legacy page', () => {
    expect(DEFAULT_PREFERENCES.version).toBe(1)
    expect(DEFAULT_PREFERENCES.subtitle_groups).toEqual({
      preferred: [],
      excluded: [],
      fallback: 'next_preferred',
    })
    expect(DEFAULT_PREFERENCES.filter_defaults).toEqual({
      must_contain: '',
      must_not_contain: '',
      use_regex: false,
      case_sensitive: false,
    })
    expect(DEFAULT_PREFERENCES.naming).toEqual({
      strategy: 'official_title_season',
      template: '{title}',
    })
    expect(DEFAULT_PREFERENCES.search).toEqual({
      reuse_explicit_corrections: true,
    })
  })

  it('contains no sensitive fields (endpoint/token/cookie/password)', () => {
    const text = JSON.stringify(DEFAULT_PREFERENCES)
    for (const sensitive of ['endpoint', 'token', 'cookie', 'password', 'http://']) {
      expect(text.toLowerCase()).not.toContain(sensitive)
    }
  })
})

describe('listToText / textToList (US-201)', () => {
  it('joins subtitle-group lists with newlines', () => {
    expect(listToText(['喵萌', 'Loli'])).toBe('喵萌\nLoli')
    expect(listToText([])).toBe('')
    expect(listToText(undefined)).toBe('')
  })

  it('splits text into trimmed non-empty lines (legacy normalization)', () => {
    expect(textToList('喵萌\n\n   \nLoli')).toEqual(['喵萌', 'Loli'])
    expect(textToList('  喵萌  ')).toEqual(['喵萌'])
    expect(textToList('')).toEqual([])
    expect(textToList('  \n  ')).toEqual([])
  })

  it('round-trips list → text → list', () => {
    const groups = ['喵萌', 'Loli', '北宇治字幕组']
    expect(textToList(listToText(groups))).toEqual(groups)
  })
})
