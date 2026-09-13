import { describe, expect, it } from 'vitest'

import {
  batchParseTimeoutMs,
  candidateResultFailureMessage,
  MIKAN_BATCH_MAX_ITEMS,
  MIKAN_BATCH_PARSE_MAX_TIMEOUT_MS,
  MIKAN_CANDIDATE_SEARCH_TIMEOUT_MS,
  MIKAN_DRAFT_GENERATION_TIMEOUT_MS,
  mikanFailureMessage,
} from './mikanFeedback'

describe('mikanFeedback', () => {
  it('keeps endpoint timeout budgets bounded by the server query plan', () => {
    expect(MIKAN_CANDIDATE_SEARCH_TIMEOUT_MS).toBe(135000)
    expect(MIKAN_DRAFT_GENERATION_TIMEOUT_MS).toBeGreaterThan(MIKAN_CANDIDATE_SEARCH_TIMEOUT_MS)
    expect(batchParseTimeoutMs(1)).toBe(180000)
    expect(batchParseTimeoutMs(3)).toBe(420000)
    expect(batchParseTimeoutMs(12)).toBe(1500000)
    expect(batchParseTimeoutMs(MIKAN_BATCH_MAX_ITEMS + 10)).toBe(MIKAN_BATCH_PARSE_MAX_TIMEOUT_MS)
  })

  it.each([
    ['request_timeout', '等待超时'],
    ['mikan_timeout', 'MiKan 上游响应超时'],
    ['mikan_connection_failed', '网络或连接不可用'],
    ['mikan_http_failed', 'MiKan 服务暂时异常'],
    ['upstream_unavailable', 'MiKan 服务暂时异常'],
    ['mikan_parse_failed', 'MiKan 页面解析异常'],
    ['rss_parse_failed', 'MiKan 页面解析异常'],
    ['unexpected', '候选搜索失败，请稍后重试'],
  ])('maps %s to fixed feedback', (type, expected) => {
    const message = mikanFailureMessage({ type, message: 'https://secret.example/raw?password=canary' }, '候选搜索')
    expect(message).toContain(expected)
    expect(message).not.toContain('secret.example')
    expect(message).not.toContain('canary')
  })

  it('maps a generated 200 FAILED result and leaves EMPTY/FOUND alone', () => {
    expect(candidateResultFailureMessage({ status: 'FOUND', candidates: [] } as never)).toBeNull()
    expect(candidateResultFailureMessage({ status: 'EMPTY', candidates: [] } as never)).toBeNull()
    expect(candidateResultFailureMessage({
      status: 'FAILED',
      candidates: [],
      error: {
        error_type: 'mikan_timeout',
        error_message: 'raw endpoint https://secret.example/rss',
        details: { category: 'mikan_search' },
      },
    } as never)).toContain('MiKan 上游响应超时')
  })
})
