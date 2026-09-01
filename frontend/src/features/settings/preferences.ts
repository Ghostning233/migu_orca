/**
 * Non-sensitive user preferences (US-201).
 *
 * These defaults prefill batch subscription drafts (subtitle groups, filter
 * rules, naming strategy/template, search reuse). They are the ONLY values
 * the Settings page sends to `/api/v1/preferences`; credentials, endpoints,
 * tokens, cookies, raw bodies and absolute paths are rejected server-side
 * and never rendered here.
 */

export interface SubtitleGroupPreference {
  preferred: string[]
  excluded: string[]
  fallback: string
}

export interface FilterDefaults {
  must_contain: string
  must_not_contain: string
  use_regex: boolean
  case_sensitive: boolean
}

export interface NamingPreference {
  strategy: string
  template: string
}

export interface SearchPreference {
  reuse_explicit_corrections: boolean
}

export interface UserPreferences {
  version: number
  subtitle_groups: SubtitleGroupPreference
  filter_defaults: FilterDefaults
  naming: NamingPreference
  search: SearchPreference
}

export const DEFAULT_PREFERENCES: UserPreferences = {
  version: 1,
  subtitle_groups: {
    preferred: [],
    excluded: [],
    fallback: 'next_preferred',
  },
  filter_defaults: {
    must_contain: '',
    must_not_contain: '',
    use_regex: false,
    case_sensitive: false,
  },
  naming: {
    strategy: 'official_title_season',
    template: '{title}',
  },
  search: {
    reuse_explicit_corrections: true,
  },
}

/** Line-separated list ↔ array conversion for the subtitle-group textareas. */
export function listToText(value: string[] | undefined): string {
  if (!Array.isArray(value)) return ''
  return value.join('\n')
}

/** Trim + drop empty lines (mirrors the legacy normalization). */
export function textToList(value: string): string[] {
  return (value || '')
    .split('\n')
    .map((item) => item.trim())
    .filter((item) => item.length > 0)
}
