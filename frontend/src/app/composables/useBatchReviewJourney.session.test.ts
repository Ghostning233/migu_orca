import { computed, ref } from 'vue'
import { describe, expect, it } from 'vitest'

import {
  useBatchReviewJourney,
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

/** #162：假工厂，记录句柄的创建、失效与销毁；不碰 IO。 */
function fakeDraftPorts() {
  const created = { sessions: [] as string[], schedulers: [] as string[] }
  const sessions: Array<Record<string, unknown>> = []
  const schedulers: Array<Record<string, unknown>> = []
  const ports = {
    createSession: (facts: { itemId: string; draftId: string }) => {
      created.sessions.push(`${facts.itemId}:${facts.draftId}`)
      const session = {
        draftId: ref<string | null>(facts.draftId),
        draftRevision: ref<number | null>(1),
        dirty: ref(false),
        applying: ref(false),
        invalid: ref(false),
        error: ref<unknown>(null),
        canRetry: computed(() => false),
        invalidated: 0,
        invalidate() {
          session.invalidated += 1
          session.invalid.value = true
          session.draftId.value = null
        },
      }
      sessions.push(session)
      return session
    },
    createScheduler: (facts: { itemId: string }) => {
      created.schedulers.push(facts.itemId)
      const scheduler = {
        waiting: ref(false),
        folderPending: computed(() => false),
        groupPending: computed(() => false),
        disposed: 0,
        cancelled: 0,
        dropped: 0,
        dispose() { scheduler.disposed += 1 },
        cancelTimer() { scheduler.cancelled += 1 },
        dropPending() { scheduler.dropped += 1 },
      }
      schedulers.push(scheduler)
      return scheduler
    },
  }
  return { ports, created, sessions, schedulers }
}

const draftFacts = (itemId: string, draftId: string) => ({ itemId, draftId, draftRevision: 1, source: null })

describe('useBatchReviewJourney draft handle ownership (#162)', () => {
  it('creates one session and one scheduler per item and draft identity', () => {
    const fake = fakeDraftPorts()
    const session = useBatchReviewJourney('', fake.ports)
    session.finishParse(parsed([draftItem('a')]))

    const first = session.ensureDraftSession(draftFacts('a', 'draft-a'))
    const again = session.ensureDraftSession(draftFacts('a', 'draft-a'))
    const scheduler = session.ensureScheduler(draftFacts('a', 'draft-a'))
    const schedulerAgain = session.ensureScheduler(draftFacts('a', 'draft-a'))

    expect(again).toBe(first)
    expect(schedulerAgain).toBe(scheduler)
    expect(fake.created.sessions).toEqual(['a:draft-a'])
    expect(fake.created.schedulers).toEqual(['a'])
  })

  it('replaces the session and disposes the scheduler when the draft identity changes', () => {
    const fake = fakeDraftPorts()
    const session = useBatchReviewJourney('', fake.ports)
    session.finishParse(parsed([draftItem('a')]))

    const first = session.ensureDraftSession(draftFacts('a', 'draft-a'))
    session.ensureScheduler(draftFacts('a', 'draft-a'))
    const second = session.ensureDraftSession(draftFacts('a', 'draft-b'))
    const nextScheduler = session.ensureScheduler(draftFacts('a', 'draft-b'))

    expect(second).not.toBe(first)
    expect(fake.created.sessions).toEqual(['a:draft-a', 'a:draft-b'])
    expect(fake.created.schedulers).toEqual(['a', 'a'])
    expect(fake.schedulers[0]?.disposed).toBe(1)
    expect(fake.schedulers[1]?.disposed).toBe(0)
    expect(nextScheduler).toBe(fake.schedulers[1])
    // 被替换的会话不主动作废：它只是从 Map 里消失（与旧实现一致）。
    expect(fake.sessions[0]?.invalidated).toBe(0)
  })

  it('publishes the save-gate facts from the live handles', () => {
    const fake = fakeDraftPorts()
    const session = useBatchReviewJourney('', fake.ports)
    session.finishParse(parsed([draftItem('a')]))
    session.ensureScheduler(draftFacts('a', 'draft-a'))

    expect(session.snapshot.value.drafts.a).toEqual({
      draftId: 'draft-a',
      draftRevision: 1,
      invalid: false,
      dirty: false,
      applying: false,
      hasError: false,
      canRetry: false,
      waiting: false,
      folderPending: false,
      groupPending: false,
    })

    const sessionHandle = fake.sessions[0] as {
      dirty: { value: boolean }
      error: { value: unknown }
    }
    const schedulerHandle = fake.schedulers[0] as { waiting: { value: boolean } }
    sessionHandle.dirty.value = true
    schedulerHandle.waiting.value = true
    sessionHandle.error.value = { type: 'network_error' }
    expect(session.snapshot.value.drafts.a).toMatchObject({ dirty: true, waiting: true, hasError: true })
  })

  it('invalidateItemResources is the single death of an item\'s handles', () => {
    const fake = fakeDraftPorts()
    const session = useBatchReviewJourney('', fake.ports)
    session.finishParse(parsed([draftItem('a'), draftItem('b')]))
    session.ensureScheduler(draftFacts('a', 'draft-a'))
    session.ensureScheduler(draftFacts('b', 'draft-b'))

    session.invalidateItemResources('a')

    expect(fake.schedulers[0]?.disposed).toBe(1)
    expect(fake.sessions[0]?.invalidated).toBe(1)
    expect(fake.schedulers[1]?.disposed).toBe(0)
    expect(session.snapshot.value.drafts.a).toBeUndefined()
    expect(session.snapshot.value.drafts.b).toBeDefined()
    // 失效后重新进入该条目会拿到全新句柄。
    expect(session.ensureDraftSession(draftFacts('a', 'draft-a'))).not.toBe(fake.sessions[0])
  })

  it('route cleanup disposes every scheduler and invalidates every session', () => {
    const fake = fakeDraftPorts()
    const session = useBatchReviewJourney('', fake.ports)
    session.finishParse(parsed([draftItem('a'), draftItem('b')]))
    session.ensureScheduler(draftFacts('a', 'draft-a'))
    session.ensureScheduler(draftFacts('b', 'draft-b'))

    session.invalidateAllItemResources()

    expect(fake.schedulers.map((scheduler) => (scheduler as { disposed: number }).disposed)).toEqual([1, 1])
    expect(fake.sessions.map((entry) => (entry as { invalidated: number }).invalidated)).toEqual([1, 1])
    expect(session.snapshot.value.drafts).toEqual({})
  })

  it('unmount only stops the timers and keeps the sessions', () => {
    const fake = fakeDraftPorts()
    const session = useBatchReviewJourney('', fake.ports)
    session.finishParse(parsed([draftItem('a')]))
    session.ensureScheduler(draftFacts('a', 'draft-a'))

    session.disposeAllSchedulers()

    expect(fake.schedulers[0]?.disposed).toBe(1)
    expect(fake.sessions[0]?.invalidated).toBe(0)
    expect(session.snapshot.value.drafts.a).toBeDefined()
  })

  it('leaving an item drops its unapplied intent without touching the session', () => {
    const fake = fakeDraftPorts()
    const session = useBatchReviewJourney('', fake.ports)
    session.finishParse(parsed([draftItem('a')]))
    session.ensureScheduler(draftFacts('a', 'draft-a'))

    session.releaseItemEditing('a')

    expect(fake.schedulers[0]?.cancelled).toBe(1)
    expect(fake.schedulers[0]?.dropped).toBe(1)
    expect(fake.schedulers[0]?.disposed).toBe(0)
    expect(session.snapshot.value.drafts.a).toBeDefined()
  })

  it('without ports the handle commands stay inert', () => {
    const session = useBatchReviewJourney()
    session.finishParse(parsed([draftItem('a')]))
    expect(session.ensureDraftSession(draftFacts('a', 'draft-a'))).toBeNull()
    expect(session.ensureScheduler(draftFacts('a', 'draft-a'))).toBeNull()
    expect(session.snapshot.value.drafts).toEqual({})
  })
})
