import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'

import { flushPromises, mount } from '@vue/test-utils'
import { createPinia } from 'pinia'
import { createMemoryHistory, createRouter } from 'vue-router'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { api } from '@/api/client'
import TrackingView from './TrackingView.vue'

vi.mock('@/api/client', () => ({ api: { get: vi.fn(), post: vi.fn() }, toApiError: (e: unknown) => e }))
const apiGet = vi.mocked(api.get)
const apiPost = vi.mocked(api.post)

const caps = {
  probe_status: 'VERIFIED', version: '3.1.18', adapter: 'legacy_3_1',
  subscription_list: 'SUPPORTED', subscription_detail: 'SUPPORTED', subscription_submit: 'SUPPORTED',
  subscription_modify: 'SUPPORTED', subscription_enable: 'SUPPORTED', subscription_disable: 'SUPPORTED',
  subscription_delete: 'SUPPORTED', rss_list: 'SUPPORTED', rss_modify: 'SUPPORTED', rss_enable: 'SUPPORTED',
  rss_disable: 'SUPPORTED', rss_delete: 'SUPPORTED', rss_refresh: 'SUPPORTED', external_verify: 'SUPPORTED',
  checked_at: null, safe_message: null,
}
function row(actions: unknown[] = [], posterPath: string | null = null) {
  return { tracking_id: 'tracking-1', request_id: 'request-1', title: '测试番', season: 1,
    subtitle_group: '字幕组', poster_path: posterPath, status: 'PENDING_SUBMIT', status_label: '待提交',
    status_group: 'PENDING', available_actions: actions, valid_resource_count: 1, updated_episode: null,
    updated_episode_status: 'NOT_IMPLEMENTED', total_episodes: null, revision: 1,
    updated_at: '2026-09-14T00:00:00Z' }
}
const defaultSummary = {
  total: 1, pending: 1, processing: 0, active: 0, added_to_download: 0,
  inactive: 0, needs_attention: 0, unreadable: 0,
}
/** Issue #224 A7: the server publishes the group vocabulary and its counts. */
const GROUP_LABELS = {
  PENDING: '待处理', PROCESSING: '处理中', ACTIVE: '追番中',
  ATTENTION: '需处理', INACTIVE: '已停用',
} as const
const CARD_GROUPS = new Set(['PENDING', 'ACTIVE', 'ATTENTION', 'INACTIVE'])
function statusGroups(counts: Partial<Record<keyof typeof GROUP_LABELS, number>> = { PENDING: 1 }) {
  return (Object.keys(GROUP_LABELS) as (keyof typeof GROUP_LABELS)[]).map((group) => ({
    group, label: GROUP_LABELS[group], count: counts[group] ?? 0,
    has_overview_card: CARD_GROUPS.has(group),
  }))
}
async function mountSaved(
  actions: unknown[] = [],
  posterPath: string | null = null,
  summary: Record<string, number> = defaultSummary,
  rows?: unknown[],
  groups: unknown = statusGroups(),
) {
  const router = createRouter({ history: createMemoryHistory('/app/'), routes: [
    { path: '/tracking', component: TrackingView },
  ] })
  await router.push('/tracking'); await router.isReady()
  apiGet.mockImplementation(async (path) => path === '/api/v1/settings/autobangumi'
    ? { configured: true, credential_present: true, connection_ref: '11111111-1111-4111-8111-111111111111', configuration_revision: 3, connection_status: 'CONFIGURED', capabilities: null }
    : { items: rows ?? [row(actions, posterPath)], summary, status_groups: groups, warnings: [] })
  // #229: the page syncs once on entry; unless a test installs its own result
  // the fixture echoes the same rows so an unrelated test keeps its data and
  // its payload shape.
  const fixture = nextSyncFixture ?? syncResult({
    summary: { ...UNCHANGED_SUMMARY, checked: (rows ?? [row(actions, posterPath)]).length },
    items: rows ?? [row(actions, posterPath)],
  })
  nextSyncFixture = null
  answerSyncOnce(fixture)
  const wrapper = mount(TrackingView, { attachTo: document.body, global: { plugins: [createPinia(), router], stubs: { Teleport: true } } })
  await flushPromises()
  return { wrapper, router }
}
const REF = '11111111-1111-4111-8111-111111111111'
const UNCHANGED_SUMMARY = { checked: 1, created: 0, updated: 0, unchanged: 1, ignored: 0, failed: 0, unreadable: 0 }
/** T6 (#229): one read-only sync runs when the page is entered. */
function syncResult(overrides: Record<string, unknown> = {}) {
  return {
    sync_status: 'COMPLETE', checked_at: '2026-10-21T00:00:00Z', capabilities: caps,
    summary: { ...UNCHANGED_SUMMARY }, warnings: [], items: [row()],
    ...overrides,
  } as never
}
/**
 * Answer the page-entry sync and refuse every other POST, so a test proves the
 * entry itself never turns into a write (AC3 on the frontend side).
 */
const unexpectedPosts: string[] = []
function answerSyncOnce(result: unknown = syncResult()) {
  unexpectedPosts.length = 0
  apiPost.mockImplementation(async (path: string) => {
    if (path === '/api/v1/tracking/sync') return result as never
    // Recorded so the test can prove the entry never became a write; the throw
    // alone would just be swallowed by the session's fixed failure copy.
    unexpectedPosts.push(path)
    throw new Error(`unexpected POST ${path}`)
  })
}
function syncCalls() {
  return apiPost.mock.calls.filter((call) => call[0] === '/api/v1/tracking/sync')
}
/**
 * One-shot override for the page-entry sync used by `mountSaved`. It is stored
 * outside the mount helpers so a sync-specific test reads as a single line.
 */
let nextSyncFixture: unknown = null
function useSyncFixture(result: unknown) {
  nextSyncFixture = result
}

function rowFor(
  trackingId: string,
  title: string,
  actions: unknown[] = [
    { code: 'SUBMIT', label: '提交', style: 'PRIMARY', requires_confirmation: true, target_scopes: [] },
  ],
  statusGroup = 'PENDING',
) {
  return {
    ...row(actions),
    tracking_id: trackingId,
    request_id: `request-${trackingId}`,
    title,
    status_group: statusGroup,
  }
}

