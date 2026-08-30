import { mount, flushPromises } from '@vue/test-utils'
import { createPinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createMemoryHistory, createRouter } from 'vue-router'
import { nextTick } from 'vue'

import { api } from '@/api/client'
import RequestsView from '@/features/requests/RequestsView.vue'
import type { operations } from '@/api/generated/api'

// US-202: Requests list migration. The view loads summaries through the shared
// transport (mocked here), then filters/sorts client-side with the same
// helpers as the legacy list. Selection pushes `request_id` into the URL so a
// refresh restores it; the storage profile comes from localStorage (relative
// only, never an absolute path).

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

type ListResult = operations['listRequests']['responses']['200']['content']['application/json']['result']

function summary(overrides: Partial<Record<string, unknown>> = {}) {
  return {
    request_id: 'req-a',
    status: 'PENDING_CONFIRM',
    bangumi_title: '葬送的芙莉莲',
    candidate_subtitle_groups: [],
    selected_subtitle_group: '喵萌奶茶屋',
    effective_seed_count: 5,
    expected_folder_name: '葬送的芙莉莲 (2023)',
    warnings: [],
    ...overrides,
  }
}

const LIST_RESULT: ListResult = {
  requests: [
    summary() as never,
    summary({
      request_id: 'req-b',
      status: 'ACCEPTED',
      bangumi_title: '咒术回战第三季',
      expected_folder_name: '咒术回战第三季',
    }) as never,
    summary({
      request_id: 'req-c',
      status: 'CANCELLED',
      bangumi_title: '葬送的芙莉莲',
      expected_folder_name: '葬送的芙莉莲 S2',
    }) as never,
  ],
}

async function mountRequests(query: Record<string, string> = {}) {
  const router = createRouter({
    history: createMemoryHistory('/app/'),
    routes: [
      {
        path: '/requests',
        name: 'requests',
        component: RequestsView,
      },
      // The detail route is registered in the real app (US-203 renders it);
      // keep the test router table in sync so navigation never warns.
      {
        path: '/requests/:requestId',
        name: 'request-detail',
        component: { template: '<p>detail</p>' },
      },
    ],
  })
  await router.push({ path: '/requests', query })
  await router.isReady()

  const wrapper = mount(RequestsView, {
    attachTo: document.body,
    global: {
      plugins: [createPinia(), router],
      stubs: { teleport: true },
    },
  })
  await nextTick()
  await nextTick()
  return { wrapper, router }
}

describe('RequestsView list load (US-202)', () => {
  beforeEach(() => {
    localStorage.clear()
    apiGet.mockReset()
    apiGet.mockResolvedValue(LIST_RESULT)
  })

  it('loads summaries from GET /api/v1/requests on mount', async () => {
    const { wrapper } = await mountRequests()
    await nextTick()

    expect(apiGet).toHaveBeenCalledWith('/api/v1/requests', { query: {} })
    expect(wrapper.find('#request-list-count').text()).toContain('显示 3 / 3')
    const items = wrapper.findAll('.request-list-item')
    expect(items).toHaveLength(3)
    expect(items[0]!.text()).toContain('葬送的芙莉莲')
  })

  it('passes the relative storage profile from localStorage', async () => {
    localStorage.setItem('miguOrca.web.storageDir', 'backups')
    await mountRequests()
    await nextTick()

    expect(apiGet).toHaveBeenCalledWith('/api/v1/requests', { query: { storage_dir: 'backups' } })
  })

  it('never sends an absolute storage path in the query', async () => {
    localStorage.setItem('miguOrca.web.storageDir', '/etc/passwd')
    await mountRequests()
    await nextTick()

    expect(apiGet).toHaveBeenCalledWith('/api/v1/requests', { query: {} })
  })

  it('shows the empty state for a zero-result list', async () => {
    apiGet.mockResolvedValue({ requests: [] })
    const { wrapper } = await mountRequests()
    await nextTick()

    expect(wrapper.find('#request-list-count').text()).toContain('显示 0 / 0')
    expect(wrapper.find('.empty-state').text()).toContain('暂无已保存的订阅方案')
  })

  it('shows a safe Chinese error state with retry on API failure', async () => {
    apiGet.mockRejectedValue({
      type: 'storage_error',
      message: '读取订阅方案失败',
    })
    const { wrapper } = await mountRequests()
    await nextTick()

    const error = wrapper.find('.error-state')
    expect(error.exists()).toBe(true)
    expect(error.text()).toContain('订阅方案列表加载失败')
    // The raw server error_message never reaches the DOM.
    expect(error.text()).not.toContain('storage_error')

    apiGet.mockResolvedValue(LIST_RESULT)
    await wrapper.find('.error-state .secondary-button').trigger('click')
    await nextTick()
    await nextTick()
    expect(wrapper.find('#request-list-count').text()).toContain('显示 3 / 3')
  })
})

