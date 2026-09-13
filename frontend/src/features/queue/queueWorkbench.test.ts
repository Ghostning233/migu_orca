import { beforeEach, describe, expect, it, vi } from 'vitest'

import { api } from '@/api/client'
import {
  batchSubmitNotification,
  batchSubmitSummaryMessage,
  buildAbConfig,
  loadQueue,
  queueItemCanRecover,
  queueItemCanRetry,
  queueItemIsStuck,
  queueItemIsTerminal,
  queueItemSummary,
  queueStatusClass,
  queueStatusLabel,
  recoverNeedsManualMessage,
  recoverOutcomeNeedsManual,
  recoverQueueItem,
  retryQueueItem,
  submitQueue,
  validateAbConfig,
} from '@/features/queue/queueWorkbench'

// US-206: pure queue helpers (legacy app.js batchQueueStatusLabel /
// batchQueueStatusClass / batchQueueItemSummary / batchQueueSummaryMessage /
// buildAbConfig / syncAbAuthMode parity).

vi.mock('@/api/client', () => ({
  api: {
    get: vi.fn(),
    post: vi.fn(),
    put: vi.fn(),
    patch: vi.fn(),
    delete: vi.fn(),
    poster: vi.fn(),
  },
  toApiError: (error: unknown) =>
    error && typeof error === 'object' && 'type' in error
      ? (error as { type: string; message: string })
      : { type: 'request_error', message: '请求失败，请重试' },
  isApiError: () => false,
  apiRequest: vi.fn(),
}))

const apiGet = vi.mocked(api.get)
const apiPost = vi.mocked(api.post)

describe('queue status helpers', () => {
  it('maps every queue status code to a Chinese label (legacy parity)', () => {
    expect(queueStatusLabel('READY_TO_SUBMIT')).toBe('待提交')
    expect(queueStatusLabel('SUBMITTING')).toBe('提交中')
    expect(queueStatusLabel('SUCCEEDED')).toBe('提交成功')
    expect(queueStatusLabel('FAILED')).toBe('提交失败')
    expect(queueStatusLabel('RETRYABLE')).toBe('可重试')
    expect(queueStatusLabel('RESULT_PERSIST_FAILED')).toBe('结果保存失败')
    // Unknown codes render as-is (never collapsed to a default).
    expect(queueStatusLabel('NEW_SERVER_STATE')).toBe('NEW_SERVER_STATE')
    expect(queueStatusLabel(null)).toBe('')
  })

  it('maps statuses to stable CSS classes with a ready fallback', () => {
    expect(queueStatusClass('SUCCEEDED')).toBe('succeeded')
    expect(queueStatusClass('SUBMITTING')).toBe('submitting')
    expect(queueStatusClass('RESULT_PERSIST_FAILED')).toBe('result-persist-failed')
    expect(queueStatusClass('UNKNOWN')).toBe('ready')
    expect(queueStatusClass(null)).toBe('ready')
  })

  it('exposes per-status action capabilities', () => {
    expect(queueItemCanRetry('FAILED')).toBe(true)
    expect(queueItemCanRetry('RETRYABLE')).toBe(true)
    expect(queueItemCanRetry('SUCCEEDED')).toBe(false)
    expect(queueItemCanRetry('READY_TO_SUBMIT')).toBe(false)
    expect(queueItemCanRecover('SUBMITTING')).toBe(true)
    expect(queueItemCanRecover('RESULT_PERSIST_FAILED')).toBe(true)
    expect(queueItemCanRecover('FAILED')).toBe(false)
    expect(queueItemIsStuck('SUBMITTING')).toBe(true)
    expect(queueItemIsStuck('RESULT_PERSIST_FAILED')).toBe(true)
    expect(queueItemIsStuck('READY_TO_SUBMIT')).toBe(false)
    expect(queueItemIsTerminal('SUCCEEDED')).toBe(true)
    expect(queueItemIsTerminal('FAILED')).toBe(true)
    expect(queueItemIsTerminal('RETRYABLE')).toBe(false)
  })

  it('summarizes result > error > none (legacy batchQueueItemSummary)', () => {
    expect(queueItemSummary({ ab_result_summary: 'Auto Bangumi 已接受' } as never)).toBe(
      '结果：Auto Bangumi 已接受',
    )
    expect(queueItemSummary({ last_error: '连接失败' } as never)).toBe('错误：连接失败')
    expect(queueItemSummary({} as never)).toBe('尚无结果摘要')
    // result summary wins over last_error.
    expect(
      queueItemSummary({ ab_result_summary: 'ok', last_error: 'err' } as never),
    ).toBe('结果：ok')
  })
})

