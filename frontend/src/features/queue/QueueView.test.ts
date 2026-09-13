import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import { createPinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createMemoryHistory, createRouter } from 'vue-router'
import { nextTick } from 'vue'

import { api } from '@/api/client'
import type { operations } from '@/api/generated/api'
import QueueView from '@/features/queue/QueueView.vue'

// US-206: 提交队列 migration. The view reads the pre-submission queue from
// the URL batch_id, offers per-status 重试/恢复 actions and a single
// request-scoped Auto Bangumi credential form for submit/retry/recover.
// Sensitive values (endpoint/username/password/token) must never appear in
// localStorage, sessionStorage or the rendered DOM after success/cancel.

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

type QueueResult = NonNullable<
  operations['getBatchQueue']['responses']['200']['content']['application/json']['result']
>
type SubmitResult = NonNullable<
  operations['submitBatchQueue']['responses']['200']['content']['application/json']['result']
>

function queueItem(
  itemId: string,
  requestId: string,
  status = 'READY_TO_SUBMIT',
  overrides: Record<string, unknown> = {},
) {
  return {
    queue_id: 'queue-1',
    batch_id: 'batch-1',
    item_id: itemId,
    request_id: requestId,
    title: '关于我转生变成史莱姆这档事 第四季',
    status,
    status_label: '待提交',
    attempts: 0,
    last_error: null,
    ab_result_summary: null,
    created_at: '2026-08-31T00:00:00+00:00',
    updated_at: '2026-08-31T00:00:00+00:00',
    ...overrides,
  } as never
}

function queueResult(items: unknown[]): QueueResult {
  return {
    batch_id: 'batch-1',
    queue: {
      queue_id: 'queue-1',
      batch_id: 'batch-1',
      created_at: '2026-08-31T00:00:00+00:00',
      updated_at: '2026-08-31T00:00:00+00:00',
      items: items as never,
    },
  }
}

function submitResult(
  items: unknown[],
  summary: Record<string, number>,
  queueItems: unknown[] = [],
): SubmitResult {
  return {
    batch_id: 'batch-1',
    queue: {
      queue_id: 'queue-1',
      batch_id: 'batch-1',
      created_at: '2026-08-31T00:00:00+00:00',
      updated_at: '2026-08-31T00:00:00+00:00',
      items: queueItems as never,
    },
    items: items as never,
    summary,
  }
}