describe('TrackingView page skeleton and row model (#225)', () => {
  it('registers the five row geometry aliases in the shared token file', () => {
    const tokens = readFileSync(resolve(process.cwd(), 'src/styles/tokens.css'), 'utf8')
    expect(tokens).toContain('--tracking-poster-width: calc(var(--space-10) + var(--space-5))')
    expect(tokens).toContain('--tracking-poster-height: calc(var(--tracking-poster-width) * 1.5)')
    expect(tokens).toContain(
      '--tracking-row-min-height: calc(\n    var(--tracking-poster-height) + 2 * var(--space-3) + var(--control-border-width)\n  )',
    )
    expect(tokens).toContain('--tracking-search-min-width: calc(4 * var(--space-10))')
    expect(tokens).toContain('--tracking-search-width: calc(6 * var(--space-10))')
    // No new colour or interaction-state token came with the row spec.
    expect(tokens.match(/--tracking-[a-z-]+:/g)?.sort()).toEqual([
      '--tracking-poster-height:',
      '--tracking-poster-width:',
      '--tracking-row-min-height:',
      '--tracking-search-min-width:',
      '--tracking-search-width:',
    ])
  })

  beforeEach(() => { apiGet.mockReset(); apiPost.mockReset(); nextSyncFixture = null })

  it('adopts the summary capability projection without probing (#225 B1)', async () => {
    const router = createRouter({ history: createMemoryHistory('/app/'), routes: [
      { path: '/tracking', component: TrackingView },
    ] })
    await router.push('/tracking'); await router.isReady()
    apiGet.mockImplementation(async (path) => path === '/api/v1/settings/autobangumi'
      ? {
          configured: true, credential_present: true,
          connection_ref: '11111111-1111-4111-8111-111111111111',
          configuration_revision: 3, connection_status: 'VERIFIED', capabilities: caps,
        }
      : { items: [row()], summary: defaultSummary, status_groups: statusGroups(), warnings: [] })
    answerSyncOnce()
    const wrapper = mount(TrackingView, { attachTo: document.body, global: { plugins: [createPinia(), router], stubs: { Teleport: true } } })
    await flushPromises()

    // Stage 39: loading the page never probes by itself; the published summary
    // is the only capability source, and it is not rendered as a module. #229
    // replaces the manual entry with exactly one automatic read-only sync.
    expect(apiPost.mock.calls.map((call) => call[0])).toEqual(['/api/v1/tracking/sync'])
    expect(wrapper.find('#tracking-probe-saved').exists()).toBe(false)
    expect(wrapper.find('.tracking-connection-status').exists()).toBe(false)
    expect(wrapper.find('#tracking-capability-summary').exists()).toBe(false)
  })

  it('does not probe when no connection is saved', async () => {
    const router = createRouter({ history: createMemoryHistory('/app/'), routes: [
      { path: '/tracking', component: TrackingView },
    ] })
    await router.push('/tracking'); await router.isReady()
    apiGet.mockImplementation(async (path) => path === '/api/v1/settings/autobangumi'
      ? { configured: false, credential_present: false, connection_ref: null, configuration_revision: 0, connection_status: 'UNCONFIGURED', capabilities: null }
      : { items: [row()], summary: defaultSummary, status_groups: statusGroups(), warnings: [] })
    const wrapper = mount(TrackingView, { attachTo: document.body, global: { plugins: [createPinia(), router], stubs: { Teleport: true } } })
    await flushPromises()

    expect(apiPost).not.toHaveBeenCalled()
    expect(wrapper.find('#tracking-sync').exists()).toBe(false)
  })

  it('retires the header card and the old toolbar entries (#225 B1/C5)', async () => {
    const { wrapper } = await mountSaved()

    expect(wrapper.find('.tracking-header').exists()).toBe(false)
    expect(wrapper.find('#tracking-probe-saved').exists()).toBe(false)
    expect(wrapper.find('#tracking-refresh').exists()).toBe(false)
    expect(wrapper.find('#tracking-status-filter').exists()).toBe(false)
    expect(wrapper.find('#tracking-all').exists()).toBe(false)
    // The status overview is the only filter entry; the page title is the page
    // header, not a panel heading.
    expect(wrapper.find('#tracking-heading').element.tagName).toBe('H1')
    expect(wrapper.find('.tracking-list-heading').text()).toBe('追番列表')
    // #229 F1: the manual sync entry is retired with its confirmation dialog.
    expect(wrapper.find('#tracking-sync').exists()).toBe(false)
  })

  it('renders the persisted same-origin cover for a listed record', async () => {
    const cover = `/api/v1/mikan/posters/${'a'.repeat(64)}`
    const { wrapper } = await mountSaved([], cover)

    const poster = wrapper.find('.tracking-list-item .tracking-poster')
    expect(poster.attributes('data-poster-state')).toBe('ready')
    expect(poster.find('img').attributes('src')).toBe(cover)
    expect(wrapper.html()).not.toContain('mikan.example')
  })

  it('falls back to the placeholder when a listed record has no cover', async () => {
    const { wrapper } = await mountSaved()

    const poster = wrapper.find('.tracking-list-item .tracking-poster')
    expect(poster.attributes('data-poster-state')).toBe('placeholder')
    expect(poster.find('img').exists()).toBe(false)
  })

  it('renders exactly the four server-owned cards with authoritative counts (#224 A2)', async () => {
    const { wrapper } = await mountSaved([], null, {
      total: 9, pending: 4, processing: 2, active: 2, added_to_download: 1,
      inactive: 1, needs_attention: 1, unreadable: 1,
    }, undefined, statusGroups({ PENDING: 4, PROCESSING: 2, ACTIVE: 3, ATTENTION: 1, INACTIVE: 1 }))

    expect(wrapper.text()).toContain('我的追番')
    expect(wrapper.text()).toContain('管理待提交任务和正在运行的追番')
    const cards = wrapper.findAll('.tracking-status-card')
    // 追番中 includes 已加入下载; 需处理 includes 外部已删除. 处理中 has no card.
    expect(cards.map((card) => card.text())).toEqual([
      '待处理4', '追番中3', '需处理1', '已停用1',
    ])
    // The single legit "正在追番" copy is gone from the whole page.
    expect(wrapper.html()).not.toContain('正在追番')
    expect(wrapper.find('.tracking-list-count').text()).toBe('共 9 部')
  })

  it('runs the entry sync once and re-reads the authoritative counts (#224 A5/#229)', async () => {
    const router = createRouter({ history: createMemoryHistory('/app/'), routes: [
      { path: '/tracking', component: TrackingView },
    ] })
    await router.push('/tracking'); await router.isReady()
    let listReads = 0
    apiGet.mockImplementation(async (path) => {
      if (path === '/api/v1/settings/autobangumi') {
        return {
          configured: true, credential_present: true,
          connection_ref: '11111111-1111-4111-8111-111111111111',
          configuration_revision: 3, connection_status: 'CONFIGURED', capabilities: null,
        }
      }
      listReads += 1
      // The sync changed the record's category, so only a second server read
      // can state the new authoritative counts.
      return listReads === 1
        ? {
            items: [rowFor('a', '番 A')],
            summary: { ...defaultSummary, total: 1, pending: 1 },
            status_groups: statusGroups({ PENDING: 1 }), warnings: [],
          }
        : {
            items: [rowFor('a', '番 A', [], 'ACTIVE')],
            summary: { ...defaultSummary, total: 1, active: 1 },
            status_groups: statusGroups({ ACTIVE: 1 }), warnings: [],
          }
    })
    answerSyncOnce(syncResult({
      summary: { checked: 1, created: 0, updated: 1, unchanged: 0, ignored: 0, failed: 0, unreadable: 0 },
      items: [rowFor('a', '番 A', [], 'ACTIVE')],
    }))
    const wrapper = mount(TrackingView, {
      attachTo: document.body,
      global: { plugins: [createPinia(), router], stubs: { Teleport: true } },
    })
    await flushPromises()

    // #229 F1: entering the page is the trigger — exactly one read-only sync,
    // with no confirmation dialog in front of it.
    expect(syncCalls()).toHaveLength(1)
    expect(wrapper.find('.confirm-dialog').exists()).toBe(false)
    expect(syncCalls()[0]![1]).toMatchObject({
      body: { connection_ref: '11111111-1111-4111-8111-111111111111', configuration_revision: 3, confirm: true },
    })

    // The rows changed category, so the page must state the re-read server
    // projection: nothing in the sync response or the row convergence carries
    // the card metadata, so only a second list read can explain the new counts.
    expect(listReads).toBeGreaterThan(1)
    expect(wrapper.findAll('.tracking-status-card').map((card) => card.text())).toEqual([
      '待处理0', '追番中1', '需处理0', '已停用0',
    ])
  })

  it('clicking a card clears the search box and keeps the card count authoritative (#224 A5)', async () => {
    const rows = [
      rowFor('a', '芙莉莲'),
      rowFor('b', '咒术回战', [], 'ACTIVE'),
      rowFor('c', '已加入下载番', [], 'ACTIVE'),
      rowFor('d', '已停用番', [], 'INACTIVE'),
      {
        ...rowFor('e', '仅外部番', [], 'INACTIVE'),
        status: 'EXTERNAL_ONLY',
        status_label: '仅外部',
      },
    ]
    const { wrapper } = await mountSaved(
      [], null,
      { ...defaultSummary, total: 5, pending: 1, active: 2, inactive: 1 },
      rows,
      statusGroups({ PENDING: 1, ACTIVE: 2, INACTIVE: 1 }),
    )

    // 全部 keeps the retired archive visible with its real label.
    expect(wrapper.findAll('.tracking-list-row')).toHaveLength(5)
    expect(wrapper.text()).toContain('仅外部')
    expect(wrapper.find('.tracking-list-count').text()).toBe('共 5 部')

    // 追番中 card: rows == server card count without a search condition.
    await wrapper.findAll('.tracking-status-card')[1]!.trigger('click')
    await flushPromises()
    expect(wrapper.findAll('.tracking-list-row')).toHaveLength(2)
    expect(wrapper.find('.tracking-list-count').text()).toBe('共 2 部')

    // A search narrows the rows but never the authoritative card count.
    await wrapper.find('#tracking-search').setValue('咒术')
    await flushPromises()
    expect(wrapper.findAll('.tracking-list-row')).toHaveLength(1)
    expect(wrapper.find('.tracking-list-count').text()).toBe('筛选出 1 部 · 共 2 部')

    // Clicking another card clears the search box (user decision, A5).
    await wrapper.findAll('.tracking-status-card')[3]!.trigger('click')
    await flushPromises()
    expect((wrapper.find('#tracking-search').element as HTMLInputElement).value).toBe('')
    // The retired EXTERNAL_ONLY archive never joins the 已停用 card.
    expect(wrapper.findAll('.tracking-list-row')).toHaveLength(1)
    expect(wrapper.find('.tracking-list-count').text()).toBe('共 1 部')
  })

  it('renders each row as two sibling buttons with only the five fixed elements', async () => {
    const { wrapper } = await mountSaved()
    const row = wrapper.find('.tracking-list-row')
    const buttons = row.findAll('button')

    expect(buttons).toHaveLength(2)
    expect(buttons[0]!.classes()).toContain('tracking-list-item')
    expect(buttons[1]!.classes()).toContain('tracking-list-arrow')
    // Siblings never nested: the body button contains no second button.
    expect(buttons[0]!.findAll('button')).toHaveLength(0)
    expect(buttons[0]!.find('.tracking-poster').exists()).toBe(true)
    expect(buttons[0]!.find('.tracking-list-title').text()).toBe('测试番')
    expect(buttons[0]!.find('.tracking-list-season').text()).toBe('第 1 季')
    expect(buttons[0]!.find('.tracking-status-pill').text()).toBe('待提交')
    expect(buttons[1]!.find('.tracking-list-chevron').exists()).toBe(true)
    // No checkbox/selection column, submission mode, timestamp or legacy bar.
    expect(wrapper.find('input[type="checkbox"]').exists()).toBe(false)
    expect(wrapper.find('.tracking-list-mode').exists()).toBe(false)
    expect(wrapper.find('.tracking-list-indicator').exists()).toBe(false)
    expect(row.text()).not.toMatch(/\d{4}-\d{2}-\d{2}/)
  })

  it('never puts the arrow in the tab order and keeps the row body as the keyboard path', async () => {
    const { wrapper } = await mountSaved()
    const arrow = wrapper.find('.tracking-list-arrow')
    const body = wrapper.find('.tracking-list-item')

    expect(arrow.attributes('tabindex')).toBe('-1')
    expect(arrow.attributes('aria-hidden')).toBe('true')
    expect(body.attributes('tabindex')).toBeUndefined()
    expect(body.attributes('aria-current')).toBeUndefined()
  })

  it('maps each exact status to the documented pill tone', async () => {
    const rows = [
      { ...rowFor('a', 'A'), status: 'ACTIVE', status_label: '追番中' },
      { ...rowFor('b', 'B'), status: 'SUBMIT_FAILED', status_label: '提交失败' },
      { ...rowFor('c', 'C'), status: 'RECOVERY_REQUIRED', status_label: '需要恢复' },
      { ...rowFor('d', 'D'), status: 'DISABLED', status_label: '已停用' },
      { ...rowFor('e', 'E'), status: 'ADDED_TO_DOWNLOAD', status_label: '已加入下载' },
    ]
    const { wrapper } = await mountSaved([], null, { ...defaultSummary, total: 5 }, rows)

    const tones = wrapper.findAll('.tracking-status-pill').map(
      (pill) => pill.classes().find((name) => name.startsWith('is-')),
    )
    expect(tones).toEqual(['is-info', 'is-danger', 'is-warning', 'is-unknown', 'is-unknown'])
  })

  it('uses the shared row background for multi-select and the arrow only for the detail', async () => {
    const items = [rowFor('a', '番 A'), rowFor('b', '番 B')]
    const { wrapper } = await mountSaved([], null, { ...defaultSummary, total: 2 }, items)

    await wrapper.find('#tracking-batch-mode').trigger('click')
    expect(wrapper.find('#tracking-batch-mode').text()).toBe('完成')
    const rows = wrapper.findAll('.tracking-list-row')

    // Row body in multi-select toggles the selection only.
    await rows[0]!.find('.tracking-list-item').trigger('click')
    expect(rows[0]!.classes()).toContain('is-batch-selected')
    expect(rows[0]!.classes()).not.toContain('is-selected')
    expect(wrapper.find('#tracking-batch-count').text()).toContain('已选 1 部')

    // The arrow always opens the detail and never changes the selection.
    await rows[1]!.find('.tracking-list-arrow').trigger('click')
    await flushPromises()
    expect(rows[1]!.classes()).toContain('is-selected')
    expect(rows[1]!.classes()).not.toContain('is-batch-selected')
    expect(wrapper.find('#tracking-batch-count').text()).toContain('已选 1 部')

    // Browse mode: the row body opens the detail.
    await wrapper.find('#tracking-batch-mode').trigger('click')
    await rows[0]!.find('.tracking-list-item').trigger('click')
    await flushPromises()
    expect(rows[0]!.classes()).toContain('is-selected')
  })

  it('puts the batch toolbar on its own row and never moves the list away (C7)', async () => {
    const items = [rowFor('a', '番 A'), rowFor('b', '番 B', [], 'PROCESSING'), rowFor('c', '番 C', [])]
    const { wrapper } = await mountSaved([], null, { ...defaultSummary, total: 3 }, items)

    await wrapper.find('#tracking-batch-mode').trigger('click')
    const panel = wrapper.find('.tracking-list-panel')
    const heading = panel.find('.tracking-list-heading-row')
    const toolbar = panel.find('.tracking-batch-toolbar')
    const children = Array.from(panel.element.children)
    expect(children.indexOf(heading.element)).toBeLessThan(children.indexOf(toolbar.element))

    // Left selection group + the single primary submit action.
    expect(toolbar.find('#tracking-batch-count').text()).toContain('已选 0 部')
    expect(toolbar.find('#tracking-batch-submit').classes()).toContain('primary-button')
    expect(toolbar.find('#tracking-batch-select-all').element.tagName).toBe('BUTTON')
    expect(toolbar.find('#tracking-batch-clear').element.tagName).toBe('BUTTON')

    await toolbar.find('#tracking-batch-select-all').trigger('click')

    // Issue #223: select-all covers every row a batch may act on, so a
    // deletable row without a submit action is selected too; only the
    // in-flight row is skipped and explained.
    expect(wrapper.find('#tracking-batch-count').text()).toContain('已选 2 部')
    expect(toolbar.find('#tracking-batch-select-all').text()).toBe('全选当前 3 部')
    const skipped = wrapper.find('#tracking-batch-skipped').text()
    expect(skipped).toContain('已跳过 1 条')
    expect(skipped).toContain('正在处理中')
    // C7: the skip notice must not remove the list container.
    expect(wrapper.find('#tracking-list-container').exists()).toBe(true)
  })

  it('offers multi-select without a saved connection but keeps submit disabled and explained', async () => {
    const router = createRouter({ history: createMemoryHistory('/app/'), routes: [
      { path: '/tracking', component: TrackingView },
    ] })
    await router.push('/tracking'); await router.isReady()
    apiGet.mockImplementation(async (path) => path === '/api/v1/settings/autobangumi'
      ? { configured: false, credential_present: false, connection_ref: null, configuration_revision: 0, connection_status: 'UNCONFIGURED', capabilities: null }
      : { items: [rowFor('a', '番 A')], summary: defaultSummary, status_groups: statusGroups(), warnings: [] })
    const wrapper = mount(TrackingView, { attachTo: document.body, global: { plugins: [createPinia(), router], stubs: { Teleport: true } } })
    await flushPromises()

    await wrapper.find('#tracking-batch-mode').trigger('click')
    expect(wrapper.find('#tracking-batch-submit').attributes('disabled')).toBeDefined()
    expect(wrapper.find('#tracking-batch-connection-required').text()).toContain('先在设置中连接 Auto Bangumi')
  })

  it('clears the selection when leaving multi-select', async () => {
    const items = [rowFor('a', '番 A')]
    const { wrapper } = await mountSaved([], null, defaultSummary, items)

    await wrapper.find('#tracking-batch-mode').trigger('click')
    await wrapper.find('#tracking-batch-select-all').trigger('click')
    expect(wrapper.find('#tracking-batch-count').text()).toContain('已选 1 部')

    await wrapper.find('#tracking-batch-mode').trigger('click')
    expect(wrapper.find('#tracking-batch-mode').text()).toBe('多选')
    expect(wrapper.find('.tracking-batch-toolbar').exists()).toBe(false)
    expect(wrapper.find('#tracking-batch-count').exists()).toBe(false)
  })
})

