import { isApiError } from '@/api/client'
import type { operations } from '@/api/generated/api'

export const MIKAN_UPSTREAM_TIMEOUT_MS = 15_000
export const MIKAN_QUERY_PLAN_LIMIT = 8
export const MIKAN_CANDIDATE_SEARCH_TIMEOUT_MS =
  MIKAN_QUERY_PLAN_LIMIT * MIKAN_UPSTREAM_TIMEOUT_MS + 15_000
export const MIKAN_DRAFT_GENERATION_TIMEOUT_MS = 240_000
export const MIKAN_BATCH_PARSE_OVERHEAD_MS = 60_000
export const MIKAN_BATCH_MAX_ITEMS = 36
// Twelve rows at eight bounded 15s upstream calls each, plus fixed overhead.
// Larger batches remain bounded instead of making the browser wait indefinitely.
export const MIKAN_BATCH_PARSE_MAX_TIMEOUT_MS = 1_800_000

/** A bounded timeout for the sequential batch search plan. */
export function batchParseTimeoutMs(itemCount: number): number {
  const count = Math.max(1, Math.min(MIKAN_BATCH_MAX_ITEMS, Math.ceil(itemCount)))
  return Math.min(
    MIKAN_BATCH_PARSE_MAX_TIMEOUT_MS,
    count * MIKAN_QUERY_PLAN_LIMIT * MIKAN_UPSTREAM_TIMEOUT_MS + MIKAN_BATCH_PARSE_OVERHEAD_MS,
  )
}

type CandidateResult = NonNullable<
  operations['searchMikanCandidates']['responses']['200']['content']['application/json']['result']
>

function kindFor(errorType: string | undefined, category: string | undefined): string {
  if (errorType === 'request_timeout' || errorType === 'request_cancelled') return 'browser_wait'
  if (errorType === 'mikan_timeout' || errorType === 'upstream_timeout') return 'upstream_timeout'
  if (errorType === 'mikan_connection_failed' || errorType === 'network_error') return 'network'
  if (
    errorType === 'mikan_http_failed' ||
    errorType === 'upstream_unavailable' ||
    errorType === 'service_unavailable' ||
    errorType === 'server_error'
  ) return 'service'
  if (
    errorType === 'mikan_parse_failed' ||
    errorType === 'rss_parse_failed' ||
    errorType === 'ai_title_parse_failed' ||
    category === 'title_parse'
  ) return 'parse'
  if (errorType === 'mikan_search_failed') return 'service'
  return 'unknown'
}

function fixedFailureMessage(type: string | undefined, category: string | undefined, subject: string): string {
  switch (kindFor(type, category)) {
    case 'browser_wait': return `${subject}等待超时，服务端可能仍在处理；请稍后重试。`
    case 'upstream_timeout': return `${subject}失败：MiKan 上游响应超时，请稍后重试。`
    case 'network': return `${subject}失败：网络或连接不可用，请检查网络后重试。`
    case 'service': return `${subject}失败：MiKan 服务暂时异常，请稍后重试。`
    case 'parse': return `${subject}失败：MiKan 页面解析异常，请稍后重试。`
    default: return `${subject}失败，请稍后重试。`
  }
}

export function mikanFailureMessage(error: unknown, subject = '操作'): string {
  const apiError = isApiError(error) ? error : null
  const structural = error && typeof error === 'object' ? error as { type?: unknown; details?: unknown } : null
  const type = typeof apiError?.type === 'string' ? apiError.type : typeof structural?.type === 'string' ? structural.type : undefined
  const details = apiError?.details ?? (structural?.details && typeof structural.details === 'object' ? structural.details as Record<string, unknown> : null)
  const category = typeof details?.category === 'string' ? details.category : undefined
  return fixedFailureMessage(type, category, subject)
}

/** Map the safe, generated 200+FAILED result without treating it as EMPTY. */
export function candidateResultFailureMessage(result: CandidateResult): string | null {
  if (result.status !== 'FAILED') return null
  const error = result.error
  const errorType = typeof error?.error_type === 'string' ? error.error_type : undefined
  const details = error?.details as { category?: unknown } | null | undefined
  const category = typeof details?.category === 'string' ? details.category : undefined
  return fixedFailureMessage(errorType, category, '候选搜索')
}

/** Map a public batch item error without trusting arbitrary server text. */
export function batchItemFailureMessage(item: unknown): string {
  const raw = item && typeof item === 'object' ? (item as { error?: unknown }).error : null
  const error = raw && typeof raw === 'object' ? raw as { error_type?: unknown; details?: unknown } : {}
  const type = typeof error.error_type === 'string' ? error.error_type : undefined
  const details = error.details && typeof error.details === 'object' ? error.details as { category?: unknown } : {}
  const category = typeof details.category === 'string' ? details.category : undefined
  return fixedFailureMessage(type, category, '该条目候选搜索')
}
