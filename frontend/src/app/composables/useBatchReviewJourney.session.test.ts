import { describe, expect, it } from 'vitest'

import { useBatchReviewJourney, type BatchParseItem, type ParseBatchTitlesResult } from './useBatchReviewJourney'

function item(itemId: string, status: string, extra: Record<string, unknown> = {}): BatchParseItem {
  return {
    item_id: itemId,
    raw_title: itemId,
    status,
    queue_status: null,
    canonical_title_candidates: [],
    season_hint: null,
    search_queries: [],
    confidence: null,
    needs_user_review: false,
    source: null,
    parse_result: null,
    attempted_queries: [],
    candidates: [],
    applied_preferences: null,
    preference_hits: [],
    preference_warnings: [],
    review_hints: [],
    enhanced_search_queries: [],
    preview_request: null,
    draft_id: null,
    draft_revision: null,
    error: null,
    ...extra,
  } as BatchParseItem
}

function parsed(items: BatchParseItem[], batchId = 'batch-1'): ParseBatchTitlesResult {
  return { batch_id: batchId, raw_input: items.map((entry) => entry.raw_title).join('\n'), items } as ParseBatchTitlesResult
}

const draftItem = (itemId: string, extra: Record<string, unknown> = {}) =>
  item(itemId, 'DRAFT', { preview_request: {}, draft_id: `draft-${itemId}`, draft_revision: 1, ...extra })

/**
 * #161：命令返回「是否被接受 + 待执行效应」，只读快照承载客户端生命周期。
 * 这些用例记录模块的会话接口，不重复 reducer 的纯转换用例。
 */
