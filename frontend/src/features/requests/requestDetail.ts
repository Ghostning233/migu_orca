/**
 * Request detail helpers (US-203).
 *
 * Pure display helpers shared by the RequestDetailPanel and its unit tests.
 * They mirror the legacy `app.js` detail rendering (renderDetailPayload /
 * selectedRssSource / combinedSeedNames / displayValue / actionLabel /
 * scrubConfig) so the old `/index` detail panel and the new
 * `/app/requests` detail panel stay parity for the same API result.
 *
 * Security boundary: these helpers operate on the generated OpenAPI detail
 * types only. They never receive credentials, raw bodies or local absolute
 * paths, and they actively redact URL-looking values at display time. No
 * value here is ever persisted or logged.
 */
import type { operations } from '@/api/generated/api'
import { fieldValue } from '@/features/requests/requestsList'

/** @internal re-export for callers that need the shared string helper. */
export { fieldValue }

/** Public detail result shape produced by `GET /api/v1/requests/{id}`. */
export type RequestDetailResult = NonNullable<
  operations['getRequestDetail']['responses']['200']['content']['application/json']['result']
>

/** The strict, server-sanitized Request snapshot used by the detail panel. */
export type RequestDetailSnapshot = RequestDetailResult['request']

/**
 * The legacy action/preview snapshot returned by request creation and draft
 * endpoints. It is intentionally separate from the safe detail projection:
 * draft editing needs its historical shape, while detail rendering must not
 * widen back into engine fields or URL-bearing fields.
 */
export type RequestSnapshot = NonNullable<
  NonNullable<
    operations['createRequest']['responses']['200']['content']['application/json']['result']
  >['request']
>

/** One RSS source in the snapshot (lenient, extra fields allowed). */
export type RssSource = NonNullable<
  NonNullable<RequestSnapshot['source_info'] | RequestDetailSnapshot['source_info']>['rss_sources']
>[number]
type DisplaySnapshot = RequestSnapshot | RequestDetailSnapshot

/** One excluded-seed entry: either a bare title or `{name, reason, rule}`. */
export interface ExcludedSeed {
  name: string
  reason: string
}

/** A subtitle-group bucket of complete seed titles for the Seeds section. */
export interface CompleteSeedGroup {
  subtitleGroup: string
  seedNames: string[]
}

/** User-facing Chinese label for a history event action code. */
export const ACTION_LABELS: Record<string, string> = {
  ACCEPT: '确认',
  CANCEL: '取消',
  MODIFY: '修改',
}

/** Chinese label for a history event action; unknown codes render as-is. */
export function actionLabel(action: string | null | undefined): string {
  const value = fieldValue(action)
  return ACTION_LABELS[value] ?? value
}

/**
 * Redact a value for display like the legacy `displayValue`: URL-looking
 * strings become `[redacted_url]`, arrays join with `，`, null/empty become
 * 未设置/无.
 */
export function displayValue(value: unknown): string {
  let text: string
  if (Array.isArray(value)) {
    text = value.length ? value.map(String).join('，') : '无'
  } else if (value === null || value === undefined || value === '') {
    text = '未设置'
  } else {
    text = String(value)
  }
  if (/^[a-z][a-z0-9+.-]*:\/\//i.test(text)) {
    return '[redacted_url]'
  }
  return text
}

/**
 * Pick the RSS source whose subtitle group matches the selected group,
 * falling back to the first source (legacy `selectedRssSource`).
 */
export function selectedRssSource(snapshot: DisplaySnapshot): RssSource | null {
  const sources = snapshot.source_info?.rss_sources ?? []
  const selectedGroup = snapshot.confirmable_config?.selected_subtitle_group
  if (selectedGroup) {
    const match = sources.find((source) => source.subtitle_group === selectedGroup)
    if (match) return match
  }
  return sources.length ? sources[0]! : null
}

/** Combined unique seed names from valid + excluded titles (legacy helper). */
export function combinedSeedNames(valid: readonly string[] = [], excluded: readonly string[] = []): string[] {
  const names: string[] = []
  for (const value of [...valid, ...excluded]) {
    if (value && !names.includes(value)) {
      names.push(value)
    }
  }
  return names
}

/** Split the raw `excluded_seed_names` entries into `{name, reason}` pairs. */
export function excludedSeeds(snapshot: DisplaySnapshot): ExcludedSeed[] {
  const source = selectedRssSource(snapshot)
  const raw = source?.excluded_seed_names ?? []
  return raw.map((entry) => {
    if (entry && typeof entry === 'object' && 'name' in entry) {
      const name = String(entry.name ?? '')
      const reason = typeof entry.reason === 'string' ? entry.reason : ''
      return { name, reason }
    }
    return { name: String(entry ?? ''), reason: '' }
  })
}

/** Effective seed titles for the current subtitle group (legacy fallback chain). */
export function effectiveSeeds(snapshot: DisplaySnapshot): string[] {
  const source = selectedRssSource(snapshot)
  return source?.valid_seed_names ?? snapshot.confirmable_config?.effective_seed_names ?? []
}

/** Complete seeds grouped by the MiKan subtitle group (legacy grouping). */
export function completeSeedGroups(snapshot: DisplaySnapshot): CompleteSeedGroup[] {
  const sources = snapshot.source_info?.rss_sources ?? []
  return sources.map((source) => ({
    subtitleGroup: source.subtitle_group ?? '未知字幕组',
    seedNames: combinedSeedNames(
      source.valid_seed_names ?? [],
      (source.excluded_seed_names ?? []).map((entry) =>
        typeof entry === 'string' ? entry : String(entry.name ?? ''),
      ),
    ),
  }))
}

/** Total complete seed count across all subtitle groups. */
export function totalCompleteSeedCount(snapshot: DisplaySnapshot): number {
  return completeSeedGroups(snapshot).reduce((sum, group) => sum + group.seedNames.length, 0)
}

/** Recursively redact sensitive-looking keys/URLs before rendering config. */
export function scrubConfig(value: unknown): unknown {
  if (Array.isArray(value)) {
    return value.map(scrubConfig)
  }
  if (value && typeof value === 'object') {
    const clean: Record<string, unknown> = {}
    const blockedKey = /token|secret|password|authorization|cookie|sid|session|api[_-]?key|url|endpoint/i
    for (const [key, child] of Object.entries(value as Record<string, unknown>)) {
      clean[key] = blockedKey.test(key) ? '[redacted]' : scrubConfig(child)
    }
    return clean
  }
  if (typeof value === 'string' && /^[a-z][a-z0-9+.-]*:\/\//i.test(value)) {
    return '[redacted_url]'
  }
  return value
}

/** True when the payload carries a `saved_request` flag (unsaved preview draft). */
export function isPreview(payload: RequestDetailResult | Record<string, unknown>): boolean {
  const candidate = payload as Record<string, unknown>
  return Object.prototype.hasOwnProperty.call(candidate, 'saved_request') && !candidate.saved_request
}
