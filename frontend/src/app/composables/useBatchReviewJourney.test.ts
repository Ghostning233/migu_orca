import { describe, expect, it } from 'vitest'

import {
  batchItemCanConfirm,
  canTransitionBatchItem,
  createBatchReviewState,
  reduceBatchReview,
  toSafeBatchError,
  type BatchParseItem,
  type ParseBatchTitlesResult,
} from './useBatchReviewJourney'

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

function parsed(items: BatchParseItem[]): ParseBatchTitlesResult {
  return { batch_id: 'batch-1', raw_input: items.map((entry) => entry.raw_title).join('\n'), items } as ParseBatchTitlesResult
}

describe('useBatchReviewJourney', () => {
  it('freezes exception-first review order while retaining input order', () => {
    const state = reduceBatchReview(
      reduceBatchReview(createBatchReviewState('ok\nfailed\nreview'), { type: 'parse_started' }),
      { type: 'parse_succeeded', result: parsed([item('ok', 'FOUND'), item('failed', 'FAILED'), item('review', 'FOUND', { needs_user_review: true })]) },
    )
    expect(state.inputOrder).toEqual(['ok', 'failed', 'review'])
    expect(state.reviewOrder).toEqual(['failed', 'review', 'ok'])
    expect(state.currentItemId).toBe('failed')
  })

  it('keeps current detail and selection intent independent', () => {
    let state = reduceBatchReview(createBatchReviewState(), { type: 'parse_succeeded', result: parsed([item('a', 'FOUND', { candidates: [{}] }), item('b', 'FOUND', { candidates: [{}] })]) })
    state = reduceBatchReview(state, { type: 'set_current', itemId: 'b' })
    state = reduceBatchReview(state, { type: 'set_selected', itemId: 'a', selected: true })
    expect(state.currentItemId).toBe('b')
    expect(state.items.a!.selected).toBe(true)
    expect(state.items.b!.selected).toBe(false)
    expect(reduceBatchReview(state, { type: 'set_selected', itemId: 'b', selected: true }).items.b!.selected).toBe(true)
  })

  it('consumes the draft and key only after a confirmed save', () => {
    let state = reduceBatchReview(createBatchReviewState(), { type: 'parse_succeeded', result: parsed([item('a', 'DRAFT', { preview_request: {}, draft_id: 'draft-a', draft_revision: 2 })]) })
    expect(batchItemCanConfirm(state.items.a!)).toBe(true)
    state = reduceBatchReview(state, { type: 'begin_save', itemIds: ['a'] })
    const key = state.items.a!.idempotencyKey
    expect(key).toBeTruthy()
    state = reduceBatchReview(state, { type: 'save_response_unknown', itemIds: ['a'] })
    expect(state.items.a!.phase).toBe('response_unknown')
    expect(state.items.a!.idempotencyKey).toBe(key)
    state = reduceBatchReview(state, { type: 'save_succeeded', itemId: 'a', result: { item_id: 'a', outcome: 'CONFIRMED', request_id: 'req-a', tracking_id: null, status: 'PENDING_SUBMIT', error_type: null, error_message: null, tracking_ready: false } })
    expect(state.items.a!.phase).toBe('confirmed')
    expect(state.items.a!.draftId).toBeNull()
    expect(state.items.a!.idempotencyKey).toBeNull()
  })

  it('allows only the documented item transitions and redacts unsafe errors', () => {
    expect(canTransitionBatchItem('draft', 'saving')).toBe(true)
    expect(canTransitionBatchItem('confirmed', 'draft')).toBe(false)
    expect(toSafeBatchError({ type: 'unknown', details: { raw_body: 'secret', path: '/absolute/private' } })).toEqual({
      type: 'batch_error', message: '操作失败，请重新尝试。',
    })
    expect(toSafeBatchError({ type: 'save_confirm_failed', details: { details: { outcome: 'SAVED_CONFIRM_FAILED', request_id: 'req-a', retry_action: 'ACCEPT_SAVED_REQUEST', secret: 'no' } } })).toMatchObject({
      type: 'save_confirm_failed', requestId: 'req-a', retryAction: 'ACCEPT_SAVED_REQUEST',
    })
  })

  it('blocks dirty/applying drafts and rotates keys after capability changes', () => {
    let state = reduceBatchReview(createBatchReviewState(), { type: 'parse_succeeded', result: parsed([item('a', 'DRAFT', { preview_request: {}, draft_id: 'draft-a', draft_revision: 1 })]) })
    state = reduceBatchReview(state, { type: 'set_dirty', itemId: 'a', dirty: true })
    expect(batchItemCanConfirm(state.items.a!)).toBe(false)
    state = reduceBatchReview(state, { type: 'set_dirty', itemId: 'a', dirty: false })
    state = reduceBatchReview(state, { type: 'begin_apply', itemId: 'a' })
    expect(state.items.a!.phase).toBe('applying')
    expect(batchItemCanConfirm(state.items.a!)).toBe(false)
    state = reduceBatchReview(state, { type: 'apply_failed', itemId: 'a', error: { type: 'network_error' } })
    expect(state.items.a!.phase).toBe('apply_failed')
    expect(batchItemCanConfirm(state.items.a!)).toBe(false)
    state = reduceBatchReview(state, { type: 'retry_apply', itemId: 'a' })
    state = reduceBatchReview(state, { type: 'apply_succeeded', itemId: 'a', draftId: 'draft-a', revision: 2 })
    state = reduceBatchReview(state, { type: 'begin_save', itemIds: ['a'] })
    const firstKey = state.items.a!.idempotencyKey
    state = reduceBatchReview(state, { type: 'save_response_unknown', itemIds: ['a'] })
    expect(state.items.a!.idempotencyKey).toBe(firstKey)
    state = reduceBatchReview(state, { type: 'set_draft', itemId: 'a', draftId: 'draft-b', revision: 1 })
    expect(state.items.a!.idempotencyKey).toBeNull()
    state = reduceBatchReview(state, { type: 'begin_save', itemIds: ['a'] })
    expect(state.items.a!.idempotencyKey).not.toBe(firstKey)
  })
})
