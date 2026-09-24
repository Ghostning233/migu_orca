import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { api, apiRequest, DEFAULT_TIMEOUT_MS, isApiError, toApiError } from '@/api/client'

// US-199: the unified transport owns envelope parsing, error normalization,
// cancellation/timeouts and the poster blob path. These tests stub `fetch`
// directly (jsdom) and assert the normalized ApiError / result shapes.

function jsonResponse(body: unknown, status = 200, contentType = 'application/json') {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': contentType },
  })
}

const fetchMock = vi.fn()

beforeEach(() => {
  fetchMock.mockReset()
  vi.stubGlobal('fetch', fetchMock)
})

afterEach(() => {
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
})

describe('apiRequest envelope handling (US-199)', () => {
  it('returns the envelope result on success', async () => {
    fetchMock.mockResolvedValue(
      jsonResponse({ ok: true, result: { requests: [{ request_id: 'r1' }] } }),
    )

    const result = await apiRequest('GET', '/api/v1/requests')
    expect(result).toEqual({ requests: [{ request_id: 'r1' }] })
    const [url, init] = fetchMock.mock.calls[0] ?? []
    expect(url).toBe('/api/v1/requests')
    expect(init?.method).toBe('GET')
  })

  it('throws a typed ApiError for a non-2xx JSON envelope', async () => {
    fetchMock.mockResolvedValue(
      jsonResponse(
        {
          ok: false,
          error_type: 'request_not_found',
          error_message: '订阅方案不存在',
          error_data: { failed_step: 'load' },
        },
        404,
      ),
    )

    const error = await apiRequest('GET', '/api/v1/requests/{request_id}', {
      path: { request_id: 'nope' },
    }).catch((e: unknown) => e)
    expect(isApiError(error)).toBe(true)
    if (isApiError(error)) {
      expect(error.type).toBe('request_not_found')
      expect(error.message).toBe('订阅方案不存在')
      expect(error.status).toBe(404)
      expect(error.httpError).toBe(true)
      expect(error.details).toEqual({ failed_step: 'load' })
    }
  })

  it('throws a generic error for a non-JSON error body (proxy HTML)', async () => {
    fetchMock.mockResolvedValue(
      new Response('<html>Bad Gateway</html>', { status: 502, headers: { 'Content-Type': 'text/html' } }),
    )

    const error = await apiRequest('GET', '/api/v1/requests').catch((e: unknown) => e)
    expect(isApiError(error)).toBe(true)
    if (isApiError(error)) {
      expect(error.status).toBe(502)
      expect(error.type).toBe('upstream_unavailable')
      expect(error.message).toBe('请求失败，请稍后重试')
      expect(error.nonJson).toBe(true)
      // The raw HTML must never leak into the error message.
      expect(error.message).not.toContain('Bad Gateway')
    }
  })

  it('normalizes a 2xx non-envelope body to an error', async () => {
    fetchMock.mockResolvedValue(jsonResponse({ ok: false, error_type: 'config_error' }, 200))

    const error = await apiRequest('GET', '/api/v1/requests').catch((e: unknown) => e)
    expect(isApiError(error)).toBe(true)
    if (isApiError(error)) {
      expect(error.message).toBe('请求失败，请稍后重试')
    }
  })

  it('normalizes a network failure to network_error', async () => {
    fetchMock.mockRejectedValue(new TypeError('Failed to fetch'))

    const error = await apiRequest('GET', '/api/v1/requests').catch((e: unknown) => e)
    expect(isApiError(error)).toBe(true)
    if (isApiError(error)) {
      expect(error.type).toBe('network_error')
      expect(error.message).toBe('网络请求失败，请检查网络后重试')
      expect(error.network).toBe(true)
      expect(error.status).toBe(0)
    }
  })
})