describe('RequestsView search/filter/sort (US-202)', () => {
  beforeEach(() => {
    localStorage.clear()
    apiGet.mockReset()
    apiGet.mockResolvedValue(LIST_RESULT)
  })

  it('filters by search term and updates the count', async () => {
    const { wrapper } = await mountRequests()
    await nextTick()

    await wrapper.find('#request-list-search').setValue('芙莉莲')
    await nextTick()
    expect(wrapper.find('#request-list-count').text()).toContain('显示 2 / 3')
    const items = wrapper.findAll('.request-list-item')
    expect(items).toHaveLength(2)
    expect(items[0]!.text()).toContain('葬送的芙莉莲')
  })

  it('filters by status code', async () => {
    const { wrapper } = await mountRequests()
    await nextTick()

    await wrapper.find('#request-list-status-filter').setValue('ACCEPTED')
    await nextTick()
    expect(wrapper.find('#request-list-count').text()).toContain('显示 1 / 3')
    expect(wrapper.find('.request-list-item').text()).toContain('咒术回战第三季')
  })

  it('sorts by title ascending', async () => {
    const { wrapper } = await mountRequests()
    await nextTick()

    await wrapper.find('#request-list-sort').setValue('title_asc')
    await nextTick()
    const titles = wrapper.findAll('.request-list-item strong').map((node) => node.text())
    expect(titles).toEqual([...titles].sort((a, b) => a.localeCompare(b, 'zh-CN')))
  })

  it('shows a no-match empty state and clears it', async () => {
    const { wrapper } = await mountRequests()
    await nextTick()

    await wrapper.find('#request-list-search').setValue('不存在的番剧')
    await nextTick()
    expect(wrapper.find('.empty-state').text()).toContain('没有匹配的订阅方案')

    await wrapper.find('#request-list-search').setValue('')
    await nextTick()
    expect(wrapper.find('#request-list-count').text()).toContain('显示 3 / 3')
  })

  it('populates the status filter from the loaded list', async () => {
    const { wrapper } = await mountRequests()
    await nextTick()

    const options = wrapper
      .findAll('#request-list-status-filter option')
      .map((node) => ({ value: node.attributes('value'), text: node.text() }))
    expect(options[0]).toEqual({ value: '', text: '全部' })
    expect(options).toContainEqual({ value: 'PENDING_CONFIRM', text: '待确认' })
    expect(options).toContainEqual({ value: 'ACCEPTED', text: '已确认' })
    expect(options).toContainEqual({ value: 'CANCELLED', text: '已取消' })
  })
})

describe('RequestsView selection & copy (US-202)', () => {
  beforeEach(() => {
    localStorage.clear()
    apiGet.mockReset()
    apiGet.mockResolvedValue(LIST_RESULT)
  })

  it('restores the selected item from the URL request_id', async () => {
    const { wrapper } = await mountRequests({ request_id: 'req-b' })
    await nextTick()

    const selected = wrapper.find('.request-list-item.is-selected')
    expect(selected.exists()).toBe(true)
    expect(selected.attributes('data-request-id')).toBe('req-b')
    expect(selected.attributes('aria-current')).toBe('true')
  })

  it('pushes request_id into the URL when an item is clicked', async () => {
    const { wrapper, router } = await mountRequests()
    await nextTick()

    await wrapper.findAll('.request-list-item')[1]!.trigger('click')
    await flushPromises()
    expect(router.currentRoute.value.query.request_id).toBe('req-b')
    expect(wrapper.find('.request-list-item.is-selected').attributes('data-request-id')).toBe('req-b')
  })

  it('clears the URL request_id when clicking the refresh/empty selection', async () => {
    const { wrapper, router } = await mountRequests({ request_id: 'req-b' })
    await nextTick()

    // Clicking an item with a null request_id clears the query.
    const emptySummary = summary({ request_id: null })
    apiGet.mockResolvedValue({ requests: [emptySummary as never] })
    await wrapper.find('#request-list-refresh').trigger('click')
    await flushPromises()

    await wrapper.find('.request-list-item').trigger('click')
    await flushPromises()
    expect(router.currentRoute.value.query.request_id).toBeUndefined()
  })

  it('copies request_id to the clipboard and shows a notification', async () => {
    Object.assign(navigator, { clipboard: { writeText: vi.fn().mockResolvedValue(undefined) } })
    const { wrapper } = await mountRequests()
    await nextTick()

    await wrapper.find('.copy-request-id').trigger('click')
    await nextTick()

    expect(navigator.clipboard.writeText).toHaveBeenCalledWith('req-a')
    // The notification store drives the shell's aria-live region; assert the
    // store state so the message copy is covered without mounting the shell.
    const { useNotificationStore } = await import('@/app/stores/notification')
    const notification = useNotificationStore()
    expect(notification.current?.kind).toBe('success')
    expect(notification.current?.title).toBe('已复制 request_id')
    expect(notification.current?.message).toBe('req-a')
  })

  it('shows a safe error notification when clipboard write fails', async () => {
    Object.assign(navigator, {
      clipboard: { writeText: vi.fn().mockRejectedValue(new Error('denied')) },
    })
    const { wrapper } = await mountRequests()
    await nextTick()

    await wrapper.find('.copy-request-id').trigger('click')
    await nextTick()

    // No raw error text leaks into the DOM.
    expect(wrapper.text()).not.toContain('denied')
  })
})
