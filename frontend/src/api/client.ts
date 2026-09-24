/**
 * Unified API transport (US-199).
 *
 * The new frontend never builds `/api/v1` URLs by hand — every feature goes
 * through `apiRequest`. The transport owns:
 *
 * - the shared success/error envelope (`{ok: true, result}` /
 *   `{ok: false, error_type, error_message, error_data}`),
 * - non-2xx JSON errors, non-JSON error bodies (proxy HTML pages) and
 *   network failures,
 * - cancellation (AbortSignal) and timeouts,
 * - the relative `storage_dir` query parameter (server-root-relative profile,
 *   never an absolute path — US-193),
 * - poster blobs (binary endpoint that never carries the JSON envelope),
 * - a safe, sanitized error message so raw bodies, URLs or credentials never
 *   leak into the UI, logs or store.
 *
 * Sensitive values (endpoint, token, cookie, password, raw HTML/RSS,
 * raw response bodies, full failed URLs, local absolute paths) must never
 * be persisted, put into URLs/browser storage, logs or traces — this module
 * treats every error payload as untrusted text and only ever surfaces
 * server-provided `error_message` strings or generic Chinese fallbacks.
 */
import type { paths } from '@/api/generated/api'

/** Default timeout for every request unless overridden (milliseconds). */
export const DEFAULT_TIMEOUT_MS = 15_000

export type HttpMethod = 'GET' | 'POST' | 'PUT' | 'PATCH' | 'DELETE'

/** Path keys carry `{param}` placeholders; interpolate before calling. */
export type ApiPath = Extract<keyof paths, string>

/** Safe, ready-to-display failure (never raw bodies, URLs or credentials). */
export interface ApiError {
  /** Stable machine-readable error type (envelope `error_type`). */
  type: string
  /** Safe Chinese message, ready to render. */
  message: string
  /** HTTP status; 0 for network failures/cancellations before a response. */
  status: number
  /** Sanitized envelope details (never raw response content). */
  details: Record<string, unknown> | null
  /** True when the request was cancelled (AbortSignal/timeout). */
  cancelled: boolean
  /** True when the fetch itself failed (offline/DNS/refused). */
  network: boolean
  /** True when the server did not return JSON (e.g. proxy error page). */
  nonJson: boolean
  /** True when the server returned a non-2xx status. */
  httpError: boolean
}

export interface ApiRequestOptions {
  /** Path parameters, e.g. `{ request_id: 'abc' }` for `/requests/{request_id}`. */
  path?: Record<string, string | number>
  /** Query parameters (only non-sensitive values; relative `storage_dir`). */
  query?: Record<string, string | number | boolean | undefined>
  /** JSON request body (credentials are request-scoped, never persisted). */
  body?: unknown
  /** Abort this request. */
  signal?: AbortSignal
  /** Timeout in milliseconds (default `DEFAULT_TIMEOUT_MS`). */
  timeoutMs?: number
  /** True for the binary poster endpoint (no JSON envelope parsing). */
  binary?: boolean
  /** Explicit `Accept` header (Issue 112: `text/event-stream`). */
  accept?: string
  /** Per-frame callback when the server answers with an SSE stream. */
  onEvent?: (event: ApiStreamEvent) => void
}

const errorTypeFrom = (status: number, cancelled: boolean, network: boolean): string => {
  if (cancelled) return 'request_cancelled'
  if (network) return 'network_error'
  if (status === 401) return 'auth_failed'
  if (status === 404) return 'not_found'
  if (status === 409) return 'conflict'
  if (status === 502) return 'upstream_unavailable'
  if (status === 503) return 'service_unavailable'
  if (status === 504) return 'upstream_timeout'
  if (status >= 500) return 'server_error'
  return 'request_error'
}

/**
 * Extract the path without its `{param}` placeholders, e.g.
 * `/api/v1/requests/{request_id}/accept` → `/api/v1/requests/accept`.
 * Used for sanitized error context; never leaks request values.
 */
function pathTemplateKey(path: string): string {
  return path.replace(/\{[^}]*\}/g, '')
}

function interpolatePath(path: string, params: Record<string, string | number>): string {
  return path.replace(/\{([^}]+)\}/g, (_whole, name: string) => {
    const value = params[name]
    if (value === undefined) {
      throw new Error(`缺少路径参数: ${name} (${pathTemplateKey(path)})`)
    }
    return encodeURIComponent(String(value))
  })
}

function buildQuery(query: Record<string, string | number | boolean | undefined>): string {
  const params = new URLSearchParams()
  for (const [key, value] of Object.entries(query)) {
    if (value === undefined || value === null) continue
    params.set(key, String(value))
  }
  const raw = params.toString()
  return raw ? `?${raw}` : ''
}

