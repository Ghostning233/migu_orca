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
  // B1 retires the visible probe entry; the page keeps the read-only capability
  // projection current with one automatic probe per load.
  apiPost.mockResolvedValue(caps as never)
  apiGet.mockImplementation(async (path) => path === '/api/v1/settings/autobangumi'
    ? { configured: true, credential_present: true, connection_ref: '11111111-1111-4111-8111-111111111111', configuration_revision: 3, connection_status: 'CONFIGURED', capabilities: null }
    : { items: rows ?? [row(actions, posterPath)], summary, status_groups: groups, warnings: [] })
  const wrapper = mount(TrackingView, { attachTo: document.body, global: { plugins: [createPinia(), router], stubs: { Teleport: true } } })
  await flushPromises()
  return { wrapper, router }
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
  beforeEach(() => { apiGet.mockReset(); apiPost.mockReset() })

  it('keeps the read-only capability current without a visible probe entry', async () => {
    const { wrapper } = await mountSaved()

    const calls = apiPost.mock.calls.map(([path]) => path)
    // Exactly one bounded read-only probe on load; never a business write.
    expect(calls).toEqual(['/api/v1/settings/autobangumi/probe'])
    const [, options] = apiPost.mock.calls[0] as [string, { body: Record<string, unknown> }]
    expect(options.body).toEqual({
      connection_ref: '11111111-1111-4111-8111-111111111111',
      configuration_revision: 3,
    })
    expect(JSON.stringify(options.body)).not.toContain('password')
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
    expect(wrapper.find('#tracking-sync').exists()).toBe(true)
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

  it('re-reads the authoritative card counts after a successful sync (#224 A5)', async () => {
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
    apiPost.mockImplementation(async (path) => {
      if (path === '/api/v1/settings/autobangumi/probe') return caps as never
      if (path !== '/api/v1/tracking/sync') throw new Error(`unexpected POST ${path}`)
      return {
        sync_status: 'COMPLETE', checked_at: '2026-09-14T00:00:00Z', capabilities: caps,
        summary: {
          checked: 1, created: 0, updated: 1, unchanged: 0,
          ignored: 0, failed: 0, unreadable: 0,
        },
        warnings: [], items: [rowFor('a', '番 A', [], 'ACTIVE')],
      }
    })
    const wrapper = mount(TrackingView, {
      attachTo: document.body,
      global: { plugins: [createPinia(), router], stubs: { Teleport: true } },
    })
    await flushPromises()
    expect(wrapper.findAll('.tracking-status-card').map((card) => card.text())).toEqual([
      '待处理1', '追番中0', '需处理0', '已停用0',
    ])

    await wrapper.find('#tracking-sync').trigger('click')
    await flushPromises()
    await wrapper.find('.confirm-dialog .primary-button').trigger('click')
    await flushPromises()

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

    expect(wrapper.find('#tracking-batch-count').text()).toContain('已选 1 部')
    expect(toolbar.find('#tracking-batch-select-all').text()).toBe('全选当前 3 部')
    const skipped = wrapper.find('#tracking-batch-skipped').text()
    expect(skipped).toContain('已跳过 2 条')
    expect(skipped).toContain('正在处理中')
    expect(skipped).toContain('不可提交')
    // C7: the skip notice must not remove the list container.
    expect(wrapper.find('#tracking-list-container').exists()).toBe(true)
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

async function mountPending() {
  const router = createRouter({ history: createMemoryHistory('/app/'), routes: [
    { path: '/tracking', component: TrackingView },
  ] })
  await router.push('/tracking?tracking_id=tracking-1'); await router.isReady()
  apiGet.mockImplementation(async (path) => {
    if (path === '/api/v1/settings/autobangumi') {
      return { configured: true, credential_present: true, connection_ref: '11111111-1111-4111-8111-111111111111', configuration_revision: 3, connection_status: 'CONFIGURED', capabilities: null } as never
    }
    if (path === '/api/v1/tracking/items/{tracking_id}') return pendingDetail() as never
    return {
      items: [pendingRow()],
      summary: { ...defaultSummary, pending: 0, processing: 1 },
      status_groups: statusGroups({ PROCESSING: 1 }),
      warnings: [],
    } as never
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

  it('sends no write-family request while checking', async () => {
    apiPost.mockResolvedValue({
      tracking_id: 'tracking-1', action: 'VERIFY_EXTERNAL', outcome: 'ACTIVE',
      checked_revision: 4, next_revision: 5, checked_at: '2026-10-11T00:00:00Z',
      operation_id: 'operation-1', needs_manual: false, verification_reason: null,
      tracking: pendingRow(),
    } as never)
    await mountPending()

    const families = apiPost.mock.calls
      .map((call) => call[0])
      .filter((path) => path !== '/api/v1/settings/autobangumi/probe')
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
      if (path === '/api/v1/settings/autobangumi/probe') return caps as never
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
