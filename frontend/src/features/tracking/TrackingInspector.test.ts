import { flushPromises, mount } from '@vue/test-utils'
import { createRouter, createMemoryHistory } from 'vue-router'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { api } from '@/api/client'
import TrackingInspector from './TrackingInspector.vue'
import type { CapabilityResult } from './trackingProjection'

vi.mock('@/api/client', () => ({
  api: { get: vi.fn(), post: vi.fn() },
  toApiError: (error: unknown) =>
    typeof error === 'object' && error !== null && 'type' in error
      ? (error as { type: string; message?: string; status?: number; cancelled?: boolean; httpError?: boolean })
      : { type: 'unexpected_error', message: '发生意外错误，请稍后重试', status: 0, cancelled: false, httpError: false },
}))
const apiGet = vi.mocked(api.get)
const apiPost = vi.mocked(api.post)

function detail(overrides: Record<string, unknown> = {}) {
  return {
    tracking_id: 'tracking-1', request_id: 'request-1', title: '葬送的芙莉莲', season: 1,
    subtitle_group: '喵萌奶茶屋', poster_path: null, status: 'ACTIVE', status_label: '追番中',
    status_group: 'ACTIVE', available_actions: [], valid_resource_count: 2,
    updated_episode: null, updated_episode_status: 'NOT_IMPLEMENTED', total_episodes: null,
    revision: 2, origin: 'single', batch_id: null, created_at: '2026-09-12T00:00:00Z',
    updated_at: '2026-09-13T00:00:00Z', last_synced_at: null, safe_info: {
      request_id: 'request-1', status: 'ACCEPTED', raw_title: '安全标题', title: '葬送的芙莉莲',
      aliases: [], season: 1, season_raw: null, season_evidence: null, mikan_collection: null,
      subtitle_groups: [], selected_subtitle_group: '喵萌奶茶屋', filter_rule: {
        must_contain: '', must_not_contain: '', use_regex: false, case_sensitive: false,
      }, resources: { selected_subtitle_group: '喵萌奶茶屋', valid_resource_count: 2,
        invalid_resource_count: 0, complete_resource_count: 2, valid_file_names: ['第一集.mkv'], excluded_file_names: [] },
      folder_name: '安全文件夹', storage_profile: 'profile', total_episodes: null,
      updated_episode: null, updated_episode_status: 'NOT_IMPLEMENTED', history_summary: [], ab_status: null,
    }, current_operation: null, revalidation_issues: [], external_mapping: null, audit_events: [], warnings: [],
    ...overrides,
  }
}

const revalidateAction = {
  code: 'REVALIDATE', label: '重新复核', style: 'SECONDARY',
  requires_confirmation: false, target_scopes: [],
}

/** A §11.5 revalidate result whose returned tracking is the convergent summary. */
function revalidateResult(overrides: Record<string, unknown> = {}) {
  return {
    tracking_id: 'tracking-1', ready: false, checked_revision: 2, next_revision: 3,
    checked_at: '2026-09-13T02:00:00Z', next_status: 'NEEDS_RECONFIRM',
    issues: [{
      code: 'REQUEST_CHANGED', field: null,
      message: '本地方案已变化，需要重新确认后再提交', recovery_action: 'SUBMIT',
    }],
    tracking: {
      tracking_id: 'tracking-1', request_id: 'request-1', title: '葬送的芙莉莲', season: 1,
      subtitle_group: '喵萌奶茶屋', poster_path: null, status: 'NEEDS_RECONFIRM',
      status_label: '需重新确认', status_group: 'ATTENTION', available_actions: [revalidateAction],
      valid_resource_count: 2, updated_episode: null, updated_episode_status: 'NOT_IMPLEMENTED',
      total_episodes: null, revision: 3, updated_at: '2026-09-13T02:00:00Z',
    },
    ...overrides,
  }
}

