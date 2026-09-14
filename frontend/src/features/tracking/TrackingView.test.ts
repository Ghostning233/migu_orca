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
function row(actions: unknown[] = []) {
  return { tracking_id: 'tracking-1', request_id: 'request-1', title: '测试番', season: 1,
    subtitle_group: '字幕组', poster_path: null, status: 'PENDING_SUBMIT', status_label: '待提交',
    status_group: 'PENDING', available_actions: actions, valid_resource_count: 1, updated_episode: null,
    updated_episode_status: 'NOT_IMPLEMENTED', total_episodes: null, revision: 1,
    updated_at: '2026-09-14T00:00:00Z' }
}
async function mountSaved(actions: unknown[] = []) {
  const router = createRouter({ history: createMemoryHistory('/app/'), routes: [
    { path: '/tracking', component: TrackingView },
  ] })
  await router.push('/tracking'); await router.isReady()
  apiGet.mockImplementation(async (path) => path === '/api/v1/settings/autobangumi'
    ? { configured: true, credential_present: true, connection_ref: '11111111-1111-4111-8111-111111111111', configuration_revision: 3, connection_status: 'CONFIGURED', capabilities: null }
    : { items: [row(actions)], summary: {}, warnings: [] })
  const wrapper = mount(TrackingView, { attachTo: document.body, global: { plugins: [createPinia(), router], stubs: { Teleport: true } } })
  await flushPromises()
  return { wrapper, router }
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
  it('keeps local recovery connection-free while unknown capability disables external actions', async () => {
    apiPost.mockResolvedValue({ ...caps, probe_status: 'UNKNOWN', subscription_submit: 'UNKNOWN' } as never)
    const { wrapper } = await mountSaved([{ code: 'AUTO', label: '本地恢复', style: 'SECONDARY', requires_confirmation: false, target_scopes: [] }])
    await wrapper.find('#tracking-probe-saved').trigger('click'); await flushPromises()
    expect(wrapper.find('#tracking-sync').attributes('disabled')).toBeDefined()
    expect(apiPost.mock.calls.filter((c) => c[0] !== '/api/v1/settings/autobangumi/probe')).toHaveLength(0)
  })
  it('changing saved generation clears the prior capability state', async () => {
    apiPost.mockResolvedValue(caps as never)
    const { wrapper } = await mountSaved(); await wrapper.find('#tracking-probe-saved').trigger('click'); await flushPromises()
    expect(wrapper.find('#tracking-sync').exists()).toBe(true)
    apiGet.mockImplementation(async (path) => path === '/api/v1/settings/autobangumi'
      ? { configured: true, credential_present: true, connection_ref: '22222222-2222-4222-8222-222222222222', configuration_revision: 4, connection_status: 'CONFIGURED', capabilities: null }
      : { items: [row()], summary: {}, warnings: [] })
    await wrapper.find('#tracking-refresh').trigger('click'); await flushPromises()
    expect(wrapper.find('#tracking-sync').exists()).toBe(false)
  })
})
