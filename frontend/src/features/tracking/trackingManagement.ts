/**
 * Management modify form model and patch builders (US-313).
 *
 * The four management write *sessions* (intents, keys, request bodies, results,
 * confirmations) live in ``useTrackingWriteSession`` (issue #168).  What remains
 * here is the write-only form model the modify form renders plus the strict,
 * scope-discriminated patch it builds: the page never reads the current external
 * values, so every field is opt-in and an enabled-but-empty field is an explicit
 * clear rather than "keep the existing value".
 */
import type { operations } from '@/api/generated/api'

import type { TrackingManagementScope } from './useTrackingWriteSession'

export type TrackingModifyBody = NonNullable<
  operations['modifyTrackingItem']['requestBody']['content']['application/json']
>
type SubscriptionModifyBody = Extract<TrackingModifyBody, { target_scope: 'SUBSCRIPTION' }>
type RssModifyBody = Extract<TrackingModifyBody, { target_scope: 'ASSOCIATED_RSS' }>
export type TrackingSubscriptionPatch = SubscriptionModifyBody['patch']
export type TrackingRssPatch = RssModifyBody['patch']

/** The enable/disable request body; ``enabled`` is the only extra field. */
export type TrackingSetEnabledBody = NonNullable<
  operations['setTrackingItemEnabled']['requestBody']['content']['application/json']
>
/** The refresh request body; the generated scope is fixed to the associated RSS. */
export type TrackingRefreshRssBody = NonNullable<
  operations['refreshTrackingRss']['requestBody']['content']['application/json']
>
/**
 * The saved Auto Bangumi generation every management request carries.
 *
 * ``base_url`` is a legacy input value the request builders deliberately ignore:
 * only the server-issued connection reference and its configuration revision
 * ever leave the page.
 */
export interface SavedConnectionGeneration {
  connection_ref?: string | null
  configuration_revision?: number
  /** Legacy test/input values are deliberately ignored by request builders. */
  base_url?: string
}

/**
 * Every management route answers with the same ``TrackingManagementResultDTO``,
 * so one generated result type describes all four requests this page sends.
 */
export type TrackingManagementResult = NonNullable<
  operations['modifyTrackingItem']['responses']['200']['content']['application/json']['result']
>

// -- form model --------------------------------------------------------------

export interface TrackingSubscriptionForm {
  enabled: Record<string, boolean>
  title: string
  season: string
  subtitleGroup: string
  offset: string
  expectedFolderName: string
  filter: Record<string, boolean>
  mustContain: string
  mustNotContain: string
  useRegex: boolean
  caseSensitive: boolean
}

export interface TrackingRssForm {
  enabled: Record<string, boolean>
  name: string
  aggregate: boolean
  parser: string
}

export function emptySubscriptionForm(): TrackingSubscriptionForm {
  return {
    enabled: {}, title: '', season: '', subtitleGroup: '', offset: '', expectedFolderName: '',
    filter: {}, mustContain: '', mustNotContain: '', useRegex: false, caseSensitive: false,
  }
}

/** The free-text fields of the subscription form, keyed by their public patch name. */
export type TrackingSubscriptionTextField =
  'title' | 'season' | 'subtitle_group' | 'offset' | 'expected_folder_name'

/** The free-text fields of the RSS form, keyed by their public patch name. */
export type TrackingRssTextField = 'name' | 'parser'

export function subscriptionTextValue(
  form: TrackingSubscriptionForm,
  field: TrackingSubscriptionTextField,
): string {
  if (field === 'title') return form.title
  if (field === 'season') return form.season
  if (field === 'subtitle_group') return form.subtitleGroup
  if (field === 'offset') return form.offset
  return form.expectedFolderName
}

export function setSubscriptionTextValue(
  form: TrackingSubscriptionForm,
  field: TrackingSubscriptionTextField,
  value: string,
): void {
  if (field === 'title') form.title = value
  else if (field === 'season') form.season = value
  else if (field === 'subtitle_group') form.subtitleGroup = value
  else if (field === 'offset') form.offset = value
  else form.expectedFolderName = value
}

export function rssTextValue(form: TrackingRssForm, field: TrackingRssTextField): string {
  return field === 'name' ? form.name : form.parser
}

export function setRssTextValue(form: TrackingRssForm, field: TrackingRssTextField, value: string): void {
  if (field === 'name') form.name = value
  else form.parser = value
}

export function emptyRssForm(): TrackingRssForm {
  return { enabled: {}, name: '', aggregate: false, parser: '' }
}