describe('AB config helpers', () => {
  it('builds a password-mode config with only public/credential fields', () => {
    const config = buildAbConfig('password', '192.168.1.20:7890', true, {
      username: 'user',
      password: 'secret',
      token: 'token',
    })
    expect(config).toEqual({
      auth_mode: 'password',
      base_url: 'http://192.168.1.20:7890',
      fallback_enabled: true,
      username: 'user',
      password: 'secret',
    })
    expect(config.token).toBeUndefined()
  })

  it('builds an api_token-mode config without password fields', () => {
    const config = buildAbConfig('api_token', 'https://ab.example', false, {
      token: 'tok',
    })
    expect(config).toEqual({
      auth_mode: 'api_token',
      base_url: 'https://ab.example',
      fallback_enabled: false,
      token: 'tok',
    })
    expect(config.username).toBeUndefined()
    expect(config.password).toBeUndefined()
  })

  it('validates required fields with fixed Chinese copy', () => {
    expect(validateAbConfig('password', '', {})).toBe('请填写服务地址。')
    expect(validateAbConfig('password', 'https://ab.example', { username: '', password: '' })).toBe(
      '请填写用户名。',
    )
    expect(
      validateAbConfig('password', 'https://ab.example', { username: 'u', password: '' }),
    ).toBe('请填写密码。')
    expect(validateAbConfig('api_token', 'https://ab.example', { token: '' })).toBe(
      '请填写 API Token。',
    )
    expect(
      validateAbConfig('api_token', 'https://ab.example', { token: 'tok' }),
    ).toBeNull()
    expect(
      validateAbConfig('password', 'https://ab.example', { username: 'u', password: 'p' }),
    ).toBeNull()
  })
})

describe('submit summary/notification helpers', () => {
  it('summarizes succeeded/failed/retryable/skipped counts (legacy parity)', () => {
    expect(batchSubmitSummaryMessage({ succeeded: 1, failed: 1, retryable: 1, skipped: 1 })).toBe(
      '提交成功 1 项；提交失败 1 项；可重试 1 项；跳过 1 项',
    )
    expect(batchSubmitSummaryMessage({ succeeded: 2 })).toBe('提交成功 2 项')
  })

  it('picks kind/title from the summary (legacy showBatchQueueSubmitNotification)', () => {
    expect(batchSubmitNotification({ succeeded: 1 })).toMatchObject({
      kind: 'success',
      title: '批量提交成功',
    })
    expect(batchSubmitNotification({ succeeded: 1, failed: 1 })).toMatchObject({
      kind: 'success',
      title: '批量提交完成',
    })
    expect(batchSubmitNotification({ failed: 1, retryable: 1 })).toMatchObject({
      kind: 'error',
      title: '批量提交失败',
    })
    expect(batchSubmitNotification({ retryable: 2 })).toMatchObject({
      kind: 'error',
      title: '批量提交失败',
    })
  })

  it('detects the needs_manual recovery outcome', () => {
    expect(recoverOutcomeNeedsManual({ status: 'needs_manual' })).toBe(true)
    expect(recoverOutcomeNeedsManual({ status: 'succeeded' })).toBe(false)
    expect(recoverOutcomeNeedsManual(undefined)).toBe(false)
    expect(recoverOutcomeNeedsManual(null)).toBe(false)
  })

  it('builds the manual-verification message with a Chinese status label', () => {
    expect(recoverNeedsManualMessage('SUBMITTING')).toContain('「提交中」')
    expect(recoverNeedsManualMessage('RESULT_PERSIST_FAILED')).toContain('「结果保存失败」')
  })
})

describe('queue transport wrappers', () => {
  beforeEach(() => {
    apiGet.mockReset()
    apiPost.mockReset()
  })

  it('reads the queue through the shared transport with relative storage query', async () => {
    apiGet.mockResolvedValue({ batch_id: 'batch-1', queue: null })
    await loadQueue('batch-1', { storage_dir: 'backups' })
    expect(apiGet).toHaveBeenCalledWith('/api/v1/batches/{batch_id}/queue', {
      path: { batch_id: 'batch-1' },
      query: { storage_dir: 'backups' },
    })
  })

  it('posts submit/retry/recover with the request-scoped payload shape', async () => {
    apiPost.mockResolvedValue({ batch_id: 'batch-1', queue: null, items: [], summary: {} })
    const payload = { ab_config: { auth_mode: 'api_token' }, confirm: true }

    await submitQueue('batch-1', payload)
    expect(apiPost).toHaveBeenCalledWith('/api/v1/batches/{batch_id}/submit', {
      path: { batch_id: 'batch-1' },
      body: payload,
    })

    await retryQueueItem('batch-1', 'req-1', payload)
    expect(apiPost).toHaveBeenCalledWith('/api/v1/batches/{batch_id}/retry', {
      path: { batch_id: 'batch-1' },
      body: { ...payload, request_id: 'req-1' },
    })

    await recoverQueueItem('batch-1', 'req-1', 'auto', false, {})
    expect(apiPost).toHaveBeenCalledWith('/api/v1/batches/{batch_id}/recover', {
      path: { batch_id: 'batch-1' },
      query: {},
      body: { request_id: 'req-1', action: 'auto', confirm: false },
    })
  })
})
