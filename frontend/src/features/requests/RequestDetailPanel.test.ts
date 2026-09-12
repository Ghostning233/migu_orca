import { flushPromises, mount } from '@vue/test-utils'
import { createPinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createMemoryHistory, createRouter } from 'vue-router'
import { nextTick } from 'vue'

import { api } from '@/api/client'
import RequestDetailPanel from '@/features/requests/RequestDetailPanel.vue'
import type { operations } from '@/api/generated/api'

// US-203: Request detail panel. Loads `GET /api/v1/requests/{request_id}` via
// the shared transport, renders Overview/Source/Filter/Seeds/Audit and the
// status-dependent management actions (accept/cancel/modify/delete), all
// through the shared primitives (ConfirmDialog, BaseButton, FormField, ...).
// Sensitive values never reach the DOM; destructive actions require confirm.

vi.mock('@/api/client', () => ({
  api: {
    get: vi.fn(),
    post: vi.fn(),
    put: vi.fn(),
    patch: vi.fn(),
    delete: vi.fn(),
    poster: vi.fn(),
  },
  toApiError: (error: unknown) =>
    error && typeof error === 'object' && 'type' in error
      ? (error as { type: string; message: string; status?: number; network?: boolean; cancelled?: boolean; nonJson?: boolean })
      : { type: 'request_error', message: '请求失败，请重试' },
  isApiError: () => false,
  apiRequest: vi.fn(),
}))

const apiGet = vi.mocked(api.get)
const apiPost = vi.mocked(api.post)

type DetailResult = NonNullable<
  operations['getRequestDetail']['responses']['200']['content']['application/json']['result']
>

function detailFixture(overrides: Partial<Record<string, unknown>> = {}): DetailResult {
  return {
    request: {
      request_id: 'req-a',
      status: 'PENDING_CONFIRM',
      input: { raw_title: '葬送的芙莉莲' },
      source_info: {
        matched_bangumi: {
          title: '葬送的芙莉莲',
          aliases: [],
          match_score: 1,
        },
        rss_sources: [
          {
            subtitle_group: '喵萌奶茶屋',
            source_type: 'mikan',
            total_seed_count: 2,
            seed_names: ['[喵萌] 芙莉莲 01.mkv', '[喵萌] 芙莉莲 SP.mkv'],
            valid_seed_count: 1,
            invalid_seed_count: 1,
            valid_seed_names: ['[喵萌] 芙莉莲 01.mkv'],
            excluded_seed_names: [
              { name: '[喵萌] 芙莉莲 SP.mkv', reason: '命中排除规则：SP' },
            ],
            warnings: [],
          },
        ],
      },
      confirmable_config: {
        selected_subtitle_group: '喵萌奶茶屋',
        selected_rss_url: 'SELECTED',
        filter_rule: {
          must_contain: '',
          must_not_contain: '',
          use_regex: false,
          case_sensitive: false,
        },
        effective_seed_names: ['[喵萌] 芙莉莲 01.mkv'],
        expected_folder_name: '葬送的芙莉莲',
        warnings: [],
      },
      created_at: '2026-08-31T00:00:00+00:00',
      updated_at: '2026-08-31T00:00:00+00:00',
      user_action: null,
    },
    history: { available: true, events: [], error: null },
    ab_result: { available: false, record: null, error: null },
    ...overrides,
  }
}

function acceptedFixture(): DetailResult {
  return detailFixture({
    request: {
      ...detailFixture().request,
      status: 'ACCEPTED',
      user_action: { action: 'ACCEPT', reason: null, decided_at: '2026-08-31T00:00:00+00:00' },
    },
  })
}