// -- Issue #183: bounded read-only check of a pending submission --------------

function pendingRow() {
  return {
    ...row([], null),
    tracking_id: 'tracking-1',
    status: 'VERIFYING_EXTERNAL',
    status_label: '核验外部结果中',
    status_group: 'PROCESSING',
    revision: 4,
  }
}

function pendingDetail() {
  return {
    tracking_id: 'tracking-1', request_id: 'request-1', title: '测试番', season: 1,
    subtitle_group: '字幕组', poster_path: null, status: 'VERIFYING_EXTERNAL',
    status_label: '核验外部结果中', status_group: 'PROCESSING',
    submission_mode: 'CONTINUE_TRACKING',
    // Issue #228: an unresolved record projects no state-changing action.
    available_actions: [],
    valid_resource_count: 1, updated_episode: null, updated_episode_status: 'NOT_IMPLEMENTED',
    total_episodes: null, revision: 4, origin: 'single', batch_id: null,
    created_at: '2026-09-14T00:00:00Z', updated_at: '2026-09-14T00:00:00Z', last_synced_at: null,
    safe_info: null, current_operation: {
      operation_id: 'operation-1', operation: 'SUBMIT', state: 'OUTCOME_UNKNOWN', attempt: 1,
      external_result_id: null, error_type: null, created_at: null, updated_at: null, completed_at: null,
    },
    revalidation_issues: [], external_mapping: null, audit_events: [], warnings: [],
  }
}

async function mountPending(detailOverride?: unknown) {
  const router = createRouter({ history: createMemoryHistory('/app/'), routes: [
    { path: '/tracking', component: TrackingView },
  ] })
  await router.push('/tracking?tracking_id=tracking-1'); await router.isReady()
  apiGet.mockImplementation(async (path) => {
    if (path === '/api/v1/settings/autobangumi') {
      return { configured: true, credential_present: true, connection_ref: '11111111-1111-4111-8111-111111111111', configuration_revision: 3, connection_status: 'CONFIGURED', capabilities: null } as never
    }
    if (path === '/api/v1/tracking/items/{tracking_id}') return (detailOverride ?? pendingDetail()) as never
    return {
      items: [pendingRow()],
      summary: { ...defaultSummary, pending: 0, processing: 1 },
      status_groups: statusGroups({ PROCESSING: 1 }),
      warnings: [],
    } as never
  })
  // #229: the page syncs once on entry. This fixture is about the bounded
  // check transport, so the read-only refresh is answered as offline and never
  // replaces the pending record (or its revision) under test.
  const sessionPost = apiPost.getMockImplementation()
  apiPost.mockImplementation(async (path, options) => {
    if (path === '/api/v1/tracking/sync') throw new Error('sync fixture is offline')
    return sessionPost ? sessionPost(path, options) : undefined
  })
  const wrapper = mount(TrackingView, {
    attachTo: document.body, global: { plugins: [createPinia(), router], stubs: { Teleport: true } },
  })
  await flushPromises()
  return wrapper
}

function checkCall() {
  return apiPost.mock.calls.find((call) => call[0] === '/api/v1/tracking/items/{tracking_id}/check')
}

