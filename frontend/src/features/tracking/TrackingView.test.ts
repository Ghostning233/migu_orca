import { flushPromises, mount } from '@vue/test-utils'
import { nextTick } from 'vue'
import { createPinia } from 'pinia'
import { createMemoryHistory, createRouter } from 'vue-router'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { api } from '@/api/client'
import TrackingView from './TrackingView.vue'

vi.mock('@/api/client', () => ({ api: { get: vi.fn() } }))
const apiGet = vi.mocked(api.get)

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

async function mountTracking(query: Record<string, string> = {}) {
  const router = createRouter({ history: createMemoryHistory('/app/'), routes: [
    { path: '/tracking', name: 'tracking', component: TrackingView },
    { path: '/plans', name: 'plans', component: { template: '<div />' } },
  ] })
  await router.push({ path: '/tracking', query })
  await router.isReady()
  const wrapper = mount(TrackingView, {
    attachTo: document.body, global: { plugins: [createPinia(), router] },
  })
  await flushPromises()
  return { wrapper, router }
}

describe('TrackingView formal overview (US-305)', () => {
  beforeEach(() => apiGet.mockReset())

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
})