async function mountPanel(requestId = 'req-a', options: {
  stubsTeleport?: boolean
  trackingId?: string | null
  trackingStatus?: 'loading' | 'failed' | 'unavailable' | 'not_linked' | 'linked'
  trackingStatusLabel?: string | null
} = {}) {
  const router = createRouter({
    history: createMemoryHistory('/app/'),
    routes: [
      {
        path: '/plans',
        name: 'plans',
        component: { template: '<p>list</p>' },
      },
      {
        path: '/settings',
        name: 'settings',
        component: { template: '<p>settings</p>' },
      },
      {
        path: '/tracking',
        name: 'tracking',
        component: { template: '<p>tracking</p>' },
      },
    ],
  })
  await router.push({ path: '/plans', query: { request_id: requestId } })
  await router.isReady()

  const wrapper = mount(RequestDetailPanel, {
    props: {
      requestId,
      trackingId: options.trackingId,
      trackingStatus: options.trackingStatus,
      trackingStatusLabel: options.trackingStatusLabel,
    },
    attachTo: document.body,
    global: {
      plugins: [createPinia(), router],
      stubs: { teleport: options.stubsTeleport ?? true },
    },
  })
  await nextTick()
  await nextTick()
  return { wrapper, router }
}

describe('RequestDetailPanel load (US-203)', () => {
  beforeEach(() => {
    localStorage.clear()
    apiGet.mockReset()
    apiPost.mockReset()
    apiGet.mockResolvedValue(detailFixture())
  })

  it('loads the detail through the typed transport with path params', async () => {
    const { wrapper } = await mountPanel('req-a')
    await nextTick()

    expect(apiGet).toHaveBeenCalledWith('/api/v1/requests/{request_id}', {
      path: { request_id: 'req-a' },
      query: {},
    })
    expect(wrapper.find('.overview-section').text()).toContain('葬送的芙莉莲')
    expect(wrapper.find('.overview-section').text()).toContain('req-a')
  })

  it('passes the relative storage profile from localStorage', async () => {
    localStorage.setItem('miguOrca.web.storageDir', 'backups')
    await mountPanel('req-a')
    await nextTick()

    expect(apiGet).toHaveBeenCalledWith('/api/v1/requests/{request_id}', {
      path: { request_id: 'req-a' },
      query: { storage_dir: 'backups' },
    })
  })

  it('never sends an absolute storage path', async () => {
    localStorage.setItem('miguOrca.web.storageDir', '/etc/passwd')
    await mountPanel('req-a')
    await nextTick()

    expect(apiGet).toHaveBeenCalledWith('/api/v1/requests/{request_id}', {
      path: { request_id: 'req-a' },
      query: {},
    })
  })

  it('shows a safe Chinese error state with retry on load failure', async () => {
    apiGet.mockRejectedValue({ type: 'request_not_found', message: '订阅方案不存在' })
    const { wrapper } = await mountPanel('req-missing')
    await nextTick()

    const error = wrapper.find('.error-state')
    expect(error.exists()).toBe(true)
    expect(error.text()).toContain('订阅方案详情加载失败')
    // The raw error_type/message never leaks into the DOM.
    expect(error.text()).not.toContain('request_not_found')

    apiGet.mockResolvedValue(detailFixture())
    await wrapper.find('.error-state .secondary-button').trigger('click')
    await nextTick()
    await nextTick()
    expect(wrapper.find('.overview-section').text()).toContain('req-a')
  })

  it('renders only the safe tracking state passed from the plans list', async () => {
    const { wrapper } = await mountPanel('req-a', { trackingStatus: 'loading' })
    await nextTick()
    expect(wrapper.text()).toContain('追番状态：正在读取追番状态')
    expect(wrapper.find('#detail-tracking-entry').exists()).toBe(false)

    await wrapper.setProps({ trackingStatus: 'unavailable', trackingId: null })
    expect(wrapper.text()).toContain('追番状态：追番状态暂不可用')
    expect(wrapper.find('#detail-tracking-entry').exists()).toBe(false)

    await wrapper.setProps({ trackingStatus: 'not_linked', trackingStatusLabel: null })
    expect(wrapper.text()).toContain('追番状态：未进入追番管理')

    await wrapper.setProps({ trackingStatus: 'linked', trackingId: 'tracking-a', trackingStatusLabel: '追番中' })
    expect(wrapper.find('#detail-tracking-entry').exists()).toBe(true)
    expect(wrapper.find('#detail-tracking-entry').attributes('href')).toBe('/app/tracking?tracking_id=tracking-a')
  })
})