describe('TrackingView bounded read-only check (issue #183)', () => {
  beforeEach(() => { apiGet.mockReset(); apiPost.mockReset() })

  it('automatically checks a reopened 待确认 submission without any connection', async () => {
    apiPost.mockResolvedValue({
      tracking_id: 'tracking-1', action: 'VERIFY_EXTERNAL', outcome: 'RECOVERY_REQUIRED',
      checked_revision: 4, next_revision: 5, checked_at: '2026-10-11T00:00:00Z',
      operation_id: 'operation-1', needs_manual: true, verification_reason: 'NOT_FOUND',
      tracking: pendingRow(),
    } as never)
    const wrapper = await mountPending()

    const call = checkCall()
    expect(call).toBeTruthy()
    const [, options] = call as [string, { path: { tracking_id: string }; body: Record<string, unknown> }]
    expect(options.path).toEqual({ tracking_id: 'tracking-1' })
    expect(options.body).toEqual({ expected_revision: 4 })
    // No connection is ever supplied by the browser.
    expect(JSON.stringify(options.body)).not.toContain('connection_ref')
    await flushPromises()
    expect(wrapper.find('#tracking-check-result').text()).toContain('暂时没有在 Auto Bangumi 中找到该订阅')
  })

  it('does not run the automatic check for a record outside the matrix', async () => {
    // An ACTIVE record with no unresolved operation: nothing to verify.
    await mountPending({
      ...pendingDetail(),
      status: 'ACTIVE', status_label: '追番中', status_group: 'ACTIVE',
      current_operation: null, submission_mode: null, available_actions: [],
    })

    expect(checkCall()).toBeUndefined()
  })

  it('sends no write-family request while checking', async () => {
    apiPost.mockResolvedValue({
      tracking_id: 'tracking-1', action: 'VERIFY_EXTERNAL', outcome: 'ACTIVE',
      checked_revision: 4, next_revision: 5, checked_at: '2026-10-11T00:00:00Z',
      operation_id: 'operation-1', needs_manual: false, verification_reason: null,
      tracking: pendingRow(),
    } as never)
    await mountPending()

    // #229: the page-entry sync is a read-only refresh, so the check must be
    // the only write-family request the page issues.
    const families = apiPost.mock.calls
      .map((call) => call[0])
      .filter((path) => path !== '/api/v1/tracking/sync')
    expect(families).toEqual(['/api/v1/tracking/items/{tracking_id}/check'])
  })
})

// -- Issue #184: risk-confirmed single manual resubmission -------------------

function resubmitCalls() {
  return apiPost.mock.calls.filter((call) => call[0] === '/api/v1/tracking/items/{tracking_id}/resubmit')
}

function offerResult(overrides: Record<string, unknown> = {}) {
  return {
    tracking_id: 'tracking-1', confirm: false, check_status: 'UNRESOLVED',
    outcome: 'RECOVERY_REQUIRED', requires_risk_confirmation: true,
    blocked_reason: null, verification_reason: 'NOT_FOUND',
    binding: {
      expected_revision: 5,
      previous_operation_id: 'operation-1',
      connection_ref: '11111111-1111-4111-8111-111111111111',
    },
    checked_revision: 4, next_revision: 5, checked_at: '2026-10-11T00:00:00Z',
    operation_id: 'operation-1', previous_operation_id: null,
    failure_category: null, diagnostics: {}, issues: [], tracking: pendingRow(),
    ...overrides,
  }
}

function writeResult(overrides: Record<string, unknown> = {}) {
  return {
    tracking_id: 'tracking-1', confirm: true, check_status: 'UNRESOLVED',
    outcome: 'ACTIVE', requires_risk_confirmation: false, blocked_reason: null,
    verification_reason: null, binding: null,
    checked_revision: 5, next_revision: 6, checked_at: '2026-10-11T00:01:00Z',
    operation_id: 'operation-2', previous_operation_id: 'operation-1',
    failure_category: null, diagnostics: {}, issues: [], tracking: pendingRow(),
    ...overrides,
  }
}