async function mountInspector(trackingId = 'tracking-1') {
  const router = createRouter({ history: createMemoryHistory('/app/'), routes: [
    { path: '/tracking', component: TrackingInspector }, { path: '/plans', component: { template: '<div />' } },
  ] })
  const wrapper = mount(TrackingInspector, {
    props: { trackingId }, global: { plugins: [router] },
  })
  await flushPromises()
  return wrapper
}

describe('TrackingInspector secure detail (US-306)', () => {
  beforeEach(() => { apiGet.mockReset(); apiPost.mockReset() })

  it('uses only generated detail and renders safe summaries/deep link', async () => {
    apiGet.mockResolvedValue(detail() as never)
    const wrapper = await mountInspector()
    expect(apiGet).toHaveBeenCalledWith('/api/v1/tracking/items/{tracking_id}', expect.objectContaining({
      path: { tracking_id: 'tracking-1' }, query: {}, signal: expect.any(AbortSignal),
    }))
    expect(wrapper.text()).toContain('有效资源')
    expect(wrapper.text()).toContain('已更新集数')
    expect(wrapper.text()).toContain('待开发')
    expect(wrapper.find('.tracking-plan-link').exists()).toBe(true)
    expect(wrapper.text()).not.toContain('request-1')
    expect(wrapper.text()).toContain('第一集.mkv')
  })

  it('hides local plan link for external-only records', async () => {
    apiGet.mockResolvedValue(detail({ status: 'EXTERNAL_ONLY', request_id: 'request-1' }) as never)
    const wrapper = await mountInspector()
    expect(wrapper.find('.tracking-plan-link').exists()).toBe(false)
    expect(wrapper.text()).toContain('没有可返回的本地订阅方案')
  })

  it('does not let an older detail response overwrite a newer selection', async () => {
    let resolveFirst: ((value: unknown) => void) | undefined
    const first = new Promise((resolve) => { resolveFirst = resolve })
    apiGet.mockReturnValueOnce(first as never).mockResolvedValueOnce(detail({ tracking_id: 'tracking-2', title: '咒术回战' }) as never)
    const wrapper = await mountInspector()
    await wrapper.setProps({ trackingId: 'tracking-2' })
    await flushPromises()
    expect(wrapper.text()).toContain('咒术回战')
    resolveFirst?.(detail())
    await flushPromises()
    expect(wrapper.text()).toContain('咒术回战')
    expect(wrapper.text()).not.toContain('葬送的芙莉莲')
  })
})

