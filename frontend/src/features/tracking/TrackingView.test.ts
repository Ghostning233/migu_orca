import { flushPromises, mount } from '@vue/test-utils'
import { nextTick } from 'vue'
import { createPinia } from 'pinia'
import { createMemoryHistory, createRouter } from 'vue-router'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { api } from '@/api/client'
import ConfirmDialog from '@/components/feedback/ConfirmDialog.vue'
import TrackingView from './TrackingView.vue'

vi.mock('@/api/client', () => ({
  api: { get: vi.fn(), post: vi.fn() },
  toApiError: (error: unknown) => error,
}))
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

const revalidateAction = {
  code: 'REVALIDATE', label: '重新复核', style: 'SECONDARY',
  requires_confirmation: false, target_scopes: [],
}

/** A detail record that offers the server-computed local revalidate action. */
function revalidateDetail(overrides: Record<string, unknown> = {}) {
  return { ...detail(), available_actions: [revalidateAction], ...overrides }
}

/** The authoritative summary the revalidate endpoint returns after the check. */
function revalidateSummary(overrides: Record<string, unknown> = {}) {
  return {
    ...item('tracking-1', '葬送的芙莉莲'), status: 'NEEDS_RECONFIRM', status_label: '需重新确认',
    status_group: 'ATTENTION', revision: 3, available_actions: [revalidateAction], ...overrides,
  }
}

