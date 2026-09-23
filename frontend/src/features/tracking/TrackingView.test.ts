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
async function mountSaved(
  actions: unknown[] = [],
  posterPath: string | null = null,
  summary: Record<string, number> = defaultSummary,
  rows?: unknown[],
) {
  const router = createRouter({ history: createMemoryHistory('/app/'), routes: [
    { path: '/tracking', component: TrackingView },
  ] })
  await router.push('/tracking'); await router.isReady()
  apiGet.mockImplementation(async (path) => path === '/api/v1/settings/autobangumi'
    ? { configured: true, credential_present: true, connection_ref: '11111111-1111-4111-8111-111111111111', configuration_revision: 3, connection_status: 'CONFIGURED', capabilities: null }
    : { items: rows ?? [row(actions, posterPath)], summary, warnings: [] })
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

function probeCall() {
  return apiPost.mock.calls.find((call) => call[0] === '/api/v1/settings/autobangumi/probe')
}

describe('TrackingView saved connection flow', () => {
  beforeEach(() => { apiGet.mockReset(); apiPost.mockReset() })

  it('loads safe summary without probing or external business actions', async () => {
    await mountSaved(); expect(apiPost).not.toHaveBeenCalled()
    expect(apiGet.mock.calls[0]?.[0]).toBe('/api/v1/settings/autobangumi')
  })
  it('probes only after explicit user action and sends ref/revision only', async () => {
    apiPost.mockResolvedValue(caps as never)
    const { wrapper } = await mountSaved()
    await wrapper.find('#tracking-probe-saved').trigger('click'); await flushPromises()
    expect(probeCall()?.[1]).toEqual({ body: { connection_ref: '11111111-1111-4111-8111-111111111111', configuration_revision: 3 } })
    expect(JSON.stringify(probeCall()?.[1])).not.toContain('password')
  })
  it('keeps local recovery connection-free and never lets a probe result disable sync', async () => {
    apiPost.mockResolvedValue({ ...caps, probe_status: 'UNKNOWN', subscription_submit: 'UNKNOWN' } as never)
    const { wrapper } = await mountSaved([{ code: 'AUTO', label: '本地恢复', style: 'SECONDARY', requires_confirmation: false, target_scopes: [] }])
    await wrapper.find('#tracking-probe-saved').trigger('click'); await flushPromises()
    // Issue #86: the probe is diagnostic; the saved connection still offers the
    // server-validated external action, and no business request was sent.
    expect(wrapper.find('#tracking-sync').attributes('disabled')).toBeUndefined()
    expect(apiPost.mock.calls.filter((c) => c[0] !== '/api/v1/settings/autobangumi/probe')).toHaveLength(0)
  })
  it('changing the saved generation clears the prior capability summary only', async () => {
    apiPost.mockResolvedValue(caps as never)
    const { wrapper } = await mountSaved(); await wrapper.find('#tracking-probe-saved').trigger('click'); await flushPromises()
    expect(wrapper.find('#tracking-sync').exists()).toBe(true)
    expect(wrapper.find('#tracking-capability-summary').exists()).toBe(true)
    apiGet.mockImplementation(async (path) => path === '/api/v1/settings/autobangumi'
      ? { configured: true, credential_present: true, connection_ref: '22222222-2222-4222-8222-222222222222', configuration_revision: 4, connection_status: 'CONFIGURED', capabilities: null }
      : { items: [row()], summary: {}, warnings: [] })
    await wrapper.find('#tracking-refresh').trigger('click'); await flushPromises()
    // The stale diagnostic summary is dropped, but the saved connection keeps
    // offering the server-validated action (issue #86).
    expect(wrapper.find('#tracking-capability-summary').exists()).toBe(false)
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

  it('presents the unified workbench with server overview counts', async () => {
    const { wrapper } = await mountSaved([], null, {
      total: 9, pending: 4, processing: 2, active: 2, added_to_download: 1,
      inactive: 1, needs_attention: 1, unreadable: 1,
    })

    expect(wrapper.text()).toContain('我的追番')
    expect(wrapper.text()).toContain('管理待提交任务和正在运行的追番')
    const cards = wrapper.findAll('.tracking-status-card')
    // Issue #99: five fixed categories; 已加入下载 is counted on its own.
    expect(cards.map((card) => card.text())).toEqual([
      '待提交4', '追番中2', '已停用1', '已加入下载1', '需处理1',
    ])
    expect(wrapper.find('.tracking-status-total').text()).toBe('共 9 条追番记录')
  })

  it('shows checkboxes only in batch mode and keeps row selection separate', async () => {
    const items = [rowFor('a', '番 A'), rowFor('b', '番 B')]
    const { wrapper } = await mountSaved([], null, { ...defaultSummary, total: 2 }, items)

    // Ordinary browsing never renders bulk controls.
    expect(wrapper.find('.tracking-list-checkbox').exists()).toBe(false)

    await wrapper.find('#tracking-batch-mode').trigger('click')
    expect(wrapper.findAll('.tracking-list-checkbox')).toHaveLength(2)

    // Checking a box changes the batch selection only.
    await wrapper.findAll('.tracking-list-checkbox')[0]!.setValue(true)
    expect(wrapper.find('#tracking-batch-count').text()).toContain('已选 1 条')
    expect(wrapper.find('.tracking-list-item.is-selected').exists()).toBe(false)

    // Clicking the row body switches the detail and leaves the selection alone.
    await wrapper.findAll('.tracking-list-item')[1]!.trigger('click')
    await flushPromises()
    const selected = wrapper.find('.tracking-list-item.is-selected')
    expect(selected.attributes('data-tracking-id')).toBe('b')
    expect(wrapper.find('#tracking-batch-count').text()).toContain('已选 1 条')
  })

  it('selects every submittable row of the current result and states the skips', async () => {
    const items = [
      rowFor('a', '番 A'),
      rowFor('b', '番 B', [], 'PROCESSING'),
      rowFor('c', '番 C', []),
    ]
    const { wrapper } = await mountSaved([], null, { ...defaultSummary, total: 3 }, items)

    await wrapper.find('#tracking-batch-mode').trigger('click')
    await wrapper.find('#tracking-batch-select-all').trigger('click')

    expect(wrapper.find('#tracking-batch-count').text()).toContain('已选 1 条')
    const skipped = wrapper.find('#tracking-batch-skipped').text()
    expect(skipped).toContain('已跳过 2 条')
    expect(skipped).toContain('正在处理中')
    expect(skipped).toContain('不可提交')
  })

  it('clears the selection when leaving batch mode', async () => {
    const items = [rowFor('a', '番 A')]
    const { wrapper } = await mountSaved([], null, defaultSummary, items)

    await wrapper.find('#tracking-batch-mode').trigger('click')
    await wrapper.find('#tracking-batch-select-all').trigger('click')
    expect(wrapper.find('#tracking-batch-count').text()).toContain('已选 1 条')

    await wrapper.find('#tracking-batch-mode').trigger('click')
    expect(wrapper.find('.tracking-list-checkbox').exists()).toBe(false)
    expect(wrapper.find('#tracking-batch-count').exists()).toBe(false)
  })

  it('shows season and last-updated columns from the server summary row', async () => {
    const { wrapper } = await mountSaved()

    const items = wrapper.findAll('.tracking-list-item')
    expect(items[0]!.text()).toContain('第 1 季')
    expect(items[0]!.text()).toContain('待提交')
    expect(items[0]!.text()).toContain('2026')
  })
})
