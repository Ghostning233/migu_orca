import { flushPromises, mount } from '@vue/test-utils'
import { nextTick } from 'vue'
import { createPinia } from 'pinia'
import { createMemoryHistory, createRouter } from 'vue-router'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { api } from '@/api/client'
import TrackingView from './TrackingView.vue'

vi.mock('@/api/client', () => ({ api: { get: vi.fn(), post: vi.fn() } }))
const apiGet = vi.mocked(api.get)
const apiPost = vi.mocked(api.post)

function item(id: string, title: string, group: 'ACTIVE' | 'ATTENTION' = 'ACTIVE') {
  return {
    tracking_id: id, request_id: `request-${id}`, title, season: 1, subtitle_group: '喵萌奶茶屋',
    poster_path: null, status: group === 'ACTIVE' ? 'ACTIVE' : 'SUBMIT_FAILED',
    status_label: group === 'ACTIVE' ? '追番中' : '提交失败', status_group: group,
    available_actions: [], valid_resource_count: 1, updated_episode: null,
    updated_episode_status: 'NOT_IMPLEMENTED', total_episodes: null, revision: 1,
    updated_at: '2026-09-13T00:00:00Z',
  }
}

function detail() {
  return {
    ...item('tracking-1', '葬送的芙莉莲'), origin: 'single', batch_id: null,
    created_at: '2026-09-12T00:00:00Z', last_synced_at: null, safe_info: null,
    current_operation: null, revalidation_issues: [], external_mapping: null,
    audit_events: [], warnings: [],
  }
}

function capabilities(overrides: Record<string, unknown> = {}) {
  return {
    probe_status: 'VERIFIED', version: '3.1.18', adapter: 'legacy_3_1',
    subscription_list: 'SUPPORTED', subscription_detail: 'SUPPORTED', subscription_submit: 'SUPPORTED',
    subscription_modify: 'SUPPORTED', subscription_enable: 'SUPPORTED', subscription_disable: 'SUPPORTED',
    subscription_delete: 'SUPPORTED', rss_list: 'SUPPORTED', rss_modify: 'SUPPORTED', rss_enable: 'SUPPORTED',
    rss_disable: 'SUPPORTED', rss_delete: 'SUPPORTED', rss_refresh: 'SUPPORTED', external_verify: 'SUPPORTED',
    checked_at: null, safe_message: null, ...overrides,
  }
}

async function mountTracking(query: Record<string, string> = {}) {
  const router = createRouter({ history: createMemoryHistory('/app/'), routes: [
    { path: '/tracking', name: 'tracking', component: TrackingView },
    { path: '/plans', name: 'plans', component: { template: '<div />' } },
  ] })
  await router.push({ path: '/tracking', query })
  await router.isReady()
  const wrapper = mount(TrackingView, {
    attachTo: document.body, global: { plugins: [createPinia(), router], stubs: { Teleport: true } },
  })
  await flushPromises()
  return { wrapper, router }
}

