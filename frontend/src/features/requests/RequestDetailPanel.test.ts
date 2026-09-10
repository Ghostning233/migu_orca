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
      ? (error as { type: string; message: string })
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

async function mountPanel(requestId = 'req-a', options: { stubsTeleport?: boolean } = {}) {
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
    ],
  })
  await router.push({ path: '/plans', query: { request_id: requestId } })
  await router.isReady()

  const wrapper = mount(RequestDetailPanel, {
    props: { requestId },
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

  it('shows modify/delete/AB entry for ACCEPTED and no accept/cancel', async () => {
    apiGet.mockResolvedValue(acceptedFixture())
    const { wrapper } = await mountPanel()
    await nextTick()

    expect(wrapper.find('#detail-delete-button').exists()).toBe(true)
    expect(wrapper.find('#detail-ab-submit-entry').exists()).toBe(true)
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
    await wrapper.find('#detail-modify-submit').trigger('click')
    await nextTick()

    expect(apiPost).not.toHaveBeenCalled()
    expect(wrapper.find('#detail-modify-error').text()).toContain('请至少修改或清空一个字段')
  })

  it('modify sends a patch for changed fields only', async () => {
    const { wrapper } = await mountPanel()
    await nextTick()

    apiPost.mockResolvedValue({ request: detailFixture().request })
    apiGet.mockResolvedValue(detailFixture())

    await wrapper.find('#detail-modify-toggle').trigger('click')
    await nextTick()
    await wrapper.find('#modify-folder-name').setValue('新目录名')
    await wrapper.find('#modify-filter-use-regex').setValue(true)
    await wrapper.find('#detail-modify-submit').trigger('click')
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

  it('clear-field checkboxes send explicit empty values', async () => {
    const { wrapper } = await mountPanel()
    await nextTick()

    apiPost.mockResolvedValue({ request: detailFixture().request })
    apiGet.mockResolvedValue(detailFixture())

    await wrapper.find('#detail-modify-toggle').trigger('click')
    await nextTick()
    await wrapper.find('#modify-clear-must-contain').setValue(true)
    await wrapper.find('#modify-clear-folder-name').setValue(true)
    await wrapper.find('#detail-modify-submit').trigger('click')
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

  it('copy request_id uses the clipboard and notifies', async () => {
    Object.assign(navigator, { clipboard: { writeText: vi.fn().mockResolvedValue(undefined) } })
    const { wrapper } = await mountPanel()
    await nextTick()

    await wrapper.find('.copy-request-id').trigger('click')
    await nextTick()

    expect(navigator.clipboard.writeText).toHaveBeenCalledWith('req-a')
    const { useNotificationStore } = await import('@/app/stores/notification')
    const notification = useNotificationStore()
    expect(notification.current?.title).toBe('已复制 request_id')
  })

  it('AB submit entry links to Settings with the request_id', async () => {
    apiGet.mockResolvedValue(acceptedFixture())
    const { wrapper } = await mountPanel()
    await nextTick()

    const link = wrapper.find('#detail-ab-submit-entry')
    expect(link.exists()).toBe(true)
    expect(link.attributes('href')).toBe('/app/settings?request_id=req-a')
  })
})