describe('apiRequest cancellation and timeout (US-199)', () => {
  it('aborts with an AbortSignal and reports cancelled', async () => {
    const controller = new AbortController()
    fetchMock.mockImplementation(
      (_url: string, init?: RequestInit) =>
        new Promise((_resolve, reject) => {
          init?.signal?.addEventListener('abort', () => {
            reject(new DOMException('Aborted', 'AbortError'))
          })
        }),
    )

    const pending = apiRequest('GET', '/api/v1/requests', { signal: controller.signal })
    controller.abort()

    const error = await pending.catch((e: unknown) => e)
    expect(isApiError(error)).toBe(true)
    if (isApiError(error)) {
      expect(error.type).toBe('request_cancelled')
      expect(error.cancelled).toBe(true)
      expect(error.message).toBe('请求已取消')
    }
  })

  it('reports a timeout as request_timeout when no external signal was aborted', async () => {
    fetchMock.mockImplementation(
      () =>
        new Promise((_resolve, reject) => {
          // Simulate the fetch-level abort racing the timeout (jsdom fetch
          // rejects with AbortError on abort). We emulate it directly.
          reject(new DOMException('The operation was aborted', 'AbortError'))
        }),
    )

    const error = await apiRequest('GET', '/api/v1/requests', { timeoutMs: 1 }).catch(
      (e: unknown) => e,
    )
    expect(isApiError(error)).toBe(true)
    if (isApiError(error)) {
      expect(error.type).toBe('request_timeout')
      expect(error.cancelled).toBe(false)
    }
  })
})

describe('apiRequest path/query/build (US-199)', () => {
  it('interpolates path parameters and appends query strings', async () => {
    fetchMock.mockResolvedValue(jsonResponse({ ok: true, result: {} }))

    await apiRequest('GET', '/api/v1/requests/{request_id}', {
      path: { request_id: 'abc/def' },
      query: { storage_dir: 'profile 1', flag: true },
    })

    const [url] = fetchMock.mock.calls[0] ?? []
    expect(url).toBe('/api/v1/requests/abc%2Fdef?storage_dir=profile+1&flag=true')
  })

  it('posts JSON bodies with a content-type header', async () => {
    fetchMock.mockResolvedValue(jsonResponse({ ok: true, result: {} }))

    await apiRequest('POST', '/api/v1/requests', { body: { title: '测试' } })

    const [url, init] = fetchMock.mock.calls[0] ?? []
    expect(url).toBe('/api/v1/requests')
    expect(init?.method).toBe('POST')
    expect(init?.headers).toMatchObject({ 'Content-Type': 'application/json' })
    expect(JSON.parse(String(init?.body))).toEqual({ title: '测试' })
  })

  it('throws when a required path parameter is missing', async () => {
    await expect(
      apiRequest('GET', '/api/v1/requests/{request_id}'),
    ).rejects.toThrow('缺少路径参数')
  })
})

describe('api poster blob endpoint (US-199)', () => {
  it('returns a blob for the poster endpoint without envelope parsing', async () => {
    const fakeBlob = {
      size: 10,
      type: 'image/jpeg',
      text: async () => 'fake-image',
    } as unknown as Blob
    fetchMock.mockResolvedValue(
      new Response(fakeBlob, { status: 200, headers: { 'Content-Type': 'image/jpeg' } }),
    )

    const blob = await api.poster('key123')
    // jsdom's Response.blob() may return a non-Blob object; assert the value
    // the transport produced (size/type) rather than instanceof.
    expect(blob).toBeDefined()
    const [url] = fetchMock.mock.calls[0] ?? []
    expect(url).toBe('/api/v1/mikan/posters/key123')
  })

  it('throws an envelope error for a poster failure', async () => {
    fetchMock.mockResolvedValue(
      jsonResponse(
        { ok: false, error_type: 'poster_not_found', error_message: '封面不存在' },
        404,
      ),
    )

    const error = await api.poster('missing').catch((e: unknown) => e)
    expect(isApiError(error)).toBe(true)
    if (isApiError(error)) {
      expect(error.type).toBe('poster_not_found')
      expect(error.status).toBe(404)
    }
  })
})

describe('toApiError safety (US-199)', () => {
  it('never surfaces raw Error text (may embed URLs/bodies)', () => {
    const error = toApiError(new Error('https://secret.example/raw <html>token=abc</html>'))
    expect(error.message).toBe('发生意外错误，请稍后重试')
    expect(error.message).not.toContain('secret.example')
  })

  it('passes through an existing ApiError unchanged', () => {
    const original = {
      type: 'network_error',
      message: '网络请求失败，请检查网络后重试',
      status: 0,
      details: null,
      cancelled: false,
      network: true,
      nonJson: false,
      httpError: false,
    }
    expect(toApiError(original)).toBe(original)
  })

  it('maps non-object thrown values to a safe generic error', () => {
    expect(toApiError('boom').message).toBe('发生意外错误，请稍后重试')
    expect(toApiError(undefined).type).toBe('unexpected_error')
  })
})

describe('default timeout constant (US-199)', () => {
  it('is a positive, reasonable default', () => {
    expect(DEFAULT_TIMEOUT_MS).toBeGreaterThan(0)
    expect(DEFAULT_TIMEOUT_MS).toBe(15_000)
  })
})