describe('TrackingView formal overview (US-305)', () => {
  beforeEach(() => { apiGet.mockReset(); apiPost.mockReset() })

  it('loads only generated listTrackingItems and renders overview/list/placeholder', async () => {
    apiGet.mockResolvedValue({ items: [item('tracking-1', '葬送的芙莉莲')], summary: {}, warnings: [] } as never)
    const { wrapper } = await mountTracking()
    expect(apiGet).toHaveBeenCalledWith('/api/v1/tracking/items', { query: { sort: 'updated_at' } })
    expect(wrapper.find('#tracking-overview').exists()).toBe(true)
    expect(wrapper.find('.tracking-list-item').text()).toContain('葬送的芙莉莲')
    expect(wrapper.find('.tracking-inspector').text()).toContain('选择一条追番记录')
    expect(wrapper.find('input[type="checkbox"]').exists()).toBe(false)
  })

  it('selects a legal tracking id and keeps it as a single aria-current row', async () => {
    apiGet.mockResolvedValueOnce({ items: [item('tracking-1', '葬送的芙莉莲')], summary: {}, warnings: [] } as never)
    apiGet.mockResolvedValueOnce(detail() as never)
    const { wrapper, router } = await mountTracking({ tracking_id: 'tracking-1' })
    await nextTick()
    expect(router.currentRoute.value.fullPath).toBe('/tracking?tracking_id=tracking-1')
    expect(wrapper.find('[aria-current="true"]').attributes('data-tracking-id')).toBe('tracking-1')
    expect(document.activeElement).toBe(wrapper.find('[aria-current="true"]').element)
    expect(wrapper.find('.tracking-inspector-detail').text()).toContain('葬送的芙莉莲')
  })

  it('keeps a legal tracking query when the list request fails', async () => {
    apiGet.mockRejectedValueOnce(new Error('private upstream detail'))
    const { wrapper, router } = await mountTracking({ tracking_id: 'tracking-1' })
    expect(router.currentRoute.value.fullPath).toBe('/tracking?tracking_id=tracking-1')
    expect(wrapper.text()).toContain('暂时无法读取本地追番列表')
    expect(wrapper.text()).not.toContain('private upstream detail')
  })

  it('cleans an unknown tracking query and shows fixed error/empty states', async () => {
    apiGet.mockResolvedValue({ items: [], summary: {}, warnings: [] } as never)
    const { wrapper, router } = await mountTracking({ tracking_id: 'missing' })
    expect(router.currentRoute.value.fullPath).toBe('/tracking')
    expect(wrapper.text()).toContain('还没有本地追番记录')
    apiGet.mockRejectedValueOnce(new Error('sensitive endpoint'))
    await wrapper.find('#tracking-refresh').trigger('click')
    await flushPromises()
    expect(wrapper.text()).toContain('暂时无法读取本地追番列表')
    expect(wrapper.text()).not.toContain('sensitive endpoint')
  })

  it('syncs only after a connected session and explicit confirmation', async () => {
    apiGet.mockResolvedValue({ items: [item('tracking-1', '旧本地记录')], summary: {}, warnings: [] } as never)
    apiPost.mockResolvedValueOnce(capabilities() as never).mockResolvedValueOnce({
      sync_status: 'COMPLETE', checked_at: '2026-09-13T01:00:00Z', capabilities: capabilities(),
      summary: { checked: 1, created: 0, updated: 1, unchanged: 0, external_only: 0, failed: 0, unreadable: 0 },
      items: [item('tracking-1', '同步后的记录')], warnings: [],
    } as never)
    const { wrapper } = await mountTracking()
    await wrapper.find('#tracking-connect').trigger('click')
    await wrapper.find('#tracking-ab-base-url').setValue('https://ab.invalid')
    await wrapper.find('#tracking-ab-username').setValue('user')
    await wrapper.find('#tracking-ab-password').setValue('pass')
    await wrapper.find('#tracking-ab-probe').trigger('click')
    await flushPromises()
    expect(wrapper.find('#tracking-sync').exists()).toBe(true)
    await wrapper.find('#tracking-sync').trigger('click')
    expect(document.body.textContent).toContain('同步 Auto Bangumi')
    const confirm = Array.from(document.querySelectorAll('button')).find((button) => button.textContent?.includes('确认同步'))
    expect(confirm).toBeTruthy()
    confirm?.click()
    await flushPromises()
    expect(apiPost).toHaveBeenLastCalledWith('/api/v1/tracking/sync', {
      body: { ab_config: { auth_mode: 'password', base_url: 'https://ab.invalid', username: 'user', password: 'pass', fallback_enabled: false }, confirm: true },
      signal: expect.any(AbortSignal),
    })
    expect(wrapper.text()).toContain('同步后的记录')
  })

  it('keeps the old list when sync fails', async () => {
    apiGet.mockResolvedValue({ items: [item('tracking-1', '仍在本地')], summary: {}, warnings: [] } as never)
    apiPost.mockResolvedValueOnce(capabilities() as never).mockRejectedValueOnce(new Error('private response'))
    const { wrapper } = await mountTracking()
    await wrapper.find('#tracking-connect').trigger('click')
    await wrapper.find('#tracking-ab-base-url').setValue('https://ab.invalid')
    await wrapper.find('#tracking-ab-username').setValue('user')
    await wrapper.find('#tracking-ab-password').setValue('pass')
    await wrapper.find('#tracking-ab-probe').trigger('click')
    await flushPromises()
    await wrapper.find('#tracking-sync').trigger('click')
    const confirm = Array.from(document.querySelectorAll('button')).find((button) => button.textContent?.includes('确认同步'))
    confirm?.click()
    await flushPromises()
    expect(wrapper.text()).toContain('仍在本地')
    expect(wrapper.text()).toContain('已保留原有本地列表')
    expect(wrapper.text()).not.toContain('private response')
  })

  it('aborts an in-flight sync when the page connection is cleared', async () => {
    apiGet.mockResolvedValue({ items: [item('tracking-1', '仍在本地')], summary: {}, warnings: [] } as never)
    let resolveSync: ((value: unknown) => void) | undefined
    apiPost.mockResolvedValueOnce(capabilities() as never)
      .mockReturnValueOnce(new Promise((resolve) => { resolveSync = resolve }) as never)
    const { wrapper } = await mountTracking()
    await wrapper.find('#tracking-connect').trigger('click')
    await wrapper.find('#tracking-ab-base-url').setValue('https://ab.invalid')
    await wrapper.find('#tracking-ab-username').setValue('user')
    await wrapper.find('#tracking-ab-password').setValue('pass')
    await wrapper.find('#tracking-ab-probe').trigger('click')
    await flushPromises()
    await wrapper.find('#tracking-sync').trigger('click')
    document.querySelector<HTMLButtonElement>('.confirm-dialog-actions .primary-button')?.click()
    await flushPromises()
    const signal = apiPost.mock.calls.at(-1)?.[1]?.signal as AbortSignal
    await wrapper.find('.tracking-clear-connection').trigger('click')
    resolveSync?.({ sync_status: 'COMPLETE', items: [item('tracking-1', '不应写回')], summary: {}, capabilities: capabilities() })
    await flushPromises()
    expect(signal.aborted).toBe(true)
    expect(wrapper.text()).toContain('仍在本地')
    expect(wrapper.text()).not.toContain('不应写回')
    expect(wrapper.find('#tracking-sync').exists()).toBe(false)
  })

  it('clearing connection does not strand an unrelated local list request', async () => {
    let resolveList: ((value: unknown) => void) | undefined
    apiGet.mockReturnValueOnce(new Promise((resolve) => { resolveList = resolve }) as never)
    apiPost.mockResolvedValueOnce(capabilities() as never)
    const { wrapper } = await mountTracking()
    await wrapper.find('#tracking-connect').trigger('click')
    await wrapper.find('#tracking-ab-base-url').setValue('https://ab.invalid')
    await wrapper.find('#tracking-ab-username').setValue('user')
    await wrapper.find('#tracking-ab-password').setValue('pass')
    await wrapper.find('#tracking-ab-probe').trigger('click')
    await flushPromises()
    await wrapper.find('.tracking-clear-connection').trigger('click')
    resolveList?.({ items: [item('tracking-1', '列表仍可完成')], summary: {}, warnings: [] })
    await flushPromises()
    expect(wrapper.text()).toContain('列表仍可完成')
    expect(wrapper.find('.tracking-list-state').exists()).toBe(false)
  })

  it('aborts a pending sync on unmount and ignores its late response', async () => {
    apiGet.mockResolvedValue({ items: [item('tracking-1', '仍在本地')], summary: {}, warnings: [] } as never)
    let resolveSync: ((value: unknown) => void) | undefined
    apiPost.mockResolvedValueOnce(capabilities() as never)
      .mockReturnValueOnce(new Promise((resolve) => { resolveSync = resolve }) as never)
    const { wrapper } = await mountTracking()
    await wrapper.find('#tracking-connect').trigger('click')
    await wrapper.find('#tracking-ab-base-url').setValue('https://ab.invalid')
    await wrapper.find('#tracking-ab-username').setValue('user')
    await wrapper.find('#tracking-ab-password').setValue('pass')
    await wrapper.find('#tracking-ab-probe').trigger('click')
    await flushPromises()
    await wrapper.find('#tracking-sync').trigger('click')
    document.querySelector<HTMLButtonElement>('.confirm-dialog-actions .primary-button')?.click()
    await flushPromises()
    const signal = apiPost.mock.calls.at(-1)?.[1]?.signal as AbortSignal
    wrapper.unmount()
    resolveSync?.({ sync_status: 'COMPLETE', items: [item('tracking-1', '不应覆盖')], summary: {}, capabilities: capabilities() })
    await flushPromises()
    expect(signal.aborted).toBe(true)
    expect(wrapper.emitted()).toBeDefined()
  })
})