async function mountQueue(query: Record<string, string> = { batch_id: 'batch-1' }) {
  const router = createRouter({
    history: createMemoryHistory('/app/'),
    routes: [{ path: '/tracking', name: 'tracking', component: QueueView }],
  })
  await router.push({ path: '/tracking', query })
  await router.isReady()

  const wrapper = mount(QueueView, {
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

describe('QueueView queue read (US-206)', () => {
  beforeEach(() => {
    localStorage.clear()
    sessionStorage.clear()
    apiGet.mockReset()
    apiPost.mockReset()
  })

  it('reads the queue from the URL batch_id and renders items + count', async () => {
    apiGet.mockResolvedValue(
      queueResult([
        queueItem('item-1', 'req-1', 'SUCCEEDED', { ab_result_summary: 'Auto Bangumi 已接受该订阅方案' }),
        queueItem('item-2', 'req-2', 'FAILED', { attempts: 2, last_error: '订阅方案已不存在，跳过提交' }),
      ]),
    )
    const { wrapper } = await mountQueue()
    await flushPromises()

    expect(apiGet).toHaveBeenCalledWith('/api/v1/batches/{batch_id}/queue', {
      path: { batch_id: 'batch-1' },
      query: {},
    })
    expect(wrapper.find('#batch-queue-count').text()).toContain('队列中 2 项')
    const items = wrapper.findAll('.batch-queue-item')
    expect(items).toHaveLength(2)
    expect(items[0]!.text()).toContain('提交成功')
    expect(items[0]!.text()).toContain('结果：Auto Bangumi 已接受该订阅方案')
    expect(items[1]!.text()).toContain('提交失败')
    expect(items[1]!.text()).toContain('错误：订阅方案已不存在，跳过提交')
    expect(wrapper.find('#batch-queue-submit-form').exists()).toBe(true)
  })

  it('shows the empty state when there are no items and hides the submit form', async () => {
    apiGet.mockResolvedValue(queueResult([]))
    const { wrapper } = await mountQueue()
    await flushPromises()

    expect(wrapper.find('#batch-queue-count').text()).toContain('队列中 0 项')
    expect(wrapper.find('.empty-state').text()).toContain('暂无队列项目')
    expect(wrapper.find('#batch-queue-submit-form').exists()).toBe(false)
  })

  it('shows a safe Chinese error state when the queue read fails', async () => {
    apiGet.mockRejectedValue({ type: 'server_error', message: '内部错误' })
    const { wrapper } = await mountQueue()
    await flushPromises()

    expect(wrapper.find('.error-state').text()).toContain('队列读取失败')
    expect(wrapper.text()).not.toContain('server_error')
    expect(wrapper.find('#batch-queue-refresh').attributes('disabled')).toBeUndefined()
  })

  it('clears the queue when no batch_id is in the URL', async () => {
    const { wrapper } = await mountQueue({})
    await flushPromises()

    expect(apiGet).not.toHaveBeenCalled()
    expect(wrapper.find('#batch-queue-count').text()).toContain('队列中 0 项')
    expect(wrapper.find('#batch-queue-refresh').attributes('disabled')).toBeDefined()
  })

  it('re-reads the queue when the URL batch_id changes', async () => {
    apiGet.mockResolvedValue(queueResult([]))
    const { router } = await mountQueue()
    await flushPromises()

    await router.push({ path: '/tracking', query: { batch_id: 'batch-2' } })
    await flushPromises()
    expect(apiGet).toHaveBeenLastCalledWith('/api/v1/batches/{batch_id}/queue', {
      path: { batch_id: 'batch-2' },
      query: {},
    })
  })
})

describe('QueueView submit (US-206)', () => {
  beforeEach(() => {
    localStorage.clear()
    apiGet.mockReset()
    apiPost.mockReset()
    apiGet.mockResolvedValue(queueResult([queueItem('item-1', 'req-1')]))
  })

  async function fillAbForm(wrapper: VueWrapper) {
    await wrapper.find('#batch-queue-ab-endpoint').setValue('192.168.1.20:7890')
    await wrapper.find('#batch-queue-ab-username').setValue('browser-user')
    await wrapper.find('#batch-queue-ab-password').setValue('browser-secret-password')
    await wrapper.find('#batch-queue-ab-confirm').setValue(true)
  }

  it('validates the AB form before calling submit', async () => {
    const { wrapper } = await mountQueue()
    await flushPromises()

    await wrapper.find('#batch-queue-submit-button').trigger('submit')
    await nextTick()
    expect(apiPost).not.toHaveBeenCalled()
    expect(wrapper.find('#batch-queue-submit-form .status-alert').text()).toContain(
      '请填写服务地址。',
    )

    await wrapper.find('#batch-queue-ab-endpoint').setValue('https://ab.example')
    await wrapper.find('#batch-queue-submit-button').trigger('submit')
    await nextTick()
    expect(apiPost).not.toHaveBeenCalled()
    expect(wrapper.find('#batch-queue-submit-form .status-alert').text()).toContain(
      '请填写用户名。',
    )
  })

  it('requires the explicit confirm checkbox', async () => {
    const { wrapper } = await mountQueue()
    await flushPromises()

    await wrapper.find('#batch-queue-ab-endpoint').setValue('https://ab.example')
    await wrapper.find('#batch-queue-ab-username').setValue('u')
    await wrapper.find('#batch-queue-ab-password').setValue('p')
    await wrapper.find('#batch-queue-submit-button').trigger('submit')
    await nextTick()

    expect(apiPost).not.toHaveBeenCalled()
    expect(wrapper.find('#batch-queue-submit-form .status-alert').text()).toContain(
      '请勾选确认后再提交到 Auto Bangumi。',
    )
  })

  it('submits with request-scoped config and clears credentials on success', async () => {
    apiPost.mockResolvedValue(
      submitResult([{ item_id: 'item-1', status: 'succeeded', reason: null }], { succeeded: 1 }, [
        queueItem('item-1', 'req-1', 'SUCCEEDED', { ab_result_summary: 'Auto Bangumi 已接受该订阅方案' }),
      ]),
    )
    const { wrapper } = await mountQueue()
    await flushPromises()

    await fillAbForm(wrapper)
    await wrapper.find('#batch-queue-submit-button').trigger('submit')
    await flushPromises()

    const submitCall = apiPost.mock.calls.find(([path]) => path === '/api/v1/batches/{batch_id}/submit')
    expect(submitCall).toBeDefined()
    const body = submitCall![1]!.body as Record<string, unknown>
    expect(body).toMatchObject({
      storage_dir: null,
      confirm: true,
      ab_config: {
        auth_mode: 'password',
        base_url: 'http://192.168.1.20:7890',
        username: 'browser-user',
        password: 'browser-secret-password',
        fallback_enabled: false,
      },
    })
    // Sensitive inputs cleared after success; confirm unchecked.
    expect(wrapper.find<HTMLInputElement>('#batch-queue-ab-endpoint').element.value).toBe('')
    expect(wrapper.find<HTMLInputElement>('#batch-queue-ab-password').element.value).toBe('')
    expect(wrapper.find<HTMLInputElement>('input#batch-queue-ab-confirm').element.checked).toBe(false)
    // The updated queue renders the succeeded status.
    expect(wrapper.find('.batch-queue-item .batch-queue-status').text()).toContain('提交成功')
    // Success feedback + global notification.
    expect(wrapper.find('#batch-queue-submit-form .status-alert').text()).toContain('提交成功 1 项')
    const { useNotificationStore } = await import('@/app/stores/notification')
    expect(useNotificationStore().current?.title).toBe('批量提交成功')
  })

  it('keeps inputs on HTTP failure and shows fixed Chinese copy only', async () => {
    apiPost.mockRejectedValue({ type: 'ab_connection_failed', message: 'Auto Bangumi HTTP 连接失败' })
    const { wrapper } = await mountQueue()
    await flushPromises()

    await fillAbForm(wrapper)
    await wrapper.find('#batch-queue-submit-button').trigger('submit')
    await flushPromises()

    expect(wrapper.find('#batch-queue-submit-form .status-alert').text()).toContain(
      'Auto Bangumi 批量提交失败',
    )
    // Legacy parity: HTTP-level failure preserves inputs for retry.
    expect(wrapper.find<HTMLInputElement>('#batch-queue-ab-endpoint').element.value).toBe(
      '192.168.1.20:7890',
    )
    expect(wrapper.find<HTMLInputElement>('#batch-queue-ab-password').element.value).toBe(
      'browser-secret-password',
    )
    expect(wrapper.find<HTMLInputElement>('input#batch-queue-ab-confirm').element.checked).toBe(true)
    // The raw server error/type never reaches the DOM.
    expect(wrapper.text()).not.toContain('ab_connection_failed')
    expect(wrapper.text()).not.toContain('Auto Bangumi HTTP 连接失败')
  })

  it('switching auth mode clears the credentials', async () => {
    const { wrapper } = await mountQueue()
    await flushPromises()

    await wrapper.find('#batch-queue-ab-endpoint').setValue('https://ab.example')
    await wrapper.find('#batch-queue-ab-username').setValue('u')
    await wrapper.find('#batch-queue-ab-password').setValue('p')
    await wrapper.find('#batch-queue-ab-auth-mode').setValue('api_token')
    await nextTick()

    // The endpoint (shared across modes) is cleared and the password-mode
    // fields unmount; the token field appears empty.
    expect(wrapper.find<HTMLInputElement>('#batch-queue-ab-endpoint').element.value).toBe('')
    expect(wrapper.find('#batch-queue-ab-username').exists()).toBe(false)
    expect(wrapper.find('#batch-queue-ab-password').exists()).toBe(false)
    expect(wrapper.find<HTMLInputElement>('#batch-queue-ab-token').element.value).toBe('')
  })
})

describe('QueueView retry & recover (US-206)', () => {
  beforeEach(() => {
    localStorage.clear()
    apiGet.mockReset()
    apiPost.mockReset()
  })

  it('shows the retry button only for FAILED/RETRYABLE items', async () => {
    apiGet.mockResolvedValue(
      queueResult([
        queueItem('item-ok', 'req-ok', 'SUCCEEDED'),
        queueItem('item-fail', 'req-fail', 'FAILED'),
        queueItem('item-retry', 'req-retry', 'RETRYABLE'),
        queueItem('item-sub', 'req-sub', 'SUBMITTING'),
      ]),
    )
    const { wrapper } = await mountQueue()
    await flushPromises()

    expect(wrapper.findAll('.batch-queue-item-retry')).toHaveLength(2)
    expect(wrapper.findAll('.batch-queue-item-recover')).toHaveLength(1)
    const retryItem = wrapper.find('.batch-queue-item[data-item-id="item-retry"]')
    expect(retryItem.find('.batch-queue-item-retry').attributes('data-request-id')).toBe('req-retry')
  })

  it('retries a single failed item with the request-scoped config', async () => {
    apiGet.mockResolvedValue(
      queueResult([queueItem('item-fail', 'req-fail', 'FAILED', { attempts: 1 })]),
    )
    apiPost.mockResolvedValue(
      submitResult([{ item_id: 'item-fail', status: 'succeeded', reason: null }], { succeeded: 1 }, [
        queueItem('item-fail', 'req-fail', 'SUCCEEDED', { attempts: 2, ab_result_summary: 'ok' }),
      ]),
    )
    const { wrapper } = await mountQueue()
    await flushPromises()

    await wrapper.find('#batch-queue-ab-endpoint').setValue('https://ab.example')
    await wrapper.find('#batch-queue-ab-username').setValue('u')
    await wrapper.find('#batch-queue-ab-password').setValue('p')
    await wrapper.find('#batch-queue-ab-confirm').setValue(true)
    await wrapper.find('.batch-queue-item-retry').trigger('click')
    await flushPromises()

    const retryCall = apiPost.mock.calls.find(([path]) => path === '/api/v1/batches/{batch_id}/retry')
    expect(retryCall).toBeDefined()
    const body = retryCall![1]!.body as Record<string, unknown>
    expect(body).toMatchObject({
      request_id: 'req-fail',
      confirm: true,
      ab_config: { auth_mode: 'password', base_url: 'https://ab.example' },
    })
    // Retry button disappears once the item becomes SUCCEEDED.
    expect(wrapper.find('.batch-queue-item-retry').exists()).toBe(false)
    expect(wrapper.find('.batch-queue-item .batch-queue-status').text()).toContain('提交成功')
    expect(wrapper.find('.batch-queue-item-meta').text()).toContain('尝试次数：2')
    // Sensitive inputs cleared after success.
    expect(wrapper.find<HTMLInputElement>('#batch-queue-ab-endpoint').element.value).toBe('')
  })

  it('recover: auto first, then manual verification through the confirm dialog', async () => {
    apiGet.mockResolvedValue(queueResult([queueItem('item-sub', 'req-sub', 'SUBMITTING')]))
    apiPost
      .mockResolvedValueOnce(
        submitResult(
          [{ item_id: 'item-sub', status: 'needs_manual', reason: 'requires_manual_recovery' }],
          { needs_manual: 1 },
          [queueItem('item-sub', 'req-sub', 'SUBMITTING')],
        ),
      )
      .mockResolvedValueOnce(
        submitResult([{ item_id: 'item-sub', status: 'succeeded', reason: null }], { succeeded: 1 }, [
          queueItem('item-sub', 'req-sub', 'SUCCEEDED'),
        ]),
      )
    const { wrapper } = await mountQueue()
    await flushPromises()

    await wrapper.find('.batch-queue-item-recover').trigger('click')
    await flushPromises()

    // Auto-recover was attempted first.
    let recoverCalls = apiPost.mock.calls.filter(([path]) => path === '/api/v1/batches/{batch_id}/recover')
    expect(recoverCalls).toHaveLength(1)
    expect(recoverCalls[0]![1]!.body).toMatchObject({ request_id: 'req-sub', action: 'auto', confirm: false })
    // Manual verification confirm dialog appeared (teleport stub renders inline).
    expect(wrapper.find('.confirm-dialog').text()).toContain('无法自动判断 Auto Bangumi 是否已创建订阅')
    await wrapper.find('.confirm-dialog .primary-button').trigger('click')
    await flushPromises()

    recoverCalls = apiPost.mock.calls.filter(([path]) => path === '/api/v1/batches/{batch_id}/recover')
    expect(recoverCalls).toHaveLength(2)
    expect(recoverCalls[1]![1]!.body).toMatchObject({ request_id: 'req-sub', action: 'succeeded', confirm: true })
    expect(wrapper.find('.batch-queue-item .batch-queue-status').text()).toContain('提交成功')
  })

  it('recover: cancel marks the item as failed (retryable)', async () => {
    apiGet.mockResolvedValue(queueResult([queueItem('item-sub', 'req-sub', 'RESULT_PERSIST_FAILED')]))
    apiPost
      .mockResolvedValueOnce(
        submitResult(
          [{ item_id: 'item-sub', status: 'needs_manual', reason: 'requires_manual_recovery' }],
          { needs_manual: 1 },
          [queueItem('item-sub', 'req-sub', 'RESULT_PERSIST_FAILED')],
        ),
      )
      .mockResolvedValueOnce(
        submitResult([{ item_id: 'item-sub', status: 'failed', reason: null }], { failed: 1 }, [
          queueItem('item-sub', 'req-sub', 'FAILED', { attempts: 2 }),
        ]),
      )
    const { wrapper } = await mountQueue()
    await flushPromises()

    await wrapper.find('.batch-queue-item-recover').trigger('click')
    await flushPromises()

    let recoverCalls = apiPost.mock.calls.filter(([path]) => path === '/api/v1/batches/{batch_id}/recover')
    expect(recoverCalls).toHaveLength(1)
    await wrapper.find('.confirm-dialog .secondary-button').trigger('click')
    await flushPromises()

    recoverCalls = apiPost.mock.calls.filter(([path]) => path === '/api/v1/batches/{batch_id}/recover')
    expect(recoverCalls).toHaveLength(2)
    expect(recoverCalls[1]![1]!.body).toMatchObject({ request_id: 'req-sub', action: 'failed', confirm: true })
    expect(wrapper.find('.batch-queue-item .batch-queue-status').text()).toContain('提交失败')
    expect(wrapper.find('.batch-queue-item-retry').exists()).toBe(true)
  })

  it('shows a fixed Chinese error when recover fails', async () => {
    apiGet.mockResolvedValue(queueResult([queueItem('item-sub', 'req-sub', 'SUBMITTING')]))
    apiPost.mockRejectedValue({ type: 'server_error', message: '内部错误' })
    const { wrapper } = await mountQueue()
    await flushPromises()

    await wrapper.find('.batch-queue-item-recover').trigger('click')
    await flushPromises()

    expect(wrapper.find('#batch-queue-submit-form .status-alert').text()).toContain(
      '队列项目恢复失败',
    )
    expect(wrapper.text()).not.toContain('server_error')
  })

  it('never leaks sensitive values into storage or the DOM after success', async () => {
    apiGet.mockResolvedValue(queueResult([queueItem('item-1', 'req-1')]))
    apiPost.mockResolvedValue(submitResult([{ item_id: 'item-1', status: 'succeeded' }], { succeeded: 1 }, []))
    const { wrapper } = await mountQueue()
    await flushPromises()

    await wrapper.find('#batch-queue-ab-endpoint').setValue('https://private-ab.example')
    await wrapper.find('#batch-queue-ab-username').setValue('secret-user')
    await wrapper.find('#batch-queue-ab-password').setValue('secret-password')
    await wrapper.find('#batch-queue-ab-confirm').setValue(true)
    await wrapper.find('#batch-queue-submit-button').trigger('submit')
    await flushPromises()

    const storageState = JSON.stringify({
      localStorage,
      sessionStorage,
    })
    expect(storageState).not.toContain('private-ab.example')
    expect(storageState).not.toContain('secret-user')
    expect(storageState).not.toContain('secret-password')
    expect(wrapper.text()).not.toContain('secret-password')
    expect(wrapper.text()).not.toContain('private-ab.example')
  })
})