const SUBSCRIPTION_FIELDS = [
  'title', 'season', 'subtitle_group', 'filter_rule', 'offset', 'expected_folder_name',
] as const satisfies readonly (keyof TrackingSubscriptionPatch)[]
const RSS_FIELDS = ['name', 'aggregate', 'parser'] as const satisfies readonly (keyof TrackingRssPatch)[]

/**
 * Client-side guard mirroring the server's patch-value contract.
 *
 * The server refuses URLs, absolute paths and path traversal in patch text
 * (``unsafe_management_patch``).  Blocking them here keeps a rejected value out
 * of the request without inventing any new rule: every rejected string is one
 * the server would reject anyway.
 */
const UNSAFE_VALUE_PATTERN = /(?:https?|ftp|file):[/\\]|(?:^|\s)www\.|^(?:\/|[A-Za-z]:[\\/]|\\\\)/

export function isUnsafePatchValue(value: string): boolean {
  return UNSAFE_VALUE_PATTERN.test(value)
}

function textPatchValue(value: string): string | null {
  const trimmed = value.trim()
  return trimmed ? trimmed : null
}

function nullableNumber(value: string): number | null {
  const trimmed = value.trim()
  if (!trimmed) return null
  return Number(trimmed)
}

function filterFieldEnabled(form: TrackingSubscriptionForm, field: string): boolean {
  return form.filter[field] === true
}

/**
 * Build the strict subscription patch for the fields the user switched on.
 *
 * Returns ``null`` when nothing is selected, when a selected value is malformed
 * (or unsafe), or when the filter rule is switched on without any of its own
 * fields: an empty rule is not a valid Auto Bangumi filter and an empty patch is
 * refused by the server, so both fail closed here instead of being sent.
 */
export function buildSubscriptionPatch(form: TrackingSubscriptionForm): TrackingSubscriptionPatch | null {
  const patch: Record<string, unknown> = {}
  for (const field of SUBSCRIPTION_FIELDS) {
    if (form.enabled[field] !== true) continue
    if (field === 'filter_rule') {
      // The two switches are always carried: Auto Bangumi's filter is one
      // exclusion expression, so a rule that omits them is not expressible.
      // The text terms are only sent when the user switched that term on, and
      // an empty text term is an explicit clear (``null``).
      const rule: Record<string, unknown> = {
        use_regex: form.useRegex === true,
        case_sensitive: form.caseSensitive === true,
      }
      if (filterFieldEnabled(form, 'must_contain')) rule.must_contain = textPatchValue(form.mustContain)
      if (filterFieldEnabled(form, 'must_not_contain')) rule.must_not_contain = textPatchValue(form.mustNotContain)
      patch.filter_rule = rule
      continue
    }
    if (field === 'season') {
      const season = nullableNumber(form.season)
      if (season !== null && (!Number.isInteger(season) || season < 0 || season > 100)) return null
      patch.season = season
      continue
    }
    if (field === 'offset') {
      const offset = nullableNumber(form.offset)
      if (offset !== null && (!Number.isInteger(offset) || offset < 0)) return null
      patch.offset = offset
      continue
    }
    const value = textPatchValue(subscriptionTextValue(form, field))
    if (value !== null && isUnsafePatchValue(value)) return null
    patch[field] = value
  }
  return Object.keys(patch).length ? (patch as TrackingSubscriptionPatch) : null
}

/** Build the strict RSS patch; ``null`` when nothing is selected or malformed. */
export function buildRssPatch(form: TrackingRssForm): TrackingRssPatch | null {
  const patch: Record<string, unknown> = {}
  for (const field of RSS_FIELDS) {
    if (form.enabled[field] !== true) continue
    if (field === 'aggregate') {
      patch.aggregate = form.aggregate === true
      continue
    }
    const value = textPatchValue(rssTextValue(form, field))
    if (value !== null && isUnsafePatchValue(value)) return null
    patch[field] = value
  }
  return Object.keys(patch).length ? (patch as TrackingRssPatch) : null
}

/** True only for a patch that carries at least one field for its own scope. */
export function managementPatchPresent(
  scope: TrackingManagementScope,
  patch: unknown,
): boolean {
  if (!patch || typeof patch !== 'object') return false
  const keys = Object.keys(patch as Record<string, unknown>)
  if (!keys.length) return false
  const allowed: readonly string[] = scope === 'SUBSCRIPTION' ? SUBSCRIPTION_FIELDS : RSS_FIELDS
  return keys.every((key) => allowed.includes(key))
}
