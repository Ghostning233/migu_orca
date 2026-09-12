import { describe, expect, it } from 'vitest'

import {
  batchItemCanConfirm,
  canTransitionBatchItem,
  createBatchReviewState,
  reduceBatchReview,
  toSafeBatchError,
  toSafeBatchResultError,
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

  it('ends saving on deterministic result errors and returns expired drafts to candidates', () => {
    let state = reduceBatchReview(createBatchReviewState(), { type: 'parse_succeeded', result: parsed([
      item('expired', 'DRAFT', { candidates: [{}], preview_request: {}, draft_id: 'draft-expired', draft_revision: 1 }),
      item('saved', 'DRAFT', { preview_request: {}, draft_id: 'draft-saved', draft_revision: 1 }),
    ]) })
    state = reduceBatchReview(state, { type: 'set_selected', itemId: 'saved', selected: true })
    state = reduceBatchReview(state, { type: 'begin_save', itemIds: ['expired', 'saved'] })
    expect(state.busy).toBe('saving')
    state = reduceBatchReview(state, { type: 'save_failed', itemId: 'expired', error: { error_type: 'draft_expired', outcome: 'FAILED' } })
    expect(state.items.expired?.phase).toBe('candidates')
    expect(state.items.expired?.draftId).toBeNull()
    state = reduceBatchReview(state, { type: 'save_failed', itemId: 'saved', error: {
      error_type: 'save_confirm_failed', outcome: 'failed', request_id: 'req-saved',
    } })
    expect(state.busy).toBeNull()
    expect(state.items.saved?.phase).toBe('saved_pending_confirm')
    expect(state.items.saved?.selected).toBe(false)
    expect(toSafeBatchResultError({ error_type: 'save_confirm_failed', outcome: 'failed', request_id: 'req-saved' } as never)).toMatchObject({
      type: 'save_confirm_failed', requestId: 'req-saved',
    })
  })

  it('has explicit apply retry and reset transitions', () => {
    let state = reduceBatchReview(createBatchReviewState(), { type: 'parse_succeeded', result: parsed([item('a', 'DRAFT', { preview_request: {}, draft_id: 'draft-a', draft_revision: 1 })]) })
    state = reduceBatchReview(state, { type: 'begin_apply', itemId: 'a' })
    state = reduceBatchReview(state, { type: 'apply_failed', itemId: 'a', error: { type: 'network_error' } })
    state = reduceBatchReview(state, { type: 'retry_apply', itemId: 'a' })
    expect(state.items.a?.phase).toBe('applying')
    state = reduceBatchReview(state, { type: 'apply_failed', itemId: 'a', error: { type: 'network_error' } })
    state = reduceBatchReview(state, { type: 'reset_apply', itemId: 'a' })
    expect(state.items.a?.phase).toBe('draft')
    expect(state.items.a?.error).toBeNull()
  })

  it('clears a deterministic save error and rotates its key on the next explicit save', () => {
    let state = reduceBatchReview(createBatchReviewState(), { type: 'parse_succeeded', result: parsed([item('a', 'DRAFT', { preview_request: {}, draft_id: 'draft-a', draft_revision: 1 })]) })
    state = reduceBatchReview(state, { type: 'begin_save', itemIds: ['a'] })
    const firstKey = state.items.a?.idempotencyKey
    state = reduceBatchReview(state, { type: 'save_failed', itemId: 'a', error: { error_type: 'idempotency_conflict', outcome: 'failed', request_id: null } })
    expect(state.items.a?.phase).toBe('draft')
    expect(state.items.a?.idempotencyKey).toBeNull()
    expect(batchItemCanConfirm(state.items.a)).toBe(true)
    state = reduceBatchReview(state, { type: 'begin_save', itemIds: ['a'] })
    expect(state.items.a?.idempotencyKey).not.toBe(firstKey)
  })

  it('maps unknown retry results to candidates and keeps tracking phases aligned', () => {
    let state = reduceBatchReview(createBatchReviewState(), { type: 'parse_succeeded', result: parsed([item('a', 'DRAFT', { candidates: [{}], preview_request: {}, draft_id: 'draft-a', draft_revision: 1 })]) })
    state = reduceBatchReview(state, { type: 'begin_save', itemIds: ['a'] })
    state = reduceBatchReview(state, { type: 'save_response_unknown', itemIds: ['a'] })
    state = reduceBatchReview(state, { type: 'save_failed', itemId: 'a', error: { error_type: 'draft_expired', outcome: 'failed', request_id: null } })
    expect(state.items.a?.phase).toBe('candidates')
    expect(state.items.a?.idempotencyKey).toBeNull()
    state = reduceBatchReview(state, { type: 'set_draft', itemId: 'a', draftId: 'draft-b', revision: 1 })
    state = reduceBatchReview(state, { type: 'begin_save', itemIds: ['a'] })
    state = reduceBatchReview(state, { type: 'save_failed', itemId: 'a', error: { error_type: 'save_confirm_failed', outcome: 'failed', request_id: 'req-a' } })
    expect(state.items.a?.phase).toBe('saved_pending_confirm')
    state = reduceBatchReview(state, { type: 'tracking_verification_failed', itemId: 'a' })
    expect(state.items.a?.phase).toBe('response_unknown')
    state = reduceBatchReview(state, { type: 'tracking_not_found', itemId: 'a' })
    expect(state.items.a?.phase).toBe('saved_pending_confirm')
    state = reduceBatchReview(state, { type: 'tracking_located', itemId: 'a', requestId: 'req-a', trackingId: 'track-a' })
    expect(state.items.a).toMatchObject({ phase: 'confirmed', requestId: 'req-a', trackingId: 'track-a' })
  })
})