export function isApiError(value: unknown): value is ApiError {
  return (
    typeof value === 'object' &&
    value !== null &&
    'type' in value &&
    'message' in value &&
    'status' in value
  )
}

/**
 * Create an ApiError from an unknown thrown value. All inputs are treated as
 * untrusted; the resulting message is always a safe generic Chinese string or
 * the server's own `error_message` (already sanitized server-side).
 */
export function toApiError(value: unknown): ApiError {
  if (isApiError(value)) return value
  if (value instanceof Error) {
    // `ApiError` is a plain object, so an Error here is a genuine
    // programming/runtime error — never display its raw text (it may embed
    // URLs or bodies). Keep the machine type and a safe generic message.
    return {
      type: 'unexpected_error',
      message: '发生意外错误，请稍后重试',
      status: 0,
      details: null,
      cancelled: false,
      network: false,
      nonJson: false,
      httpError: false,
    }
  }
  return {
    type: 'unexpected_error',
    message: '发生意外错误，请稍后重试',
    status: 0,
    details: null,
    cancelled: false,
    network: false,
    nonJson: false,
    httpError: false,
  }
}

function envelopeError(
  status: number,
  envelope: { error_type?: unknown; error_message?: unknown; error_data?: unknown } | null,
  nonJson = false,
): ApiError {
  const errorType = typeof envelope?.error_type === 'string' ? envelope.error_type : ''
  return {
    type: errorType || errorTypeFrom(status, false, false),
    message:
      typeof envelope?.error_message === 'string' && envelope.error_message.trim()
        ? envelope.error_message
        : '请求失败，请稍后重试',
    status,
    details:
      envelope?.error_data && typeof envelope.error_data === 'object'
        ? (envelope.error_data as Record<string, unknown>)
        : null,
    cancelled: false,
    network: false,
    nonJson,
    httpError: true,
  }
}

/**
 * Perform an API request and return the envelope `result` (or the raw blob
 * for the poster endpoint). Throws an `ApiError` on failure.
 */
export async function apiRequest<T = unknown>(method: HttpMethod, path: ApiPath, options: ApiRequestOptions = {}): Promise<T> {
  const { path: pathParams = {}, query, body, signal, timeoutMs = DEFAULT_TIMEOUT_MS, binary = false, accept, onEvent } = options

  const url = interpolatePath(path, pathParams)
  const queryString = buildQuery(query ?? {})
  const fullUrl = `${url}${queryString}`
  const headers: Record<string, string> = {}
  if (body !== undefined && !binary) {
    headers['Content-Type'] = 'application/json'
  }
  if (accept) {
    headers['Accept'] = accept
  }

  const controller = new AbortController()
  const cancel = () => controller.abort()
  if (signal) {
    if (signal.aborted) {
      controller.abort()
    } else {
      signal.addEventListener('abort', cancel, { once: true })
    }
  }
  const timeoutId = setTimeout(() => controller.abort(), timeoutMs)

  try {
    const response = await fetch(fullUrl, {
      method,
      headers,
      body: body !== undefined ? JSON.stringify(body) : undefined,
      signal: controller.signal,
    })

    if (binary) {
      if (!response.ok) {
        throw envelopeError(response.status, await safeJson(response), true)
      }
      return (await response.blob()) as T
    }

    const contentType = response.headers.get('content-type') || ''
    if (contentType.includes('text/event-stream') && response.body) {
      // Issue 112: the batch parse progress stream. Frames resolve to the
      // final `result` payload; a stream without one is never a success.
      return (await consumeEventStream<T>(response, onEvent)) as T
    }
    let payload: { ok?: unknown; result?: unknown; error_type?: unknown; error_message?: unknown; error_data?: unknown } | null = null
    if (contentType.includes('application/json')) {
      payload = await safeJson(response)
    }

    if (!response.ok || !payload || payload.ok !== true) {
      const isNonJson = !contentType.includes('application/json') || !payload
      throw envelopeError(response.status, payload, isNonJson)
    }
    return payload.result as T
  } catch (error) {
    throw transportError(error, signal)
  } finally {
    clearTimeout(timeoutId)
    signal?.removeEventListener('abort', cancel)
  }
}

/**
 * Normalize any transport failure into the shared `ApiError` shape.
 *
 * Shared by the buffered request and the SSE stream so a timeout, an explicit
 * cancellation and a network failure always classify identically.
 */
