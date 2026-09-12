import { flushPromises, mount } from '@vue/test-utils'
import { createPinia } from 'pinia'
import { createMemoryHistory, createRouter } from 'vue-router'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { api } from '@/api/client'
import TrackingView from './TrackingView.vue'

vi.mock('@/api/client', () => ({
  api: { get: vi.fn(), post: vi.fn() },
  toApiError: vi.fn(),
}))

const apiGet = vi.mocked(api.get)

function detail() {
  return {
    tracking_id: 'tracking-safe-1',
    request_id: 'request-safe-1',
    title: '葬送的芙莉莲',
    season: 1,
    subtitle_group: '喵萌奶茶屋',
    poster_path: null,
    status: 'PENDING_SUBMIT',
    status_label: '待提交',
    status_group: 'PENDING',
    available_actions: [{ code: 'SUBMIT', label: '提交', style: 'PRIMARY', requires_confirmation: true }],
    valid_resource_count: 12,
    updated_episode: null,
    updated_episode_status: 'NOT_IMPLEMENTED',
    total_episodes: 28,
    revision: 1,
    origin: 'single',
    batch_id: null,
    created_at: '2026-09-12T00:00:00Z',
    updated_at: null,
    last_synced_at: null,
    safe_info: { request_id: 'secret-snapshot', title: '不要渲染' },
  }
}

async function mountTracking(query: Record<string, string>) {
  const router = createRouter({
    history: createMemoryHistory('/app/'),
    routes: [{ path: '/tracking', name: 'tracking', component: TrackingView }],
  })
  await router.push({ path: '/tracking', query })
  await router.isReady()
  const wrapper = mount(TrackingView, { global: { plugins: [createPinia(), router] } })
  await flushPromises()
  return wrapper
}

describe('TrackingView read-only handoff (US-280)', () => {
  beforeEach(() => apiGet.mockReset())

  it('loads a tracking_id detail and renders only the safe top-level summary', async () => {
    apiGet.mockResolvedValue(detail() as never)
    const wrapper = await mountTracking({ tracking_id: 'tracking-safe-1' })

    expect(apiGet).toHaveBeenCalledWith('/api/v1/tracking/items/{tracking_id}', {
      path: { tracking_id: 'tracking-safe-1' },
      query: {},
    })
    expect(wrapper.find('#tracking-detail-heading').text()).toContain('葬送的芙莉莲')
    expect(wrapper.text()).toContain('有效资源')
    expect(wrapper.text()).toContain('12')
    expect(wrapper.text()).not.toContain('不要渲染')
    expect(wrapper.find('#tracking-detail-target button').exists()).toBe(false)
    expect(wrapper.find('#tracking-detail-target').attributes('tabindex')).toBe('-1')
  })

  it('shows a fixed empty state when no detail can be recovered', async () => {
    apiGet.mockResolvedValue(null as never)
    const wrapper = await mountTracking({ tracking_id: 'tracking-safe-1' })

    expect(wrapper.text()).toContain('没有可定位的追番记录')
  })
})