describe('TrackingInspector local revalidation (US-309)', () => {
  beforeEach(() => {
    apiGet.mockReset()
    apiPost.mockReset()
    window.localStorage.clear()
  })

  it('sends only the latest revision and safe storage profile, never credentials', async () => {
    window.localStorage.setItem('miguOrca.web.storageDir', 'backups')
    apiGet.mockResolvedValue(detail({ available_actions: [revalidateAction] }) as never)
    apiPost.mockResolvedValue(revalidateResult({ ready: true, next_status: 'PENDING_SUBMIT', issues: [] }) as never)

    const wrapper = await mountInspector()
    await wrapper.find('#tracking-revalidate').trigger('click')
    await flushPromises()

    expect(apiPost).toHaveBeenCalledTimes(1)
    const call = apiPost.mock.calls.at(0)
    expect(call?.[0]).toBe('/api/v1/tracking/items/{tracking_id}/revalidate')
    expect(call?.[1]?.path).toEqual({ tracking_id: 'tracking-1' })
    expect(call?.[1]?.body).toEqual({ expected_revision: 2, storage_dir: 'backups' })
    expect(call?.[1]?.signal).toBeInstanceOf(AbortSignal)
    expect(JSON.stringify(call?.[1]?.body)).not.toContain('ab_config')
    expect(wrapper.find('#tracking-revalidate-result').text()).toContain('复核通过')
    expect(wrapper.text()).toContain('尚未向 Auto Bangumi 创建订阅')
  })

  it('renders a ready=false business result with server issues and no external subscription', async () => {
    apiGet.mockResolvedValue(detail({ available_actions: [revalidateAction] }) as never)
    apiPost.mockResolvedValue(revalidateResult() as never)

    const wrapper = await mountInspector()
    await wrapper.find('#tracking-revalidate').trigger('click')
    await flushPromises()

    const result = wrapper.find('#tracking-revalidate-result')
    expect(result.text()).toContain('提交前复核未通过')
    expect(result.text()).toContain('尚未向 Auto Bangumi 创建订阅')
    expect(result.find('.tracking-revalidate-issues').text()).toContain('本地方案已变化，需要重新确认后再提交')
    // The returned tracking converges the inspector without a second detail read.
    expect(apiGet).toHaveBeenCalledTimes(1)
    expect(wrapper.text()).toContain('需重新确认')
    expect(wrapper.emitted('tracking-updated')?.at(-1)?.[0]).toMatchObject({
      tracking_id: 'tracking-1', revision: 3, status: 'NEEDS_RECONFIRM',
    })
  })

  it('fails closed on unknown issue codes and never echoes unvetted server text', async () => {
    apiGet.mockResolvedValue(detail({ available_actions: [revalidateAction] }) as never)
    apiPost.mockResolvedValue(revalidateResult({
      issues: [
        { code: 'TOTALLY_NEW_CODE', field: null, message: 'https://private.invalid/leak', recovery_action: '' },
        { code: 'NO_VALID_RESOURCES', field: null, message: '', recovery_action: '' },
      ],
    }) as never)

    const wrapper = await mountInspector()
    await wrapper.find('#tracking-revalidate').trigger('click')
    await flushPromises()

    const issues = wrapper.find('.tracking-revalidate-issues')
    expect(issues.text()).not.toContain('private.invalid')
    expect(issues.text()).not.toContain('TOTALLY_NEW_CODE')
    expect(issues.text()).toContain('本地方案尚未通过提交前复核')
  })

  it('refreshes the detail and requires a new confirmation on a revision conflict', async () => {
    apiGet.mockResolvedValueOnce(detail({ available_actions: [revalidateAction] }) as never)
      .mockResolvedValueOnce(detail({ revision: 5, available_actions: [revalidateAction] }) as never)
    apiPost.mockRejectedValueOnce({
      type: 'tracking_revision_conflict', message: '追番记录版本已变化，请刷新后重试', status: 409,
      cancelled: false, httpError: true,
    } as never)

    const wrapper = await mountInspector()
    await wrapper.find('#tracking-revalidate').trigger('click')
    await flushPromises()

    // The old intent is dropped and the detail is re-read — nothing is resent.
    expect(apiPost).toHaveBeenCalledTimes(1)
    expect(apiGet).toHaveBeenCalledTimes(2)
    expect(wrapper.find('#tracking-revalidate-result').text()).toContain('请重新确认后再发起复核')

    apiPost.mockResolvedValueOnce(revalidateResult({ checked_revision: 5, next_revision: 5 }) as never)
    await wrapper.find('#tracking-revalidate').trigger('click')
    await flushPromises()
    expect(apiPost).toHaveBeenCalledTimes(2)
    expect(apiPost.mock.calls.at(-1)?.[1]?.body).toEqual({ expected_revision: 5 })
  })

  it('reuses the same intent on a transport retry instead of rebuilding it', async () => {
    apiGet.mockResolvedValue(detail({ available_actions: [revalidateAction] }) as never)
    apiPost.mockRejectedValueOnce({
      type: 'network_error', message: '网络请求失败', status: 0, cancelled: false, httpError: false,
    } as never).mockResolvedValueOnce(revalidateResult({ ready: true, issues: [] }) as never)

    const wrapper = await mountInspector()
    await wrapper.find('#tracking-revalidate').trigger('click')
    await flushPromises()
    expect(wrapper.find('#tracking-revalidate-result').text()).toContain('复核请求失败')

    await wrapper.find('#tracking-revalidate').trigger('click')
    await flushPromises()
    expect(apiPost).toHaveBeenCalledTimes(2)
    expect(apiPost.mock.calls.at(-1)?.[1]?.body).toEqual({ expected_revision: 2 })
    expect(wrapper.find('#tracking-revalidate-result').text()).toContain('复核通过')
  })

  it('discards an in-flight revalidate when the selection changes', async () => {
    let resolveRevalidate: ((value: unknown) => void) | undefined
    apiGet.mockResolvedValueOnce(detail({ available_actions: [revalidateAction] }) as never)
      .mockResolvedValueOnce(detail({ tracking_id: 'tracking-2', title: '咒术回战', available_actions: [revalidateAction] }) as never)
    apiPost.mockReturnValueOnce(new Promise((resolve) => { resolveRevalidate = resolve }) as never)

    const wrapper = await mountInspector()
    await wrapper.find('#tracking-revalidate').trigger('click')
    await flushPromises()
    const signal = apiPost.mock.calls.at(-1)?.[1]?.signal as AbortSignal

    await wrapper.setProps({ trackingId: 'tracking-2' })
    await flushPromises()
    expect(signal.aborted).toBe(true)

    resolveRevalidate?.(revalidateResult())
    await flushPromises()
    expect(wrapper.find('#tracking-revalidate-result').exists()).toBe(false)
    expect(wrapper.emitted('tracking-updated')).toBeUndefined()
    expect(wrapper.text()).toContain('咒术回战')
  })

  it('offers no revalidate button when the server does not return the action', async () => {
    apiGet.mockResolvedValue(detail() as never)
    const wrapper = await mountInspector()
    expect(wrapper.find('#tracking-revalidate').exists()).toBe(false)
    expect(wrapper.text()).toContain('当前状态不可发起本地复核')
    expect(apiPost).not.toHaveBeenCalled()
  })
})

