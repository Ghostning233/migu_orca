import { describe, expect, it } from 'vitest'

import type { operations } from '@/api/generated/api'
import {
  batchAcceptAllScopeText,
  batchCandidateSelectionIsBlocked,
  batchCardNeedsReview,
  batchCardPreferenceSummary,
  batchCardSeedSummary,
  batchCardTitle,
  batchItemCount,
  batchItemIsException,
  batchItemMatchesReviewFilters,
  batchStatusLabel,
  batchSaveConfirmErrorLabel,
  batchSaveConfirmRecoveryAllowed,
  batchSaveConfirmSucceeded,
  buildBatchSaveConfirmPayload,
  buildBatchCandidateCreatePayload,
  buildBatchParsePayload,
  canAcceptBatchCard,
  canChooseBatchCandidate,
  canExpandBatchCard,
  orderBatchItemsForReview,
  validateBatchRawInput,
  type BatchItem,
} from '@/features/workbench/batchWorkbench'

describe('batch save-confirm contract (US-290)', () => {
  it('sends only generated capability descriptors and relative storage profile', () => {
    expect(buildBatchSaveConfirmPayload([
      { item_id: 'item-2', draft_id: 'draft-2', base_revision: 4, idempotency_key: 'key-2' },
    ], ['item-2'], 'profile')).toEqual({
      items: [{ item_id: 'item-2', draft_id: 'draft-2', base_revision: 4, idempotency_key: 'key-2' }],
      item_ids: ['item-2'],
      storage_dir: 'profile',
    })
  })

  it('recognizes confirmed results and maps only stable errors to safe copy', () => {
    expect(batchSaveConfirmSucceeded({ outcome: 'CONFIRMED', request_id: 'req-ok', tracking_id: null, status: null } as never)).toBe(true)
    expect(batchSaveConfirmSucceeded({ outcome: 'CONFIRMED', request_id: null, tracking_id: null, status: 'CONFIRMED' } as never)).toBe(false)
    expect(batchSaveConfirmSucceeded({ outcome: 'failed', status: 'FAILED' } as never)).toBe(false)
    expect(batchSaveConfirmErrorLabel({ outcome: 'failed', error_type: 'save_confirm_failed' } as never)).toContain('确认未完成')
    expect(batchSaveConfirmErrorLabel({ outcome: 'failed', error_type: 'private_backend_detail' } as never)).toBe('保存确认失败，请重试。')
    expect(batchSaveConfirmRecoveryAllowed({ outcome: 'failed', error_type: 'save_confirm_failed', request_id: 'req-saved' } as never)).toBe(true)
    expect(batchSaveConfirmRecoveryAllowed({ outcome: 'SAVED_CONFIRM_FAILED', error_type: 'save_confirm_failed', request_id: 'req-saved' } as never)).toBe(false)
    expect(batchSaveConfirmRecoveryAllowed({ outcome: 'failed', error_type: 'save_confirm_failed', request_id: 'https://private.invalid' } as never)).toBe(false)
  })
})

type ParseResult = NonNullable<
  operations['parseBatchTitles']['responses']['200']['content']['application/json']['result']
>

function batchItem(overrides: Record<string, unknown> = {}): BatchItem {
  return {
    item_id: 'item-1',
    raw_title: '萌王S4',
    status: 'FOUND',
    canonical_title_candidates: ['关于我转生变成史莱姆这档事 第四季'],
    season_hint: 'S4',
    search_queries: ['转生史莱姆 第四季'],
    confidence: 0.9,
    needs_user_review: false,
    source: 'rule',
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
    error: null,
    ...overrides,
  } as never
}

function previewRequest(requestId = 'req-1') {
  return {
    request_id: requestId,
    status: 'PENDING_CONFIRM',
    input: { raw_title: '萌王S4' },
    source_info: { matched_bangumi: { title: '关于我转生变成史莱姆这档事 第四季' }, rss_sources: [] },
    confirmable_config: {
      selected_subtitle_group: '喵萌奶茶屋',
      filter_rule: { must_contain: '', must_not_contain: '', use_regex: false, case_sensitive: false },
      effective_seed_names: ['史莱姆 S4 01 [1080p]'],
      expected_folder_name: '关于我转生变成史莱姆这档事 第四季',
      warnings: [],
    },
  }
}

function parseResult(overrides: Partial<Record<string, unknown>> = {}): ParseResult {
  return {
    batch_id: 'batch-1',
    raw_input: '萌王S4',
    items: [batchItem()],
    ...overrides,
  } as never
}

