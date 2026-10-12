import { describe, expect, it } from 'vitest'

import {
  buildRssPatch,
  buildSubscriptionPatch,
  emptyRssForm,
  emptySubscriptionForm,
  isUnsafePatchValue,
  managementPatchPresent,
  rssTextValue,
  setRssTextValue,
  setSubscriptionTextValue,
  subscriptionTextValue,
  type TrackingRssForm,
  type TrackingSubscriptionForm,
} from './trackingManagement'

function subscriptionForm(overrides: Partial<TrackingSubscriptionForm> = {}): TrackingSubscriptionForm {
  return { ...emptySubscriptionForm(), ...overrides }
}

function rssForm(overrides: Partial<TrackingRssForm> = {}): TrackingRssForm {
  return { ...emptyRssForm(), ...overrides }
}

describe('tracking modify form model (US-313)', () => {
  it('refuses an empty patch, so every scope needs an explicit field', () => {
    expect(buildSubscriptionPatch(subscriptionForm())).toBeNull()
    expect(buildRssPatch(rssForm())).toBeNull()
    // Selecting a field is what makes a patch non-empty; the value may be an
    // explicit clear (null) and the patch is still a real, non-empty patch.
    const cleared = buildSubscriptionPatch(subscriptionForm({ enabled: { title: true } }))
    expect(cleared).toEqual({ title: null })
  })

  it('keeps the two scope field sets apart on both builders', () => {
    const subscription = buildSubscriptionPatch(subscriptionForm({
      enabled: { title: true, season: true, subtitle_group: true, offset: true, expected_folder_name: true },
      title: '新标题', season: '2', subtitleGroup: '新字幕组', offset: '3', expectedFolderName: '新文件夹',
    }))
    expect(subscription).toEqual({
      title: '新标题', season: 2, subtitle_group: '新字幕组', offset: 3, expected_folder_name: '新文件夹',
    })
    // A subscription patch can never carry an RSS field, and the reverse holds
    // too: the builders only read their own scope's fields.
    expect(Object.keys(subscription ?? {})).not.toContain('name')
    expect(Object.keys(subscription ?? {})).not.toContain('parser')

    const rss = buildRssPatch(rssForm({ enabled: { name: true, aggregate: true, parser: true }, name: 'RSS 名称', aggregate: true, parser: 'mikan' }))
    expect(rss).toEqual({ name: 'RSS 名称', aggregate: true, parser: 'mikan' })
    expect(Object.keys(rss ?? {})).not.toContain('title')
    expect(Object.keys(rss ?? {})).not.toContain('season')
    // An RSS value can be an explicit clear as well.
    expect(buildRssPatch(rssForm({ enabled: { name: true } }))).toEqual({ name: null })
  })

  it('sends the filter rule as a complete exclusion expression', () => {
    const rule = buildSubscriptionPatch(subscriptionForm({
      enabled: { filter_rule: true },
      filter: { must_contain: true, must_not_contain: true },
      mustContain: '简体', mustNotContain: '合集',
    }))
    expect(rule).toEqual({
      filter_rule: { use_regex: false, case_sensitive: false, must_contain: '简体', must_not_contain: '合集' },
    })
    // The two switches always travel together; the text terms only when their
    // own switch is on, so an untouched term keeps its Auto Bangumi value.
    expect(buildSubscriptionPatch(subscriptionForm({
      enabled: { filter_rule: true }, filter: { must_contain: true }, mustContain: '简体',
    }))).toEqual({ filter_rule: { use_regex: false, case_sensitive: false, must_contain: '简体' } })
    // A switched-on but empty term is an explicit clear, not an omission.
    expect(buildSubscriptionPatch(subscriptionForm({
      enabled: { filter_rule: true }, filter: { must_contain: true },
    }))).toEqual({ filter_rule: { use_regex: false, case_sensitive: false, must_contain: null } })
    expect(buildSubscriptionPatch(subscriptionForm({
      enabled: { filter_rule: true }, useRegex: true, caseSensitive: true,
    }))).toEqual({ filter_rule: { use_regex: true, case_sensitive: true } })
  })

  it('refuses malformed numbers, traversal-unsafe text and unknown fields', () => {
    for (const season of ['abc', '1.5', '-1', '101']) {
      expect(buildSubscriptionPatch(subscriptionForm({
        enabled: { season: true }, season,
      }))).toBeNull()
    }
    for (const offset of ['abc', '-2']) {
      expect(buildSubscriptionPatch(subscriptionForm({ enabled: { offset: true }, offset }))).toBeNull()
    }
    // The server refuses URLs and absolute paths in patch text, so those values
    // never leave the page either. (Path traversal is deliberately left to the
    // server: it is legal inside a folder name, and the server is authoritative.)
    for (const value of ['https://private.invalid', 'www.example.com', '/etc/passwd', 'C:\\secret']) {
      expect(isUnsafePatchValue(value)).toBe(true)
      expect(buildSubscriptionPatch(subscriptionForm({ enabled: { title: true }, title: value }))).toBeNull()
      expect(buildRssPatch(rssForm({ enabled: { name: true }, name: value }))).toBeNull()
    }
    expect(isUnsafePatchValue('安全的文件夹名')).toBe(false)
    expect(isUnsafePatchValue('第 1 季')).toBe(false)

    // The patch presence check is scope-strict: a cross-scope key is refused.
    expect(managementPatchPresent('SUBSCRIPTION', { title: 'x' })).toBe(true)
    expect(managementPatchPresent('SUBSCRIPTION', { name: 'x' })).toBe(false)
    expect(managementPatchPresent('ASSOCIATED_RSS', { name: 'x' })).toBe(true)
    expect(managementPatchPresent('ASSOCIATED_RSS', { title: 'x' })).toBe(false)
    expect(managementPatchPresent('SUBSCRIPTION', {})).toBe(false)
    expect(managementPatchPresent('SUBSCRIPTION', { title: 'x', name: 'y' })).toBe(false)
    expect(managementPatchPresent('SUBSCRIPTION', null)).toBe(false)
  })

  it('reads and writes only the public patch field names', () => {
    const form = subscriptionForm()
    setSubscriptionTextValue(form, 'subtitle_group', '新字幕组')
    expect(subscriptionTextValue(form, 'subtitle_group')).toBe('新字幕组')
    expect(form.subtitleGroup).toBe('新字幕组')
    // The internal camelCase keys never become patch keys.
    expect(buildSubscriptionPatch({ ...form, enabled: { subtitle_group: true } }))
      .toEqual({ subtitle_group: '新字幕组' })

    const rss = rssForm()
    setRssTextValue(rss, 'parser', 'mikan')
    expect(rssTextValue(rss, 'parser')).toBe('mikan')
    expect(rssTextValue(rss, 'name')).toBe('')
  })
})
