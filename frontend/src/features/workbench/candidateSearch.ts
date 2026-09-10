/**
 * Workbench single-search helpers (US-204).
 *
 * Pure display/validation helpers shared by the WorkbenchView and its unit
 * tests. They mirror the legacy `app.js` single-search flow
 * (renderCandidateCard / buildCandidateSearchPayload / candidateSelectionIsBlocked
 * / renderTitleParseSummary / collectPreviewEditPatch) so the old `/index`
 * and the new `/app/add` stay parity for the same API result.
 *
 * Security boundary: these helpers operate on the generated OpenAPI candidate
 * types only. They never receive credentials, raw bodies or local absolute
 * paths. `mikan_url` / `poster_url` are public metadata used by the backend
 * and poster endpoint, but the card renderer only shows the opaque poster key
 * path and never renders the raw URL text. `candidate_context` is a one-time
 * opaque capability kept in component memory only.
 */
import type { operations } from '@/api/generated/api'
import { displayValue } from '@/features/requests/requestDetail'

/** Public candidate-search result produced by `POST /api/v1/mikan/candidates`. */
export type CandidateSearchResult = NonNullable<
  operations['searchMikanCandidates']['responses']['200']['content']['application/json']['result']
>

/** One typed candidate card (public whitelist from the generated client). */
export type MikanCandidate = CandidateSearchResult['candidates'][number]

/** Season evidence summary on a candidate (PROVEN / NEEDS_CONFIRMATION / CONFLICT / NONE). */
export type SeasonEvidence = NonNullable<MikanCandidate['season_evidence']>

/** Chinese label for a title-parse source code (legacy `titleParseSourceLabels`). */
export const PARSE_SOURCE_LABELS: Record<string, string> = {
  correction: '用户修正',
  rule: '规则识别',
  alias: '别名匹配',
  fallback: '原始标题回退',
  fake: '测试解析',
}

/** Chinese label for a parse source; unknown codes fall back to 原始标题回退. */
export function parseSourceLabel(source: string | null | undefined): string {
  const value = String(source ?? '')
  return PARSE_SOURCE_LABELS[value] ?? '原始标题回退'
}

/** True when the parse result carries a reviewable season number (1-99). */
export function parseSeasonNumber(parseResult: CandidateSearchResult['parse_result'] | null | undefined): number | null {
  const season = parseResult?.season
  if (!season || typeof season !== 'object') return null
  const number = Number((season as { number?: unknown }).number)
  return Number.isInteger(number) && number >= 1 && number <= 99 ? number : null
}

/** True when the candidate requires the explicit season-confirmation checkbox. */
export function needsSeasonConfirmation(candidate: MikanCandidate): boolean {
  return candidate.season_evidence?.status === 'NEEDS_CONFIRMATION'
}

/** True when the candidate selection is blocked (conflict or unconfirmed season). */
export function candidateSelectionIsBlocked(candidate: MikanCandidate, confirmedSeason: number | null): boolean {
  const evidence = candidate.season_evidence
  if (!evidence) return false
  if (evidence.status === 'CONFLICT') return true
  return evidence.status === 'NEEDS_CONFIRMATION' && !Number.isInteger(confirmedSeason)
}

/** Episode-progress display text (legacy `播出进度：待开发 / N 集`). */
export function episodeProgressText(totalEpisodes: number | null | undefined): string {
  const total = Number(totalEpisodes)
  return Number.isInteger(total) && total > 0 ? `播出进度：待开发 / ${total} 集` : '播出进度：待开发 / 未知'
}

/** Validate the single-search query input (legacy `buildCandidateSearchPayload`). */
export function validateCandidateQuery(query: string): string | null {
  const trimmed = query.trim()
  if (!trimmed) {
    return '搜索 MiKan 候选前必须填写番剧标题。'
  }
  return null
}

/** Validate the direct-fallback value (legacy local sanity check). */
export function validateFallbackValue(value: string): string | null {
  const trimmed = value.trim()
  if (!trimmed) {
    return '生成前必须填写 MiKan 合集 URL 或 ID。'
  }
  const isBareId = /^[0-9]+$/.test(trimmed)
  const isHttpUrl = /^https?:\/\//i.test(trimmed)
  if (!isBareId && !isHttpUrl) {
    return '必须是数字 ID 或 HTTP(S) URL。'
  }
  return null
}

/** Collect the editable preview-edit patch (legacy `collectPreviewEditPatch`). */
export interface PreviewEditState {
  selectedSubtitleGroup: string
  mustContain: string
  mustNotContain: string
  useRegex: boolean
  caseSensitive: boolean
  expectedFolderName: string
}

export interface PreviewPatch {
  selected_subtitle_group?: string
  filter_rule?: {
    must_contain?: string
    must_not_contain?: string
    use_regex?: boolean
    case_sensitive?: boolean
  }
  expected_folder_name?: string
}

/** Build a modify patch from the preview-edit form state (legacy helper). */
export function collectPreviewEditPatch(original: PreviewEditState, current: PreviewEditState): PreviewPatch {
  const patch: PreviewPatch = {}
  if (current.selectedSubtitleGroup && current.selectedSubtitleGroup !== original.selectedSubtitleGroup) {
    patch.selected_subtitle_group = current.selectedSubtitleGroup
  }
  const mcChanged = current.mustContain !== original.mustContain
  const mncChanged = current.mustNotContain !== original.mustNotContain
  const filterChanged =
    mcChanged ||
    mncChanged ||
    current.useRegex !== original.useRegex ||
    current.caseSensitive !== original.caseSensitive
  if (filterChanged) {
    patch.filter_rule = {}
    if (mcChanged) {
      patch.filter_rule.must_contain = current.mustContain
    }
    if (mncChanged) {
      patch.filter_rule.must_not_contain = current.mustNotContain
    }
    patch.filter_rule.use_regex = current.useRegex
    patch.filter_rule.case_sensitive = current.caseSensitive
  }
  if (current.expectedFolderName !== original.expectedFolderName) {
    patch.expected_folder_name = current.expectedFolderName
  }
  return patch
}

/** Build the create-request payload for a selected candidate (legacy helper). */
export function buildCandidateCreatePayload(
  candidate: MikanCandidate,
  options: { storageDir: string; confirmedSeason: number | null },
): Record<string, unknown> {
  const payload: Record<string, unknown> = {
    title: candidate.title || '未命名合集',
    source: 'mikan',
    mikan_bangumi: candidate.mikan_url,
    storage_dir: options.storageDir || null,
    save_request: false,
  }
  if (typeof candidate.candidate_context === 'string' && candidate.candidate_context) {
    payload.candidate_context = candidate.candidate_context
  }
  if (Number.isInteger(options.confirmedSeason)) {
    payload.season_confirmation = options.confirmedSeason
  }
  return payload
}

/** Build the create-request payload for the direct fallback (legacy helper). */
export function buildFallbackCreatePayload(
  fallbackValue: string,
  options: { storageDir: string; title: string },
): Record<string, unknown> {
  return {
    title: options.title || 'MiKan 直连合集',
    source: 'mikan',
    mikan_bangumi: fallbackValue.trim(),
    storage_dir: options.storageDir || null,
    save_request: false,
  }
}

export { displayValue }