describe('TrackingView risk-confirmed resubmission (issue #184)', () => {
  beforeEach(() => { apiGet.mockReset(); apiPost.mockReset() })

  it('offers the risk first and writes only after the explicit confirmation', async () => {
    apiPost.mockImplementation(async (path: string, options?: { body?: unknown }) => {
      const sentBody = options?.body as Record<string, unknown> | undefined
      if (path === '/api/v1/tracking/items/{tracking_id}/check') {
        return {
          tracking_id: 'tracking-1', action: 'VERIFY_EXTERNAL', outcome: 'RECOVERY_REQUIRED',
          checked_revision: 4, next_revision: 5, checked_at: '2026-10-11T00:00:00Z',
          operation_id: 'operation-1', needs_manual: true, verification_reason: 'NOT_FOUND',
          tracking: pendingRow(),
        } as never
      }
      expect(path).toBe('/api/v1/tracking/items/{tracking_id}/resubmit')
      return (sentBody?.confirm === true ? writeResult() : offerResult()) as never
    })
    const wrapper = await mountPending()
    await flushPromises()

    await wrapper.find('#tracking-resubmit').trigger('click')
    await flushPromises()

    // Only the read-only phase ran: no binding, no key, no connection, no write.
    let calls = resubmitCalls()
    expect(calls).toHaveLength(1)
    const [, first] = calls[0] as [string, { body: Record<string, unknown> }]
    expect(first.body).toEqual({ expected_revision: 4, confirm: false })
    expect(JSON.stringify(first.body)).not.toContain('connection_ref')
    // The dialog states the proven risk and sends nothing until it is confirmed.
    expect(wrapper.find('.confirm-dialog-message').text()).toContain('重复订阅')
    expect(resubmitCalls()).toHaveLength(1)

    // The read-only phase has settled: the cards still show the server's
    // pre-write projection (处理中 has no card), so any later change can only
    // come from the settled write's own authoritative count refresh.
    expect(wrapper.findAll('.tracking-status-card').map((card) => card.text())).toEqual([
      '待处理0', '追番中0', '需处理0', '已停用0',
    ])
    apiGet.mockImplementation(async (path) => {
      if (path === '/api/v1/settings/autobangumi') {
        return {
          configured: true, credential_present: true,
          connection_ref: '11111111-1111-4111-8111-111111111111',
          configuration_revision: 3, connection_status: 'CONFIGURED', capabilities: null,
        } as never
      }
      if (path === '/api/v1/tracking/items/{tracking_id}') return pendingDetail() as never
      return {
        items: [pendingRow()],
        summary: { ...defaultSummary, active: 1 },
        status_groups: statusGroups({ ACTIVE: 1 }),
        warnings: [],
      } as never
    })

    await wrapper.find('.confirm-dialog .primary-button').trigger('click')
    await flushPromises()

    calls = resubmitCalls()
    expect(calls).toHaveLength(2)
    const [, second] = calls[1] as [string, { body: Record<string, unknown> }]
    expect(second.body).toEqual({
      expected_revision: 5,
      confirm: true,
      previous_operation_id: 'operation-1',
      connection_ref: '11111111-1111-4111-8111-111111111111',
    })
    expect(wrapper.find('#tracking-submit-result').text()).toContain('提交成功')
    // Issue #224 A5: the settled write re-read the authoritative projection, so
    // 追番中 now states the new category.  Without that read the four cards
    // would still render the pre-write (all-zero) projection.
    expect(wrapper.findAll('.tracking-status-card').map((card) => card.text())).toEqual([
      '待处理0', '追番中1', '需处理0', '已停用0',
    ])
  })

  it('cancelling the risk confirmation sends no second request at all', async () => {
    apiPost.mockImplementation(async (path: string) => (
      path.endsWith('/check')
        ? {
            tracking_id: 'tracking-1', action: 'VERIFY_EXTERNAL', outcome: 'RECOVERY_REQUIRED',
            checked_revision: 4, next_revision: 5, checked_at: '2026-10-11T00:00:00Z',
            operation_id: 'operation-1', needs_manual: true, verification_reason: 'NOT_FOUND',
            tracking: pendingRow(),
          } as never
        : offerResult() as never
    ))
    const wrapper = await mountPending()
    await flushPromises()

    await wrapper.find('#tracking-resubmit').trigger('click')
    await flushPromises()
    await wrapper.find('.confirm-dialog .secondary-button').trigger('click')
    await flushPromises()

    expect(resubmitCalls()).toHaveLength(1)
    expect(wrapper.find('#tracking-resubmit-result').text()).toContain('已取消重新提交')
  })

  it('never opens the risk dialog when the server refuses the resubmit', async () => {
    apiPost.mockImplementation(async (path: string) => (
      path.endsWith('/check')
        ? {
            tracking_id: 'tracking-1', action: 'VERIFY_EXTERNAL', outcome: 'RECOVERY_REQUIRED',
            checked_revision: 4, next_revision: 5, checked_at: '2026-10-11T00:00:00Z',
            operation_id: 'operation-1', needs_manual: true, verification_reason: 'NOT_FOUND',
            tracking: pendingRow(),
          } as never
        : offerResult({
            check_status: 'BLOCKED', requires_risk_confirmation: false, binding: null,
            blocked_reason: 'EXTERNAL_WRITE_IN_PROGRESS',
          }) as never
    ))
    const wrapper = await mountPending()
    await flushPromises()

    await wrapper.find('#tracking-resubmit').trigger('click')
    await flushPromises()

    expect(wrapper.find('.confirm-dialog').exists()).toBe(false)
    expect(resubmitCalls()).toHaveLength(1)
    expect(wrapper.find('#tracking-resubmit-result').text()).toContain('可能仍在执行')
  })

  it('a proven subscription converges from the read-only phase with zero writes', async () => {
    apiPost.mockImplementation(async (path: string) => (
      path.endsWith('/check')
        ? {
            tracking_id: 'tracking-1', action: 'VERIFY_EXTERNAL', outcome: 'ACTIVE',
            checked_revision: 4, next_revision: 5, checked_at: '2026-10-11T00:00:00Z',
            operation_id: 'operation-1', needs_manual: false, verification_reason: null,
            tracking: pendingRow(),
          } as never
        : offerResult({
            check_status: 'CONFIRMED', outcome: 'ACTIVE', requires_risk_confirmation: false,
            binding: null, verification_reason: null,
          }) as never
    ))
    const wrapper = await mountPending()
    await flushPromises()

    await wrapper.find('#tracking-resubmit').trigger('click')
    await flushPromises()

    expect(resubmitCalls()).toHaveLength(1)
    expect(wrapper.find('#tracking-resubmit-result').text()).toContain('已确认订阅存在')
    expect(wrapper.find('.confirm-dialog').exists()).toBe(false)
  })

  it('treats a stale confirmation as a conflict and starts over from a new check', async () => {
    let offers = 0
    apiPost.mockImplementation(async (path: string, options?: { body?: unknown }) => {
      if (path.endsWith('/check')) {
        return {
          tracking_id: 'tracking-1', action: 'VERIFY_EXTERNAL', outcome: 'RECOVERY_REQUIRED',
          checked_revision: 4, next_revision: 5, checked_at: '2026-10-11T00:00:00Z',
          operation_id: 'operation-1', needs_manual: true, verification_reason: 'NOT_FOUND',
          tracking: pendingRow(),
        } as never
      }
      const body = options?.body as Record<string, unknown> | undefined
      if (body?.confirm === true) {
        throw { type: 'tracking_revision_conflict', status: 409, httpError: true }
      }
      offers += 1
      return offerResult() as never
    })
    const wrapper = await mountPending()
    await flushPromises()

    await wrapper.find('#tracking-resubmit').trigger('click')
    await flushPromises()
    await wrapper.find('.confirm-dialog .primary-button').trigger('click')
    await flushPromises()

    // The 409 refuses the confirmation before the external boundary, states the
    // proven reason in the ordinary submit panel, and spends the binding: the
    // next click starts a fresh read-only phase instead of replaying it.
    expect(wrapper.find('#tracking-submit-result').text()).toContain('追番记录已变化')
    expect(offers).toBe(1)

    await wrapper.find('#tracking-resubmit').trigger('click')
    await flushPromises()
    expect(offers).toBe(2)
  })

  it('states the proven reason when the read-only phase itself conflicts', async () => {
    apiPost.mockImplementation(async (path: string, options?: { body?: unknown }) => {
      if (path.endsWith('/check')) {
        return {
          tracking_id: 'tracking-1', action: 'VERIFY_EXTERNAL', outcome: 'RECOVERY_REQUIRED',
          checked_revision: 4, next_revision: 5, checked_at: '2026-10-11T00:00:00Z',
          operation_id: 'operation-1', needs_manual: true, verification_reason: 'NOT_FOUND',
          tracking: pendingRow(),
        } as never
      }
      const body = options?.body as Record<string, unknown> | undefined
      if (body?.confirm === false) {
        // AC 6/3: the oldest write may still be running; the page must state
        // that proven condition instead of claiming a binding change.
        throw { type: 'tracking_operation_in_progress', status: 409, httpError: true }
      }
      return writeResult() as never
    })
    const wrapper = await mountPending()
    await flushPromises()

    await wrapper.find('#tracking-resubmit').trigger('click')
    await flushPromises()

    expect(wrapper.find('#tracking-resubmit-result').text()).toContain('存在尚未完成的提交操作')
    expect(wrapper.find('#tracking-resubmit-result').text()).not.toContain('绑定已变化')
    expect(wrapper.find('.confirm-dialog').exists()).toBe(false)
    expect(resubmitCalls()).toHaveLength(1)
  })

  it('replays the identical confirmation when the write result is unreadable', async () => {
    let confirmedAttempts = 0
    apiPost.mockImplementation(async (path: string, options?: { body?: unknown }) => {
      const sentBody = options?.body as Record<string, unknown> | undefined
      if (path.endsWith('/check')) {
        return {
          tracking_id: 'tracking-1', action: 'VERIFY_EXTERNAL', outcome: 'RECOVERY_REQUIRED',
          checked_revision: 4, next_revision: 5, checked_at: '2026-10-11T00:00:00Z',
          operation_id: 'operation-1', needs_manual: true, verification_reason: 'NOT_FOUND',
          tracking: pendingRow(),
        } as never
      }
      if (sentBody?.confirm !== true) return offerResult() as never
      confirmedAttempts += 1
      if (confirmedAttempts === 1) throw { type: 'network_error', status: 0, network: true }
      return writeResult() as never
    })
    const wrapper = await mountPending()
    await flushPromises()

    await wrapper.find('#tracking-resubmit').trigger('click')
    await flushPromises()
    await wrapper.find('.confirm-dialog .primary-button').trigger('click')
    await flushPromises()

    const confirmed = resubmitCalls()[1]
    expect(confirmed).toBeTruthy()
    const firstBody = (confirmed as [string, { body: Record<string, unknown> }])[1].body
    expect(resubmitCalls()).toHaveLength(2)

    // The retry replays the exact same confirmation body: no new offer, no new key.
    await wrapper.find('#tracking-resubmit').trigger('click')
    await flushPromises()

    const calls = resubmitCalls()
    expect(calls).toHaveLength(3)
    const replayed = calls[2]
    expect(replayed).toBeTruthy()
    expect((replayed as [string, { body: Record<string, unknown> }])[1].body).toEqual(firstBody)
  })
})

// -- T6 (#229): automatic read-only sync and the retired manual entry -------

