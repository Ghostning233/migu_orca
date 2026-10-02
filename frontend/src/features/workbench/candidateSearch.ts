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
import type { RequestDetailSnapshot, RequestSnapshot } from '@/features/requests/requestDetail'

/** Public candidate-search result produced by `POST /api/v1/mikan/candidates`. */
export type CandidateSearchResult = NonNullable<
  operations['searchMikanCandidates']['responses']['200']['content']['application/json']['result']
>

/** One typed candidate card (public whitelist from the generated client). */
export type MikanCandidate = CandidateSearchResult['candidates'][number]

/**
 * Issue 110：单番候选与第二屏同排展示的上限。
 *
 * 设计图表达「1～4 项同宽同排居中」；后端若意外返回更多，只展示前四项并给
 * 简短截断提示，不自动选择、不虚构卡片，也不新增复杂救援入口。
 */
export const MAX_SINGLE_CANDIDATES = 4

/** The first four candidates rendered in the single-anime row. */
export function visibleSingleCandidates(candidates: MikanCandidate[]): MikanCandidate[] {
  return candidates.slice(0, MAX_SINGLE_CANDIDATES)
}

/** How many candidates the single-anime row hides behind the truncation note. */
export function hiddenSingleCandidateCount(candidates: MikanCandidate[]): number {
  return Math.max(0, candidates.length - MAX_SINGLE_CANDIDATES)
}

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

/** Public total-episode evidence; progress is deliberately not inferred here. */
export function episodeProgressText(totalEpisodes: number | null | undefined): string {
  const total = Number(totalEpisodes)
  return Number.isInteger(total) && total > 0 ? `总集数：${total} 集` : '总集数：未知'
}

/** Season number carried by the candidate's own public season evidence. */
export function candidateSeasonNumber(candidate: MikanCandidate): number | null {
  const season = Number(candidate.season_evidence?.season)
  return Number.isInteger(season) && season >= 1 && season <= 99 ? season : null
}

/**
 * Chinese season-evidence line for the candidate default layer (F4). Conflicts
 * and the explicit confirmation checkbox are rendered in place by the card;
 * this line covers the plain-evidence case so every card states its season
 * evidence instead of leaving the season field unstated.
 */
export function seasonEvidenceText(candidate: MikanCandidate): string {
  const season = candidateSeasonNumber(candidate)
  return season === null ? '季度证据：候选合集未提供季数' : `季度证据：候选合集为第 ${season} 季`
}

/**
 * Display-only projection of the candidate the user selected (F4 审核默认层).
 *
 * The unsaved draft snapshot returned by `POST /api/v1/requests` carries no
 * season, poster or total-episode fields, and this Stage must not add an
 * endpoint or call `safe-info` for an unsaved draft (D40-01). The review header
 * therefore answers「已选哪部/哪一季」from the already-public candidate
 * metadata the host still holds in component memory — never from a new DTO.
 */
export interface SelectedCollectionSummary {
  title: string
  season: number | null
  totalEpisodes: number | null
  /** Same-origin opaque poster key, never an external URL. */
  posterUrl: string | null
}

/**
 * Same-origin opaque poster key path, or null.
 *
 * Shared by every cover renderer (single candidate card, batch candidate card,
 * batch draft card, batch draft detail): only the opaque
 * `/api/v1/mikan/posters/<key>` path may reach an `<img src>`; an external URL,
 * a `data:` payload or a local path fails closed to the placeholder.
 */
export function publicPosterPath(value: unknown): string | null {
  const path = typeof value === 'string' ? value : ''
  return /^\/api\/v1\/mikan\/posters\/[A-Za-z0-9_-]+$/.test(path) ? path : null
}

/** Project the chosen candidate into the review header summary. */
export function selectedCollectionSummary(
  candidate: MikanCandidate,
  confirmedSeason: number | null,
): SelectedCollectionSummary {
  const total = Number(candidate.total_episodes)
  const season = Number.isInteger(confirmedSeason) ? Number(confirmedSeason) : candidateSeasonNumber(candidate)
  return {
    title: String(candidate.title ?? '').trim() || '未命名合集',
    season: season !== null && season >= 1 && season <= 99 ? season : null,
    totalEpisodes: Number.isInteger(total) && total > 0 ? total : null,
    posterUrl: publicPosterPath(candidate.poster_url),
  }
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

/** Preview-modify patch, kept in lockstep with the generated API contract. */
export type PreviewPatch = NonNullable<
  operations['previewModifyRequest']['requestBody']
>['content']['application/json']['patch']

/**
 * Project a server snapshot onto the editable form state (US-344). Hosts and
 * the edit scheduler compare this projection with the live form state, so the
 * two must never drift.
 */
export function previewEditStateFrom(request: RequestSnapshot | RequestDetailSnapshot): PreviewEditState {
  const config = request.confirmable_config
  return {
    selectedSubtitleGroup: config?.selected_subtitle_group ?? '',
    mustContain: config?.filter_rule?.must_contain ?? '',
    mustNotContain: config?.filter_rule?.must_not_contain ?? '',
    useRegex: config?.filter_rule?.use_regex === true,
    caseSensitive: config?.filter_rule?.case_sensitive === true,
    expectedFolderName: config?.expected_folder_name ?? '',
  }
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
    mikan_bangumi: candidate.mikan_url,
    storage_dir: options.storageDir || null,
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
    mikan_bangumi: fallbackValue.trim(),
    storage_dir: options.storageDir || null,
  }
}

export { displayValue }