const submitAction = {
  code: 'SUBMIT', label: '提交到 Auto Bangumi', style: 'PRIMARY',
  requires_confirmation: true, target_scopes: [],
}

function capabilities(overrides: Partial<CapabilityResult> = {}): CapabilityResult {
  return {
    probe_status: 'VERIFIED', version: '3.1.18', adapter: 'legacy_3_1',
    subscription_list: 'SUPPORTED', subscription_detail: 'SUPPORTED', subscription_submit: 'SUPPORTED',
    subscription_modify: 'SUPPORTED', subscription_enable: 'SUPPORTED', subscription_disable: 'SUPPORTED',
    subscription_delete: 'SUPPORTED', rss_list: 'SUPPORTED', rss_modify: 'SUPPORTED', rss_enable: 'SUPPORTED',
    rss_disable: 'SUPPORTED', rss_delete: 'SUPPORTED', rss_refresh: 'SUPPORTED', external_verify: 'SUPPORTED',
    checked_at: null, safe_message: null, ...overrides,
  }
}

function writeSession(overrides: Record<string, unknown> = {}) {
  return {
    trackingId: 'tracking-1', action: 'SUBMIT', state: 'ACTIVE',
    message: '提交成功：已在 Auto Bangumi 创建外部订阅。', issues: [], ...overrides,
  }
}

/** Mount the inspector with a live page credential session offering SUBMIT. */
async function mountSubmittable(
  props: Record<string, unknown> = {},
  detailOverrides: Record<string, unknown> = {},
) {
  apiGet.mockResolvedValue(detail({ available_actions: [revalidateAction, submitAction], ...detailOverrides }) as never)
  const router = createRouter({ history: createMemoryHistory('/app/'), routes: [
    { path: '/tracking', component: TrackingInspector }, { path: '/plans', component: { template: '<div />' } },
  ] })
  const wrapper = mount(TrackingInspector, {
    props: { trackingId: 'tracking-1', credentialReady: true, capabilities: capabilities(), ...props },
    global: { plugins: [router] },
  })
  await flushPromises()
  return wrapper
}