describe('TrackingView automatic sync (#229 F1/F2/AC3/AC4/AC7)', () => {
  beforeEach(() => {
    apiGet.mockReset(); apiPost.mockReset(); nextSyncFixture = null
    localStorage.clear()
  })

  it('syncs once on entry with the saved connection and never asks for confirmation', async () => {
    const { wrapper } = await mountSaved()

    expect(syncCalls()).toHaveLength(1)
    expect(syncCalls()[0]?.[1]).toMatchObject({
      body: { connection_ref: REF, configuration_revision: 3, confirm: true },
    })
    // AC3 (frontend side): entering the page never becomes a write.
    expect(apiPost.mock.calls.map((call) => call[0])).toEqual(['/api/v1/tracking/sync'])
    expect(unexpectedPosts).toEqual([])
    // F1: neither the manual entry nor its confirmation dialog exists any more.
    expect(wrapper.find('#tracking-sync').exists()).toBe(false)
    expect(wrapper.find('.confirm-dialog').exists()).toBe(false)
    // B5/AC7: a clean success is a global notification, never an inline region.
    const { useNotificationStore } = await import('@/app/stores/notification')
    expect(useNotificationStore().current?.title).toBe('同步完成')
    expect(wrapper.find('#tracking-sync-status').exists()).toBe(false)
  })

  it('does not repeat the entry sync on re-render, filtering or opening a record', async () => {
    const { wrapper, router } = await mountSaved()
    expect(syncCalls()).toHaveLength(1)

    await wrapper.find('#tracking-overview-pending').trigger('click')
    wrapper.vm.$forceUpdate()
    await flushPromises()

    apiGet.mockImplementation(async (path) => path === '/api/v1/settings/autobangumi'
      ? { configured: true, credential_present: true, connection_ref: REF, configuration_revision: 3, connection_status: 'CONFIGURED', capabilities: null }
      : path === '/api/v1/tracking/items/{tracking_id}'
        ? pendingDetail()
        : { items: [row()], summary: defaultSummary, status_groups: statusGroups(), warnings: [] })
    await router.push('/tracking?tracking_id=tracking-1')
    await flushPromises()
    wrapper.vm.$forceUpdate()
    await flushPromises()

    // AC4: one page entry, one sync — a re-render, a filter or an opened record
    // never stacks a second read against the same connection.
    expect(syncCalls()).toHaveLength(1)
  })

  it('keeps degraded, incomplete and ignored results in the bounded status area', async () => {
    useSyncFixture(syncResult({ sync_status: 'PARTIAL' }))
    const partial = await mountSaved()
    expect(partial.wrapper.find('#tracking-sync-status').text()).toContain('同步部分完成')
    expect(partial.wrapper.find('.tracking-list-panel #tracking-sync-status').exists()).toBe(true)
    const { useNotificationStore } = await import('@/app/stores/notification')
    expect(useNotificationStore().current).toBeNull()
    partial.wrapper.unmount()

    useSyncFixture(syncResult({ summary: { ...UNCHANGED_SUMMARY, ignored: 2 } }))
    const ignored = await mountSaved()
    expect(ignored.wrapper.find('#tracking-sync-status').text()).toContain('忽略 2 条')
    expect(useNotificationStore().current).toBeNull()
    ignored.wrapper.unmount()
  })

  it('keeps the list loading until the entry sync converges it, without an empty flash', async () => {
    let releaseSync!: (value: unknown) => void
    const heldSync = new Promise((resolve) => { releaseSync = resolve })
    let releaseFirstList!: (value: unknown) => void
    const firstList = new Promise((resolve) => { releaseFirstList = resolve })
    let listCalls = 0
    apiGet.mockImplementation(async (path) => {
      if (path === '/api/v1/settings/autobangumi') {
        return { configured: true, credential_present: true, connection_ref: REF, configuration_revision: 3, connection_status: 'CONFIGURED', capabilities: null }
      }
      listCalls += 1
      if (listCalls === 1) return firstList as never
      return { items: [row()], summary: defaultSummary, status_groups: statusGroups(), warnings: [] }
    })
    answerSyncOnce(heldSync)
    const router = createRouter({ history: createMemoryHistory('/app/'), routes: [
      { path: '/tracking', component: TrackingView },
    ] })
    await router.push('/tracking'); await router.isReady()
    const wrapper = mount(TrackingView, {
      attachTo: document.body,
      global: { plugins: [createPinia(), router], stubs: { Teleport: true } },
    })
    await flushPromises()

    // Both the first list read and the entry sync are still in flight: the page
    // must keep its loading state instead of claiming 「还没有本地追番记录」.
    expect(wrapper.find('.tracking-list-state .loading-state').exists()).toBe(true)
    expect(wrapper.text()).not.toContain('还没有本地追番记录')

    releaseSync(syncResult())
    await flushPromises()
    // The sync's snapshot and its re-read own the list now; the superseded
    // first read can no longer clear or overwrite anything.
    expect(wrapper.find('.tracking-list-item').exists()).toBe(true)
    expect(wrapper.find('.loading-state').exists()).toBe(false)
    releaseFirstList({ items: [], summary: { total: 0 }, status_groups: [], warnings: [] })
    await flushPromises()
    expect(wrapper.find('.tracking-list-item').exists()).toBe(true)
    expect(wrapper.text()).not.toContain('还没有本地追番记录')
  })

  it('adopts the sync snapshot that detects an externally deleted record (F2)', async () => {
    const active = {
      ...rowFor('tracking-1', '外部已删', [], 'ATTENTION'),
      status: 'ACTIVE', status_label: '追番中', status_group: 'ACTIVE',
    }
    const deleted = { ...active, status: 'EXTERNAL_DELETED', status_label: '外部已删除' }
    let listReads = 0
    apiGet.mockImplementation(async (path) => {
      if (path === '/api/v1/settings/autobangumi') {
        return { configured: true, credential_present: true, connection_ref: REF, configuration_revision: 3, connection_status: 'CONFIGURED', capabilities: null }
      }
      if (path === '/api/v1/tracking/items/{tracking_id}') return pendingDetail() as never
      listReads += 1
      if (listReads === 1) {
        // The pre-sync read still sees the record as 追番中.
        return {
          items: [active],
          summary: { ...defaultSummary, pending: 0, active: 1 },
          status_groups: statusGroups({ ACTIVE: 1 }), warnings: [],
        } as never
      }
      // The post-sync re-read fails, so only the adopted snapshot can carry the
      // external-deletion fact into the page.
      throw new Error('list re-read offline')
    })
    answerSyncOnce(syncResult({
      items: [deleted],
      summary: { checked: 1, created: 0, updated: 1, unchanged: 0, ignored: 0, failed: 0, unreadable: 0 },
    }))
    const router = createRouter({ history: createMemoryHistory('/app/'), routes: [
      { path: '/tracking', component: TrackingView },
    ] })
    await router.push('/tracking?tracking_id=tracking-1'); await router.isReady()
    const wrapper = mount(TrackingView, {
      attachTo: document.body,
      global: { plugins: [createPinia(), router], stubs: { Teleport: true } },
    })
    await flushPromises()

    // The fact stays visible in the list, but the dead mapping is no longer an
    // open record (the selection and the URL are dropped).
    expect(wrapper.find('.tracking-list-item').text()).toContain('外部已删除')
    expect(wrapper.find('.tracking-inspector-content').exists()).toBe(false)
    expect(router.currentRoute.value.query.tracking_id).toBeUndefined()
  })

  it('binds the entry sync to the selected storage profile (M-1)', async () => {
    localStorage.setItem('miguOrca.web.storageDir', 'backups')
    const profile = await mountSaved()
    expect(syncCalls()[0]?.[1]).toMatchObject({ body: { storage_dir: 'backups' } })
    profile.wrapper.unmount()

    localStorage.clear()
    const root = await mountSaved()
    const body = (syncCalls().at(-1)?.[1] as { body?: Record<string, unknown> } | undefined)?.body
    expect(body).toBeDefined()
    // The default root profile stays implicit: the body keeps its exact shape.
    expect(body).not.toHaveProperty('storage_dir')
    root.wrapper.unmount()
  })

  it('never reports an unknown capability for a complete sync without a snapshot (m-1)', async () => {
    useSyncFixture(syncResult({ items: undefined }))
    const { wrapper } = await mountSaved()

    const status = wrapper.find('#tracking-sync-status').text()
    expect(status).toContain('没有返回列表快照')
    expect(status).not.toContain('能力未知')
  })

  it('renders the list after a failed entry sync and a held first read (AC4)', async () => {
    let releaseList!: (value: unknown) => void
    const firstList = new Promise((resolve) => { releaseList = resolve })
    let listCalls = 0
    apiGet.mockImplementation(async (path) => {
      if (path === '/api/v1/settings/autobangumi') {
        return { configured: true, credential_present: true, connection_ref: REF, configuration_revision: 3, connection_status: 'CONFIGURED', capabilities: null }
      }
      listCalls += 1
      if (listCalls === 1) return firstList as never
      return { items: [row()], summary: defaultSummary, status_groups: statusGroups(), warnings: [] }
    })
    apiPost.mockImplementation(async (path) => {
      if (path === '/api/v1/tracking/sync') throw new Error('sync offline')
      throw new Error(`unexpected POST ${path}`)
    })
    const router = createRouter({ history: createMemoryHistory('/app/'), routes: [
      { path: '/tracking', component: TrackingView },
    ] })
    await router.push('/tracking'); await router.isReady()
    const wrapper = mount(TrackingView, {
      attachTo: document.body,
      global: { plugins: [createPinia(), router], stubs: { Teleport: true } },
    })
    await flushPromises()

    expect(wrapper.find('#tracking-sync-status').text()).toContain('同步 Auto Bangumi 失败')
    // The first read is still pending: the page keeps its loading state.
    expect(wrapper.find('.tracking-list-state .loading-state').exists()).toBe(true)

    releaseList({ items: [row()], summary: defaultSummary, status_groups: statusGroups(), warnings: [] })
    await flushPromises()
    expect(wrapper.find('.tracking-list-item').exists()).toBe(true)
    expect(wrapper.find('.tracking-list-state .loading-state').exists()).toBe(false)
  })

  it('still runs exactly one bounded check when the entry sync remounts the detail (AC2)', async () => {
    const checkResult = {
      tracking_id: 'tracking-1', action: 'VERIFY_EXTERNAL', outcome: 'ACTIVE',
      checked_revision: 4, next_revision: 5, checked_at: '2026-10-21T00:00:00Z',
      operation_id: 'operation-1', needs_manual: false, verification_reason: null,
      tracking: pendingRow(),
    }
    apiGet.mockImplementation(async (path) => {
      if (path === '/api/v1/settings/autobangumi') {
        return { configured: true, credential_present: true, connection_ref: REF, configuration_revision: 3, connection_status: 'CONFIGURED', capabilities: null }
      }
      if (path === '/api/v1/tracking/items/{tracking_id}') return pendingDetail() as never
      return {
        items: [pendingRow()],
        summary: { ...defaultSummary, pending: 0, processing: 1 },
        status_groups: statusGroups({ PROCESSING: 1 }), warnings: [],
      } as never
    })
    apiPost.mockImplementation(async (path) => {
      if (path === '/api/v1/tracking/sync') return syncResult() as never
      if (path === '/api/v1/tracking/items/{tracking_id}/check') return checkResult as never
      throw new Error(`unexpected POST ${path}`)
    })
    const router = createRouter({ history: createMemoryHistory('/app/'), routes: [
      { path: '/tracking', component: TrackingView },
    ] })
    await router.push('/tracking?tracking_id=tracking-1'); await router.isReady()
    const wrapper = mount(TrackingView, {
      attachTo: document.body,
      global: { plugins: [createPinia(), router], stubs: { Teleport: true } },
    })
    await flushPromises()
    await flushPromises()

    const checks = apiPost.mock.calls.filter((call) => call[0] === '/api/v1/tracking/items/{tracking_id}/check')
    expect(syncCalls()).toHaveLength(1)
    expect(checks).toHaveLength(1)
    wrapper.unmount()
  })

  it('never turns the last capability probe into a submit condition', async () => {
    const unverified = { ...caps, probe_status: 'UNKNOWN' }
    apiGet.mockImplementation(async (path) => path === '/api/v1/settings/autobangumi'
      ? { configured: true, credential_present: true, connection_ref: REF, configuration_revision: 3, connection_status: 'CONFIGURED', capabilities: unverified }
      : { items: [rowFor('a', '番 A')], summary: defaultSummary, status_groups: statusGroups(), warnings: [] })
    answerSyncOnce(syncResult({ capabilities: unverified }))
    const router = createRouter({ history: createMemoryHistory('/app/'), routes: [
      { path: '/tracking', component: TrackingView },
    ] })
    await router.push('/tracking'); await router.isReady()
    const wrapper = mount(TrackingView, {
      attachTo: document.body,
      global: { plugins: [createPinia(), router], stubs: { Teleport: true } },
    })
    await flushPromises()

    // The saved connection is the only condition; an unverified projection is a
    // diagnostic fact, never a display or authorization gate (F3).
    expect(wrapper.find('#tracking-probe-saved').exists()).toBe(false)
    await wrapper.find('#tracking-batch-mode').trigger('click')
    expect(wrapper.find('#tracking-batch-connection-required').exists()).toBe(false)
  })
})