describe('batchWorkbench helpers (US-205)', () => {
  it('maps batch status codes to Chinese labels', () => {
    expect(batchStatusLabel('FOUND')).toBe('找到候选')
    expect(batchStatusLabel('EMPTY')).toBe('未找到候选')
    expect(batchStatusLabel('FAILED')).toBe('搜索失败')
    expect(batchStatusLabel('DRAFT')).toBe('草案')
    expect(batchStatusLabel('ACCEPTED')).toBe('已接受')
    expect(batchStatusLabel('UNKNOWN')).toBe('UNKNOWN')
  })

  it('validates the batch raw input before calling the API', () => {
    expect(validateBatchRawInput('')).toContain('0 部')
    expect(validateBatchRawInput('   ')).toContain('0 部')
    expect(validateBatchRawInput('萌王S4')).toBeNull()
    expect(batchItemCount('萌王S4\n\n路哥S4')).toBe(2)
    expect(validateBatchRawInput(Array.from({ length: 37 }, (_, index) => `番剧${index}`).join('\n'))).toContain('37 部')
    expect(validateBatchRawInput(Array.from({ length: 36 }, (_, index) => `番剧${index}`).join('\n'))).toBeNull()
  })

  it('orders blocking and review items first while preserving each input group order', () => {
    const ordered = orderBatchItemsForReview([
      batchItem({ item_id: 'normal-1', status: 'FOUND' }),
      batchItem({ item_id: 'review', status: 'FOUND', needs_user_review: true }),
      batchItem({ item_id: 'failed', status: 'FAILED' }),
      batchItem({ item_id: 'empty', status: 'EMPTY' }),
      batchItem({ item_id: 'normal-2', status: 'DRAFT' }),
    ])
    expect(ordered.map((item) => item.item_id)).toEqual(['failed', 'empty', 'review', 'normal-1', 'normal-2'])
  })

  it('matches additive title, status, and exception filters without changing item identity', () => {
    const failed = batchItem({ item_id: 'failed', status: 'FAILED', raw_title: '路哥' })
    const normal = batchItem({ item_id: 'normal', status: 'DRAFT', raw_title: '萌王' })
    expect(batchItemIsException(failed)).toBe(true)
    expect(batchItemIsException(normal)).toBe(false)
    expect(batchItemMatchesReviewFilters(failed, { query: '路', status: 'FAILED', exceptionsOnly: true })).toBe(true)
    expect(batchItemMatchesReviewFilters(normal, { query: '路', status: '', exceptionsOnly: false })).toBe(false)
    expect(batchItemMatchesReviewFilters(failed, { query: '', status: 'DRAFT', exceptionsOnly: true })).toBe(false)
  })

  it('builds the parse payload with only input + storage context', () => {
    expect(buildBatchParsePayload('萌王S4\n路哥S4', 'storage')).toEqual({
      raw_input: '萌王S4\n路哥S4',
      storage_dir: 'storage',
    })
    expect(buildBatchParsePayload('萌王S4', null)).toEqual({
      raw_input: '萌王S4',
      storage_dir: null,
    })
  })

  it('derives the card title from canonical candidates, falling back to raw', () => {
    expect(batchCardTitle(batchItem())).toBe('关于我转生变成史莱姆这档事 第四季')
    expect(batchCardTitle(batchItem({ canonical_title_candidates: [] }))).toBe('萌王S4')
    expect(batchCardTitle(batchItem({ canonical_title_candidates: [], raw_title: null }))).toBe('未命名条目')
  })

  it('only expands DRAFT/READY cards and requires a reviewable request to accept', () => {
    expect(canExpandBatchCard(batchItem({ status: 'FOUND' }))).toBe(false)
    expect(canExpandBatchCard(batchItem({ status: 'DRAFT', preview_request: previewRequest() }))).toBe(true)
    expect(canAcceptBatchCard(batchItem({ status: 'DRAFT', preview_request: null }))).toBe(false)
    expect(canAcceptBatchCard(batchItem({ status: 'DRAFT', preview_request: previewRequest() }))).toBe(true)
    expect(canAcceptBatchCard(batchItem({ status: 'ACCEPTED' }))).toBe(false)
  })

  it('summarizes preference hits and flags the fallback', () => {
    expect(batchCardPreferenceSummary(batchItem())).toBe('未配置偏好，使用默认流程')
    expect(
      batchCardPreferenceSummary(
        batchItem({
          preference_hits: [
            { field: 'subtitle_groups', applied: true },
            { field: 'filter_rule', applied: true },
            { field: 'naming', applied: true },
          ],
        }),
      ),
    ).toBe('偏好命中：字幕组、筛选、命名')
    expect(
      batchCardPreferenceSummary(
        batchItem({ preference_warnings: ['偏好读取失败，已回退默认流程'] }),
      ),
    ).toBe('偏好不可用，已回退默认流程')
  })

  it('shows the effective seed count or 待展开', () => {
    expect(batchCardSeedSummary(batchItem())).toBe('待展开')
    expect(
      batchCardSeedSummary(
        batchItem({ status: 'DRAFT', preview_request: previewRequest() }),
      ),
    ).toBe('1')
  })

  it('flags review status only when needed and not accepted', () => {
    expect(batchCardNeedsReview(batchItem())).toBe(false)
    expect(batchCardNeedsReview(batchItem({ needs_user_review: true, status: 'FOUND' }))).toBe(true)
    expect(batchCardNeedsReview(batchItem({ needs_user_review: true, status: 'ACCEPTED' }))).toBe(false)
  })

  it('blocks candidate selection for conflicts and unconfirmed seasons', () => {
    expect(
      batchCandidateSelectionIsBlocked({ season_evidence: { status: 'CONFLICT' } } as never, null),
    ).toBe(true)
    expect(
      batchCandidateSelectionIsBlocked({ season_evidence: { status: 'NEEDS_CONFIRMATION', season: 4 } } as never, null),
    ).toBe(true)
    expect(
      batchCandidateSelectionIsBlocked({ season_evidence: { status: 'NEEDS_CONFIRMATION', season: 4 } } as never, 4),
    ).toBe(false)
  })

  it('builds the candidate create payload with context/season', () => {
    const payload = buildBatchCandidateCreatePayload(
      {
        bangumi_id: '42',
        title: '关于我转生变成史莱姆这档事 第四季',
        mikan_url: 'https://mikan.example/Home/Bangumi/42',
        candidate_context: 'opaque-context',
      } as never,
      { storageDir: 'storage', confirmedSeason: 4 },
    )
    expect(payload).toMatchObject({
      title: '关于我转生变成史莱姆这档事 第四季',
      mikan_bangumi: 'https://mikan.example/Home/Bangumi/42',
      candidate_context: 'opaque-context',
      season_confirmation: 4,
    })
    expect(payload.storage_dir).toBe('storage')
  })

  it('detects FOUND cards with candidate choices', () => {
    expect(canChooseBatchCandidate(batchItem())).toBe(false)
    expect(canChooseBatchCandidate(batchItem({ candidates: [{}] }))).toBe(true)
    expect(canChooseBatchCandidate(batchItem({ status: 'EMPTY' }))).toBe(false)
  })

  it('keeps the batch request serialization free of raw candidate URLs', () => {
    const result = parseResult()
    expect(JSON.stringify(result)).not.toContain('token')
    expect(JSON.stringify(result)).not.toContain('cookie')
  })
})