function revalidatePayload(overrides: Record<string, unknown> = {}) {
  return {
    tracking_id: 'tracking-1', ready: true, checked_revision: 1, next_revision: 1,
    checked_at: '2026-09-13T02:00:00Z', next_status: 'PENDING_SUBMIT', issues: [],
    tracking: revalidateSummary(), ...overrides,
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

type TrackingWrapper = Awaited<ReturnType<typeof mountTracking>>['wrapper']

function syncPayload(overrides: Record<string, unknown> = {}) {
  return {
    sync_status: 'COMPLETE', checked_at: '2026-09-13T01:00:00Z', capabilities: capabilities(),
    summary: { checked: 1, created: 0, updated: 1, unchanged: 0, external_only: 0, failed: 0, unreadable: 0 },
    items: [item('tracking-1', '同步后的记录')], warnings: [], ...overrides,
  }
}

async function connect(wrapper: TrackingWrapper): Promise<void> {
  await wrapper.find('#tracking-connect').trigger('click')
  await wrapper.find('#tracking-ab-base-url').setValue('https://ab.invalid')
  await wrapper.find('#tracking-ab-username').setValue('user')
  await wrapper.find('#tracking-ab-password').setValue('pass')
  await wrapper.find('#tracking-ab-probe').trigger('click')
  await flushPromises()
}

function confirmPrimaryButton(): HTMLButtonElement | undefined {
  return Array.from(document.querySelectorAll<HTMLButtonElement>('.confirm-dialog-actions button'))
    .find((button) => button.textContent?.includes('确认同步'))
}

/** Count how many sync intents actually reach the shared confirmation dialog. */
function spyConfirmDialog(wrapper: TrackingWrapper) {
  const instance = wrapper.findComponent(ConfirmDialog).vm as unknown as {
    $: { exposed: { confirm: (options: Record<string, unknown>) => Promise<boolean> } | null }
  }
  const exposed = instance.$.exposed
  if (!exposed) throw new Error('ConfirmDialog must expose confirm()')
  const spy = vi.fn(exposed.confirm)
  exposed.confirm = spy
  return spy
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

  it('shows a Chinese page-level capability summary instead of raw probe enums', async () => {
    apiGet.mockResolvedValue({ items: [], summary: {}, warnings: [] } as never)
    apiPost.mockResolvedValueOnce(capabilities({
      version: null, subscription_submit: 'UNSUPPORTED', rss_refresh: 'UNKNOWN',
    }) as never)
    const { wrapper } = await mountTracking()
    await connect(wrapper)

    const status = wrapper.find('.tracking-connection-status')
    expect(status.exists()).toBe(true)
    expect(status.text()).toContain('已验证')
    expect(status.find('.tracking-clear-connection').exists()).toBe(true)
    const summary = wrapper.find('#tracking-capability-summary')
    expect(summary.findAll('div')).toHaveLength(16)
    expect(summary.text()).toContain('未确认')
    expect(summary.text()).toContain('新增订阅')
    expect(summary.text()).toContain('刷新 RSS')
    expect(summary.text()).toContain('修改 RSS')
    // Compare the rendered states exactly so 支持 is not satisfied by 不支持.
    const states = Array.from(summary.element.querySelectorAll('dd'))
      .map((node) => node.textContent?.trim())
    expect(states).toContain('不支持')
    expect(states).toContain('未知')
    expect(states).toContain('支持')
    expect(status.text()).not.toContain('VERIFIED')
    expect(status.text()).not.toContain('UNSUPPORTED')
    expect(status.text()).not.toContain('UNKNOWN')
    expect(status.text()).not.toContain('ab.invalid')
    expect(status.text()).not.toContain('pass')
  })

  it('applies the sync result when the list is refreshed while sync is in flight', async () => {
    apiGet.mockResolvedValue({ items: [item('tracking-1', '旧本地记录')], summary: {}, warnings: [] } as never)
    let resolveSync: ((value: unknown) => void) | undefined
    apiPost.mockResolvedValueOnce(capabilities() as never)
      .mockReturnValueOnce(new Promise((resolve) => { resolveSync = resolve }) as never)
    const { wrapper } = await mountTracking()
    await connect(wrapper)
    await wrapper.find('#tracking-sync').trigger('click')
    confirmPrimaryButton()?.click()
    await flushPromises()
    expect(wrapper.find('#tracking-sync').attributes('disabled')).toBeDefined()

    await wrapper.find('#tracking-refresh').trigger('click')
    await flushPromises()
    resolveSync?.(syncPayload())
    await flushPromises()

    expect(wrapper.find('#tracking-sync-status').text()).toContain('同步完成')
    expect(wrapper.find('.tracking-list-item').text()).toContain('同步后的记录')
    expect(wrapper.text()).not.toContain('旧本地记录')
    expect(wrapper.find('#tracking-sync').attributes('disabled')).toBeUndefined()
    expect(wrapper.find('#tracking-sync').attributes('aria-busy')).toBeUndefined()
  })

  it('never lets a list response started before sync overwrite the synced revision', async () => {
    let resolveList: ((value: unknown) => void) | undefined
    apiGet.mockResolvedValueOnce({ items: [item('tracking-1', '初始记录')], summary: {}, warnings: [] } as never)
      .mockReturnValueOnce(new Promise((resolve) => { resolveList = resolve }) as never)
    apiPost.mockResolvedValueOnce(capabilities() as never).mockResolvedValueOnce(syncPayload() as never)
    const { wrapper } = await mountTracking()
    await connect(wrapper)
    await wrapper.find('#tracking-refresh').trigger('click')
    await wrapper.find('#tracking-sync').trigger('click')
    confirmPrimaryButton()?.click()
    await flushPromises()
    expect(wrapper.find('.tracking-list-item').text()).toContain('同步后的记录')

    resolveList?.({ items: [item('tracking-1', '陈旧列表')], summary: {}, warnings: [] })
    await flushPromises()
    expect(wrapper.find('.tracking-list-item').text()).toContain('同步后的记录')
    expect(wrapper.text()).not.toContain('陈旧列表')
    expect(wrapper.find('.tracking-list-state').exists()).toBe(false)
  })

  it('keeps a single sync intent while the confirmation dialog is open', async () => {
    apiGet.mockResolvedValue({ items: [item('tracking-1', '本地记录')], summary: {}, warnings: [] } as never)
    apiPost.mockResolvedValueOnce(capabilities() as never).mockResolvedValueOnce(syncPayload() as never)
    const { wrapper } = await mountTracking()
    await connect(wrapper)
    const confirmSpy = spyConfirmDialog(wrapper)

    await wrapper.find('#tracking-sync').trigger('click')
    await flushPromises()
    expect(confirmSpy).toHaveBeenCalledTimes(1)
    expect(wrapper.find('#tracking-sync').attributes('disabled')).toBeDefined()

    // The browser dialog is modal; dispatch directly to prove the intent guard
    // refuses a second confirmation even if the click reaches the handler.
    wrapper.find('#tracking-sync').element.dispatchEvent(new Event('click'))
    await flushPromises()
    expect(confirmSpy).toHaveBeenCalledTimes(1)

    confirmPrimaryButton()?.click()
    await flushPromises()
    expect(apiPost.mock.calls.filter((call) => call[0] === '/api/v1/tracking/sync')).toHaveLength(1)
    expect(wrapper.find('#tracking-sync').attributes('disabled')).toBeUndefined()
  })

  it('labels a completed sync with unknown capabilities as a read-only downgrade', async () => {
    apiGet.mockResolvedValue({ items: [item('tracking-1', '旧本地记录')], summary: {}, warnings: [] } as never)
    apiPost.mockResolvedValueOnce(capabilities() as never)
      .mockResolvedValueOnce(syncPayload({ capabilities: capabilities({ rss_refresh: 'UNKNOWN' }) }) as never)
    const { wrapper } = await mountTracking()
    await connect(wrapper)
    await wrapper.find('#tracking-sync').trigger('click')
    confirmPrimaryButton()?.click()
    await flushPromises()

    const message = wrapper.find('#tracking-sync-status').text()
    expect(message).toContain('能力未知')
    expect(message).toContain('降级为只读')
    expect(message).not.toContain('同步未完成')
    expect(wrapper.find('.tracking-list-item').text()).toContain('旧本地记录')
    expect(wrapper.text()).not.toContain('同步后的记录')
  })

  it('converges the list item from the revalidate result without remounting the inspector', async () => {
    apiGet.mockResolvedValueOnce({ items: [item('tracking-1', '葬送的芙莉莲')], summary: {}, warnings: [] } as never)
      .mockResolvedValueOnce(revalidateDetail() as never)
    apiPost.mockResolvedValueOnce(revalidatePayload() as never)

    const { wrapper } = await mountTracking({ tracking_id: 'tracking-1' })
    expect(wrapper.find('.tracking-list-item').text()).toContain('追番中')

    await wrapper.find('#tracking-revalidate').trigger('click')
    await flushPromises()

    expect(wrapper.find('#tracking-revalidate-result').text()).toContain('复核通过')
    expect(wrapper.find('.tracking-list-item').text()).toContain('需重新确认')
    // The returned tracking converges in place — no second detail read.
    expect(apiGet).toHaveBeenCalledTimes(2)
  })

  it('never lets a list response started before a revalidate restore the old revision', async () => {
    let resolveList: ((value: unknown) => void) | undefined
    apiGet.mockResolvedValueOnce({ items: [item('tracking-1', '葬送的芙莉莲')], summary: {}, warnings: [] } as never)
      .mockResolvedValueOnce(revalidateDetail() as never)
      .mockReturnValueOnce(new Promise((resolve) => { resolveList = resolve }) as never)
    apiPost.mockResolvedValueOnce(revalidatePayload() as never)

    const { wrapper } = await mountTracking({ tracking_id: 'tracking-1' })
    await wrapper.find('#tracking-refresh').trigger('click')
    await wrapper.find('#tracking-revalidate').trigger('click')
    await flushPromises()
    expect(wrapper.find('#tracking-revalidate-result').text()).toContain('复核通过')

    resolveList?.({ items: [item('tracking-1', '陈旧列表')], summary: {}, warnings: [] })
    await flushPromises()
    expect(wrapper.find('.tracking-list-item').text()).toContain('需重新确认')
    expect(wrapper.text()).not.toContain('陈旧列表')
    expect(wrapper.find('.tracking-list-state').exists()).toBe(false)
  })
})

const submitAction = {
  code: 'SUBMIT', label: '提交到 Auto Bangumi', style: 'PRIMARY',
  requires_confirmation: true, target_scopes: [],
}

function submitDetail(overrides: Record<string, unknown> = {}) {
  return { ...detail(), available_actions: [revalidateAction, submitAction], ...overrides }
}

function submitPayload(overrides: Record<string, unknown> = {}) {
  return {
    tracking_id: 'tracking-1', outcome: 'ACTIVE', checked_revision: 1, next_revision: 2,
    checked_at: '2026-09-13T03:00:00Z', operation_id: 'operation-1', issues: [],
    tracking: { ...item('tracking-1', '葬送的芙莉莲'), revision: 2 }, ...overrides,
  }
}

/** Serve the list and detail endpoints independently of call order. */
function serveApi(detailValue: () => unknown, listValue: () => unknown = () => (
  { items: [item('tracking-1', '葬送的芙莉莲')], summary: {}, warnings: [] }
)): void {
  apiGet.mockImplementation((url: string) => Promise.resolve(
    (url === '/api/v1/tracking/items' ? listValue() : detailValue()) as never,
  ))
}

/** Replace the shared confirmation dialog with a deterministic answer. */
function answerConfirm(wrapper: TrackingWrapper, answer: boolean) {
  const instance = wrapper.findComponent(ConfirmDialog).vm as unknown as {
    $: { exposed: { confirm: (options: Record<string, unknown>) => Promise<boolean> } | null }
  }
  const exposed = instance.$.exposed
  if (!exposed) throw new Error('ConfirmDialog must expose confirm()')
  const spy = vi.fn((options: Record<string, unknown>) => {
    void options
    return Promise.resolve(answer)
  })
  exposed.confirm = spy
  return spy
}

function submittedBodies(): Record<string, unknown>[] {
  return apiPost.mock.calls
    .filter((call) => call[0] === '/api/v1/tracking/items/{tracking_id}/submit')
    .map((call) => call[1]?.body as Record<string, unknown>)
}

const conflictError = {
  type: 'tracking_revision_conflict', message: '追番记录版本已变化，请刷新后重试',
  status: 409, cancelled: false, httpError: true,
}
const unknownError = {
  type: 'network_error', message: '网络请求失败', status: 0, cancelled: false, httpError: false,
}
// A structured non-409 4xx the server decides *before* the external boundary:
// the request is definitely refused and Auto Bangumi was never written.
const rejectedError = {
  type: 'tracking_storage_error', message: '写请求被拒绝', status: 400, cancelled: false, httpError: true,
}

describe('TrackingView explicit submission (US-310)', () => {
  beforeEach(() => { apiGet.mockReset(); apiPost.mockReset() })

  it('never submits without a live session or an explicit confirmation', async () => {
    serveApi(() => submitDetail())
    apiPost.mockResolvedValueOnce(capabilities() as never)
    const { wrapper } = await mountTracking({ tracking_id: 'tracking-1' })
    // No page credential session yet: the action is not offered at all.
    expect(wrapper.find('#tracking-submit').exists()).toBe(false)

    await connect(wrapper)
    // Connecting must never submit on the user's behalf.
    expect(apiPost).toHaveBeenCalledTimes(1)
    const confirmSpy = answerConfirm(wrapper, false)
    await wrapper.find('#tracking-submit').trigger('click')
    await flushPromises()
    expect(confirmSpy).toHaveBeenCalledTimes(1)
    expect(String(confirmSpy.mock.calls[0]?.[0]?.message)).toContain('创建该追番的外部订阅')
    confirmSpy.mockClear()

    // Cancelling the impact confirmation sends zero requests.
    document.querySelector<HTMLButtonElement>('.confirm-dialog-actions button')?.click()
    await flushPromises()
    expect(apiPost).toHaveBeenCalledTimes(1)
    expect(submittedBodies()).toHaveLength(0)
    expect(wrapper.find('#tracking-submit-result').exists()).toBe(false)
  })

  it('sends the latest revision, one opaque key and the page credential only in the body', async () => {
    serveApi(() => submitDetail({ revision: 4 }))
    apiPost.mockResolvedValueOnce(capabilities() as never).mockResolvedValueOnce(submitPayload() as never)
    const { wrapper } = await mountTracking({ tracking_id: 'tracking-1' })
    await connect(wrapper)
    answerConfirm(wrapper, true)
    await wrapper.find('#tracking-submit').trigger('click')
    await flushPromises()

    expect(apiPost).toHaveBeenLastCalledWith('/api/v1/tracking/items/{tracking_id}/submit', {
      path: { tracking_id: 'tracking-1' },
      body: {
        expected_revision: 4, idempotency_key: expect.stringMatching(/^[A-Za-z0-9-]{8,128}$/), confirm: true,
        ab_config: {
          auth_mode: 'password', base_url: 'https://ab.invalid', username: 'user',
          password: 'pass', fallback_enabled: false,
        },
      },
      signal: expect.any(AbortSignal),
    })
    const result = wrapper.find('#tracking-submit-result')
    expect(result.text()).toContain('提交成功')
    expect(result.text()).not.toContain('ACTIVE')
    // The key stays in page memory: never in the URL, DOM or storage.
    const key = submittedBodies()[0]?.idempotency_key as string
    expect(window.location.href).not.toContain(key)
    expect(document.body.textContent).not.toContain(key)
    expect(JSON.stringify(window.localStorage)).not.toContain(key)
  })

  it('converges the list from the returned tracking and re-reads the detail', async () => {
    serveApi(() => submitDetail())
    apiPost.mockResolvedValueOnce(capabilities() as never).mockResolvedValueOnce(submitPayload({
      tracking: { ...item('tracking-1', '葬送的芙莉莲'), status_label: '已提交', revision: 2 },
    }) as never)
    const { wrapper } = await mountTracking({ tracking_id: 'tracking-1' })
    await connect(wrapper)
    const detailReads = apiGet.mock.calls.filter((call) => call[0] === '/api/v1/tracking/items/{tracking_id}').length
    answerConfirm(wrapper, true)
    await wrapper.find('#tracking-submit').trigger('click')
    await flushPromises()

    expect(wrapper.find('.tracking-list-item').text()).toContain('已提交')
    const after = apiGet.mock.calls.filter((call) => call[0] === '/api/v1/tracking/items/{tracking_id}').length
    expect(after).toBe(detailReads + 1)
  })

  it('branches every persisted outcome into fixed Chinese copy', async () => {
    const cases: Array<[string, string]> = [
      ['SUBMIT_FAILED', '提交明确失败'],
      ['NEEDS_RECONFIRM', '本地方案已变化'],
      ['VERIFYING_EXTERNAL', '外部提交结果未知'],
      ['RECOVERY_REQUIRED', '本地结果未完成落盘'],
    ]
    for (const [outcome, copy] of cases) {
      apiGet.mockReset()
      apiPost.mockReset()
      serveApi(() => submitDetail())
      apiPost.mockResolvedValueOnce(capabilities() as never)
        .mockResolvedValueOnce(submitPayload({ outcome, issues: [{
          code: 'REQUEST_CHANGED', field: null, message: '本地方案已变化', recovery_action: 'SUBMIT',
        }] }) as never)
      const { wrapper } = await mountTracking({ tracking_id: 'tracking-1' })
      await connect(wrapper)
      answerConfirm(wrapper, true)
      await wrapper.find('#tracking-submit').trigger('click')
      await flushPromises()
      const result = wrapper.find('#tracking-submit-result')
      expect(result.text()).toContain(copy)
      expect(result.text()).not.toContain(outcome)
      wrapper.unmount()
    }
  })

  it('keeps the locked key and only reads back when the result is unknown', async () => {
    serveApi(() => submitDetail())
    apiPost.mockResolvedValueOnce(capabilities() as never)
      .mockRejectedValueOnce(unknownError as never)
      .mockResolvedValueOnce(submitPayload() as never)
    const { wrapper } = await mountTracking({ tracking_id: 'tracking-1' })
    await connect(wrapper)
    answerConfirm(wrapper, true)
    await wrapper.find('#tracking-submit').trigger('click')
    await flushPromises()

    // No blind resend: exactly one submit reached the server and the panel says so.
    expect(submittedBodies()).toHaveLength(1)
    const result = wrapper.find('#tracking-submit-result')
    expect(result.text()).toContain('提交结果未知')
    expect(result.text()).toContain('只读回查')
    expect(wrapper.text()).not.toContain('network_error')

    answerConfirm(wrapper, true)
    await wrapper.find('#tracking-submit').trigger('click')
    await flushPromises()
    const bodies = submittedBodies()
    expect(bodies).toHaveLength(2)
    expect(bodies[1]?.idempotency_key).toBe(bodies[0]?.idempotency_key)
    expect(wrapper.find('#tracking-submit-result').text()).toContain('提交成功')
  })

  it('treats a structured non-409 4xx as a definite refusal, not an unknown result', async () => {
    for (const status of [400, 404]) {
      apiGet.mockReset()
      apiPost.mockReset()
      serveApi(() => submitDetail())
      apiPost.mockResolvedValueOnce(capabilities() as never)
        .mockRejectedValueOnce({
          type: 'tracking_storage_error', message: '服务端已拒绝本次写入',
          status, cancelled: false, httpError: true,
        } as never)
        .mockResolvedValueOnce(submitPayload() as never)
      const { wrapper } = await mountTracking({ tracking_id: 'tracking-1' })
      await connect(wrapper)
      const before = reads()
      answerConfirm(wrapper, true)
      await wrapper.find('#tracking-submit').trigger('click')
      await flushPromises()

      // Fixed Chinese refusal copy, rendered through the inspector's is-rejected
      // state: the raw error_type and the raw status never reach the DOM, and
      // the copy never pretends a subscription may still have been created.
      const result = wrapper.find('#tracking-submit-result')
      expect(result.classes()).toContain('is-rejected')
      expect(result.text()).toContain('服务端明确拒绝了本次请求')
      expect(result.text()).toContain('本次未创建 Auto Bangumi 外部订阅')
      expect(result.text()).toContain('重新确认')
      expect(result.text()).not.toContain('tracking_storage_error')
      expect(result.text()).not.toContain(String(status))
      expect(wrapper.text()).not.toContain('结果未知')
      // Definite refusal: no automatic resend, and only a read-back convergence.
      expect(submittedBodies()).toHaveLength(1)
      expect(reads().list).toBe(before.list + 1)
      expect(reads().detail).toBe(before.detail + 1)

      // The refusal released the intent: the next explicit confirmation on the
      // very same item mints a fresh key instead of replaying the refused one.
      answerConfirm(wrapper, true)
      await wrapper.find('#tracking-submit').trigger('click')
      await flushPromises()
      const bodies = submittedBodies()
      expect(bodies).toHaveLength(2)
      expect(bodies[1]?.idempotency_key).not.toBe(bodies[0]?.idempotency_key)
      wrapper.unmount()
    }
  })

  it('releases the page write lock after a 4xx refusal so another item can submit', async () => {
    let currentDetail: unknown = submitDetail()
    apiGet.mockImplementation((url: string) => Promise.resolve(
      (url === '/api/v1/tracking/items'
        ? { items: [item('tracking-1', '葬送的芙莉莲'), item('tracking-2', '咒术回战')], summary: {}, warnings: [] }
        : currentDetail) as never,
    ))
    apiPost.mockResolvedValueOnce(capabilities() as never)
      .mockRejectedValueOnce(rejectedError as never)
      .mockResolvedValueOnce(submitPayload({
        tracking_id: 'tracking-2',
        tracking: { ...item('tracking-2', '咒术回战'), revision: 8 },
      }) as never)
    const { wrapper } = await mountTracking({ tracking_id: 'tracking-1' })
    await connect(wrapper)
    answerConfirm(wrapper, true)
    await wrapper.find('#tracking-submit').trigger('click')
    await flushPromises()
    expect(wrapper.find('#tracking-submit-result').classes()).toContain('is-rejected')

    // Switch to the untouched record: because a refusal keeps no intent, the
    // page-level write lock must not disable its submit action.
    currentDetail = {
      ...submitDetail(), tracking_id: 'tracking-2', request_id: 'request-tracking-2',
      title: '咒术回战', revision: 7,
    }
    await wrapper.findAll('.tracking-list-item')[1]?.trigger('click')
    await flushPromises()
    const otherSubmit = wrapper.find('#tracking-submit')
    expect(otherSubmit.exists()).toBe(true)
    expect(otherSubmit.attributes('disabled')).toBeUndefined()

    answerConfirm(wrapper, true)
    await otherSubmit.trigger('click')
    await flushPromises()
    const bodies = submittedBodies()
    expect(bodies).toHaveLength(2)
    expect(bodies[1]?.expected_revision).toBe(7)
    expect(bodies[1]?.idempotency_key).not.toBe(bodies[0]?.idempotency_key)
  })

  it('keeps a 5xx, network or timeout result unknown with the locked key', async () => {
    const cases: Array<[string, Record<string, unknown>]> = [
      ['server_error', { type: 'server_error', message: '服务端错误', status: 500, cancelled: false, httpError: true }],
      ['network_error', unknownError],
      ['request_timeout', { type: 'request_timeout', message: '请求超时，请稍后重试', status: 0, cancelled: false, httpError: false }],
      ['html_400', { type: 'request_error', message: '请求失败', status: 400, cancelled: false, httpError: true, nonJson: true }],
      ['html_404', { type: 'not_found', message: '请求失败', status: 404, cancelled: false, httpError: true, nonJson: true }],
      ['timeout_408', { type: 'request_error', message: '请求失败', status: 408, cancelled: false, httpError: true }],
      ['rate_limit_429', { type: 'request_error', message: '请求失败', status: 429, cancelled: false, httpError: true }],
    ]
    for (const [type, failure] of cases) {
      apiGet.mockReset()
      apiPost.mockReset()
      serveApi(() => submitDetail({ revision: 4 }))
      apiPost.mockResolvedValueOnce(capabilities() as never)
        .mockRejectedValueOnce(failure as never)
        .mockResolvedValueOnce(submitPayload() as never)
      const { wrapper } = await mountTracking({ tracking_id: 'tracking-1' })
      await connect(wrapper)
      answerConfirm(wrapper, true)
      await wrapper.find('#tracking-submit').trigger('click')
      await flushPromises()

      // Still indeterminate: no resend, the intent stays locked.
      expect(submittedBodies()).toHaveLength(1)
      const result = wrapper.find('#tracking-submit-result')
      expect(result.classes()).toContain('is-unknown')
      expect(result.text()).toContain('提交结果未知')
      expect(wrapper.text()).not.toContain(type)

      // The explicit retry replays the very same key and revision binding.
      answerConfirm(wrapper, true)
      await wrapper.find('#tracking-submit').trigger('click')
      await flushPromises()
      const bodies = submittedBodies()
      expect(bodies).toHaveLength(2)
      expect(bodies[1]?.idempotency_key).toBe(bodies[0]?.idempotency_key)
      expect(bodies[1]?.expected_revision).toBe(bodies[0]?.expected_revision)
      expect(wrapper.find('#tracking-submit-result').text()).toContain('提交成功')
      wrapper.unmount()
    }
  })

  it('drops the spent intent and requires a new confirmation on a conflict', async () => {
    let revision = 1
    serveApi(() => submitDetail({ revision }))
    apiPost.mockResolvedValueOnce(capabilities() as never)
      // The record moves on while the submit is in flight.
      .mockImplementationOnce((async () => { revision = 5; throw conflictError }) as never)
      .mockResolvedValueOnce(submitPayload() as never)
    const { wrapper } = await mountTracking({ tracking_id: 'tracking-1' })
    await connect(wrapper)
    answerConfirm(wrapper, true)
    await wrapper.find('#tracking-submit').trigger('click')
    await flushPromises()

    expect(wrapper.find('#tracking-submit-result').text()).toContain('请重新确认后再提交')
    expect(wrapper.text()).not.toContain('tracking_revision_conflict')

    // The conflict re-read the fresh detail; the next confirmation is a fresh
    // intent built from the new revision with a new key.
    answerConfirm(wrapper, true)
    await wrapper.find('#tracking-submit').trigger('click')
    await flushPromises()
    const bodies = submittedBodies()
    expect(bodies).toHaveLength(2)
    expect(bodies[1]?.expected_revision).toBe(5)
    expect(bodies[1]?.idempotency_key).not.toBe(bodies[0]?.idempotency_key)
  })

  it('mints a new key for the next confirmation after an explicit failure', async () => {
    serveApi(() => submitDetail())
    apiPost.mockResolvedValueOnce(capabilities() as never)
      .mockResolvedValueOnce(submitPayload({ outcome: 'SUBMIT_FAILED' }) as never)
      .mockResolvedValueOnce(submitPayload() as never)
    const { wrapper } = await mountTracking({ tracking_id: 'tracking-1' })
    await connect(wrapper)
    answerConfirm(wrapper, true)
    await wrapper.find('#tracking-submit').trigger('click')
    await flushPromises()
    expect(wrapper.find('#tracking-submit-result').text()).toContain('提交明确失败')

    await wrapper.find('#tracking-submit').trigger('click')
    await flushPromises()
    const bodies = submittedBodies()
    expect(bodies).toHaveLength(2)
    expect(bodies[1]?.idempotency_key).not.toBe(bodies[0]?.idempotency_key)
  })

  it('locks only the conflicting actions of the item being written', async () => {
    let resolveSubmit: ((value: unknown) => void) | undefined
    serveApi(() => submitDetail())
    apiPost.mockResolvedValueOnce(capabilities() as never)
      .mockReturnValueOnce(new Promise((resolve) => { resolveSubmit = resolve }) as never)
    const { wrapper } = await mountTracking({ tracking_id: 'tracking-1' })
    await connect(wrapper)
    answerConfirm(wrapper, true)
    await wrapper.find('#tracking-submit').trigger('click')
    await flushPromises()

    expect(wrapper.find('#tracking-submit-result').text()).toContain('正在提交')
    expect(wrapper.find('#tracking-submit').attributes('disabled')).toBeDefined()
    expect(wrapper.find('#tracking-revalidate').attributes('disabled')).toBeDefined()
    // The rest of the page stays usable: filtering, refreshing and re-reading.
    expect(wrapper.find('#tracking-refresh').attributes('disabled')).toBeUndefined()
    expect(wrapper.find('#tracking-search').attributes('disabled')).toBeUndefined()
    expect(wrapper.find('.tracking-list-item').exists()).toBe(true)

    resolveSubmit?.(submitPayload())
    await flushPromises()
    expect(wrapper.find('#tracking-submit-result').text()).toContain('提交成功')
  })

  it('aborts an in-flight submit but keeps a safe unknown tombstone when cleared', async () => {
    let resolveSubmit: ((value: unknown) => void) | undefined
    serveApi(() => submitDetail())
    apiPost.mockResolvedValueOnce(capabilities() as never)
      .mockReturnValueOnce(new Promise((resolve) => { resolveSubmit = resolve }) as never)
    const { wrapper } = await mountTracking({ tracking_id: 'tracking-1' })
    await connect(wrapper)
    answerConfirm(wrapper, true)
    await wrapper.find('#tracking-submit').trigger('click')
    await flushPromises()
    const signal = apiPost.mock.calls.at(-1)?.[1]?.signal as AbortSignal

    await wrapper.find('.tracking-clear-connection').trigger('click')
    resolveSubmit?.(submitPayload())
    await flushPromises()
    expect(signal.aborted).toBe(true)
    expect(wrapper.find('#tracking-submit').exists()).toBe(false)
    expect(wrapper.find('#tracking-submit-result').text()).toContain('提交结果未知')
  })
})

const retryAction = {
  code: 'RETRY', label: '重试提交', style: 'SECONDARY',
  requires_confirmation: true, target_scopes: [],
}

/** A definitely-failed record: the only status the retry endpoint accepts. */
function retryDetail(overrides: Record<string, unknown> = {}) {
  return {
    ...detail(), status: 'SUBMIT_FAILED', status_label: '提交失败',
    available_actions: [revalidateAction, retryAction], ...overrides,
  }
}

function retryPayload(overrides: Record<string, unknown> = {}) {
  return {
    tracking_id: 'tracking-1', outcome: 'ACTIVE', checked_revision: 1, next_revision: 2,
    checked_at: '2026-09-13T04:00:00Z', operation_id: 'operation-2', issues: [],
    tracking: { ...item('tracking-1', '葬送的芙莉莲'), revision: 2 }, ...overrides,
  }
}

function retriedBodies(): Record<string, unknown>[] {
  return apiPost.mock.calls
    .filter((call) => call[0] === '/api/v1/tracking/items/{tracking_id}/retry')
    .map((call) => call[1]?.body as Record<string, unknown>)
}

/** Count the reads the conflict path must perform: silent list + detail reload. */
function reads(): { list: number; detail: number } {
  return {
    list: apiGet.mock.calls.filter((call) => call[0] === '/api/v1/tracking/items').length,
    detail: apiGet.mock.calls.filter((call) => call[0] === '/api/v1/tracking/items/{tracking_id}').length,
  }
}

describe('TrackingView explicit retry (US-311)', () => {
  beforeEach(() => { apiGet.mockReset(); apiPost.mockReset() })

  it('never retries without a live session and an explicit impact confirmation', async () => {
    serveApi(() => retryDetail())
    apiPost.mockResolvedValueOnce(capabilities() as never)
    const { wrapper } = await mountTracking({ tracking_id: 'tracking-1' })
    // RETRY is server-computed and capability-gated: no session, no button.
    expect(wrapper.find('#tracking-retry').exists()).toBe(false)
    expect(wrapper.find('#tracking-submit').exists()).toBe(false)

    await connect(wrapper)
    // Connecting must never retry on the user's behalf.
    expect(retriedBodies()).toHaveLength(0)
    const confirmSpy = answerConfirm(wrapper, false)
    await wrapper.find('#tracking-retry').trigger('click')
    await flushPromises()
    expect(confirmSpy).toHaveBeenCalledTimes(1)
    expect(String(confirmSpy.mock.calls[0]?.[0]?.title)).toContain('重试')
    expect(String(confirmSpy.mock.calls[0]?.[0]?.message)).toContain('重新创建外部订阅')
    expect(retriedBodies()).toHaveLength(0)
    expect(wrapper.find('#tracking-submit-result').exists()).toBe(false)
  })

  it('sends the generated retry request with the latest revision and one opaque key', async () => {
    serveApi(() => retryDetail({ revision: 6 }))
    apiPost.mockResolvedValueOnce(capabilities() as never).mockResolvedValueOnce(retryPayload() as never)
    const { wrapper } = await mountTracking({ tracking_id: 'tracking-1' })
    await connect(wrapper)
    answerConfirm(wrapper, true)
    await wrapper.find('#tracking-retry').trigger('click')
    await flushPromises()

    expect(apiPost).toHaveBeenLastCalledWith('/api/v1/tracking/items/{tracking_id}/retry', {
      path: { tracking_id: 'tracking-1' },
      body: {
        expected_revision: 6, idempotency_key: expect.stringMatching(/^[A-Za-z0-9-]{8,128}$/),
        confirm: true,
        ab_config: {
          auth_mode: 'password', base_url: 'https://ab.invalid', username: 'user',
          password: 'pass', fallback_enabled: false,
        },
      },
      signal: expect.any(AbortSignal),
    })
    // The retry endpoint is never reached through the submit action.
    expect(submittedBodies()).toHaveLength(0)
    expect(wrapper.find('#tracking-submit-result').text()).toContain('提交成功')
    const key = retriedBodies()[0]?.idempotency_key as string
    expect(window.location.href).not.toContain(key)
    expect(document.body.textContent).not.toContain(key)
    expect(JSON.stringify(window.localStorage)).not.toContain(key)
  })

  it('converges the list from the returned tracking and re-reads the detail', async () => {
    serveApi(() => retryDetail())
    apiPost.mockResolvedValueOnce(capabilities() as never).mockResolvedValueOnce(retryPayload({
      tracking: { ...item('tracking-1', '葬送的芙莉莲'), status_label: '重试成功', revision: 2 },
    }) as never)
    const { wrapper } = await mountTracking({ tracking_id: 'tracking-1' })
    await connect(wrapper)
    const before = reads()
    answerConfirm(wrapper, true)
    await wrapper.find('#tracking-retry').trigger('click')
    await flushPromises()

    expect(wrapper.find('.tracking-list-item').text()).toContain('重试成功')
    expect(reads().detail).toBe(before.detail + 1)
  })

  it('mints a new key for every confirmation after a definite failure', async () => {
    serveApi(() => retryDetail())
    apiPost.mockResolvedValueOnce(capabilities() as never)
      .mockResolvedValueOnce(retryPayload({ outcome: 'SUBMIT_FAILED' }) as never)
      .mockResolvedValueOnce(retryPayload() as never)
    const { wrapper } = await mountTracking({ tracking_id: 'tracking-1' })
    await connect(wrapper)
    answerConfirm(wrapper, true)
    await wrapper.find('#tracking-retry').trigger('click')
    await flushPromises()
    expect(wrapper.find('#tracking-submit-result').text()).toContain('提交明确失败')

    await wrapper.find('#tracking-retry').trigger('click')
    await flushPromises()
    const bodies = retriedBodies()
    expect(bodies).toHaveLength(2)
    expect(bodies[1]?.idempotency_key).not.toBe(bodies[0]?.idempotency_key)
  })

  it('reuses the very same key and revision when the retry result stays unknown', async () => {
    serveApi(() => retryDetail({ revision: 6 }))
    apiPost.mockResolvedValueOnce(capabilities() as never)
      .mockRejectedValueOnce(unknownError as never)
      .mockResolvedValueOnce(retryPayload() as never)
    const { wrapper } = await mountTracking({ tracking_id: 'tracking-1' })
    await connect(wrapper)
    answerConfirm(wrapper, true)
    await wrapper.find('#tracking-retry').trigger('click')
    await flushPromises()

    // No blind resend: exactly one retry reached the server and it says so.
    expect(retriedBodies()).toHaveLength(1)
    const result = wrapper.find('#tracking-submit-result')
    expect(result.text()).toContain('提交结果未知')
    expect(result.text()).toContain('只读回查')
    expect(wrapper.text()).not.toContain('network_error')

    await wrapper.find('#tracking-retry').trigger('click')
    await flushPromises()
    const bodies = retriedBodies()
    expect(bodies).toHaveLength(2)
    expect(bodies[1]?.idempotency_key).toBe(bodies[0]?.idempotency_key)
    // The replayed request keeps the original revision binding too, otherwise
    // the server would reject the very same key as a different binding.
    expect(bodies[1]?.expected_revision).toBe(bodies[0]?.expected_revision)
    expect(wrapper.find('#tracking-submit-result').text()).toContain('提交成功')
  })

  it('converges every documented conflict on the server tracking with a fresh key', async () => {
    const cases: Array<[string, string]> = [
      ['tracking_revision_conflict', '追番记录已变化'],
      ['tracking_idempotency_conflict', '提交标识已失效'],
      ['tracking_state_conflict', '状态不允许本次提交'],
      ['tracking_operation_in_progress', '尚未完成的提交操作'],
      ['brand_new_conflict', '请重新确认后再提交'],
    ]
    for (const [errorType, copy] of cases) {
      apiGet.mockReset()
      apiPost.mockReset()
      let revision = 4
      serveApi(() => retryDetail({ revision }))
      apiPost.mockResolvedValueOnce(capabilities() as never)
        // The record moves on while the retry is in flight.
        .mockImplementationOnce((async () => { revision = 9; throw {
          type: errorType, message: '请刷新后重试', status: 409, cancelled: false, httpError: true,
        } }) as never)
        .mockResolvedValueOnce(retryPayload() as never)
      const { wrapper } = await mountTracking({ tracking_id: 'tracking-1' })
      await connect(wrapper)
      const before = reads()
      answerConfirm(wrapper, true)
      await wrapper.find('#tracking-retry').trigger('click')
      await flushPromises()

      const result = wrapper.find('#tracking-submit-result')
      expect(result.text()).toContain(copy)
      expect(result.text()).toContain('未提交到 Auto Bangumi')
      expect(wrapper.text()).not.toContain(errorType)
      // The conflict body carries no authoritative tracking: both the list and
      // the detail are re-read before the user is asked again.
      expect(reads().list).toBe(before.list + 1)
      expect(reads().detail).toBe(before.detail + 1)

      await wrapper.find('#tracking-retry').trigger('click')
      await flushPromises()
      const bodies = retriedBodies()
      expect(bodies).toHaveLength(2)
      expect(bodies[1]?.expected_revision).toBe(9)
      expect(bodies[1]?.idempotency_key).not.toBe(bodies[0]?.idempotency_key)
      wrapper.unmount()
    }
  })

  it('never mints a new key through another action while the result is unresolved', async () => {
    let actions: unknown[] = [submitAction]
    const listValue = () => ({ items: [item('tracking-1', '葬送的芙莉莲')], summary: {}, warnings: [] })
    apiGet.mockImplementation((url: string) => Promise.resolve(
      (url === '/api/v1/tracking/items' ? listValue() : submitDetail({ available_actions: actions })) as never,
    ))
    apiPost.mockResolvedValueOnce(capabilities() as never)
      // The record is refreshed to RETRY while the SUBMIT result is unreadable.
      .mockImplementationOnce((async () => { actions = [revalidateAction, retryAction]; throw unknownError }) as never)
    const { wrapper } = await mountTracking({ tracking_id: 'tracking-1' })
    await connect(wrapper)
    answerConfirm(wrapper, true)
    await wrapper.find('#tracking-submit').trigger('click')
    await flushPromises()
    expect(wrapper.find('#tracking-submit-result').text()).toContain('提交结果未知')
    expect(wrapper.find('#tracking-retry').exists()).toBe(true)

    // The locked SUBMIT intent still owns the one key: replaying it under the
    // RETRY action would send something the user did not ask for, and a new key
    // could create a second subscription. Nothing at all is sent.
    const confirmSpy = answerConfirm(wrapper, true)
    await wrapper.find('#tracking-retry').trigger('click')
    await flushPromises()
    expect(confirmSpy).not.toHaveBeenCalled()
    expect(retriedBodies()).toHaveLength(0)
    expect(submittedBodies()).toHaveLength(1)
    expect(wrapper.find('#tracking-submit-result').text()).toContain('提交结果未知')
  })
})

const recoverAutoAction = {
  code: 'RECOVER_AUTO', label: '自动恢复', style: 'SECONDARY',
  requires_confirmation: false, target_scopes: [],
}
const markSucceededAction = {
  code: 'MARK_SUCCEEDED', label: '标记为成功', style: 'PRIMARY',
  requires_confirmation: true, target_scopes: [],
}
const markFailedAction = {
  code: 'MARK_FAILED', label: '标记为失败', style: 'DANGER',
  requires_confirmation: true, target_scopes: [],
}
const recoveryActions = [recoverAutoAction, markSucceededAction, markFailedAction]

/** A record the server says is recoverable (only the three local actions). */
function recoveryDetail(overrides: Record<string, unknown> = {}) {
  return {
    ...detail(), status: 'RECOVERY_REQUIRED', status_label: '需要恢复', status_group: 'ATTENTION',
    available_actions: recoveryActions, ...overrides,
  }
}

/** The authoritative recovery summary the recover endpoint returns. */
function recoverySummary(overrides: Record<string, unknown> = {}) {
  return {
    ...item('tracking-1', '葬送的芙莉莲'), status: 'RECOVERY_REQUIRED', status_label: '需要恢复',
    status_group: 'ATTENTION', revision: 2, available_actions: recoveryActions, ...overrides,
  }
}

function recoveryPayload(overrides: Record<string, unknown> = {}) {
  return {
    tracking_id: 'tracking-1', action: 'AUTO', outcome: 'ACTIVE', checked_revision: 1, next_revision: 2,
    checked_at: '2026-09-13T05:00:00Z', operation_id: 'operation-1', needs_manual: false,
    tracking: recoverySummary({ status: 'ACTIVE', status_label: '追番中', status_group: 'ACTIVE' }),
    ...overrides,
  }
}

function recoveredBodies(): Record<string, unknown>[] {
  return apiPost.mock.calls
    .filter((call) => call[0] === '/api/v1/tracking/items/{tracking_id}/recover')
    .map((call) => (call[1]?.body ?? {}) as Record<string, unknown>)
}

function clickDialogButton(label: string): void {
  const button = Array.from(document.querySelectorAll<HTMLButtonElement>('.confirm-dialog-actions button'))
    .find((candidate) => candidate.textContent?.includes(label))
  if (!button) throw new Error(`no confirm-dialog button labelled ${label}`)
  button.click()
}

describe('TrackingView unknown-result recovery (US-312)', () => {
  beforeEach(() => { apiGet.mockReset(); apiPost.mockReset() })

  it('recovers locally with no credential, no confirmation and no external write', async () => {
    serveApi(() => recoveryDetail({ revision: 4 }))
    apiPost.mockResolvedValueOnce(recoveryPayload({
      checked_revision: 4, next_revision: 5,
      tracking: recoverySummary({ status: 'ACTIVE', status_label: '已恢复', status_group: 'ACTIVE', revision: 5 }),
    }) as never)
    const { wrapper } = await mountTracking({ tracking_id: 'tracking-1' })
    const confirmSpy = answerConfirm(wrapper, true)
    expect(wrapper.find('#tracking-recover-auto').exists()).toBe(true)

    await wrapper.find('#tracking-recover-auto').trigger('click')
    await flushPromises()

    // AUTO contacts nothing: no confirmation, no credential, no other endpoint.
    expect(confirmSpy).not.toHaveBeenCalled()
    expect(apiPost).toHaveBeenCalledTimes(1)
    expect(apiPost).toHaveBeenLastCalledWith('/api/v1/tracking/items/{tracking_id}/recover', {
      path: { tracking_id: 'tracking-1' },
      body: { expected_revision: 4, action: 'AUTO' },
      signal: expect.any(AbortSignal),
    })
    const result = wrapper.find('#tracking-recovery-result')
    expect(result.text()).toContain('恢复完成')
    expect(result.text()).not.toContain('ACTIVE')
    // The returned tracking converges the list row without a page reload.
    expect(wrapper.find('.tracking-list-item').text()).toContain('已恢复')
  })

  it('confirms every manual verdict again, defaults the focus on cancel and sends no external evidence', async () => {
    let recovered = false
    serveApi(() => (recovered
      ? {
          ...recoveryDetail(), status: 'SUBMIT_FAILED', status_label: '提交失败',
          available_actions: [revalidateAction, retryAction],
        }
      : recoveryDetail()))
    apiPost.mockResolvedValueOnce(capabilities() as never)
      .mockImplementationOnce((async () => {
        recovered = true
        return recoveryPayload({
          action: 'MARK_FAILED', outcome: 'SUBMIT_FAILED',
          tracking: recoverySummary({
            status: 'SUBMIT_FAILED', status_label: '提交失败', available_actions: [revalidateAction, retryAction],
          }),
        })
      }) as never)
    const { wrapper } = await mountTracking({ tracking_id: 'tracking-1' })
    await connect(wrapper)

    await wrapper.find('#tracking-recover-failed').trigger('click')
    await flushPromises()
    // A manual verdict is never inferred by one click.
    expect(recoveredBodies()).toHaveLength(0)
    await new Promise((resolve) => requestAnimationFrame(resolve))
    expect(document.querySelector('.confirm-dialog')?.textContent).toContain('独立核对')
    expect(document.activeElement).toBe(wrapper.find('.confirm-dialog .secondary-button').element)
    clickDialogButton('取消')
    await flushPromises()
    expect(recoveredBodies()).toHaveLength(0)
    expect(wrapper.find('#tracking-recovery-result').exists()).toBe(false)

    await wrapper.find('#tracking-recover-failed').trigger('click')
    await flushPromises()
    await new Promise((resolve) => requestAnimationFrame(resolve))
    clickDialogButton('确认标记失败')
    await flushPromises()

    // The body carries the verdict and nothing else: no external id/URL/raw
    // result/note can even be expressed.
    expect(recoveredBodies()).toEqual([{ expected_revision: 1, action: 'MARK_FAILED', confirm: true }])
    expect(wrapper.find('#tracking-recovery-result').text()).toContain('恢复完成')
    // The recovered record is re-read, so its next legitimate action appears.
    expect(wrapper.find('#tracking-retry').exists()).toBe(true)
  })

  it('verifies externally read-only with the live page session only', async () => {
    serveApi(() => recoveryDetail())
    apiPost.mockResolvedValueOnce(capabilities() as never)
      .mockResolvedValueOnce(recoveryPayload({ action: 'VERIFY_EXTERNAL' }) as never)
    const { wrapper } = await mountTracking({ tracking_id: 'tracking-1' })
    // No page session: the read-only external check is not offered at all.
    expect(wrapper.find('#tracking-recover-verify').exists()).toBe(false)
    // The local actions stay available without it.
    expect(wrapper.find('#tracking-recover-auto').exists()).toBe(true)
    expect(wrapper.find('#tracking-recover-succeeded').exists()).toBe(true)

    await connect(wrapper)
    answerConfirm(wrapper, true)
    await wrapper.find('#tracking-recover-verify').trigger('click')
    await flushPromises()

    expect(recoveredBodies()).toEqual([{
      expected_revision: 1,
      action: 'VERIFY_EXTERNAL',
      ab_config: {
        auth_mode: 'password', base_url: 'https://ab.invalid', username: 'user',
        password: 'pass', fallback_enabled: false,
      },
    }])
    // Only the probe and the read-only verification ever reached the server.
    expect(apiPost.mock.calls.map((call) => call[0]))
      .toEqual(['/api/v1/autobangumi/capabilities', '/api/v1/tracking/items/{tracking_id}/recover'])
    expect(wrapper.find('#tracking-recovery-result').text()).toContain('恢复完成')
    expect(wrapper.text()).not.toContain('VERIFY_EXTERNAL')
  })

  it('keeps the recovery state and only reads back when the result is unknown', async () => {
    serveApi(() => recoveryDetail({ revision: 2 }))
    apiPost.mockRejectedValueOnce(unknownError as never)
    const { wrapper } = await mountTracking({ tracking_id: 'tracking-1' })
    const readsBefore = apiGet.mock.calls.length

    await wrapper.find('#tracking-recover-auto').trigger('click')
    await flushPromises()

    const result = wrapper.find('#tracking-recovery-result')
    expect(result.classes()).toContain('is-unknown')
    expect(result.text()).toContain('恢复结果未知')
    expect(result.text()).toContain('只读回查')
    expect(wrapper.text()).not.toContain('network_error')
    // Exactly one recovery reached the server, and it was never resent.
    expect(recoveredBodies()).toHaveLength(1)
    expect(recoveredBodies()[0]).toEqual({ expected_revision: 2, action: 'AUTO' })
    expect(result.text()).not.toContain('恢复完成')
    // The page only re-read the server state, including the list.
    expect(apiGet.mock.calls.filter((call) => call[0] === '/api/v1/tracking/items').length).toBeGreaterThan(1)
    expect(apiGet.mock.calls.length).toBeGreaterThan(readsBefore)

    // The user may explicitly recover again; nothing is replayed automatically.
    apiPost.mockResolvedValueOnce(recoveryPayload({ checked_revision: 2, next_revision: 3 }) as never)
    await wrapper.find('#tracking-recover-auto').trigger('click')
    await flushPromises()
    expect(recoveredBodies()).toHaveLength(2)
    expect(wrapper.find('#tracking-recovery-result').text()).toContain('恢复完成')
  })

  it('never reads an undocumented outcome as success', async () => {
    for (const outcome of ['DISABLED', 'EXTERNAL_DELETED']) {
      apiGet.mockReset()
      apiPost.mockReset()
      serveApi(() => recoveryDetail())
      apiPost.mockResolvedValueOnce(capabilities() as never)
        .mockResolvedValueOnce(recoveryPayload({ action: 'VERIFY_EXTERNAL', outcome: outcome as never }) as never)
      const { wrapper } = await mountTracking({ tracking_id: 'tracking-1' })
      await connect(wrapper)
      answerConfirm(wrapper, true)
      await wrapper.find('#tracking-recover-verify').trigger('click')
      await flushPromises()

      const result = wrapper.find('#tracking-recovery-result')
      expect(result.classes()).toContain('is-unknown')
      expect(result.text()).not.toContain('恢复完成')
      expect(wrapper.text()).not.toContain(outcome)
      wrapper.unmount()
    }
  })

  it('converges a conflicting recovery on the server state and asks again', async () => {
    let revision = 1
    serveApi(() => recoveryDetail({ revision }))
    apiPost.mockImplementationOnce((async () => { revision = 6; throw conflictError }) as never)
      .mockResolvedValueOnce(recoveryPayload({ checked_revision: 6, next_revision: 7 }) as never)
    const { wrapper } = await mountTracking({ tracking_id: 'tracking-1' })
    const listReadsBefore = apiGet.mock.calls.filter((call) => call[0] === '/api/v1/tracking/items').length

    await wrapper.find('#tracking-recover-auto').trigger('click')
    await flushPromises()

    const result = wrapper.find('#tracking-recovery-result')
    expect(result.classes()).toContain('is-conflict')
    expect(result.text()).toContain('本次未执行恢复')
    expect(result.text()).toContain('请重新确认')
    expect(wrapper.text()).not.toContain('tracking_revision_conflict')
    expect(wrapper.text()).not.toContain('"current_revision"')
    // Nothing was silently resent; both the list and the detail were re-read.
    expect(recoveredBodies()).toHaveLength(1)
    expect(apiGet.mock.calls.filter((call) => call[0] === '/api/v1/tracking/items').length)
      .toBeGreaterThan(listReadsBefore)

    await wrapper.find('#tracking-recover-auto').trigger('click')
    await flushPromises()
    expect(recoveredBodies()).toHaveLength(2)
    expect(recoveredBodies()[1]?.expected_revision).toBe(6)
  })

  it('keeps submit and retry locked while a recovery still needs a manual verdict', async () => {
    const trackingTwoDetail = {
      ...detail(), tracking_id: 'tracking-2', request_id: 'request-tracking-2', title: '咒术回战',
      status: 'SUBMIT_FAILED', status_label: '提交失败', status_group: 'ATTENTION', revision: 7,
      available_actions: [retryAction],
    }
    let currentDetail: unknown = recoveryDetail()
    apiGet.mockImplementation((url: string) => Promise.resolve(
      (url === '/api/v1/tracking/items'
        ? { items: [item('tracking-1', '葬送的芙莉莲'), item('tracking-2', '咒术回战', 'ATTENTION')], summary: {}, warnings: [] }
        : currentDetail) as never,
    ))
    apiPost.mockResolvedValueOnce(capabilities() as never)
      // AUTO cannot conclude from local evidence: only a human may decide.
      .mockResolvedValueOnce(recoveryPayload({ outcome: 'RECOVERY_REQUIRED', needs_manual: true }) as never)
      .mockResolvedValueOnce(recoveryPayload({
        action: 'MARK_SUCCEEDED',
        tracking: recoverySummary({ status: 'ACTIVE', status_label: '已恢复', status_group: 'ACTIVE', revision: 3,
          available_actions: [] }),
      }) as never)
      .mockResolvedValueOnce(submitPayload({
        tracking_id: 'tracking-2', tracking: { ...item('tracking-2', '咒术回战'), revision: 9 },
      }) as never)
    const { wrapper } = await mountTracking({ tracking_id: 'tracking-1' })
    await connect(wrapper)

    await wrapper.find('#tracking-recover-auto').trigger('click')
    await flushPromises()
    expect(wrapper.find('#tracking-recovery-manual-notice').text()).toContain('先在 Auto Bangumi 中独立核对')
    expect(wrapper.find('#tracking-recovery-result').classes()).toContain('is-recovery_required')

    // The unresolved recovery still owns the page intent: another record's
    // retry must stay locked (D38-09.4).
    currentDetail = trackingTwoDetail
    await wrapper.findAll('.tracking-list-item')[1]?.trigger('click')
    await flushPromises()
    expect(wrapper.find('#tracking-retry').attributes('disabled')).toBeDefined()
    await wrapper.find('#tracking-retry').trigger('click')
    await flushPromises()
    // A locked action opens no dialog and sends nothing at all.
    expect(wrapper.find('.confirm-dialog').exists()).toBe(false)
    expect(recoveredBodies()).toHaveLength(1)
    expect(wrapper.find('#tracking-recovery-result').exists()).toBe(false)

    // The manual verdict is the only way out; once it lands the lock is gone.
    currentDetail = recoveryDetail({ revision: 2 })
    await wrapper.findAll('.tracking-list-item')[0]?.trigger('click')
    await flushPromises()
    expect(wrapper.find('#tracking-recovery-manual-notice').exists()).toBe(true)
    await wrapper.find('#tracking-recover-succeeded').trigger('click')
    await flushPromises()
    await new Promise((resolve) => requestAnimationFrame(resolve))
    clickDialogButton('确认标记成功')
    await flushPromises()
    expect(wrapper.find('#tracking-recovery-result').text()).toContain('恢复完成')

    // With the verdict landed the lock is gone: the other record may retry.
    currentDetail = trackingTwoDetail
    await wrapper.findAll('.tracking-list-item')[1]?.trigger('click')
    await flushPromises()
    expect(wrapper.find('#tracking-retry').attributes('disabled')).toBeUndefined()
    await wrapper.find('#tracking-retry').trigger('click')
    await flushPromises()
    clickDialogButton('确认重试')
    await flushPromises()
    expect(recoveredBodies().map((body) => body.action)).toEqual(['AUTO', 'MARK_SUCCEEDED'])
    expect(apiPost).toHaveBeenLastCalledWith('/api/v1/tracking/items/{tracking_id}/retry', expect.objectContaining({
      path: { tracking_id: 'tracking-2' },
    }))
  })

  it('aborts an in-flight recovery when the page connection is cleared', async () => {
    let resolveRecover: ((value: unknown) => void) | undefined
    serveApi(() => recoveryDetail({ revision: 1 }))
    apiPost.mockResolvedValueOnce(capabilities() as never)
      .mockReturnValueOnce(new Promise((resolve) => { resolveRecover = resolve }) as never)
    const { wrapper } = await mountTracking({ tracking_id: 'tracking-1' })
    await connect(wrapper)
    answerConfirm(wrapper, true)

    await wrapper.find('#tracking-recover-verify').trigger('click')
    await flushPromises()
    expect(recoveredBodies()).toHaveLength(1)

    await wrapper.find('.tracking-clear-connection').trigger('click')
    await flushPromises()
    resolveRecover?.(recoveryPayload({ action: 'VERIFY_EXTERNAL' }))
    await flushPromises()
    // The cleared session keeps a safe unknown lock: no stale result is
    // rendered, and the list is never rewritten by the response.
    expect(wrapper.find('#tracking-recovery-result').text()).toContain('恢复结果未知')
    expect(wrapper.find('.tracking-connection-status').exists()).toBe(false)
  })
})

const modifyAction = {
  code: 'MODIFY', label: '修改外部方案', style: 'SECONDARY',
  requires_confirmation: true, target_scopes: ['SUBSCRIPTION', 'ASSOCIATED_RSS'],
}

function modifyDetail(overrides: Record<string, unknown> = {}) {
  return {
    ...detail(),
    available_actions: [revalidateAction, modifyAction],
    external_mapping: { match_reason: '标题与季度匹配', enabled: true, external_deleted: false },
    ...overrides,
  }
}

/** The authoritative management summary the modify endpoint returns. */
function modifyPayload(overrides: Record<string, unknown> = {}) {
  return {
    action: 'MODIFY', management_status: 'SUCCEEDED', needs_manual: false,
    safe_message: 'Auto Bangumi 管理操作已完成并通过回查', operation_id: 'operation-1', operation: null,
    tracking: { ...item('tracking-1', '葬送的芙莉莲'), status_label: '已修改', revision: 2 },
    ...overrides,
  }
}

function modifiedBodies(): Record<string, unknown>[] {
  return apiPost.mock.calls
    .filter((call) => call[0] === '/api/v1/tracking/items/{tracking_id}/modify')
    .map((call) => (call[1]?.body ?? {}) as Record<string, unknown>)
}

describe('TrackingView external modify (US-313)', () => {
  beforeEach(() => { apiGet.mockReset(); apiPost.mockReset() })

  it('never offers a modify form without a live session or the proven capability', async () => {
    serveApi(() => modifyDetail())
    apiPost.mockResolvedValueOnce(capabilities())
    const { wrapper } = await mountTracking({ tracking_id: 'tracking-1' })
    // No page credential session yet: no form, no request.
    expect(wrapper.find('#tracking-modify-subscription-submit').exists()).toBe(false)
    expect(wrapper.find('#tracking-modify-rss-submit').exists()).toBe(false)
    expect(wrapper.text()).toContain('需要先在页面连接 Auto Bangumi')

    await connect(wrapper)
    // Connecting must never modify anything on the user's behalf.
    expect(modifiedBodies()).toHaveLength(0)
    expect(wrapper.find('#tracking-modify-subscription-submit').exists()).toBe(true)
    expect(wrapper.find('#tracking-modify-rss-submit').exists()).toBe(true)
  })

  it('shows only the scopes the server and the live capability both allow', async () => {
    serveApi(() => modifyDetail({
      available_actions: [modifyAction],
    }))
    // The session proves only the subscription modify capability.
    apiPost.mockResolvedValueOnce(capabilities({ rss_modify: 'UNSUPPORTED' }))
    const { wrapper } = await mountTracking({ tracking_id: 'tracking-1' })
    await connect(wrapper)
    expect(wrapper.find('#tracking-modify-subscription-submit').exists()).toBe(true)
    // The RSS scope is dropped entirely: no form, no scope label.
    expect(wrapper.find('#tracking-modify-rss-submit').exists()).toBe(false)
    expect(wrapper.find('.tracking-modify-scope').text()).toBe('外部番剧订阅')
    expect(wrapper.text()).not.toContain('ASSOCIATED_RSS')
    expect(wrapper.text()).not.toContain('SUBSCRIPTION')
  })

  it('keeps the two scope forms apart and sends only the selected scope patch', async () => {
    serveApi(() => modifyDetail())
    apiPost.mockResolvedValueOnce(capabilities()).mockResolvedValueOnce(modifyPayload())
    const { wrapper } = await mountTracking({ tracking_id: 'tracking-1' })
    await connect(wrapper)

    // Nothing selected: the submit control is disabled and sends nothing.
    await wrapper.find('#tracking-modify-subscription-submit').trigger('submit')
    await flushPromises()
    expect(wrapper.find('#tracking-modify-subscription-submit').attributes('disabled')).toBeDefined()
    expect(modifiedBodies()).toHaveLength(0)

    await wrapper.find('#tracking-modify-title-enabled').setValue(true)
    await wrapper.find('#tracking-modify-title').setValue('新标题')
    await wrapper.find('#tracking-modify-season-enabled').setValue(true)
    await wrapper.find('#tracking-modify-season').setValue('2')
    expect(wrapper.find('#tracking-modify-subscription-submit').attributes('disabled')).toBeUndefined()

    answerConfirm(wrapper, false)
    await wrapper.find('#tracking-modify-subscription-submit').trigger('submit')
    await flushPromises()
    // Cancelling the impact confirmation sends zero requests.
    expect(modifiedBodies()).toHaveLength(0)

    answerConfirm(wrapper, true)
    await wrapper.find('#tracking-modify-subscription-submit').trigger('submit')
    await flushPromises()
    const bodies = modifiedBodies()
    expect(bodies).toHaveLength(1)
    expect(bodies[0]?.target_scope).toBe('SUBSCRIPTION')
    expect(bodies[0]?.patch).toEqual({ title: '新标题', season: 2 })
    expect(bodies[0]?.expected_revision).toBe(1)
    expect(bodies[0]?.confirm).toBe(true)
    expect(bodies[0]?.ab_config).toMatchObject({ base_url: 'https://ab.invalid', password: 'pass' })
    expect(typeof bodies[0]?.idempotency_key).toBe('string')
    // The RSS form never contributed a field to the subscription request.
    expect(JSON.stringify(bodies[0]?.patch)).not.toContain('name')
    // The returned tracking converges the list row.
    expect(wrapper.find('.tracking-list-item').text()).toContain('已修改')
    expect(wrapper.text()).not.toContain('SUCCEEDED')
    expect(wrapper.text()).not.toContain('pass')
  })

  it('sends the RSS scope through its own form and its own patch shape', async () => {
    serveApi(() => modifyDetail())
    apiPost.mockResolvedValueOnce(capabilities()).mockResolvedValueOnce(modifyPayload())
    const { wrapper } = await mountTracking({ tracking_id: 'tracking-1' })
    await connect(wrapper)

    await wrapper.find('#tracking-modify-rss-name-enabled').setValue(true)
    await wrapper.find('#tracking-modify-rss-name').setValue('新 RSS 名称')
    await wrapper.find('#tracking-modify-rss-aggregate-enabled').setValue(true)
    await wrapper.find('#tracking-modify-rss-aggregate').setValue('true')
    answerConfirm(wrapper, true)
    await wrapper.find('#tracking-modify-rss-submit').trigger('submit')
    await flushPromises()

    const bodies = modifiedBodies()
    expect(bodies).toHaveLength(1)
    expect(bodies[0]?.target_scope).toBe('ASSOCIATED_RSS')
    expect(bodies[0]?.patch).toEqual({ name: '新 RSS 名称', aggregate: true })
    expect(JSON.stringify(bodies[0]?.patch)).not.toContain('title')
  })

  it('refuses an empty patch and unsafe values instead of sending them', async () => {
    serveApi(() => modifyDetail())
    apiPost.mockResolvedValueOnce(capabilities()).mockResolvedValueOnce(modifyPayload())
    const { wrapper } = await mountTracking({ tracking_id: 'tracking-1' })
    await connect(wrapper)

    // Switching the filter rule on without any term is still a valid rule (the
    // two switches travel with it), so it is a legal patch.
    await wrapper.find('#tracking-modify-filter-enabled').setValue(true)
    expect(wrapper.find('#tracking-modify-subscription-submit').attributes('disabled')).toBeUndefined()

    // A URL is refused by the page exactly like the server would refuse it.
    await wrapper.find('#tracking-modify-title-enabled').setValue(true)
    await wrapper.find('#tracking-modify-title').setValue('https://private.invalid')
    await nextTick()
    expect(wrapper.find('#tracking-modify-subscription-submit').attributes('disabled')).toBeDefined()
    expect(wrapper.find('.tracking-modify').text()).toContain('请至少勾选一个要修改的字段')
    expect(wrapper.find('.tracking-modify').text()).not.toContain('private.invalid')

    // The unsafe value never reaches the form state either.
    await wrapper.find('#tracking-modify-title').setValue('安全标题')
    await wrapper.find('#tracking-modify-season-enabled').setValue(true)
    await wrapper.find('#tracking-modify-season').setValue('2')
    expect(wrapper.find('#tracking-modify-subscription-submit').attributes('disabled')).toBeUndefined()

    answerConfirm(wrapper, true)
    await wrapper.find('#tracking-modify-subscription-submit').trigger('submit')
    await flushPromises()
    const bodies = modifiedBodies()
    expect(bodies).toHaveLength(1)
    expect(bodies[0]?.patch).toEqual({
      title: '安全标题', season: 2, filter_rule: { use_regex: false, case_sensitive: false },
    })
  })

  it('locks the intent on an unknown result and rejects a mismatching second request', async () => {
    serveApi(() => modifyDetail())
    apiPost.mockResolvedValueOnce(capabilities())
      .mockRejectedValueOnce(unknownError)
      .mockResolvedValueOnce(modifyPayload())
    const { wrapper } = await mountTracking({ tracking_id: 'tracking-1' })
    await connect(wrapper)

    await wrapper.find('#tracking-modify-title-enabled').setValue(true)
    await wrapper.find('#tracking-modify-title').setValue('第一次修改')
    answerConfirm(wrapper, true)
    await wrapper.find('#tracking-modify-subscription-submit').trigger('submit')
    await flushPromises()

    const result = wrapper.find('#tracking-modify-result')
    expect(result.text()).toContain('外部修改结果未知')
    expect(result.text()).toContain('只读回查')
    expect(result.text()).not.toContain('network_error')
    expect(modifiedBodies()).toHaveLength(1)

    // A different scope while the result is unresolved sends nothing at all.
    await wrapper.find('#tracking-modify-rss-name-enabled').setValue(true)
    await wrapper.find('#tracking-modify-rss-name').setValue('不该发送')
    await wrapper.find('#tracking-modify-rss-submit').trigger('submit')
    await flushPromises()
    expect(modifiedBodies()).toHaveLength(1)
    // The refusal is no longer silent: a fixed Chinese next step explains it,
    // without overwriting the unresolved result panel.
    const notice = wrapper.find('#tracking-intent-blocked-notice')
    expect(notice.exists()).toBe(true)
    expect(notice.attributes('role')).toBe('status')
    expect(notice.text()).toContain('上一次外部操作的结果仍未确认')
    expect(notice.text()).toContain('只读回查')
    expect(notice.text()).not.toContain('清除连接')
    expect(notice.text()).not.toContain('network_error')
    expect(wrapper.find('#tracking-modify-result').text()).toContain('外部修改结果未知')

    // The very same intent replays with the same key and revision binding: the
    // user re-selects the identical field set, so the page recognises the same
    // intent and reuses the locked key instead of minting a new one.
    await wrapper.find('#tracking-modify-title-enabled').setValue(true)
    await wrapper.find('#tracking-modify-title').setValue('第一次修改')
    await wrapper.find('.tracking-modify-form').trigger('submit')
    await flushPromises()
    const bodies = modifiedBodies()
    expect(bodies).toHaveLength(2)
    expect(bodies[1]?.idempotency_key).toBe(bodies[0]?.idempotency_key)
    expect(bodies[1]?.expected_revision).toBe(bodies[0]?.expected_revision)
    expect(bodies[1]?.patch).toEqual(bodies[0]?.patch)
    expect(wrapper.find('#tracking-modify-result').text()).toContain('已应用本次修改')
    // Replaying the same intent ends the refusal, so the notice disappears.
    expect(wrapper.find('#tracking-intent-blocked-notice').exists()).toBe(false)
  })

  it('releases the intent on a conflict and requires a fresh confirmation', async () => {
    let revision = 1
    serveApi(() => modifyDetail({ revision }))
    apiPost.mockResolvedValueOnce(capabilities())
      // The record moves on while the modify is in flight.
      .mockImplementationOnce((async () => { revision = 9; throw conflictError }) as never)
      .mockResolvedValueOnce(modifyPayload())
    const { wrapper } = await mountTracking({ tracking_id: 'tracking-1' })
    await connect(wrapper)
    const before = reads()

    await wrapper.find('#tracking-modify-title-enabled').setValue(true)
    await wrapper.find('#tracking-modify-title').setValue('冲突修改')
    answerConfirm(wrapper, true)
    await wrapper.find('#tracking-modify-subscription-submit').trigger('submit')
    await flushPromises()

    const result = wrapper.find('#tracking-modify-result')
    expect(result.text()).toContain('未提交到 Auto Bangumi')
    expect(result.text()).toContain('重新确认')
    expect(result.text()).not.toContain('tracking_revision_conflict')
    expect(modifiedBodies()).toHaveLength(1)
    // Both the list and the detail were re-read, and nothing was resent.
    expect(reads().list).toBe(before.list + 1)
    expect(reads().detail).toBe(before.detail + 1)

    // The conflict released the intent: the next confirmation is a brand new
    // one, so the user selects the field again against the fresh revision.
    await wrapper.find('#tracking-modify-title-enabled').setValue(true)
    await wrapper.find('#tracking-modify-title').setValue('重试修改')
    answerConfirm(wrapper, true)
    await wrapper.find('#tracking-modify-subscription-submit').trigger('submit')
    await flushPromises()
    const bodies = modifiedBodies()
    expect(bodies).toHaveLength(2)
    expect(bodies[1]?.idempotency_key).not.toBe(bodies[0]?.idempotency_key)
    expect(bodies[1]?.expected_revision).toBe(9)
  })

  it('treats a structured non-409 4xx as a definite refusal and frees the page lock', async () => {
    serveApi(() => modifyDetail())
    apiPost.mockResolvedValueOnce(capabilities())
      .mockRejectedValueOnce(rejectedError)
      .mockResolvedValueOnce(modifyPayload())
    const { wrapper } = await mountTracking({ tracking_id: 'tracking-1' })
    await connect(wrapper)

    await wrapper.find('#tracking-modify-title-enabled').setValue(true)
    await wrapper.find('#tracking-modify-title').setValue('被拒绝的修改')
    answerConfirm(wrapper, true)
    await wrapper.find('#tracking-modify-subscription-submit').trigger('submit')
    await flushPromises()

    const result = wrapper.find('#tracking-modify-result')
    expect(result.classes()).toContain('is-rejected')
    expect(result.text()).toContain('本次未修改 Auto Bangumi 外部订阅')
    expect(wrapper.text()).not.toContain('结果未知')
    expect(modifiedBodies()).toHaveLength(1)

    // The refusal released the page intent: a new confirmation mints a new key,
    // so the user selects the field again.
    await wrapper.find('#tracking-modify-title-enabled').setValue(true)
    await wrapper.find('#tracking-modify-title').setValue('再次修改')
    answerConfirm(wrapper, true)
    await wrapper.find('#tracking-modify-subscription-submit').trigger('submit')
    await flushPromises()
    const bodies = modifiedBodies()
    expect(bodies).toHaveLength(2)
    expect(bodies[1]?.idempotency_key).not.toBe(bodies[0]?.idempotency_key)
  })

  it('clears the page modify state when the connection is cleared', async () => {
    let resolveModify: ((value: unknown) => void) | undefined
    serveApi(() => modifyDetail())
    apiPost.mockResolvedValueOnce(capabilities())
      .mockReturnValueOnce(new Promise((resolve) => { resolveModify = resolve }) as never)
    const { wrapper } = await mountTracking({ tracking_id: 'tracking-1' })
    await connect(wrapper)

    await wrapper.find('#tracking-modify-title-enabled').setValue(true)
    await wrapper.find('#tracking-modify-title').setValue('飞行中的修改')
    answerConfirm(wrapper, true)
    await wrapper.find('#tracking-modify-subscription-submit').trigger('submit')
    await flushPromises()
    expect(modifiedBodies()).toHaveLength(1)

    await wrapper.find('.tracking-clear-connection').trigger('click')
    await flushPromises()
    resolveModify?.(modifyPayload({ tracking: { ...item('tracking-1', '葬送的芙莉莲'), status_label: '不应写回' } }))
    await flushPromises()
    expect(wrapper.find('#tracking-modify-result').text()).toContain('外部修改结果未知')
    expect(wrapper.text()).not.toContain('不应写回')
    expect(wrapper.find('.tracking-connection-status').exists()).toBe(false)
  })
})

const setEnabledAction = {
  code: 'SET_ENABLED', label: '停用外部订阅', style: 'SECONDARY',
  requires_confirmation: true, target_scopes: ['SUBSCRIPTION', 'ASSOCIATED_RSS'],
}
const enableAction = { ...setEnabledAction, label: '启用外部订阅', style: 'PRIMARY' }
const refreshAction = {
  code: 'REFRESH_RSS', label: '刷新关联 RSS', style: 'SECONDARY',
  requires_confirmation: true, target_scopes: ['ASSOCIATED_RSS'],
}

/** A detail record that offers the two US-314 management actions. */
function actionDetail(overrides: Record<string, unknown> = {}) {
  return {
    ...modifyDetail(),
    available_actions: [setEnabledAction, refreshAction],
    ...overrides,
  }
}

/** The authoritative summary either US-314 endpoint returns. */
function actionPayload(action: string, overrides: Record<string, unknown> = {}) {
  return {
    action, management_status: 'SUCCEEDED', needs_manual: false,
    safe_message: 'Auto Bangumi 管理操作已完成并通过回查', operation_id: 'operation-actions',
    operation: null,
    tracking: { ...item('tracking-1', '葬送的芙莉莲'), status_label: '已停用', revision: 2 },
    ...overrides,
  }
}

function postedBodies(endpoint: string): Record<string, unknown>[] {
  return apiPost.mock.calls
    .filter((call) => call[0] === endpoint)
    .map((call) => (call[1]?.body ?? {}) as Record<string, unknown>)
}

function actionEndpoints(): string[] {
  return apiPost.mock.calls
    .map((call) => String(call[0]))
    .filter((path) => path !== '/api/v1/autobangumi/capabilities')
}

describe('TrackingView external enable and RSS refresh (US-314)', () => {
  beforeEach(() => { apiGet.mockReset(); apiPost.mockReset() })

  it('never offers enable or refresh without a live session or the proven capability', async () => {
    serveApi(() => actionDetail())
    apiPost.mockResolvedValueOnce(capabilities())
    const { wrapper } = await mountTracking({ tracking_id: 'tracking-1' })
    // No page credential session yet: neither action is rendered, no request.
    expect(wrapper.find('#tracking-set-enabled-submit').exists()).toBe(false)
    expect(wrapper.find('#tracking-refresh-rss-submit').exists()).toBe(false)
    expect(wrapper.find('.tracking-management-actions-section').text()).toContain('需要先在页面连接 Auto Bangumi')

    await connect(wrapper)
    // Connecting never enables, disables or refreshes anything on its own.
    expect(actionEndpoints()).toEqual([])
    expect(wrapper.find('#tracking-set-enabled-submit').exists()).toBe(true)
    expect(wrapper.find('#tracking-refresh-rss-submit').exists()).toBe(true)
  })

  it('requires an explicit enable/disable target and sends only that scope', async () => {
    serveApi(() => actionDetail())
    apiPost.mockResolvedValueOnce(capabilities()).mockResolvedValueOnce(actionPayload('SET_ENABLED'))
    const { wrapper } = await mountTracking({ tracking_id: 'tracking-1' })
    await connect(wrapper)

    const section = wrapper.find('.tracking-management-actions-section')
    expect(section.text()).toContain('外部番剧订阅')
    expect(section.text()).toContain('关联 RSS')
    expect(section.text()).not.toContain('ASSOCIATED_RSS')
    expect(section.text()).not.toContain('SUBSCRIPTION')
    // No target is pre-selected: the choice is the user's.
    expect(wrapper.find('#tracking-set-enabled-submit').attributes('disabled')).toBeDefined()
    expect(section.text()).toContain('请先明确选择启停目标')

    await wrapper.find('#tracking-set-enabled-scope-ASSOCIATED_RSS').setValue()
    expect(wrapper.find('#tracking-set-enabled-submit').attributes('disabled')).toBeUndefined()
    const confirmed = answerConfirm(wrapper, true)
    await wrapper.find('#tracking-set-enabled-submit').trigger('submit')
    await flushPromises()

    // The confirmation names the action, the scope and the direction actually
    // taken from the record's status, and says it only affects Auto Bangumi.
    const options = confirmed.mock.calls[0]?.[0] as { title: string; message: string; confirmLabel: string }
    expect(options.confirmLabel).toBe('确认停用 RSS')
    expect(options.message).toContain('只影响 Auto Bangumi 外部 RSS')
    expect(options.message).toContain('不修改 MiGuOrca 本地方案')

    const bodies = postedBodies('/api/v1/tracking/items/{tracking_id}/set-enabled')
    expect(bodies).toHaveLength(1)
    expect(bodies[0]).toEqual({
      target_scope: 'ASSOCIATED_RSS',
      enabled: false,
      expected_revision: 1,
      idempotency_key: expect.any(String),
      confirm: true,
      ab_config: {
        auth_mode: 'password', base_url: 'https://ab.invalid', username: 'user',
        password: 'pass', fallback_enabled: false,
      },
    })
    // The body cannot express a patch, an external id or the other scope.
    expect(Object.keys(bodies[0] ?? {}).sort()).toEqual(
      ['target_scope', 'enabled', 'expected_revision', 'idempotency_key', 'confirm', 'ab_config'].sort(),
    )
    expect(wrapper.find('#tracking-management-result').text()).toContain('外部启停已完成')
    expect(wrapper.find('#tracking-list-container').text()).toContain('已停用')
    expect(wrapper.text()).not.toContain('pass')
    expect(wrapper.text()).not.toContain(String(bodies[0]?.idempotency_key))
  })

  it('derives the enable direction from the record status, not from the button', async () => {
    serveApi(() => actionDetail({
      status: 'DISABLED', status_label: '已停用', available_actions: [enableAction, refreshAction],
    }))
    apiPost.mockResolvedValueOnce(capabilities()).mockResolvedValueOnce(actionPayload('SET_ENABLED'))
    const { wrapper } = await mountTracking({ tracking_id: 'tracking-1' })
    await connect(wrapper)

    await wrapper.find('#tracking-set-enabled-scope-SUBSCRIPTION').setValue()
    const confirmed = answerConfirm(wrapper, true)
    await wrapper.find('#tracking-set-enabled-submit').trigger('submit')
    await flushPromises()
    expect((confirmed.mock.calls[0]?.[0] as { confirmLabel: string }).confirmLabel).toBe('确认启用订阅')
    expect(postedBodies('/api/v1/tracking/items/{tracking_id}/set-enabled')[0]).toMatchObject({
      target_scope: 'SUBSCRIPTION', enabled: true,
    })
  })

  it('drops the scope whose own direction capability is not proven', async () => {
    serveApi(() => actionDetail())
    // The session proves only the subscription disable capability.
    apiPost.mockResolvedValueOnce(capabilities({ rss_disable: 'UNSUPPORTED' }))
    const { wrapper } = await mountTracking({ tracking_id: 'tracking-1' })
    await connect(wrapper)
    expect(wrapper.find('#tracking-set-enabled-scope-SUBSCRIPTION').exists()).toBe(true)
    expect(wrapper.find('#tracking-set-enabled-scope-ASSOCIATED_RSS').exists()).toBe(false)

    // A proven enable capability cannot stand in for the disable direction, and
    // an unproven refresh hides the refresh action entirely.
    apiPost.mockReset()
    apiPost.mockResolvedValueOnce(capabilities({ rss_refresh: 'UNKNOWN' }))
    const second = await mountTracking({ tracking_id: 'tracking-1' })
    await connect(second.wrapper)
    expect(second.wrapper.find('#tracking-refresh-rss-submit').exists()).toBe(false)
    expect(second.wrapper.find('.tracking-management-actions-section').text()).toContain('已降级为只读')
  })

  it('refreshes only the current record own associated RSS', async () => {
    serveApi(() => actionDetail())
    apiPost.mockResolvedValueOnce(capabilities()).mockResolvedValueOnce(actionPayload('REFRESH_RSS'))
    const { wrapper } = await mountTracking({ tracking_id: 'tracking-1' })
    await connect(wrapper)

    const confirmed = answerConfirm(wrapper, true)
    await wrapper.find('#tracking-refresh-rss-submit').trigger('submit')
    await flushPromises()
    const options = confirmed.mock.calls[0]?.[0] as { confirmLabel: string; message: string }
    expect(options.confirmLabel).toBe('确认刷新关联 RSS')
    expect(options.message).toContain('不会刷新全局 RSS')

    // One per-record refresh, and nothing else: no global refresh route, no
    // subscription route, no delete route.
    expect(actionEndpoints()).toEqual(['/api/v1/tracking/items/{tracking_id}/refresh'])
    expect(postedBodies('/api/v1/tracking/items/{tracking_id}/refresh')[0]).toEqual({
      target_scope: 'ASSOCIATED_RSS',
      expected_revision: 1,
      idempotency_key: expect.any(String),
      confirm: true,
      ab_config: {
        auth_mode: 'password', base_url: 'https://ab.invalid', username: 'user',
        password: 'pass', fallback_enabled: false,
      },
    })
    expect(wrapper.find('#tracking-management-result').text()).toContain('关联 RSS 刷新已完成')
  })

  it('treats a partial or unknown refresh result as unresolved and never resends', async () => {
    serveApi(() => actionDetail())
    // A partial batch (one accepted, one rejected upstream) is reported by the
    // server as an unknown outcome; the page must not read it as success.
    apiPost.mockResolvedValueOnce(capabilities())
      .mockResolvedValueOnce(actionPayload('REFRESH_RSS', {
        management_status: 'RECOVERY_REQUIRED', needs_manual: true,
      }))
      .mockResolvedValueOnce(actionPayload('REFRESH_RSS'))
    const { wrapper } = await mountTracking({ tracking_id: 'tracking-1' })
    await connect(wrapper)

    answerConfirm(wrapper, true)
    await wrapper.find('#tracking-refresh-rss-submit').trigger('submit')
    await flushPromises()
    const result = wrapper.find('#tracking-management-result')
    expect(result.classes()).toContain('is-unknown')
    expect(result.text()).toContain('关联 RSS 刷新结果未知')
    expect(result.text()).toContain('只读回查')
    expect(result.text()).not.toContain('已完成')
    expect(result.text()).not.toContain('RECOVERY_REQUIRED')
    expect(result.find('#tracking-management-manual-notice').exists()).toBe(true)
    const bodies = postedBodies('/api/v1/tracking/items/{tracking_id}/refresh')
    expect(bodies).toHaveLength(1)

    // An explicit second confirmation replays the very same key and revision.
    await wrapper.find('#tracking-refresh-rss-submit').trigger('submit')
    await flushPromises()
    const replays = postedBodies('/api/v1/tracking/items/{tracking_id}/refresh')
    expect(replays).toHaveLength(2)
    expect(replays[1]?.idempotency_key).toBe(replays[0]?.idempotency_key)
    expect(replays[1]?.expected_revision).toBe(replays[0]?.expected_revision)
    expect(wrapper.find('#tracking-management-result').text()).toContain('关联 RSS 刷新已完成')
  })

  it('frees the page lock after a definite refusal and mints a new key', async () => {
    serveApi(() => actionDetail())
    apiPost.mockResolvedValueOnce(capabilities())
      .mockRejectedValueOnce(rejectedError)
      .mockRejectedValueOnce(conflictError)
    const { wrapper } = await mountTracking({ tracking_id: 'tracking-1' })
    await connect(wrapper)

    await wrapper.find('#tracking-set-enabled-scope-SUBSCRIPTION').setValue()
    answerConfirm(wrapper, true)
    await wrapper.find('#tracking-set-enabled-submit').trigger('submit')
    await flushPromises()
    const result = wrapper.find('#tracking-management-result')
    expect(result.classes()).toContain('is-rejected')
    expect(result.text()).toContain('本次未改变 Auto Bangumi 的启用状态')
    expect(result.text()).not.toContain('结果未知')

    // The refusal released the intent, so the next confirmation mints a fresh
    // key — and a 409 is refused before the external boundary just the same,
    // re-reading both views instead of resending anything.
    await wrapper.find('#tracking-set-enabled-scope-SUBSCRIPTION').setValue()
    answerConfirm(wrapper, true)
    await wrapper.find('#tracking-set-enabled-submit').trigger('submit')
    await flushPromises()
    expect(wrapper.find('#tracking-management-result').text()).toContain('未提交到 Auto Bangumi')
    expect(wrapper.text()).not.toContain('tracking_revision_conflict')

    const bodies = postedBodies('/api/v1/tracking/items/{tracking_id}/set-enabled')
    expect(bodies).toHaveLength(2)
    expect(bodies[1]?.idempotency_key).not.toBe(bodies[0]?.idempotency_key)
  })

  it('sends zero requests when the user cancels the impact confirmation', async () => {
    serveApi(() => actionDetail())
    apiPost.mockResolvedValueOnce(capabilities())
    const { wrapper } = await mountTracking({ tracking_id: 'tracking-1' })
    await connect(wrapper)

    await wrapper.find('#tracking-set-enabled-scope-SUBSCRIPTION').setValue()
    answerConfirm(wrapper, false)
    await wrapper.find('#tracking-set-enabled-submit').trigger('submit')
    await flushPromises()
    answerConfirm(wrapper, false)
    await wrapper.find('#tracking-refresh-rss-submit').trigger('submit')
    await flushPromises()
    expect(actionEndpoints()).toEqual([])
    expect(wrapper.find('#tracking-management-result').exists()).toBe(false)
  })
})

// -- Stage 38 review fix: a locked intent must never refuse silently ---------

describe('TrackingView locked-intent feedback', () => {
  beforeEach(() => { apiGet.mockReset(); apiPost.mockReset() })

  it('explains the fixed next step when a locked submit intent refuses a different action', async () => {
    let currentDetail: unknown = submitDetail()
    serveApi(() => currentDetail)
    apiPost.mockResolvedValueOnce(capabilities() as never).mockRejectedValueOnce(unknownError as never)
    const { wrapper } = await mountTracking({ tracking_id: 'tracking-1' })
    await connect(wrapper)
    const confirmSpy = answerConfirm(wrapper, true)
    // The record's next detail read will offer a different server action, but the
    // click below still requests SUBMIT against the already-loaded detail.
    currentDetail = retryDetail()
    await wrapper.find('#tracking-submit').trigger('click')
    await flushPromises()
    expect(wrapper.find('#tracking-submit-result').text()).toContain('提交结果未知')
    expect(submittedBodies()).toHaveLength(1)

    // A different action is a different request: zero requests, one fixed notice,
    // and the unresolved result panel keeps its own copy and state.
    confirmSpy.mockClear()
    await wrapper.find('#tracking-retry').trigger('click')
    await flushPromises()
    expect(confirmSpy).not.toHaveBeenCalled()
    expect(submittedBodies()).toHaveLength(1)
    expect(retriedBodies()).toHaveLength(0)
    const notice = wrapper.find('#tracking-intent-blocked-notice')
    expect(notice.exists()).toBe(true)
    expect(notice.attributes('role')).toBe('status')
    expect(notice.text()).toContain('上一次外部操作的结果仍未确认')
    expect(notice.text()).not.toContain('network_error')
    expect(wrapper.find('#tracking-submit-result').text()).toContain('提交结果未知')

    // Clearing credentials destroys the session but must retain the unresolved
    // tombstone; reconnecting cannot replay it with a different account.
    await wrapper.find('.tracking-clear-connection').trigger('click')
    await flushPromises()
    expect(wrapper.find('#tracking-intent-blocked-notice').exists()).toBe(false)
  })

  it('explains a cross-record unresolved lock instead of leaving a dead button', async () => {
    const secondDetail = {
      ...modifyDetail({ available_actions: [submitAction, modifyAction] }),
      tracking_id: 'tracking-2', request_id: 'request-tracking-2', title: '咒术回战',
    }
    let currentDetail: unknown = submitDetail()
    apiGet.mockImplementation((url: string) => Promise.resolve(
      (url === '/api/v1/tracking/items'
        ? { items: [item('tracking-1', '葬送的芙莉莲'), item('tracking-2', '咒术回战')], summary: {}, warnings: [] }
        : currentDetail) as never,
    ))
    apiPost.mockResolvedValueOnce(capabilities() as never).mockRejectedValueOnce(unknownError as never)
    const { wrapper } = await mountTracking({ tracking_id: 'tracking-1' })
    await connect(wrapper)
    answerConfirm(wrapper, true)
    await wrapper.find('#tracking-submit').trigger('click')
    await flushPromises()
    expect(wrapper.find('#tracking-submit-result').text()).toContain('提交结果未知')
    expect(submittedBodies()).toHaveLength(1)

    // Selecting another record shows the reason its external actions are locked.
    currentDetail = secondDetail
    await wrapper.findAll('.tracking-list-item')[1]?.trigger('click')
    await flushPromises()
    const notice = wrapper.find('#tracking-intent-blocked-notice')
    expect(notice.exists()).toBe(true)
    expect(notice.attributes('role')).toBe('status')
    expect(notice.text()).toContain('上一次外部操作的结果仍未确认')
    expect(wrapper.find('#tracking-submit').attributes('disabled')).toBeDefined()

    // Attempting submit or management on the second record sends zero requests
    // and opens no confirmation dialog.
    await wrapper.find('#tracking-submit').trigger('click')
    await wrapper.find('#tracking-modify-title-enabled').setValue(true)
    await wrapper.find('#tracking-modify-title').setValue('不该发送')
    await wrapper.find('#tracking-modify-subscription-submit').trigger('submit')
    await flushPromises()
    expect(submittedBodies()).toHaveLength(1)
    expect(modifiedBodies()).toHaveLength(0)
    expect(wrapper.find('.confirm-dialog').exists()).toBe(false)

    // The notice belongs to the acted-on record only: the lock owner is never
    // shown another record's refusal.
    currentDetail = submitDetail()
    await wrapper.findAll('.tracking-list-item')[0]?.trigger('click')
    await flushPromises()
    expect(wrapper.find('#tracking-intent-blocked-notice').exists()).toBe(false)

    // Resolving the lock at its owner clears it for every record.
    apiPost.mockResolvedValueOnce(submitPayload({ tracking: { ...item('tracking-1', '葬送的芙莉莲'), revision: 9 } }) as never)
    answerConfirm(wrapper, true)
    await wrapper.find('#tracking-submit').trigger('click')
    await flushPromises()
    currentDetail = secondDetail
    await wrapper.findAll('.tracking-list-item')[1]?.trigger('click')
    await flushPromises()
    expect(wrapper.find('#tracking-intent-blocked-notice').exists()).toBe(false)
  })
})

// -- US-315: per-record external delete --------------------------------------

const deleteAction = {
  code: 'DELETE_EXTERNAL', label: '删除外部订阅', style: 'DANGER',
  requires_confirmation: true, target_scopes: ['SUBSCRIPTION', 'ASSOCIATED_RSS'],
}

/** A detail record that offers the per-record external delete. */
function deleteDetail(overrides: Record<string, unknown> = {}) {
  return { ...modifyDetail(), available_actions: [deleteAction], ...overrides }
}

/** The authoritative summary the delete endpoint returns. */
function deletePayload(overrides: Record<string, unknown> = {}) {
  return {
    action: 'DELETE_EXTERNAL', management_status: 'SUCCEEDED', needs_manual: false,
    safe_message: 'Auto Bangumi 管理操作已完成并通过回查', operation_id: 'operation-delete',
    operation: null,
    tracking: {
      ...item('tracking-1', '葬送的芙莉莲'), status: 'EXTERNAL_DELETED', status_label: '外部已删除',
      status_group: 'INACTIVE', revision: 2,
    },
    ...overrides,
  }
}

function deleteBodies(): Record<string, unknown>[] {
  return apiPost.mock.calls
    .filter((call) => call[0] === '/api/v1/tracking/items/{tracking_id}/delete-external')
    .map((call) => (call[1]?.body ?? {}) as Record<string, unknown>)
}

describe('TrackingView per-record external delete (US-315)', () => {
  beforeEach(() => { apiGet.mockReset(); apiPost.mockReset() })

  it('offers no delete without a live session, a chosen target or the capability', async () => {
    serveApi(() => deleteDetail())
    apiPost.mockResolvedValueOnce(capabilities())
    const { wrapper } = await mountTracking({ tracking_id: 'tracking-1' })
    // No page credential session: no delete control at all, zero requests.
    expect(wrapper.find('#tracking-delete-external-submit').exists()).toBe(false)
    expect(wrapper.find('.tracking-delete-external-section').text())
      .toContain('需要先在页面连接 Auto Bangumi')

    await connect(wrapper)
    // Connecting never deletes anything on its own.
    expect(deleteBodies()).toHaveLength(0)
    const section = wrapper.find('.tracking-delete-external-section')
    // Single-record and explicit: no checkbox and no batch control anywhere.
    expect(section.findAll('input[type=checkbox]')).toHaveLength(0)
    expect(section.findAll('input[type=radio]')).toHaveLength(2)
    expect(section.text()).toContain('没有勾选、批量或全局删除')
    expect(section.text()).not.toContain('SUBSCRIPTION')
    expect(section.text()).not.toContain('ASSOCIATED_RSS')
    // No target is pre-selected, so nothing can be deleted by accident.
    expect(wrapper.find('#tracking-delete-external-submit').attributes('disabled')).toBeDefined()
    expect(section.text()).toContain('请先明确选择要删除的外部对象')
  })

  it('drops a scope whose own delete capability is not proven', async () => {
    serveApi(() => deleteDetail())
    apiPost.mockResolvedValueOnce(capabilities({ subscription_delete: 'UNSUPPORTED' }))
    const { wrapper } = await mountTracking({ tracking_id: 'tracking-1' })
    await connect(wrapper)
    expect(wrapper.find('#tracking-delete-external-scope-SUBSCRIPTION').exists()).toBe(false)
    expect(wrapper.find('#tracking-delete-external-scope-ASSOCIATED_RSS').exists()).toBe(true)

    // An unproven delete capability hides the action entirely instead of
    // offering a button that could never succeed.
    apiPost.mockReset()
    apiPost.mockResolvedValueOnce(capabilities({ rss_delete: 'UNKNOWN' }))
    const second = await mountTracking({ tracking_id: 'tracking-1' })
    await connect(second.wrapper)
    expect(second.wrapper.find('.tracking-delete-external-section').findAll('input[type=radio]'))
      .toHaveLength(1)
    expect(second.wrapper.find('#tracking-delete-external-submit').exists()).toBe(true)
  })

  it('deletes only the chosen external object and keeps every local record', async () => {
    let revision = 1
    serveApi(() => deleteDetail({ revision }))
    apiPost.mockResolvedValueOnce(capabilities())
      .mockImplementationOnce((async () => {
        revision = 2
        return deletePayload()
      }) as never)
    const { wrapper } = await mountTracking({ tracking_id: 'tracking-1' })
    await connect(wrapper)

    // Cancelling the impact confirmation sends zero requests.
    await wrapper.find('#tracking-delete-external-scope-SUBSCRIPTION').setValue()
    answerConfirm(wrapper, false)
    await wrapper.find('#tracking-delete-external-submit').trigger('submit')
    await flushPromises()
    expect(deleteBodies()).toHaveLength(0)
    expect(wrapper.find('#tracking-delete-external-result').exists()).toBe(false)

    const confirmed = answerConfirm(wrapper, true)
    await wrapper.find('#tracking-delete-external-submit').trigger('submit')
    await flushPromises()

    // The danger dialog names the external object and every local record kept.
    const options = confirmed.mock.calls[0]?.[0] as { message: string; danger: boolean; confirmLabel: string }
    expect(options.danger).toBe(true)
    expect(options.confirmLabel).toBe('确认删除外部对象')
    expect(options.message).toContain('不会删除任何媒体文件')
    expect(options.message).toContain('本地订阅方案')

    const bodies = deleteBodies()
    expect(bodies).toHaveLength(1)
    expect(bodies[0]).toEqual({
      target_scope: 'SUBSCRIPTION',
      expected_revision: 1,
      idempotency_key: expect.any(String),
      confirm: true,
      ab_config: {
        auth_mode: 'password', base_url: 'https://ab.invalid', username: 'user',
        password: 'pass', fallback_enabled: false,
      },
    })
    // The generated delete body cannot express a media delete, a patch or a
    // second scope, and no key or credential reaches the DOM.
    expect(Object.keys(bodies[0] ?? {}).sort()).toEqual(
      ['target_scope', 'expected_revision', 'idempotency_key', 'confirm', 'ab_config'].sort(),
    )
    expect(JSON.stringify(bodies[0])).not.toContain('file')

    const result = wrapper.find('#tracking-delete-external-result')
    expect(result.classes()).toContain('is-succeeded')
    expect(result.text()).toContain('外部删除已完成')
    expect(result.text()).toContain('本次目标：外部番剧订阅')
    expect(result.text()).not.toContain('SUCCEEDED')
    // The record stays in the local list with its history and plan entry.
    expect(wrapper.findAll('.tracking-list-item')).toHaveLength(1)
    expect(wrapper.find('#tracking-list-container').text()).toContain('外部已删除')
    expect(wrapper.find('.tracking-plan-link').exists()).toBe(true)
    expect(wrapper.text()).not.toContain(String(bodies[0]?.idempotency_key))
    expect(wrapper.text()).not.toContain('pass')
  })

  it('locks the delete intent on an unknown result and never resends a different one', async () => {
    serveApi(() => deleteDetail())
    apiPost.mockResolvedValueOnce(capabilities()).mockRejectedValueOnce(unknownError)
    const { wrapper } = await mountTracking({ tracking_id: 'tracking-1' })
    await connect(wrapper)

    await wrapper.find('#tracking-delete-external-scope-SUBSCRIPTION').setValue()
    answerConfirm(wrapper, true)
    await wrapper.find('#tracking-delete-external-submit').trigger('submit')
    await flushPromises()
    const result = wrapper.find('#tracking-delete-external-result')
    expect(result.classes()).toContain('is-unknown')
    expect(result.text()).toContain('外部删除结果未知')
    expect(result.text()).toContain('只读回查')
    expect(result.text()).not.toContain('已完成')
    expect(deleteBodies()).toHaveLength(1)

    // A different scope is a different delete: zero requests, one stated reason.
    await wrapper.find('#tracking-delete-external-scope-ASSOCIATED_RSS').setValue()
    await wrapper.find('#tracking-delete-external-submit').trigger('submit')
    await flushPromises()
    expect(deleteBodies()).toHaveLength(1)
    expect(wrapper.find('#tracking-intent-blocked-notice').text())
      .toContain('上一次外部操作的结果仍未确认')
    expect(result.text()).toContain('外部删除结果未知')

    // Replaying the same delete reuses the very same key and revision.
    await wrapper.find('#tracking-delete-external-scope-SUBSCRIPTION').setValue()
    answerConfirm(wrapper, true)
    await wrapper.find('#tracking-delete-external-submit').trigger('submit')
    await flushPromises()
    const bodies = deleteBodies()
    expect(bodies).toHaveLength(2)
    expect(bodies[1]?.idempotency_key).toBe(bodies[0]?.idempotency_key)
    expect(bodies[1]?.expected_revision).toBe(bodies[0]?.expected_revision)
  })

  it('converges a conflict and a definite refusal on the server state', async () => {
    serveApi(() => deleteDetail())
    apiPost.mockResolvedValueOnce(capabilities())
      .mockRejectedValueOnce(conflictError)
      .mockRejectedValueOnce(rejectedError)
    const { wrapper } = await mountTracking({ tracking_id: 'tracking-1' })
    await connect(wrapper)

    await wrapper.find('#tracking-delete-external-scope-SUBSCRIPTION').setValue()
    answerConfirm(wrapper, true)
    await wrapper.find('#tracking-delete-external-submit').trigger('submit')
    await flushPromises()
    const result = wrapper.find('#tracking-delete-external-result')
    expect(result.classes()).toContain('is-conflict')
    expect(result.text()).toContain('本次未提交到 Auto Bangumi')
    expect(result.text()).toContain('请重新确认')
    expect(wrapper.text()).not.toContain('tracking_revision_conflict')

    // A 409 released the intent: the next confirmation mints a fresh key and a
    // structured non-409 4xx is a definite refusal, never an unknown result.
    await wrapper.find('#tracking-delete-external-scope-SUBSCRIPTION').setValue()
    answerConfirm(wrapper, true)
    await wrapper.find('#tracking-delete-external-submit').trigger('submit')
    await flushPromises()
    expect(result.classes()).toContain('is-rejected')
    expect(result.text()).toContain('未删除 Auto Bangumi 外部对象')
    expect(result.text()).not.toContain('结果未知')

    const bodies = deleteBodies()
    expect(bodies).toHaveLength(2)
    expect(bodies[1]?.idempotency_key).not.toBe(bodies[0]?.idempotency_key)
  })
})

describe('TrackingView retired batch deep link (US-316)', () => {
  beforeEach(() => { apiGet.mockReset(); apiPost.mockReset() })

  function queuePayload(requestIds: readonly unknown[]) {
    return {
      batch_id: 'batch-legacy',
      queue: {
        queue_id: 'queue-legacy', batch_id: 'batch-legacy',
        items: requestIds.map((requestId, index) => ({ item_id: `item-${index}`, request_id: requestId })),
      },
    }
  }

  it('locates a retired batch_id once through the queue public request_id', async () => {
    apiGet.mockResolvedValueOnce({ items: [item('tracking-1', '葬送的芙莉莲')], summary: {}, warnings: [] } as never)
    apiGet.mockResolvedValueOnce(queuePayload(['request-tracking-1']) as never)
    apiGet.mockResolvedValueOnce(detail() as never)
    const { wrapper, router } = await mountTracking({ batch_id: 'batch-legacy' })
    await flushPromises()

    expect(apiGet).toHaveBeenNthCalledWith(2, '/api/v1/batches/{batch_id}/queue', {
      path: { batch_id: 'batch-legacy' }, query: {},
    })
    // The legacy query is consumed: only the tracking_id survives as the
    // authority for the selected record.
    expect(router.currentRoute.value.fullPath).toBe('/tracking?tracking_id=tracking-1')
    expect(wrapper.find('#tracking-compat-notice').exists()).toBe(false)
    expect(wrapper.find('[aria-current="true"]').attributes('data-tracking-id')).toBe('tracking-1')
    // Locating never touches an external action of any kind.
    expect(apiPost).not.toHaveBeenCalled()
  })

  it('states a fixed next step when the batch cannot be located and consumes the query', async () => {
    apiGet.mockResolvedValueOnce({ items: [item('tracking-1', '葬送的芙莉莲')], summary: {}, warnings: [] } as never)
    // A title that matches the list is still not an identity: only request_id counts.
    apiGet.mockResolvedValueOnce(queuePayload(['葬送的芙莉莲', 'request-unknown']) as never)
    const { wrapper, router } = await mountTracking({ batch_id: 'batch-legacy' })
    await flushPromises()

    expect(router.currentRoute.value.fullPath).toBe('/tracking')
    const notice = wrapper.find('#tracking-compat-notice')
    expect(notice.attributes('role')).toBe('status')
    expect(notice.text()).toContain('旧的批量入口已退出')
    expect(notice.text()).not.toContain('batch-legacy')
    expect(wrapper.find('[aria-current="true"]').exists()).toBe(false)
    expect(apiPost).not.toHaveBeenCalled()
  })

  it('never renders server text when the legacy batch read fails', async () => {
    apiGet.mockResolvedValueOnce({ items: [item('tracking-1', '葬送的芙莉莲')], summary: {}, warnings: [] } as never)
    apiGet.mockRejectedValueOnce(new Error('sensitive upstream queue detail'))
    const { wrapper, router } = await mountTracking({ batch_id: 'batch-legacy' })
    await flushPromises()

    expect(router.currentRoute.value.fullPath).toBe('/tracking')
    const notice = wrapper.find('#tracking-compat-notice')
    expect(notice.text()).toContain('暂时无法读取该批次')
    expect(wrapper.text()).not.toContain('sensitive upstream queue detail')
    expect(apiPost).not.toHaveBeenCalled()
  })

  it('does not read the legacy queue when there is no batch_id', async () => {
    apiGet.mockResolvedValue({ items: [item('tracking-1', '葬送的芙莉莲')], summary: {}, warnings: [] } as never)
    const { wrapper } = await mountTracking()
    await flushPromises()
    expect(apiGet).toHaveBeenCalledTimes(1)
    expect(wrapper.find('#tracking-compat-notice').exists()).toBe(false)
  })

  it('never steals a selection the user made while the legacy read was in flight', async () => {
    const queueResolvers: Array<(value: unknown) => void> = []
    apiGet.mockResolvedValueOnce({
      items: [item('tracking-1', '葬送的芙莉莲'), item('tracking-2', '咒术回战')],
      summary: {}, warnings: [],
    } as never)
    apiGet.mockImplementationOnce(() => new Promise((resolve) => { queueResolvers.push(resolve) }) as never)
    apiGet.mockResolvedValue({ ...detail(), tracking_id: 'tracking-2' } as never)
    const { wrapper, router } = await mountTracking({ batch_id: 'batch-legacy' })
    await flushPromises()

    // The user picks their own record while the retired batch read is pending.
    await wrapper.find('[data-tracking-id="tracking-2"]').trigger('click')
    await flushPromises()
    expect(router.currentRoute.value.fullPath).toBe('/tracking?tracking_id=tracking-2')

    // The late compat answer points at a *different* record: it must not bounce
    // the page away from the one the user chose.
    queueResolvers[0]?.(queuePayload(['request-tracking-1']))
    await flushPromises()
    expect(router.currentRoute.value.fullPath).toBe('/tracking?tracking_id=tracking-2')
    expect(wrapper.find('#tracking-compat-notice').exists()).toBe(false)
  })

  it('never drops a user selection when the legacy read fails late', async () => {
    const queueRejectors: Array<(error: unknown) => void> = []
    apiGet.mockResolvedValueOnce({
      items: [item('tracking-1', '葬送的芙莉莲'), item('tracking-2', '咒术回战')],
      summary: {}, warnings: [],
    } as never)
    apiGet.mockImplementationOnce(() => new Promise((_resolve, reject) => { queueRejectors.push(reject) }) as never)
    apiGet.mockResolvedValue({ ...detail(), tracking_id: 'tracking-2' } as never)
    const { wrapper, router } = await mountTracking({ batch_id: 'batch-legacy' })
    await flushPromises()

    await wrapper.find('[data-tracking-id="tracking-2"]').trigger('click')
    await flushPromises()
    expect(router.currentRoute.value.fullPath).toBe('/tracking?tracking_id=tracking-2')

    queueRejectors[0]?.(new Error('private queue detail'))
    await flushPromises()
    expect(router.currentRoute.value.fullPath).toBe('/tracking?tracking_id=tracking-2')
    expect(wrapper.find('#tracking-compat-notice').exists()).toBe(false)
    expect(wrapper.text()).not.toContain('private queue detail')
  })
})
