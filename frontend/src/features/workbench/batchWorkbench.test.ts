import { describe, expect, it } from 'vitest'

import type { operations } from '@/api/generated/api'
import {
  batchAcceptAllConfirmCopy,
  batchAcceptAllScopeText,
  batchCandidateSelectionIsBlocked,
  batchCardAuxiliaryFacts,
  batchCardNeedsReview,
  batchCardNextStep,
  batchCardPreferenceSummary,
  batchCardSeedSummary,
  batchCardTitle,
  batchConfirmDisabledReason,
  batchItemCount,
  batchItemIsException,
  batchItemMatchesReviewFilters,
  batchSelectedConfirmCopy,
  batchSelectedScopeText,
  batchStatusLabel,
  batchSaveConfirmErrorLabel,
  batchSaveConfirmRecoveryAllowed,
  batchSaveErrorInvalidatesDraft,
  batchSaveRecoveryAction,
  batchSaveRecoveryLabel,
  batchSaveConfirmSucceeded,
  batchSaveConfirmOutcomeSummary,
  batchSaveConfirmNextFocus,
  batchSaveConfirmTrackingId,
  buildBatchSaveConfirmPayload,
  buildBatchCandidateCreatePayload,
  buildBatchParsePayload,
  canAcceptBatchCard,
  canChooseBatchCandidate,
  canExpandBatchCard,
  orderBatchItemsForReview,
  validateBatchRawInput,
  type BatchCardGuidance,
  type BatchConfirmScopeCounts,
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

describe('batch save-confirm outcome recovery (US-357)', () => {
  it('summarizes the server results together with remaining complete-batch work', () => {
    const results = [
      { item_id: 'item-a', outcome: 'CONFIRMED', request_id: 'req-a', tracking_id: 'tracking-a' },
      { item_id: 'item-b', outcome: 'FAILED', error_type: 'draft_expired' },
    ] as never
    const items = [
      batchItem({ item_id: 'item-a', status: 'DRAFT' }),
      batchItem({ item_id: 'item-b', status: 'DRAFT' }),
      batchItem({ item_id: 'item-c', status: 'DRAFT' }),
    ]
    expect(batchSaveConfirmOutcomeSummary(results, items)).toEqual({
      requested: 2,
      confirmed: 1,
      failed: 1,
      remaining: 2,
      total: 3,
    })
  })

  it('prioritizes a failed result, then the first remaining item, without choosing a hidden node', () => {
    const items = [batchItem({ item_id: 'item-a', status: 'DRAFT' }), batchItem({ item_id: 'item-b', status: 'DRAFT' })]
    expect(batchSaveConfirmNextFocus([
      { item_id: 'item-a', outcome: 'CONFIRMED', request_id: 'req-a' },
      { item_id: 'item-b', outcome: 'FAILED', error_type: 'draft_expired' },
    ] as never, items)).toEqual({ kind: 'failed', itemId: 'item-b' })
    expect(batchSaveConfirmNextFocus([
      { item_id: 'item-a', outcome: 'CONFIRMED', request_id: 'req-a' },
    ] as never, items)).toEqual({ kind: 'remaining', itemId: 'item-b' })
  })

  it('returns only a public tracking identifier for completion navigation', () => {
    expect(batchSaveConfirmTrackingId([
      { item_id: 'item-a', outcome: 'CONFIRMED', request_id: 'req-a', tracking_id: 'https://private.invalid' },
      { item_id: 'item-b', outcome: 'CONFIRMED', request_id: 'req-b', tracking_id: 'tracking-b' },
    ] as never)).toBe('tracking-b')
    expect(batchSaveConfirmTrackingId([
      { item_id: 'item-a', outcome: 'CONFIRMED', request_id: 'req-a', tracking_id: null },
    ] as never)).toBeNull()
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

describe('batch confirm-all confirm copy (US-348)', () => {
  it('states the frozen count in the title and the confirm button', () => {
    const copy = batchAcceptAllConfirmCopy({ total: 2, confirmable: 2, hidden: 0 })
    expect(copy.title).toBe('保存并确认全部 2 部')
    expect(copy.confirmLabel).toBe('保存并确认全部 2 部')
    expect(copy.message).toContain('完整批次 2 部中当前可确认 2 部')
    expect(copy.message).not.toContain('已排除')
    expect(copy.message).toContain('仅保存本地订阅方案，不会提交到 Auto Bangumi')
    expect(copy.message).toContain('外部提交需在我的追番再次确认')
  })

  it('explains hidden participants and excluded items without naming capabilities', () => {
    const copy = batchAcceptAllConfirmCopy({ total: 3, confirmable: 2, hidden: 1 })
    expect(copy.title).toBe('保存并确认全部 2 部')
    expect(copy.message).toContain('其中 1 部被筛选隐藏，仍会一并保存并确认')
    expect(copy.message).toContain('已排除 1 部未就绪、已确认或结果待核验的条目')
    expect(copy.message).not.toContain('draft')
  })

  it('never reports counts outside the batch bounds', () => {
    const copy = batchAcceptAllConfirmCopy({ total: 2, confirmable: 5, hidden: 9 })
    expect(copy.title).toBe('保存并确认全部 2 部')
    expect(copy.message).toContain('其中 2 部被筛选隐藏')
    expect(copy.message).not.toContain('已排除')
  })
})

describe('batch card default layer (US-355)', () => {
  function guidance(overrides: Partial<BatchCardGuidance> = {}): BatchCardGuidance {
    return {
      status: 'DRAFT',
      hasCandidates: false,
      hasDraft: true,
      blocker: null,
      resultUnknown: false,
      savedPendingConfirm: false,
      trackingLocated: false,
      generating: false,
      ...overrides,
    }
  }

  it('lists only on-demand auxiliary facts and never repeats the card title', () => {
    const facts = batchCardAuxiliaryFacts(
      batchItem({
        canonical_title_candidates: ['关于我转生变成史莱姆这档事 第四季', '转生史莱姆 第四季'],
        search_queries: ['转生史莱姆 第四季'],
        season_hint: 'S4',
        candidates: [{ bangumi_id: '42' }],
        status: 'DRAFT',
        preview_request: previewRequest(),
      }),
    )
    const byLabel = Object.fromEntries(facts.map((fact) => [fact.label, fact.value]))
    expect(byLabel['别名']).toBe('转生史莱姆 第四季')
    expect(byLabel['别名']).not.toContain('关于我转生变成史莱姆这档事 第四季')
    expect(byLabel['检索关键词']).toBe('转生史莱姆 第四季')
    expect(byLabel['季数提示']).toBe('S4')
    expect(byLabel['候选合集']).toBe('1 个')
    expect(byLabel['偏好']).toBe('未配置偏好，使用默认流程')
    expect(byLabel['总集数']).toBe('未知')
    expect(batchCardAuxiliaryFacts(batchItem())).toEqual([
      { label: '检索关键词', value: '转生史莱姆 第四季' },
      { label: '季数提示', value: 'S4' },
      { label: '偏好', value: '未配置偏好，使用默认流程' },
      { label: '总集数', value: '未知' },
    ])
  })

  it('names exactly one next step for every actionable card state', () => {
    expect(batchCardNextStep(guidance({ generating: true }))).toContain('等待当前候选')
    expect(batchCardNextStep(guidance({ resultUnknown: true }))).toContain('使用相同操作重试')
    expect(batchCardNextStep(guidance({ status: 'RESPONSE_UNKNOWN', hasDraft: false }))).toContain('重试定位')
    expect(batchCardNextStep(guidance({ savedPendingConfirm: true }))).toContain('重试确认')
    expect(batchCardNextStep(guidance({ status: 'SAVED_PENDING_CONFIRM' }))).toContain('不会重复保存')
    expect(batchCardNextStep(guidance({ status: 'CONFIRMED', trackingLocated: true, hasDraft: false }))).toContain('我的追番')
    expect(batchCardNextStep(guidance({ status: 'CONFIRMED', hasDraft: false }))).toContain('重试定位')
    expect(batchCardNextStep(guidance({ status: 'FAILED', blocker: '需先生成可审核草案', hasDraft: false }))).toContain('删除该条目')
    expect(batchCardNextStep(guidance({ status: 'EMPTY', blocker: '需先生成可审核草案', hasDraft: false }))).toContain('更完整的名称')
    expect(batchCardNextStep(guidance({ hasCandidates: true, hasDraft: false, blocker: '需先生成可审核草案' })))
      .toBe('在右栏选择真实 MiKan 合集生成草案。')
    expect(batchCardNextStep(guidance({ blocker: '有尚未应用的编辑' }))).toBe('先解决：有尚未应用的编辑。')
    expect(batchCardNextStep(guidance())).toContain('保存并确认全部')
    expect(batchCardNextStep(guidance({ hasDraft: false }))).toContain('重新获取批量草案')
  })
})

// Stage 45 / WP-45-B / US-356: N 部（手工勾选且有资格）与确认全部的两种范围必须由
// 同一份计数派生；两入口的可见禁用原因常驻，不依赖 title。
describe('batch N-part selection scope (US-356)', () => {
  const scope = (overrides: Partial<BatchConfirmScopeCounts> = {}): BatchConfirmScopeCounts => ({
    total: 3,
    visible: 2,
    selected: 2,
    selectedHidden: 1,
    selectedExcluded: 0,
    confirmable: 3,
    hidden: 1,
    needsProcessing: 0,
    ...overrides,
  })

  it('states the checked-and-eligible complete-batch range with hidden participants', () => {
    expect(batchSelectedScopeText(scope())).toBe(
      '保存并确认 2 部来自完整批次 3 部中已勾选且当前可确认的条目，其中 1 部当前被筛选隐藏、仍会一并保存；筛选与可见全选不改变本集合。',
    )
    expect(batchSelectedScopeText(scope({ selectedHidden: 0, hidden: 0 }))).toBe(
      '保存并确认 2 部来自完整批次 3 部中已勾选且当前可确认的条目；筛选与可见全选不改变本集合。',
    )
  })

  it('states a visible reason when nothing checked can be confirmed', () => {
    expect(batchSelectedScopeText(scope({ selected: 0, selectedHidden: 0 }))).toContain('请先在卡片上勾选')
    expect(batchSelectedScopeText(scope({ selected: 0, selectedHidden: 0, selectedExcluded: 2 }))).toContain(
      '已勾选但当前不可确认的 2 部被排除',
    )
    expect(batchSelectedScopeText(scope({ total: 0, visible: 0, selected: 0, confirmable: 0, selectedHidden: 0 }))).toBe('')
  })

  it('never reports counts outside the batch bounds', () => {
    const clamped = batchSelectedScopeText(scope({ total: 2, selected: 9, selectedHidden: 9, selectedExcluded: 9 }))
    expect(clamped).toContain('保存并确认 2 部')
    expect(clamped).toContain('其中 2 部当前被筛选隐藏')
    expect(clamped).not.toContain('9')
  })

  it('names the frozen N count in the title, the safety list and the confirm button', () => {
    const copy = batchSelectedConfirmCopy(scope(), ['甲 第一季', '乙 第一季'])
    expect(copy.title).toBe('保存并确认 2 部')
    expect(copy.confirmLabel).toBe('保存并确认 2 部')
    expect(copy.items).toEqual(['甲 第一季', '乙 第一季'])
    expect(copy.itemsLabel).toBe('本次将保存并确认的 2 部')
    expect(copy.message).toContain('完整批次 3 部中已勾选且当前可确认的 2 部')
    expect(copy.message).toContain('其中 1 部被筛选隐藏，仍会一并保存并确认')
    expect(copy.message).toContain('仅保存本地订阅方案，不会提交到 Auto Bangumi')
    expect(copy.message).toContain('外部提交需在我的追番再次确认')
    expect(copy.message).not.toContain('draft')
  })

  it('states the exclusions of the N scope without naming capabilities', () => {
    const copy = batchSelectedConfirmCopy(scope({ selectedExcluded: 1, selected: 1, selectedHidden: 0 }), ['甲 第一季'])
    expect(copy.title).toBe('保存并确认 1 部')
    expect(copy.message).toContain('已勾选但当前不可确认的 1 部被排除')
    expect(copy.items).toEqual(['甲 第一季'])
  })

  it('lists the same frozen set as the confirm-all safety list', () => {
    const copy = batchAcceptAllConfirmCopy({ total: 3, confirmable: 2, hidden: 1 }, ['甲 第一季', '乙 第一季'])
    expect(copy.items).toEqual(['甲 第一季', '乙 第一季'])
    expect(copy.itemsLabel).toBe('本次将保存并确认的 2 部')
  })
})

describe('batch confirm disabled reasons (US-356)', () => {
  it('always explains a disabled entry with persistent copy instead of a title', () => {
    expect(batchConfirmDisabledReason({ saving: false, pendingVerification: false })).toBe('')
    expect(batchConfirmDisabledReason({ saving: true, pendingVerification: false })).toContain('正在保存确认')
    expect(batchConfirmDisabledReason({ saving: false, pendingVerification: true })).toContain('待核验')
    expect(batchConfirmDisabledReason({ saving: true, pendingVerification: true })).toContain('待核验')
  })
})

describe('batch save recovery actions (Issue 114)', () => {
  it('projects one exact recovery action per real outcome', () => {
    // 已保存但确认未完成：只允许重试确认。
    expect(batchSaveRecoveryAction({ status: 'SAVED_PENDING_CONFIRM' })).toBe('RETRY_CONFIRM')
    // 响应未知：先核验，不给普通重试保存。
    expect(batchSaveRecoveryAction({ status: 'RESPONSE_UNKNOWN' })).toBe('VERIFY_RESULT')
    // 草案失效／版本冲突：重新生成草案（draft_replayed 是「已保存」，不在此列）。
    for (const errorType of ['draft_expired', 'draft_evicted', 'draft_revision_conflict']) {
      expect(batchSaveRecoveryAction({ status: 'FOUND', errorType })).toBe('REGENERATE_DRAFT')
    }
    // 可再次保存的普通失败：重试保存。
    expect(batchSaveRecoveryAction({ status: 'DRAFT', errorType: 'save_confirm_failed' })).toBe('RETRY_SAVE')
    expect(batchSaveRecoveryAction({ status: 'DRAFT', errorType: 'storage_error' })).toBe('RETRY_SAVE')
  })

  it('fails closed when the outcome is unknown or already terminal', () => {
    expect(batchSaveRecoveryAction({ status: 'DRAFT' })).toBe('NONE')
    expect(batchSaveRecoveryAction({ status: '' })).toBe('NONE')
    // 已确认但还没定位到追番记录：只允许重试定位；定位到之后没有恢复动作。
    expect(batchSaveRecoveryAction({ status: 'CONFIRMED', trackingLocated: false })).toBe('VERIFY_RESULT')
    expect(batchSaveRecoveryAction({ status: 'CONFIRMED', trackingLocated: true })).toBe('NONE')
  })

  it('gives each action its fixed Chinese label, with no unified retry copy', () => {
    expect(batchSaveRecoveryLabel('RETRY_CONFIRM')).toBe('重试确认')
    expect(batchSaveRecoveryLabel('REGENERATE_DRAFT')).toBe('重新生成草案')
    expect(batchSaveRecoveryLabel('RETRY_SAVE')).toBe('重试保存')
    expect(batchSaveRecoveryLabel('VERIFY_RESULT')).toBe('重试定位')
    expect(batchSaveRecoveryLabel('NONE')).toBe('')
    const labels = new Set([
      batchSaveRecoveryLabel('RETRY_CONFIRM'),
      batchSaveRecoveryLabel('REGENERATE_DRAFT'),
      batchSaveRecoveryLabel('RETRY_SAVE'),
    ])
    expect(labels.size).toBe(3)
    expect([...labels].some((label) => label.includes('重试失败'))).toBe(false)
  })

  it('flags only the draft-invalidating failures', () => {
    expect(batchSaveErrorInvalidatesDraft('draft_expired')).toBe(true)
    expect(batchSaveErrorInvalidatesDraft('draft_revision_conflict')).toBe(true)
    expect(batchSaveErrorInvalidatesDraft('save_confirm_failed')).toBe(false)
    expect(batchSaveErrorInvalidatesDraft(null)).toBe(false)
    // Issue 130：draft_replayed 表示草案已经保存，不是失效，绝不能引导重新生成。
    expect(batchSaveErrorInvalidatesDraft('draft_replayed')).toBe(false)
  })

  it('freezes a replayed draft as already saved without a retry entry (Issue 130)', () => {
    // 已保存是确定事实；待核验的是确认与定位状态。
    expect(batchSaveRecoveryAction({ status: 'FOUND', errorType: 'draft_replayed' })).toBe('LOCATE_SAVED')
    expect(batchSaveRecoveryAction({ status: 'DRAFT', errorType: 'draft_replayed' })).toBe('LOCATE_SAVED')
    expect(batchSaveRecoveryLabel('LOCATE_SAVED')).toBe('已保存，待定位')
    // 它不给「重新生成草案」「重试保存」，也不伪装成普通未知结果。
    expect(batchSaveRecoveryAction({ status: 'FOUND', errorType: 'draft_replayed' })).not.toBe(
      'REGENERATE_DRAFT',
    )
    expect(batchSaveRecoveryAction({ status: 'FOUND', errorType: 'draft_replayed' })).not.toBe('RETRY_SAVE')
    expect(batchSaveRecoveryAction({ status: 'RESPONSE_UNKNOWN' })).toBe('VERIFY_RESULT')
  })
})