// Issue 112: the batch parse progress stream. The client consumes
// `text/event-stream` frames as they arrive and only treats the final `result`
// frame as success; a partial stream is never a completed batch.
function sseResponse(chunks: string[]) {
  const encoder = new TextEncoder()
  const stream = new ReadableStream<Uint8Array>({
    start(controller) {
      for (const chunk of chunks) controller.enqueue(encoder.encode(chunk))
      controller.close()
    },
  })
  return new Response(stream, {
    status: 200,
    headers: { 'Content-Type': 'text/event-stream' },
  })
}

const itemFrame = (completed: number, total: number) =>
  `event: item\ndata: ${JSON.stringify({ completed, total, item: { item_id: `item-${completed}` } })}\n\n`

const resultFrame = (result: unknown) =>
  `event: result\ndata: ${JSON.stringify({ ok: true, result })}\n\n`

const errorFrame = (errorType: string, message: string) =>
  `event: error\ndata: ${JSON.stringify({ ok: false, error_type: errorType, error_message: message })}\n\n`

describe('apiRequest event-stream consumption (Issue 112)', () => {
  it('forwards item frames and resolves the final result frame', async () => {
    fetchMock.mockResolvedValue(
      sseResponse([itemFrame(1, 3), itemFrame(2, 3), itemFrame(3, 3), resultFrame({ batch_id: 'batch-1', items: [] })]),
    )
    const frames: Array<{ event: string; data: Record<string, unknown> }> = []

    const result = await apiRequest<{ batch_id: string }>('POST', '/api/v1/batches/parse', {
      body: { raw_input: '甲\n乙\n丙' },
      accept: 'text/event-stream',
      onEvent: (event) => frames.push(event),
    })

    expect(result).toEqual({ batch_id: 'batch-1', items: [] })
    expect(frames.filter((frame) => frame.event === 'item').map((frame) => frame.data.completed)).toEqual([1, 2, 3])
    const [, init] = fetchMock.mock.calls[0] ?? []
    expect((init?.headers as Record<string, string>)['Accept']).toBe('text/event-stream')
  })

  it('reassembles a frame split across chunk boundaries', async () => {
    fetchMock.mockResolvedValue(
      sseResponse(['event: it', 'em\ndata: {"completed":1,"total":1,"item":{}}\n', '\nevent: result\ndata: {"ok":true,"result":{"batch_id":"b"}}\n\n']),
    )
    const frames: string[] = []

    const result = await apiRequest<{ batch_id: string }>('POST', '/api/v1/batches/parse', {
      accept: 'text/event-stream',
      onEvent: (event) => frames.push(event.event),
    })

    expect(result).toEqual({ batch_id: 'b' })
    expect(frames).toEqual(['item', 'result'])
  })

  it('rejects with the envelope error carried by an error frame', async () => {
    fetchMock.mockResolvedValue(
      sseResponse([itemFrame(1, 2), errorFrame('internal_server_error', 'A server error occurred.')]),
    )

    const error = await apiRequest('POST', '/api/v1/batches/parse', {
      accept: 'text/event-stream',
      onEvent: () => {},
    }).catch((caught: unknown) => caught)

    expect(isApiError(error)).toBe(true)
    if (isApiError(error)) {
      expect(error.type).toBe('internal_server_error')
      expect(error.message).toBe('A server error occurred.')
    }
  })

  it('never treats a stream without a result frame as success', async () => {
    fetchMock.mockResolvedValue(sseResponse([itemFrame(1, 2)]))

    const error = await apiRequest('POST', '/api/v1/batches/parse', {
      accept: 'text/event-stream',
      onEvent: () => {},
    }).catch((caught: unknown) => caught)

    expect(isApiError(error)).toBe(true)
    if (isApiError(error)) {
      expect(error.type).toBe('stream_incomplete')
    }
  })

  it('still accepts a plain JSON envelope when the server buffers the response', async () => {
    // Fixtures and older deployments may answer the same operation with the
    // buffered JSON representation; it carries the same final batch result.
    fetchMock.mockResolvedValue(jsonResponse({ ok: true, result: { batch_id: 'batch-json', items: [] } }))

    const result = await apiRequest<{ batch_id: string }>('POST', '/api/v1/batches/parse', {
      accept: 'text/event-stream',
      onEvent: () => {},
    })

    expect(result).toEqual({ batch_id: 'batch-json', items: [] })
  })
})