describe('RequestDetailPanel sections (US-203)', () => {
  beforeEach(() => {
    localStorage.clear()
    apiGet.mockReset()
    apiPost.mockReset()
    apiGet.mockResolvedValue(detailFixture())
  })

  it('renders Overview / Source / Filter / Seeds / Audit sections', async () => {
    const { wrapper } = await mountPanel()
    await nextTick()

    const text = wrapper.text()
    expect(text).toContain('Overview')
    expect(text).toContain('Source')
    expect(text).toContain('Filter')
    expect(text).toContain('Seeds')
    expect(text).toContain('Audit')
  })

  it('shows effective / complete / excluded seed groups with counts', async () => {
    const { wrapper } = await mountPanel()
    await nextTick()

    expect(wrapper.find('.effective-seed-group summary').text()).toContain('有效种子（当前选中字幕组：喵萌奶茶屋）(1)')
    expect(wrapper.find('.effective-seed-group').text()).toContain('[喵萌] 芙莉莲 01.mkv')
    expect(wrapper.find('.complete-seed-details summary').text()).toContain('完整种子（按字幕组分组）(2)')
    expect(wrapper.find('.excluded-seed-details summary').text()).toContain('排除种子 (1)')
    // Excluded reason is rendered beside the seed title.
    expect(wrapper.find('.excluded-seed-list').text()).toContain('命中排除规则：SP')
  })

  it('shows history and AB result placeholders when absent', async () => {
    const { wrapper } = await mountPanel()
    await nextTick()

    expect(wrapper.text()).toContain('暂无状态历史')
    expect(wrapper.text()).toContain('暂无 Auto Bangumi 提交结果')
  })

  it('renders history events and the AB result record when present', async () => {
    apiGet.mockResolvedValue(
      detailFixture({
        history: {
          available: true,
          events: [
            {
              request_id: 'req-a',
              previous_status: 'PENDING_CONFIRM',
              next_status: 'ACCEPTED',
              action: 'ACCEPT',
              timestamp: '2026-08-31T00:00:00+00:00',
              details: null,
            },
          ],
          error: null,
        },
        ab_result: {
          available: true,
          record: {
            request_id: 'req-a',
            recorded_at: '2026-08-31T00:00:00+00:00',
            ab_submit_result: {
              success: true,
              ab_subscription_id: 'ab-sub-1',
              ab_response: { id: 'ab-sub-1' },
              fallback_config: null,
              error: null,
            },
          },
          error: null,
        },
      }),
    )
    const { wrapper } = await mountPanel()
    await nextTick()

    const text = wrapper.text()
    expect(text).toContain('确认')
    expect(text).toContain('待确认')
    expect(text).toContain('已确认')
    expect(text).toContain('ab-sub-1')
    expect(text).toContain('success')
    expect(text).toContain('无')
  })

  it('does not render raw URLs from the snapshot', async () => {
    const { wrapper } = await mountPanel()
    await nextTick()

    expect(wrapper.text()).not.toContain('https://example.invalid/rss/moe.xml')
    expect(wrapper.text()).not.toContain('https://example.invalid/bangumi/frieren')
  })
})