describe('batch confirm-all scope text (US-347)', () => {
  it('describes the complete batch range with hidden and excluded counts', () => {
    expect(batchAcceptAllScopeText({ total: 3, confirmable: 2, hidden: 1 })).toBe(
      '保存并确认全部覆盖完整批次 3 项中的 2 项可确认条目，其中 1 项当前被筛选隐藏，排除 1 项未就绪、已确认或结果待核验条目；不受筛选或勾选影响。',
    )
    expect(batchAcceptAllScopeText({ total: 2, confirmable: 2, hidden: 0 })).toBe(
      '保存并确认全部覆盖完整批次 2 项中的 2 项可确认条目；不受筛选或勾选影响。',
    )
  })

  it('states a visible reason when no item of the complete batch is confirmable', () => {
    expect(batchAcceptAllScopeText({ total: 4, confirmable: 0, hidden: 0 })).toContain('完整批次 4 项均不可确认')
    expect(batchAcceptAllScopeText({ total: 0, confirmable: 0, hidden: 0 })).toBe('')
  })

  it('never reports counts outside the batch bounds', () => {
    expect(batchAcceptAllScopeText({ total: 2, confirmable: 5, hidden: 9 })).toContain('完整批次 2 项中的 2 项可确认条目')
    expect(batchAcceptAllScopeText({ total: 2, confirmable: 5, hidden: 9 })).toContain('其中 2 项当前被筛选隐藏')
    expect(batchAcceptAllScopeText({ total: 2, confirmable: -1, hidden: 0 })).toContain('完整批次 2 项均不可确认')
  })
})