describe('useBatchReviewJourney session commands (#161)', () => {
  it('reports acceptance and hands navigation/notification back as data', () => {
    const session = useBatchReviewJourney()
    expect(session.snapshot.value.parseError).toBe('')
    expect(session.snapshot.value.batchId).toBe('')

    expect(session.beginParse().accepted).toBe(true)
    expect(session.snapshot.value.state.busy).toBe('parsing')

    const rejected = session.rejectParseInput('至少需要 1 部番剧')
    expect(rejected.accepted).toBe(true)
    expect(rejected.effects).toEqual([
      { kind: 'notify', event: { type: 'parse_input_rejected', message: '至少需要 1 部番剧' } },
    ])
    expect(session.snapshot.value.parseError).toBe('至少需要 1 部番剧')

    const finished = session.finishParse(parsed([draftItem('a'), draftItem('b')]))
    expect(finished.accepted).toBe(true)
    expect(finished.effects).toEqual([
      { kind: 'navigate', batchId: 'batch-1' },
      { kind: 'notify', event: { type: 'parse_succeeded', itemCount: 2 } },
    ])
    expect(session.snapshot.value.parseError).toBe('')
    expect(session.snapshot.value.batchId).toBe('batch-1')
    expect(session.snapshot.value.state.phase).toBe('review')

    const empty = useBatchReviewJourney()
    empty.beginParse()
    expect(empty.finishParse(parsed([])).effects).toContainEqual({ kind: 'notify', event: { type: 'parse_empty' } })
  })

  it('keeps the failure message in the session while the reducer drops the payload', () => {
    const session = useBatchReviewJourney()
    session.beginParse()
    const failed = session.failParse('批量候选解析暂时不可用')

    // 对外行为与旧实现一致：不写 URL（不产生 navigate 效应）。
    expect(failed.effects).toEqual([
      { kind: 'notify', event: { type: 'parse_failed', message: '批量候选解析暂时不可用' } },
    ])
    expect(session.snapshot.value.parseError).toBe('批量候选解析暂时不可用')
    expect(session.snapshot.value.batchId).toBe('')
    // reducer 的 parse_failed 仍只负责相位，不携带错误载荷。
    expect(session.snapshot.value.state.phase).toBe('input')
    expect(session.snapshot.value.state.busy).toBeNull()
  })

  it('restores a batch id from the route without inventing a navigation', () => {
    const session = useBatchReviewJourney()
    session.restoreBatchId('batch-from-url')
    expect(session.snapshot.value.batchId).toBe('batch-from-url')
    expect(session.snapshot.value.state.phase).toBe('input')
  })

  it('reports a rejected transition without mutating the snapshot', () => {
    const session = useBatchReviewJourney()
    session.finishParse(parsed([draftItem('a')]))
    const before = session.snapshot.value.state

    expect(session.selectItem('missing').accepted).toBe(false)
    expect(session.setSelected('missing', true).accepted).toBe(false)
    expect(session.beginApply('missing').accepted).toBe(false)
    expect(session.markTrackingNotFound('a').accepted).toBe(false)
    expect(session.snapshot.value.state).toBe(before)
  })

  it('tracks per-item draft generation candidate and sanitized failure', () => {
    const session = useBatchReviewJourney()
    session.beginDraftCreate('a', 'bangumi-42')
    expect([...session.snapshot.value.draftCreateItemIds]).toEqual(['a'])
    expect(session.snapshot.value.draftCreateCandidateIds).toEqual({ a: 'bangumi-42' })
    expect(session.snapshot.value.draftCreateErrors).toEqual({})

    session.failDraftCreate('a', 'bangumi-42', '生成失败，请稍后重试')
    expect(session.snapshot.value.draftCreateErrors).toEqual({ a: { 'bangumi-42': '生成失败，请稍后重试' } })

    // 同一条目的另一次点击清掉该候选的失败，不叠加。
    session.beginDraftCreate('a', 'bangumi-42')
    expect(session.snapshot.value.draftCreateErrors).toEqual({})

    session.failDraftCreate('a', 'bangumi-7', '生成失败，请稍后重试')
    session.clearDraftCreateErrors('a')
    expect(session.snapshot.value.draftCreateErrors).toEqual({})

    // finally 只撤回「在途 + 当前候选」，历史失败反馈仍由显式命令管理。
    session.failDraftCreate('a', 'bangumi-7', '生成失败，请稍后重试')
    session.finishDraftCreate('a')
    expect(session.snapshot.value.draftCreateItemIds.size).toBe(0)
    expect(session.snapshot.value.draftCreateCandidateIds).toEqual({})
    expect(session.snapshot.value.draftCreateErrors).toEqual({ a: { 'bangumi-7': '生成失败，请稍后重试' } })
  })

  it('resetRoute clears the journey and the draft generation state it decides', () => {
    const session = useBatchReviewJourney()
    session.finishParse(parsed([draftItem('a'), draftItem('b')]))
    session.selectItem('b')
    session.setSelected('a', true)
    session.beginDraftCreate('a', 'bangumi-42')
    session.failDraftCreate('a', 'bangumi-42', '生成失败，请稍后重试')
    session.restoreBatchId('batch-1')

    const cleared = session.resetRoute()
    expect(cleared.accepted).toBe(true)
    expect(session.snapshot.value.state).toMatchObject({
      phase: 'input',
      inputOrder: [],
      reviewOrder: [],
      currentItemId: null,
      items: {},
      busy: null,
    })
    expect(session.snapshot.value.draftCreateItemIds.size).toBe(0)
    expect(session.snapshot.value.draftCreateCandidateIds).toEqual({})
    expect(session.snapshot.value.draftCreateErrors).toEqual({})
    // 旧实现的清理清单不含 batch_id：路由现场清理不据此改 URL 语义。
    expect(session.snapshot.value.batchId).toBe('batch-1')
    // 重复清理总是落回一份新的空会话（clear_route 的既有语义）。
    expect(session.resetRoute().accepted).toBe(true)
    expect(session.snapshot.value.state.items).toEqual({})
    expect(session.snapshot.value.state.phase).toBe('input')
  })
})
