import { describe, expect, it } from 'vitest'

import {
  EMPTY_BATCH_SELECTION,
  batchSelectionSummary,
  batchSkipReason,
  buildBatchSubmitBody,
  isBatchSelected,
  projectBatchOutcome,
  selectAllBatch,
  selectionAfterBatch,
  skippedBatchEntries,
  toggleBatchSelection,
} from './batchSelection'
import type { TrackingItem } from './trackingProjection'

function item(overrides: Partial<TrackingItem> = {}): TrackingItem {
  return {
    tracking_id: 'tracking-1',
    request_id: 'request-1',
    title: '测试番',
    season: 1,
    subtitle_group: '字幕组',
    poster_path: null,
    status: 'PENDING_SUBMIT',
    status_label: '待提交',
    status_group: 'PENDING',
    available_actions: [
      { code: 'SUBMIT', label: '提交', style: 'PRIMARY', requires_confirmation: true, target_scopes: [] },
    ],
    valid_resource_count: 1,
    updated_episode: null,
    updated_episode_status: 'NOT_IMPLEMENTED',
    total_episodes: null,
    revision: 2,
    updated_at: '2026-09-14T00:00:00Z',
    ...overrides,
  } as TrackingItem
}

describe('batch selection rules (issue #87)', () => {
  it('offers only server-projected submit-family rows and fails closed otherwise', () => {
    expect(batchSkipReason(item())).toBeNull()
    expect(batchSkipReason(item({
      available_actions: [
        { code: 'RETRY', label: '重试', style: 'SECONDARY', requires_confirmation: true, target_scopes: [] },
      ],
    }))).toBeNull()
    // A transient per-row state never enters a batch.
    expect(batchSkipReason(item({ status_group: 'PROCESSING' }))).toContain('正在处理中')
    // An unknown or unsupported action does not become a submit.
    expect(batchSkipReason(item({
      available_actions: [
        { code: 'MODIFY', label: '修改', style: 'SECONDARY', requires_confirmation: true, target_scopes: ['SUBSCRIPTION'] },
      ],
    }))).toContain('不可提交')
    expect(batchSkipReason(item({ available_actions: [] }))).toContain('不可提交')
  })

  it('toggles one row without disturbing the rest of the selection', () => {
    const first = toggleBatchSelection(EMPTY_BATCH_SELECTION, 'a')
    const second = toggleBatchSelection(first, 'b')
    expect(second.selected).toEqual(['a', 'b'])
    expect(isBatchSelected(second, 'a')).toBe(true)

    const removed = toggleBatchSelection(second, 'a')
    expect(removed.selected).toEqual(['b'])
    expect(isBatchSelected(removed, 'a')).toBe(false)
  })

  it('selects only the submittable rows of the current result and states the rest', () => {
    const selection = selectAllBatch([
      item({ tracking_id: 'a' }),
      item({ tracking_id: 'b', status_group: 'PROCESSING' }),
      item({ tracking_id: 'c', available_actions: [] }),
      item({
        tracking_id: 'd',
        available_actions: [
          { code: 'RETRY', label: '重试', style: 'SECONDARY', requires_confirmation: true, target_scopes: [] },
        ],
      }),
    ])

    expect(selection.selected).toEqual(['a', 'd'])
    expect(Object.keys(selection.skipped).sort()).toEqual(['b', 'c'])
    expect(selection.skipped.b).toContain('正在处理中')
    expect(selection.skipped.c).toContain('不可提交')
  })

  it('keeps hidden selections visible in the count when a filter hides them', () => {
    const selection = { selected: ['a', 'hidden'], skipped: {} }

    const summary = batchSelectionSummary(selection, [item({ tracking_id: 'a' })])

    expect(summary).toEqual({ selected: 2, hidden: 1 })
  })

  it('builds a strict body with one revision-bound opaque key per entry', () => {
    const selection = { selected: ['a', 'b', 'gone'], skipped: {} }
    const items = [
      item({ tracking_id: 'a', revision: 3 }),
      item({ tracking_id: 'b', revision: 7 }),
    ]

    const body = buildBatchSubmitBody(selection, items, {
      connection_ref: '11111111-1111-4111-8111-111111111111',
      configuration_revision: 2,
    }, 'storage')

    expect(body).not.toBeNull()
    expect(body!.confirm).toBe(true)
    expect(body!.storage_dir).toBe('storage')
    expect(body!.items.map((entry) => [entry.tracking_id, entry.expected_revision])).toEqual([
      ['a', 3], ['b', 7],
    ])
    for (const entry of body!.items) {
      expect(entry.idempotency_key).toMatch(/^[A-Za-z0-9-]{8,128}$/)
    }
    expect(body!.items[0]!.idempotency_key).not.toBe(body!.items[1]!.idempotency_key)

    // Nothing selectable means zero requests.
    expect(buildBatchSubmitBody({ selected: [], skipped: {} }, items, {
      connection_ref: '11111111-1111-4111-8111-111111111111',
      configuration_revision: 2,
    })).toBeNull()
  })

  it('projects per-entry results and never treats an unknown outcome as success', () => {
    const outcome = projectBatchOutcome({
      items: [
        {
          tracking_id: 'ok',
          ok: true,
          error_type: null,
          result: { outcome: 'ACTIVE', failure_category: null },
        },
        {
          tracking_id: 'auth',
          ok: false,
          error_type: null,
          result: { outcome: 'SUBMIT_FAILED', failure_category: 'AUTHENTICATION' },
        },
        {
          tracking_id: 'unknown',
          ok: false,
          error_type: null,
          result: { outcome: 'VERIFYING_EXTERNAL', failure_category: 'OUTCOME_UNKNOWN' },
        },
        {
          tracking_id: 'blocked',
          ok: false,
          error_type: 'tracking_revision_conflict',
          result: null,
        },
      ],
    })

    expect(outcome.succeeded).toBe(1)
    expect(outcome.failed).toBe(3)
    expect([...outcome.unresolved].sort()).toEqual(['blocked', 'unknown'])
    const byId = Object.fromEntries(outcome.entries.map((entry) => [entry.trackingId, entry]))
    expect(byId.auth!.failureCategory).toBe('AUTHENTICATION')
    expect(byId.blocked!.errorType).toBe('tracking_revision_conflict')
  })

  it('drops only the succeeded entries from the selection', () => {
    const selection = { selected: ['ok', 'auth'], skipped: {} }
    const outcome = projectBatchOutcome({
      items: [
        { tracking_id: 'ok', ok: true, result: { outcome: 'ACTIVE' } },
        { tracking_id: 'auth', ok: false, result: { outcome: 'SUBMIT_FAILED', failure_category: 'AUTHENTICATION' } },
      ],
    })

    expect(selectionAfterBatch(selection, outcome).selected).toEqual(['auth'])
  })
})

describe('skippedBatchEntries (issue #100 AC 5/6/9)', () => {
  it('lists only the selected plans the local pre-check refuses', () => {
    const submittable = {
      tracking_id: 'tracking-a', status_group: 'PENDING',
      available_actions: [{ code: 'SUBMIT', label: '提交方案', style: 'PRIMARY',
        requires_confirmation: true, target_scopes: [] }],
    } as never
    const processing = {
      tracking_id: 'tracking-b', title: '处理中番剧', status_group: 'PROCESSING',
      available_actions: [],
    } as never

    const skipped = skippedBatchEntries(
      { selected: ['tracking-a', 'tracking-b'] } as never,
      [submittable, processing],
    )

    expect(skipped).toEqual([
      { trackingId: 'tracking-b', title: '处理中番剧', reason: '正在处理中，请等待当前操作完成' },
    ])
    // A selection that is no longer in the list is reported, never dropped.
    expect(skippedBatchEntries({ selected: ['tracking-gone'] } as never, [])).toEqual([
      { trackingId: 'tracking-gone', title: '未命名番剧', reason: '不在当前列表中，请刷新后重试' },
    ])
  })
})