function transportError(error: unknown, signal?: AbortSignal): ApiError {
  if (isApiError(error)) {
    // Already-normalized transport error (envelope failure, non-JSON body,
    // aborted/network/timeout) — rethrow as-is.
    return error
  }
  if (error instanceof DOMException && error.name === 'AbortError') {
    // Timeout and explicit cancellation share the abort path; the caller
    // distinguishes via signal state if needed.
    const cancelled = Boolean(signal?.aborted)
    return {
      type: cancelled ? 'request_cancelled' : 'request_timeout',
      message: cancelled ? '请求已取消' : '请求超时，请稍后重试',
      status: 0,
      details: null,
      cancelled,
      network: false,
      nonJson: false,
      httpError: false,
    }
  }
  if (error instanceof TypeError) {
    // fetch rejects with TypeError on network failures (offline/DNS/refused).
    return {
      type: 'network_error',
      message: '网络请求失败，请检查网络后重试',
      status: 0,
      details: null,
      cancelled: false,
      network: true,
      nonJson: false,
      httpError: false,
    }
  }
  return toApiError(error)
}

/** Parse JSON safely; returns null for non-JSON/unparseable bodies. */
async function safeJson(
  response: Response,
): Promise<{ ok?: unknown; result?: unknown; error_type?: unknown; error_message?: unknown; error_data?: unknown } | null> {
  try {
    const parsed: unknown = await response.json()
    if (parsed && typeof parsed === 'object') {
      return parsed as {
        ok?: unknown
        result?: unknown
        error_type?: unknown
        error_message?: unknown
        error_data?: unknown
      }
    }
    return null
  } catch {
    return null
  }
}

/**
 * Convenience helpers bound to the shared transport. Features should use
 * these rather than calling `fetch` directly.
 */
export const api = {
  get: <T = unknown>(path: ApiPath, options?: ApiRequestOptions) => apiRequest<T>('GET', path, options),
  post: <T = unknown>(path: ApiPath, options?: ApiRequestOptions) => apiRequest<T>('POST', path, options),
  put: <T = unknown>(path: ApiPath, options?: ApiRequestOptions) => apiRequest<T>('PUT', path, options),
  patch: <T = unknown>(path: ApiPath, options?: ApiRequestOptions) => apiRequest<T>('PATCH', path, options),
  delete: <T = unknown>(path: ApiPath, options?: ApiRequestOptions) => apiRequest<T>('DELETE', path, options),
  // Poster endpoint: returns the raw blob, never parsed as envelope JSON.
  poster: (key: string, options?: ApiRequestOptions) =>
    apiRequest<Blob>('GET', '/api/v1/mikan/posters/{key}', {
      ...options,
      path: { ...(options?.path ?? {}), key },
      binary: true,
    }),
}

/** One server-sent event frame (Issue 112). */
export interface ApiStreamEvent {
  /** SSE event name (`item`, `result`, `error`). */
  event: string
  /** Parsed JSON payload of the frame. */
  data: Record<string, unknown>
}

/** Parse one SSE block into an event name and JSON payload (null if unusable). */
function parseSseFrame(block: string): ApiStreamEvent | null {
  let name = ''
  const dataLines: string[] = []
  for (const line of block.split('\n')) {
    if (line.startsWith('event:')) name = line.slice(6).trim()
    else if (line.startsWith('data:')) dataLines.push(line.slice(5).trim())
  }
  if (!name || !dataLines.length) return null
  try {
    const parsed: unknown = JSON.parse(dataLines.join('\n'))
    if (!parsed || typeof parsed !== 'object') return null
    return { event: name, data: parsed as Record<string, unknown> }
  } catch {
    return null
  }
}

/**
 * Consume a `text/event-stream` response (Issue 112).
 *
 * Resolves with the `result` payload of the final `result` frame. An `error`
 * frame, or a stream that ends without a `result`, rejects with the normalized
 * failure shape, so a partial batch is never mistaken for a completed one.
 * Frames reach `onEvent` as soon as the server flushes them: progress is never
 * estimated from elapsed time.
 */
async function consumeEventStream<T>(
  response: Response,
  onEvent?: (event: ApiStreamEvent) => void,
): Promise<T> {
  const reader = response.body!.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  let result: unknown
  let sawResult = false
  let streamError: ApiError | null = null

  for (;;) {
    const { done, value } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })
    let boundary = buffer.indexOf('\n\n')
    while (boundary >= 0) {
      const block = buffer.slice(0, boundary)
      buffer = buffer.slice(boundary + 2)
      const frame = parseSseFrame(block)
      if (frame) {
        onEvent?.(frame)
        if (frame.event === 'result') {
          result = frame.data.result
          sawResult = true
        } else if (frame.event === 'error') {
          streamError = envelopeError(response.status, frame.data)
        }
      }
      boundary = buffer.indexOf('\n\n')
    }
  }

  if (streamError) throw streamError
  if (!sawResult) {
    throw {
      type: 'stream_incomplete',
      message: '批量进度流提前结束，请重新搜索',
      status: 0,
      details: null,
      cancelled: false,
      network: false,
      nonJson: false,
      httpError: false,
    } satisfies ApiError
  }
  return result as T
}