// -- T3 residual (#226 -> #229): the selected card says it can be cleared ---

describe('TrackingView selected status card hint (#229 T3 residual)', () => {
  beforeEach(() => { apiGet.mockReset(); apiPost.mockReset(); nextSyncFixture = null })

  it('marks only the selected card with a native title and keeps aria-pressed', async () => {
    const { wrapper } = await mountSaved()
    const card = () => wrapper.find('#tracking-overview-pending')

    expect(card().attributes('title')).toBeUndefined()
    expect(card().attributes('aria-pressed')).toBe('false')

    await card().trigger('click')
    expect(card().attributes('aria-pressed')).toBe('true')
    // The hint is a native title: no aria-label/role/aria-live is added.
    expect(card().attributes('title')).toBe('再次点击取消筛选')
    expect(card().attributes('aria-label')).toBeUndefined()

    await card().trigger('click')
    expect(card().attributes('aria-pressed')).toBe('false')
    expect(card().attributes('title')).toBeUndefined()
  })
})

// -- T7 (#223): explicit batch delete ---------------------------------------

function batchDeleteBody(callIndex = 0) {
  const calls = apiPost.mock.calls.filter(([path]) => String(path).includes('batch-delete'))
  const call = calls[callIndex]
  expect(call).toBeTruthy()
  return call as [string, { body: Record<string, unknown> }]
}

function batchDeleteResponse(items: unknown[], summary?: Record<string, number>) {
  return {
    batch_key: 'batch-key',
    kind: 'LOCAL_ONLY',
    state: 'COMPLETED',
    items,
    summary: summary ?? {
      total: items.length, deleted: 1, external_deleted: 0, skipped: 0, failed: 0, unknown: 0,
    },
  }
}

async function mountBatchRows(
  rows: unknown[],
  summary: Record<string, number> = { ...defaultSummary, total: rows.length },
) {
  return mountSaved([], null, summary, rows)
}

async function enterBatchAndSelectAll(wrapper: Awaited<ReturnType<typeof mountBatchRows>>['wrapper']) {
  await wrapper.find('#tracking-batch-mode').trigger('click')
  await wrapper.find('#tracking-batch-select-all').trigger('click')
  await flushPromises()
}