describe('RequestDetailPanel actions (US-203)', () => {
  beforeEach(() => {
    localStorage.clear()
    apiGet.mockReset()
    apiPost.mockReset()
    apiGet.mockResolvedValue(detailFixture())
  })

  it('shows accept/cancel/modify for PENDING_CONFIRM and not for ACCEPTED', async () => {
    const { wrapper } = await mountPanel()
    await nextTick()

    expect(wrapper.find('#detail-accept-button').exists()).toBe(true)
    expect(wrapper.find('#detail-cancel-toggle').exists()).toBe(true)
    expect(wrapper.find('#detail-modify-toggle').exists()).toBe(true)
    expect(wrapper.find('#detail-delete-button').exists()).toBe(false)
    expect(wrapper.find('#detail-ab-submit-entry').exists()).toBe(false)
  })

  it('shows local modify/delete for ACCEPTED and no external entry', async () => {
    apiGet.mockResolvedValue(acceptedFixture())
    const { wrapper } = await mountPanel()
    await nextTick()

    expect(wrapper.find('#detail-delete-button').exists()).toBe(true)
    expect(wrapper.find('#detail-ab-submit-entry').exists()).toBe(false)
    expect(wrapper.find('#detail-accept-button').exists()).toBe(false)
    expect(wrapper.find('#detail-cancel-toggle').exists()).toBe(false)
  })

  it('shows the不可操作 note for CANCELLED', async () => {
    apiGet.mockResolvedValue(
      detailFixture({ request: { ...detailFixture().request, status: 'CANCELLED' } }),
    )
    const { wrapper } = await mountPanel()
    await nextTick()

    expect(wrapper.text()).toContain('不可操作')
    expect(wrapper.find('#detail-accept-button').exists()).toBe(false)
    expect(wrapper.find('#detail-delete-button').exists()).toBe(false)
  })

  it('accept requires confirmation and posts to the accept endpoint', async () => {
    const { wrapper } = await mountPanel()
    await nextTick()

    apiPost.mockResolvedValue({ request: { ...detailFixture().request, status: 'ACCEPTED' } })
    apiGet.mockResolvedValue(
      detailFixture({ request: { ...detailFixture().request, status: 'ACCEPTED' } }),
    )

    await wrapper.find('#detail-accept-button').trigger('click')
    await nextTick()
    // ConfirmDialog is teleported; with the teleport stub it renders inline.
    const dialog = wrapper.find('.confirm-dialog')
    expect(dialog.exists()).toBe(true)
    expect(dialog.text()).toContain('确认接受此订阅方案')
    await dialog.find('.primary-button').trigger('click')
    await flushPromises()

    expect(apiPost).toHaveBeenCalledWith('/api/v1/requests/{request_id}/accept', {
      path: { request_id: 'req-a' },
      query: {},
      body: { storage_dir: null },
    })
  })

  it('dismissing the confirm dialog does not call the API', async () => {
    const { wrapper } = await mountPanel()
    await nextTick()

    await wrapper.find('#detail-accept-button').trigger('click')
    await nextTick()
    await wrapper.find('.confirm-dialog .secondary-button').trigger('click')
    await flushPromises()

    expect(apiPost).not.toHaveBeenCalled()
  })

  it('cancel requires confirmation and sends the cancel_reason', async () => {
    const { wrapper } = await mountPanel()
    await nextTick()

    apiPost.mockResolvedValue({ request: { ...detailFixture().request, status: 'CANCELLED' } })
    apiGet.mockResolvedValue(
      detailFixture({ request: { ...detailFixture().request, status: 'CANCELLED' } }),
    )

    await wrapper.find('#detail-cancel-toggle').trigger('click')
    await nextTick()
    expect(wrapper.find('#detail-cancel-form').exists()).toBe(true)
    await wrapper.find('#cancel-reason').setValue('不需要这个番剧')
    await wrapper.find('#detail-cancel-submit').trigger('click')
    await nextTick()
    await wrapper.find('.confirm-dialog .danger-button').trigger('click')
    await flushPromises()

    expect(apiPost).toHaveBeenCalledWith('/api/v1/requests/{request_id}/cancel', {
      path: { request_id: 'req-a' },
      query: {},
      body: { cancel_reason: '不需要这个番剧', storage_dir: null },
    })
  })

  it('delete requires confirmation, calls delete, and emits deleted', async () => {
    apiGet.mockResolvedValue(acceptedFixture())
    const { wrapper } = await mountPanel()
    await nextTick()

    apiPost.mockResolvedValue({
      request_id: 'req-a',
      storage: 'local_json',
      directory: 'requests',
      filename: 'req-a.json',
      deleted: true,
    })
    apiGet.mockRejectedValueOnce({ type: 'not_found', status: 404, message: 'not found' })

    await wrapper.find('#detail-delete-button').trigger('click')
    await nextTick()
    expect(wrapper.find('.confirm-dialog').text()).toContain('确认删除此订阅方案')
    await wrapper.find('.confirm-dialog .danger-button').trigger('click')
    await flushPromises()

    expect(apiPost).toHaveBeenCalledWith('/api/v1/requests/{request_id}/delete', {
      path: { request_id: 'req-a' },
      query: {},
      body: { storage_dir: null },
    })
    expect(wrapper.emitted('deleted')?.[0]).toEqual(['req-a'])
  })

  it('action failure shows fixed Chinese feedback, never the raw error', async () => {
    const { wrapper } = await mountPanel()
    await nextTick()

    apiPost.mockRejectedValue({
      type: 'invalid_request_status',
      message: '订阅方案状态已变更，请刷新后重试',
      details: { failed_step: 'confirm' },
    })

    await wrapper.find('#detail-accept-button').trigger('click')
    await nextTick()
    await wrapper.find('.confirm-dialog .primary-button').trigger('click')
    await flushPromises()

    const { useNotificationStore } = await import('@/app/stores/notification')
    const notification = useNotificationStore()
    expect(notification.current?.title).toBe('操作失败')
    expect(notification.current?.message).toBe('确认失败，请稍后重试。')
    expect(notification.current?.message).not.toContain('invalid_request_status')
  })

  it('modify form blocks an empty patch without calling the API', async () => {
    const { wrapper } = await mountPanel()
    await nextTick()

    await wrapper.find('#detail-modify-toggle').trigger('click')
    await nextTick()
    expect(wrapper.find('#detail-modify-form').exists()).toBe(true)
    await wrapper.find('#detail-modify-form').trigger('submit')
    await nextTick()

    expect(apiPost).not.toHaveBeenCalled()
    expect(wrapper.find('#detail-modify-editor .field-error').text()).toContain('请至少修改或清空一个字段')
  })

  it('modify sends a patch for changed fields only', async () => {
    const { wrapper } = await mountPanel()
    await nextTick()

    apiPost.mockResolvedValue({ request: detailFixture().request })
    apiGet.mockResolvedValue(detailFixture())

    await wrapper.find('#detail-modify-toggle').trigger('click')
    await nextTick()
    await wrapper.find('#modify-folder-name').setValue('新目录名')
    await wrapper.find('#modify-use-regex').setValue(true)
    await wrapper.find('#detail-modify-form').trigger('submit')
    await flushPromises()

    expect(apiPost).toHaveBeenCalledWith('/api/v1/requests/{request_id}/modify', {
      path: { request_id: 'req-a' },
      query: {},
      body: {
        patch: {
          filter_rule: { use_regex: true, case_sensitive: false },
          expected_folder_name: '新目录名',
        },
        storage_dir: null,
      },
    })
  })

  it('keeps input and exposes retry/recovery after a definite modify failure', async () => {
    const { wrapper } = await mountPanel()
    await nextTick()
    await wrapper.find('#detail-modify-toggle').trigger('click')
    await nextTick()
    await wrapper.find('#modify-folder-name').setValue('用户当前输入')
    apiPost.mockRejectedValueOnce({ type: 'validation_error', message: '拒绝修改' })

    await wrapper.find('#detail-modify-form').trigger('submit')
    await flushPromises()
    expect(wrapper.find('#detail-modify-editor .field-error').text()).toContain('修改失败，请稍后重试')
    expect(wrapper.find('#modify-folder-name').element).toHaveProperty('value', '用户当前输入')

    apiPost.mockResolvedValueOnce({ request: detailFixture().request })
    apiGet.mockResolvedValue(detailFixture({ request: {
      ...detailFixture().request,
      confirmable_config: { ...detailFixture().request.confirmable_config, expected_folder_name: '用户当前输入' },
    } }))
    await wrapper.find('#modify-retry-button').trigger('click')
    await flushPromises()
    expect(apiPost).toHaveBeenCalledTimes(2)
    expect(wrapper.find('#detail-modify-form').exists()).toBe(false)
  })

  it('reconciles an uncertain modify that already took effect without a second write', async () => {
    const { wrapper } = await mountPanel()
    await nextTick()
    await wrapper.find('#detail-modify-toggle').trigger('click')
    await nextTick()
    await wrapper.find('#modify-folder-name').setValue('已生效目录')
    apiPost.mockRejectedValueOnce({ type: 'network_error', network: true, status: 0, message: 'network' })
    apiGet.mockResolvedValue(detailFixture({ request: {
      ...detailFixture().request,
      confirmable_config: { ...detailFixture().request.confirmable_config, expected_folder_name: '已生效目录' },
    } }))

    await wrapper.find('#detail-modify-form').trigger('submit')
    await flushPromises()
    expect(apiPost).toHaveBeenCalledTimes(1)
    expect(wrapper.find('#detail-modify-form').exists()).toBe(false)
  })

  it('allows retry only when an uncertain modify is confirmed not applied', async () => {
    const { wrapper } = await mountPanel()
    await nextTick()
    await wrapper.find('#detail-modify-toggle').trigger('click')
    await nextTick()
    await wrapper.find('#modify-folder-name').setValue('未生效目录')
    apiPost.mockRejectedValueOnce({ type: 'network_error', network: true, status: 0, message: 'network' })
    apiGet.mockResolvedValue(detailFixture())

    await wrapper.find('#detail-modify-form').trigger('submit')
    await flushPromises()
    expect(wrapper.find('.field-error').text()).toContain('修改未生效，请重试')
    expect(wrapper.find('#modify-folder-name').element).toHaveProperty('value', '未生效目录')
    apiPost.mockResolvedValueOnce({ request: detailFixture().request })
    await wrapper.find('#modify-retry-button').trigger('click')
    await flushPromises()
    expect(apiPost).toHaveBeenCalledTimes(2)
  })

  it('does not repeat a write when uncertain modify recheck fails', async () => {
    const { wrapper } = await mountPanel()
    await nextTick()
    await wrapper.find('#detail-modify-toggle').trigger('click')
    await nextTick()
    await wrapper.find('#modify-folder-name').setValue('结果未知目录')
    apiPost.mockRejectedValueOnce({ type: 'network_error', network: true, status: 0, message: 'network' })
    apiGet.mockRejectedValue({ type: 'server_error', status: 503, message: 'raw backend error' })

    await wrapper.find('#detail-modify-form').trigger('submit')
    await flushPromises()
    expect(wrapper.find('.field-error').text()).toContain('结果暂无法确认')
    expect(wrapper.find('#modify-folder-name').element).toHaveProperty('value', '结果未知目录')
    await wrapper.find('#detail-modify-form').trigger('submit')
    await flushPromises()
    expect(apiPost).toHaveBeenCalledTimes(1)
    await wrapper.find('#modify-retry-button').trigger('click')
    await flushPromises()
    expect(apiPost).toHaveBeenCalledTimes(1)
    expect(wrapper.find('.field-error').text()).not.toContain('raw backend error')
  })

  it('recovers the editor from the latest server snapshot without using the DOM as a patch source', async () => {
    const { wrapper } = await mountPanel()
    await nextTick()
    await wrapper.find('#detail-modify-toggle').trigger('click')
    await nextTick()
    await wrapper.find('#modify-folder-name').setValue('过时输入')
    apiPost.mockRejectedValueOnce({ type: 'validation_error', message: '拒绝修改' })
    await wrapper.find('#detail-modify-form').trigger('submit')
    await flushPromises()
    apiGet.mockResolvedValue(detailFixture({ request: {
      ...detailFixture().request,
      confirmable_config: { ...detailFixture().request.confirmable_config, expected_folder_name: '服务端最新目录' },
    } }))

    await wrapper.find('#modify-reset-button').trigger('click')
    await flushPromises()
    expect(wrapper.find('#modify-folder-name').element).toHaveProperty('value', '服务端最新目录')
  })

  it('locks an accept action after an uncertain recheck failure and rechecks with GET only', async () => {
    const { wrapper } = await mountPanel()
    await nextTick()
    apiPost.mockRejectedValueOnce({ type: 'network_error', network: true, status: 0, message: 'network' })
    apiGet.mockRejectedValue({ type: 'server_error', status: 503, message: 'raw backend error' })

    await wrapper.find('#detail-accept-button').trigger('click')
    await nextTick()
    await wrapper.find('.confirm-dialog .primary-button').trigger('click')
    await flushPromises()
    expect(wrapper.find('#detail-action-recheck-button').exists()).toBe(true)
    expect(wrapper.find('#detail-accept-button').attributes('disabled')).toBeDefined()
    await wrapper.find('#detail-accept-button').trigger('click')
    expect(apiPost).toHaveBeenCalledTimes(1)

    apiGet.mockResolvedValueOnce(detailFixture({ request: { ...detailFixture().request, status: 'ACCEPTED' } }))
    const getCount = apiGet.mock.calls.length
    await wrapper.find('#detail-action-recheck-button').trigger('click')
    await flushPromises()
    expect(apiGet.mock.calls.length).toBe(getCount + 1)
    expect(apiPost).toHaveBeenCalledTimes(1)
    expect(wrapper.find('#detail-action-recheck-button').exists()).toBe(false)
  })

  it('locks delete after an uncertain recheck failure and confirms deletion with GET only', async () => {
    apiGet.mockResolvedValue(acceptedFixture())
    const { wrapper } = await mountPanel()
    await nextTick()
    apiPost.mockRejectedValueOnce({ type: 'network_error', network: true, status: 0, message: 'network' })
    apiGet.mockRejectedValue({ type: 'server_error', status: 503, message: 'raw backend error' })

    await wrapper.find('#detail-delete-button').trigger('click')
    await nextTick()
    await wrapper.find('.confirm-dialog .danger-button').trigger('click')
    await flushPromises()
    expect(wrapper.find('#detail-action-recheck-button').exists()).toBe(true)
    await wrapper.find('#detail-delete-button').trigger('click')
    expect(apiPost).toHaveBeenCalledTimes(1)

    apiGet.mockRejectedValueOnce({ type: 'not_found', status: 404, message: 'not found' })
    const getCount = apiGet.mock.calls.length
    await wrapper.find('#detail-action-recheck-button').trigger('click')
    await flushPromises()
    expect(apiGet.mock.calls.length).toBe(getCount + 1)
    expect(apiPost).toHaveBeenCalledTimes(1)
    expect(wrapper.emitted('deleted')?.[0]).toEqual(['req-a'])
  })

  it('clear-field checkboxes send explicit empty values', async () => {
    const savedConfig = detailFixture().request.confirmable_config
    apiGet.mockResolvedValue(detailFixture({
      request: {
        ...detailFixture().request,
        confirmable_config: {
          ...savedConfig,
          filter_rule: {
            ...savedConfig?.filter_rule,
            must_contain: '1080p',
          },
          expected_folder_name: '旧目录名',
        },
      },
    }))
    const { wrapper } = await mountPanel()
    await nextTick()

    apiPost.mockResolvedValue({ request: detailFixture().request })
    apiGet.mockResolvedValue(detailFixture())

    await wrapper.find('#detail-modify-toggle').trigger('click')
    await nextTick()
    await wrapper.find('#modify-clear-must-contain').setValue(true)
    await wrapper.find('#modify-clear-folder-name').setValue(true)
    await wrapper.find('#detail-modify-form').trigger('submit')
    await flushPromises()

    expect(apiPost).toHaveBeenCalledWith('/api/v1/requests/{request_id}/modify', {
      path: { request_id: 'req-a' },
      query: {},
      body: {
        patch: {
          filter_rule: {
            must_contain: '',
            use_regex: false,
            case_sensitive: false,
          },
          expected_folder_name: '',
        },
        storage_dir: null,
      },
    })
  })

  it('does not offer an Auto Bangumi submission entry for ACCEPTED', async () => {
    apiGet.mockResolvedValue(acceptedFixture())
    const { wrapper } = await mountPanel()
    await nextTick()

    expect(wrapper.find('#detail-ab-submit-entry').exists()).toBe(false)
    expect(wrapper.text()).not.toContain('去 Settings 提交 Auto Bangumi')
  })
})