describe('TrackingInspector explicit submission (US-310)', () => {
  beforeEach(() => { apiGet.mockReset(); apiPost.mockReset() })

  it('offers SUBMIT only with a live page session and a proven capability', async () => {
    apiGet.mockResolvedValue(detail({ available_actions: [submitAction] }) as never)
    const wrapper = await mountInspector()
    expect(wrapper.find('#tracking-submit').exists()).toBe(false)
    expect(wrapper.text()).toContain('需要先在页面连接 Auto Bangumi')
    expect(apiPost).not.toHaveBeenCalled()
  })

  it('hides SUBMIT and downgrades to read-only when the capability is unsupported', async () => {
    const wrapper = await mountSubmittable(
      { capabilities: capabilities({ subscription_submit: 'UNSUPPORTED' }) },
    )
    expect(wrapper.find('#tracking-submit').exists()).toBe(false)
    expect(wrapper.text()).toContain('未确认提交能力，已降级为只读')
  })

  it('leaves the request to the page and emits the action with the latest revision', async () => {
    const wrapper = await mountSubmittable()
    await wrapper.find('#tracking-submit').trigger('click')
    await flushPromises()
    // The inspector never performs the external write itself.
    expect(apiPost).not.toHaveBeenCalled()
    const payload = wrapper.emitted('submit-requested')?.at(-1)?.[0] as {
      action: { code: string }; item: { revision: number; tracking_id: string }
    }
    expect(payload.action.code).toBe('SUBMIT')
    expect(payload.item.tracking_id).toBe('tracking-1')
    expect(payload.item.revision).toBe(2)
  })

  it('locks the conflicting actions of this item while the write is in flight', async () => {
    const wrapper = await mountSubmittable({ writeSession: writeSession({ state: 'IN_FLIGHT' }) })
    expect(wrapper.find('#tracking-submit').attributes('disabled')).toBeDefined()
    expect(wrapper.find('#tracking-submit').attributes('aria-busy')).toBe('true')
    expect(wrapper.find('#tracking-revalidate').attributes('disabled')).toBeDefined()
    await wrapper.find('#tracking-submit').trigger('click')
    await wrapper.find('#tracking-revalidate').trigger('click')
    await flushPromises()
    expect(wrapper.emitted('submit-requested')).toBeUndefined()
    expect(apiPost).not.toHaveBeenCalled()
  })

  it('renders only the fixed write copy and the documented §11.5 issues', async () => {
    const wrapper = await mountSubmittable({ writeSession: writeSession({
      state: 'VERIFYING_EXTERNAL', message: '外部提交结果未知，正在只读回查；请勿重复提交。',
      issues: [{ code: 'OPERATION_IN_PROGRESS', message: '本地方案尚未通过提交前复核。' }],
    }) })
    const result = wrapper.find('#tracking-submit-result')
    expect(result.text()).toContain('外部提交结果未知')
    expect(result.text()).toContain('请勿重复提交')
    expect(result.find('.tracking-submit-issues').text()).toContain('本地方案尚未通过提交前复核')
    expect(wrapper.text()).not.toContain('VERIFYING_EXTERNAL')
  })

  it('never shows another item write result on this item', async () => {
    const wrapper = await mountSubmittable({ writeSession: writeSession({ trackingId: 'tracking-2' }) })
    expect(wrapper.find('#tracking-submit-result').exists()).toBe(false)
  })

  it('re-reads the detail in place without blanking the panel after a write', async () => {
    const wrapper = await mountSubmittable()
    apiGet.mockResolvedValueOnce(detail({ revision: 9, title: '写后详情' }) as never)
    await (wrapper.vm as unknown as { reload: () => Promise<void> }).reload()
    await flushPromises()
    expect(wrapper.text()).toContain('写后详情')
    expect(wrapper.find('.tracking-inspector-loading').exists()).toBe(false)
    expect(document.activeElement).not.toBe(wrapper.find('#tracking-inspector-heading').element)
  })
})
