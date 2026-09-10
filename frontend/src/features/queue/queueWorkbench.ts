/**
 * 提交队列 (US-206) pure helpers.
 *
 * Pure display/validation helpers shared by QueueView and its unit tests.
 * They mirror the legacy `app.js` pre-submission queue flow
 * (batchQueueStatusLabel / batchQueueStatusClass / batchQueueItemSummary /
 * batchQueueSummaryMessage / showBatchQueueSubmitNotification /
 * buildAbConfig / syncAbAuthMode) so the old `/index` queue panel and the new
 * `/app/tracking` route stay parity for the same API result.
 *
 * Security boundary: these helpers operate on the generated OpenAPI queue
 * types only (public, sanitized queue items and the request-scoped AB config
 * snapshot taken at the exact moment a single POST body is built). They never
 * persist credentials, endpoints, raw bodies or local absolute paths, and
 * they never render server `error_message` values (only fixed Chinese copy).
 * No value here is ever logged or written to the URL/browser storage.
 */
import { api } from '@/api/client'
import type { operations } from '@/api/generated/api'

/** Public queue result produced by `GET /api/v1/batches/{id}/queue`. */
export type BatchQueueResult = NonNullable<
  operations['getBatchQueue']['responses']['200']['content']['application/json']['result']
>

/** One typed pre-submission queue item (public sanitized summary). */
export type QueueItem = NonNullable<
  NonNullable<BatchQueueResult['queue']>['items']
>[number]

/** Public submit/retry/recover result (shared accept-result shape). */
export type BatchSubmitResult = NonNullable<
  operations['submitBatchQueue']['responses']['200']['content']['application/json']['result']
>

/** Public AB config payload (request-scoped; never persisted). */
export type AbConfigPayload = {
  auth_mode: 'password' | 'api_token'
  base_url: string
  fallback_enabled: boolean
  username?: string
  password?: string
  token?: string
}

/** Chinese label for a queue item status code (legacy batchQueueStatusLabel). */
export const QUEUE_STATUS_LABELS: Record<string, string> = {
  READY_TO_SUBMIT: '待提交',
  SUBMITTING: '提交中',
  SUCCEEDED: '提交成功',
  FAILED: '提交失败',
  RETRYABLE: '可重试',
  RESULT_PERSIST_FAILED: '结果保存失败',
}

/** CSS-state class for a queue item status (legacy batchQueueStatusClass). */
export const QUEUE_STATUS_CLASSES: Record<string, string> = {
  READY_TO_SUBMIT: 'ready',
  SUBMITTING: 'submitting',
  SUCCEEDED: 'succeeded',
  FAILED: 'failed',
  RETRYABLE: 'retryable',
  RESULT_PERSIST_FAILED: 'result-persist-failed',
}

/** Chinese label for a queue status; unknown codes render as-is. */
export function queueStatusLabel(status: string | null | undefined): string {
  const value = String(status ?? '')
  return QUEUE_STATUS_LABELS[value] ?? value
}

/** CSS class for a queue status; unknown codes fall back to `ready`. */
export function queueStatusClass(status: string | null | undefined): string {
  const value = String(status ?? '')
  return QUEUE_STATUS_CLASSES[value] ?? 'ready'
}

/** One-line queue item summary (result summary > last error > none). */
export function queueItemSummary(item: QueueItem): string {
  if (item.ab_result_summary) {
    return `结果：${item.ab_result_summary}`
  }
  if (item.last_error) {
    return `错误：${item.last_error}`
  }
  return '尚无结果摘要'
}

/** True when the queue item offers the single-item 重试 action. */
export function queueItemCanRetry(status: string | null | undefined): boolean {
  const value = String(status ?? '')
  return value === 'FAILED' || value === 'RETRYABLE'
}

/** True when the queue item offers the single-item 恢复 action. */
export function queueItemCanRecover(status: string | null | undefined): boolean {
  const value = String(status ?? '')
  return value === 'SUBMITTING' || value === 'RESULT_PERSIST_FAILED'
}

/** True when the queue item is in a stuck state needing manual recovery. */
export function queueItemIsStuck(status: string | null | undefined): boolean {
  const value = String(status ?? '')
  return value === 'SUBMITTING' || value === 'RESULT_PERSIST_FAILED'
}

/** True when the queue item is already terminal (never re-submitted). */
export function queueItemIsTerminal(status: string | null | undefined): boolean {
  const value = String(status ?? '')
  return value === 'SUCCEEDED' || value === 'FAILED'
}