describe('TrackingView batch delete (#223)', () => {
  beforeEach(() => { apiGet.mockReset(); apiPost.mockReset(); nextSyncFixture = null; localStorage.clear() })

  it('offers exactly the four batch actions and a delete entry', async () => {
    const items = [rowFor('a', '番 A'), rowFor('b', '番 B')]
    const { wrapper } = await mountBatchRows(items)
    await wrapper.find('#tracking-batch-mode').trigger('click')

    const toolbar = wrapper.find('.tracking-batch-toolbar')
    expect(toolbar.findAll('button').map((button) => button.attributes('id'))).toEqual([
      'tracking-batch-select-all',
      'tracking-batch-clear',
      'tracking-batch-delete',
      'tracking-batch-submit',
    ])
    expect(wrapper.find('#tracking-batch-delete').text()).toBe('删除选中')
    // Nothing destructive exists before the user selects something.
    expect(wrapper.find('#tracking-batch-delete').attributes('disabled')).toBeDefined()
  })

  it('opens a local-only confirmation for the eligible entries', async () => {
    const items = [rowFor('a', '番 A'), rowFor('b', '番 B')]
    const { wrapper } = await mountBatchRows(items)
    await enterBatchAndSelectAll(wrapper)

    await wrapper.find('#tracking-batch-delete').trigger('click')

    const dialog = wrapper.find('.tracking-batch-delete-dialog')
    expect(dialog.exists()).toBe(true)
    expect(dialog.find('.confirm-dialog-message').text()).toContain('2 条')
    expect(dialog.find('#tracking-batch-delete-external').attributes('checked')).toBeUndefined()
    expect(dialog.text()).toContain('Auto Bangumi 中的订阅会继续运行，MiGuOrca 不再管理它们')
    expect(apiPost.mock.calls.filter(([path]) => String(path).includes('batch-delete'))).toEqual([])
  })

  it('posts one local-only batch with the eligible entries and a locked key', async () => {
    const items = [rowFor('a', '番 A'), rowFor('b', '番 B')]
    const { wrapper } = await mountBatchRows(items)
    await enterBatchAndSelectAll(wrapper)
    apiPost.mockImplementation(async (path) => {
      if (path === '/api/v1/tracking/batch-delete-plan') {
        return batchDeleteResponse([
          { tracking_id: 'a', outcome: 'DELETED', external_deleted: false, skip_reason: null },
          { tracking_id: 'b', outcome: 'DELETED', external_deleted: false, skip_reason: null },
        ]) as never
      }
      throw new Error(`unexpected POST ${path}`)
    })

    await wrapper.find('#tracking-batch-delete').trigger('click')
    await wrapper.find('#tracking-batch-delete-confirm').trigger('click')
    await flushPromises()

    const [path, options] = batchDeleteBody()
    expect(path).toBe('/api/v1/tracking/batch-delete-plan')
    expect(options.body).toMatchObject({ confirm: true })
    expect(typeof options.body.idempotency_key).toBe('string')
    expect(options.body).not.toHaveProperty('connection_ref')
    expect(options.body.items).toEqual([
      { tracking_id: 'a', expected_revision: 1 },
      { tracking_id: 'b', expected_revision: 1 },
    ])
  })

  it('uses the external endpoint only when the box is ticked', async () => {
    const items = [rowFor('a', '番 A')]
    const { wrapper } = await mountBatchRows(items)
    await enterBatchAndSelectAll(wrapper)
    apiPost.mockImplementation(async (path) => {
      if (path === '/api/v1/tracking/batch-delete-plan-external') {
        return batchDeleteResponse(
          [{ tracking_id: 'a', outcome: 'DELETED', external_deleted: true, skip_reason: null }],
          { total: 1, deleted: 1, external_deleted: 1, skipped: 0, failed: 0, unknown: 0 },
        ) as never
      }
      throw new Error(`unexpected POST ${path}`)
    })

    await wrapper.find('#tracking-batch-delete').trigger('click')
    await wrapper.find('#tracking-batch-delete-external').setValue(true)
    await wrapper.find('#tracking-batch-delete-confirm').trigger('click')
    await flushPromises()

    const [path, options] = batchDeleteBody()
    expect(path).toBe('/api/v1/tracking/batch-delete-plan-external')
    expect(options.body).toMatchObject({
      confirm: true,
      connection_ref: '11111111-1111-4111-8111-111111111111',
      configuration_revision: 3,
    })
  })

  it('keeps the external scope unavailable without a saved connection', async () => {
    const router = createRouter({ history: createMemoryHistory('/app/'), routes: [
      { path: '/tracking', component: TrackingView },
    ] })
    await router.push('/tracking'); await router.isReady()
    apiGet.mockImplementation(async (path) => path === '/api/v1/settings/autobangumi'
      ? { configured: false, credential_present: false, connection_ref: null, configuration_revision: 0, connection_status: 'UNCONFIGURED', capabilities: null }
      : { items: [rowFor('a', '番 A')], summary: defaultSummary, status_groups: statusGroups(), warnings: [] })
    const wrapper = mount(TrackingView, { attachTo: document.body, global: { plugins: [createPinia(), router], stubs: { Teleport: true } } })
    await flushPromises()

    await wrapper.find('#tracking-batch-mode').trigger('click')
    await wrapper.find('#tracking-batch-select-all').trigger('click')
    await flushPromises()
    // The delete entry exists without a connection (local deletes need none).
    expect(wrapper.find('#tracking-batch-delete').attributes('disabled')).toBeUndefined()

    await wrapper.find('#tracking-batch-delete').trigger('click')
    expect(wrapper.find('#tracking-batch-delete-external').attributes('disabled')).toBeDefined()
    expect(wrapper.text()).toContain('缺少已保存连接时只能删除本地记录')
  })

  it('keeps the deleted entries readable after the refresh removes their rows (AC3)', async () => {
    const rows = [rowFor('a', '番 A'), rowFor('b', '番 B')]
    const { wrapper, router } = await mountBatchRows(rows)
    await enterBatchAndSelectAll(wrapper)
    // After the batch, the list no longer contains the deleted row.
    let listReads = 0
    apiGet.mockImplementation(async (path) => {
      if (path === '/api/v1/settings/autobangumi') {
        return { configured: true, credential_present: true, connection_ref: REF, configuration_revision: 3, connection_status: 'CONFIGURED', capabilities: null }
      }
      listReads += 1
      return (listReads === 1 ? rows : [rows[1]])
        .map((row) => ({ ...(row as Record<string, unknown>) })) as never
    })
    apiPost.mockImplementation(async () => batchDeleteResponse([
      { tracking_id: 'a', outcome: 'DELETED', external_deleted: false, skip_reason: null },
      { tracking_id: 'b', outcome: 'DELETED', external_deleted: false, skip_reason: null },
    ]) as never)
    void router

    await wrapper.find('#tracking-batch-delete').trigger('click')
    await wrapper.find('#tracking-batch-delete-confirm').trigger('click')
    await flushPromises()

    const entries = wrapper.findAll('#tracking-batch-delete-result .tracking-batch-entries li').map((entry) => entry.text())
    // The refresh really removed the row (so the title can only come from the
    // pre-refresh snapshot), and the result still names it.
    expect(wrapper.find('[data-tracking-id="a"]').exists()).toBe(false)
    expect(entries).toContain('番 A：已删除本地记录')
  })

  it('makes deletable non-submittable rows selectable while submit stays narrow (#223)', async () => {
    // AC7 needs batch delete to cover ACTIVE plans (no SUBMIT action); the
    // submit pre-check must keep refusing them.
    const items = [
      rowFor('active', '追番中 A', [], 'ACTIVE'),
      rowFor('pending', '待提交 B'),
    ]
    const { wrapper } = await mountBatchRows(items)
    await enterBatchAndSelectAll(wrapper)
    expect(wrapper.find('#tracking-batch-count').text()).toContain('已选 2 部')

    await wrapper.find('#tracking-batch-delete').trigger('click')
    expect(wrapper.find('.tracking-batch-delete-dialog .confirm-dialog-message').text()).toContain('2 条')
    await wrapper.find('#tracking-batch-delete-cancel').trigger('click')

    apiPost.mockImplementation(async (path) => {
      if (path === '/api/v1/tracking/batch-submit') {
        return {
          items: [{
            tracking_id: 'pending', ok: true, error_type: null,
            result: {
              tracking_id: 'pending', outcome: 'ACTIVE', checked_revision: 1,
              next_revision: 2, checked_at: '2026-10-21T00:00:00Z', operation_id: 'op-1',
              failure_category: null, issues: [],
              tracking: { ...rowFor('pending', '待提交 B'), revision: 2 },
            },
          }],
          summary: { total: 1, succeeded: 1, failed: 0, unknown: 0, blocked: 0 },
        } as never
      }
      throw new Error(`unexpected POST ${path}`)
    })
    await wrapper.find('#tracking-batch-submit').trigger('click')
    await wrapper.find('#tracking-mode-continue').trigger('click')
    await flushPromises()

    const submit = apiPost.mock.calls.find(([path]) => path === '/api/v1/tracking/batch-submit')
    expect(submit).toBeTruthy()
    // Only the submittable row reaches Auto Bangumi.
    expect((submit as [string, { body: { items: { tracking_id: string }[] } }])[1].body.items
      .map((entry) => entry.tracking_id)).toEqual(['pending'])
  })

  it('reports an entry the server skipped as unresolved at execution time (AC8)', async () => {
    const rows = [rowFor('a', '番 A'), rowFor('b', '番 B')]
    const { wrapper } = await mountBatchRows(rows)
    await enterBatchAndSelectAll(wrapper)
    apiPost.mockImplementation(async () => batchDeleteResponse([
      { tracking_id: 'a', outcome: 'DELETED', external_deleted: false, skip_reason: null },
      { tracking_id: 'b', outcome: 'SKIPPED', external_deleted: false, skip_reason: 'UNRESOLVED' },
    ], { total: 2, deleted: 1, external_deleted: 0, skipped: 1, failed: 0, unknown: 0 }) as never)

    await wrapper.find('#tracking-batch-delete').trigger('click')
    await wrapper.find('#tracking-batch-delete-confirm').trigger('click')
    await flushPromises()

    const entries = wrapper.findAll('#tracking-batch-delete-result .tracking-batch-entries li').map((entry) => entry.text())
    expect(entries).toContain('番 B：结果待确认或外部操作进行中：本次跳过，需要逐条处理')
    // The skipped entry stays selected: it must be handled one by one.
    const kept = wrapper.findAll('.tracking-list-row.is-batch-selected').map((row) => row.attributes('data-tracking-id'))
    expect(kept).toEqual(['b'])
  })

  it('renders per-entry results and keeps failed entries selected (AC3/AC6)', async () => {
    const rows = [rowFor('a', '番 A'), rowFor('b', '番 B'), rowFor('c', '番 C')]
    const { wrapper } = await mountBatchRows(rows)
    await enterBatchAndSelectAll(wrapper)
    apiPost.mockImplementation(async () => batchDeleteResponse([
      { tracking_id: 'a', outcome: 'DELETED', external_deleted: true, skip_reason: null },
      { tracking_id: 'b', outcome: 'EXTERNAL_FAILED', external_deleted: false, skip_reason: null },
      { tracking_id: 'c', outcome: 'EXTERNAL_UNKNOWN', external_deleted: false, skip_reason: null },
    ], { total: 3, deleted: 1, external_deleted: 1, skipped: 0, failed: 1, unknown: 1 }) as never)

    await wrapper.find('#tracking-batch-delete').trigger('click')
    await wrapper.find('#tracking-batch-delete-external').setValue(true)
    await wrapper.find('#tracking-batch-delete-confirm').trigger('click')
    await flushPromises()

    const panel = wrapper.find('#tracking-batch-delete-result')
    expect(panel.exists()).toBe(true)
    expect(panel.find('#tracking-batch-delete-summary').text()).toContain('已删除 1 条')
    expect(panel.find('#tracking-batch-delete-summary').text()).toContain('其中 1 条同时删除了受控外部订阅')
    expect(panel.find('#tracking-batch-delete-summary').text()).toContain('外部删除失败 1 条')
    const entries = panel.findAll('.tracking-batch-entries li').map((entry) => entry.text())
    expect(entries).toEqual([
      '番 A：已删除本地记录，并已删除受控外部订阅',
      '番 B：外部订阅删除失败：本地方案与记录已保留',
      '番 C：外部删除结果待确认：本地方案与记录已保留，请先核验',
    ])
    // AC6: no retry-all entry; failed entries stay selected for single handling.
    expect(panel.findAll('button')).toHaveLength(0)
    const kept = wrapper.findAll('.tracking-list-row.is-batch-selected').map((row) => row.attributes('data-tracking-id'))
    expect(kept).toEqual(['b', 'c'])
  })

  it('replays the same batch key after a lost response (AC9)', async () => {
    const items = [rowFor('a', '番 A')]
    const { wrapper } = await mountBatchRows(items)
    await enterBatchAndSelectAll(wrapper)
    apiPost.mockRejectedValueOnce({ type: 'request_timeout', message: 'timeout' } as never)
    apiPost.mockResolvedValueOnce(batchDeleteResponse(
      [{ tracking_id: 'a', outcome: 'DELETED', external_deleted: false, skip_reason: null }],
    ) as never)

    await wrapper.find('#tracking-batch-delete').trigger('click')
    await wrapper.find('#tracking-batch-delete-confirm').trigger('click')
    await flushPromises()
    expect(wrapper.find('#tracking-batch-delete-notice').text()).toContain('同一批次查询/重放')

    await wrapper.find('#tracking-batch-delete').trigger('click')
    await wrapper.find('#tracking-batch-delete-confirm').trigger('click')
    await flushPromises()

    const firstKey = batchDeleteBody(0)[1].body.idempotency_key
    const secondKey = batchDeleteBody(1)[1].body.idempotency_key
    expect(secondKey).toBe(firstKey)
  })

  it('starts a new batch key once the selection changes', async () => {
    const rows = [rowFor('a', '番 A'), rowFor('b', '番 B')]
    const { wrapper } = await mountBatchRows(rows)
    await enterBatchAndSelectAll(wrapper)
    apiPost.mockRejectedValueOnce({ type: 'request_timeout', message: 'timeout' } as never)
    await wrapper.find('#tracking-batch-delete').trigger('click')
    await wrapper.find('#tracking-batch-delete-confirm').trigger('click')
    await flushPromises()

    await wrapper.find('[data-tracking-id="b"] .tracking-list-item').trigger('click')
    apiPost.mockResolvedValueOnce(batchDeleteResponse(
      [{ tracking_id: 'a', outcome: 'DELETED', external_deleted: false, skip_reason: null }],
    ) as never)
    await wrapper.find('#tracking-batch-delete').trigger('click')
    await wrapper.find('#tracking-batch-delete-confirm').trigger('click')
    await flushPromises()

    expect(batchDeleteBody(1)[1].body.idempotency_key).not.toBe(batchDeleteBody(0)[1].body.idempotency_key)
  })

  it('sends nothing when the pre-check leaves no deletable entry (AC8)', async () => {
    // A selected row without a verifiable revision cannot be sent: the dialog
    // states the skip and the confirm path returns without any request.
    const rows = [{ ...rowFor('a', '番 A'), revision: 0 }]
    const { wrapper } = await mountBatchRows(rows)
    await wrapper.find('#tracking-batch-mode').trigger('click')
    // Locked rows are not selectable, so select explicitly through the row body.
    await wrapper.find('[data-tracking-id="a"] .tracking-list-item').trigger('click')
    await flushPromises()
    expect(wrapper.find('#tracking-batch-count').text()).toContain('已选 1 部')

    await wrapper.find('#tracking-batch-delete').trigger('click')
    expect(wrapper.find('.tracking-batch-delete-dialog .confirm-dialog-message').text()).toContain('0 条')
    expect(wrapper.find('.tracking-batch-delete-skipped').text()).toContain('缺少可校验的记录版本')
    await wrapper.find('#tracking-batch-delete-confirm').trigger('click')
    await flushPromises()

    expect(apiPost.mock.calls.filter(([path]) => String(path).includes('batch-delete'))).toEqual([])
    expect(wrapper.find('#tracking-batch-delete-notice').text()).toContain('没有可删除的条目')
  })
})