/** Build the AB config payload from request-scoped field values. */
export function buildAbConfig(
  authMode: 'password' | 'api_token',
  baseUrl: string,
  fallbackEnabled: boolean,
  credentials: { username?: string; password?: string; token?: string },
): AbConfigPayload {
  const base: AbConfigPayload = {
    auth_mode: authMode,
    base_url: baseUrl,
    fallback_enabled: fallbackEnabled,
  }
  if (authMode === 'api_token') {
    base.token = credentials.token ?? ''
  } else {
    base.username = credentials.username ?? ''
    base.password = credentials.password ?? ''
  }
  return base
}

/** Validate the AB config fields; returns a Chinese error message or null. */
export function validateAbConfig(
  authMode: 'password' | 'api_token',
  baseUrl: string,
  credentials: { username?: string; password?: string; token?: string },
): string | null {
  if (!baseUrl.trim()) {
    return '请填写服务地址。'
  }
  if (authMode === 'api_token') {
    if (!(credentials.token ?? '').trim()) {
      return '请填写 API Token。'
    }
    return null
  }
  if (!(credentials.username ?? '').trim()) {
    return '请填写用户名。'
  }
  if (!(credentials.password ?? '')) {
    return '请填写密码。'
  }
  return null
}

/** Build the batch submit summary message (legacy batchQueueSummaryMessage). */
export function batchSubmitSummaryMessage(summary: Record<string, number | undefined>): string {
  const succeeded = summary.succeeded ?? 0
  const failed = summary.failed ?? 0
  const retryable = summary.retryable ?? 0
  const skipped = summary.skipped ?? 0
  let message = `提交成功 ${succeeded} 项`
  if (failed) {
    message += `；提交失败 ${failed} 项`
  }
  if (retryable) {
    message += `；可重试 ${retryable} 项`
  }
  if (skipped) {
    message += `；跳过 ${skipped} 项`
  }
  return message
}

/** Build the submit notification kind/title from the summary. */
export function batchSubmitNotification(summary: Record<string, number | undefined>): {
  kind: 'success' | 'error'
  title: string
  message: string
} {
  const message = batchSubmitSummaryMessage(summary)
  const succeeded = summary.succeeded ?? 0
  const failed = summary.failed ?? 0
  const retryable = summary.retryable ?? 0
  if (succeeded === 0 && (failed > 0 || retryable > 0)) {
    return { kind: 'error', title: '批量提交失败', message }
  }
  if (failed > 0 || retryable > 0) {
    return { kind: 'success', title: '批量提交完成', message }
  }
  return { kind: 'success', title: '批量提交成功', message }
}

/** True when a recover result item asked for manual verification. */
export function recoverOutcomeNeedsManual(item: { status?: string | null } | undefined | null): boolean {
  return String(item?.status ?? '') === 'needs_manual'
}

/** Chinese message used when auto-recovery needs manual verification. */
export function recoverNeedsManualMessage(itemStatus: string | null | undefined): string {
  const label = queueStatusLabel(itemStatus)
  return `该订阅方案处于「${label}」，无法自动判断 Auto Bangumi 是否已创建订阅。请前往 Auto Bangumi 核对后选择。`
}

/** Read the pre-submission queue (safe Chinese error on failure). */
export async function loadQueue(
  batchId: string,
  query: Record<string, string | undefined>,
): Promise<BatchQueueResult> {
  return api.get<BatchQueueResult>(`/api/v1/batches/{batch_id}/queue`, {
    path: { batch_id: batchId },
    query,
  })
}

/** Submit the whole queue to Auto Bangumi. */
export async function submitQueue(
  batchId: string,
  payload: Record<string, unknown>,
): Promise<BatchSubmitResult> {
  return api.post<BatchSubmitResult>(`/api/v1/batches/{batch_id}/submit`, {
    path: { batch_id: batchId },
    body: payload,
  })
}

/** Retry a single FAILED/RETRYABLE queue item. */
export async function retryQueueItem(
  batchId: string,
  requestId: string,
  payload: Record<string, unknown>,
): Promise<BatchSubmitResult> {
  return api.post<BatchSubmitResult>(`/api/v1/batches/{batch_id}/retry`, {
    path: { batch_id: batchId },
    body: { ...payload, request_id: requestId },
  })
}

/** Recover a stuck (SUBMITTING / RESULT_PERSIST_FAILED) queue item. */
export async function recoverQueueItem(
  batchId: string,
  requestId: string,
  action: 'auto' | 'succeeded' | 'failed',
  confirm: boolean,
  query: Record<string, string | undefined>,
): Promise<BatchSubmitResult> {
  return api.post<BatchSubmitResult>(`/api/v1/batches/{batch_id}/recover`, {
    path: { batch_id: batchId },
    query,
    body: { request_id: requestId, action, confirm },
  })
}
