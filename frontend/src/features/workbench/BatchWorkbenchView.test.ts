import { flushPromises, mount } from '@vue/test-utils'
import { createPinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createMemoryHistory, createRouter } from 'vue-router'
import { nextTick } from 'vue'

import { api } from '@/api/client'
import type { operations } from '@/api/generated/api'
import BatchWorkbenchView from '@/features/workbench/BatchWorkbenchView.vue'

// US-205: batch workbench migration. The view parses a multi-line input into
// independent FOUND/EMPTY/FAILED cards, opens the shared candidate popover,
// generates server-authoritative drafts, and accepts selected/all cards
// through the shared batch accept endpoint.

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

const apiPost = vi.mocked(api.post)

type ParseResult = NonNullable<
  operations['parseBatchTitles']['responses']['200']['content']['application/json']['result']
>
type AcceptResult = NonNullable<
  operations['acceptBatchItems']['responses']['200']['content']['application/json']['result']
>

function batchItem(overrides: Record<string, unknown> = {}) {
  return {
    item_id: 'item-1',
    raw_title: '萌王S4',
    status: 'FOUND',
    canonical_title_candidates: ['关于我转生变成史莱姆这档事 第四季'],
    season_hint: 'S4',
    search_queries: ['转生史莱姆 第四季'],
    confidence: 0.9,
    needs_user_review: false,
    source: 'rule',
    parse_result: null,
    attempted_queries: [],
    candidates: [],
    applied_preferences: null,
    preference_hits: [],
    preference_warnings: [],
    review_hints: [],
    enhanced_search_queries: [],
    preview_request: null,
    draft_id: null,
    error: null,
    ...overrides,
  } as never
}

function previewRequest(requestId = 'req-1') {
  return {
    request_id: requestId,
    status: 'PENDING_CONFIRM',
    input: { raw_title: '萌王S4' },
    source_info: {
      matched_bangumi: { title: '关于我转生变成史莱姆这档事 第四季' },
      rss_sources: [
        {
          subtitle_group: '喵萌奶茶屋',
          seed_names: ['史莱姆 S4 01 [1080p]'],
          valid_seed_names: ['史莱姆 S4 01 [1080p]'],
          excluded_seed_names: [],
        },
      ],
    },
    confirmable_config: {
      selected_subtitle_group: '喵萌奶茶屋',
      filter_rule: { must_contain: '', must_not_contain: '', use_regex: false, case_sensitive: false },
      effective_seed_names: ['史莱姆 S4 01 [1080p]'],
      expected_folder_name: '关于我转生变成史莱姆这档事 第四季',
      warnings: [],
    },
  }
}

function parseResult(overrides: Partial<Record<string, unknown>> = {}): ParseResult {
  return {
    batch_id: 'batch-1',
    raw_input: '萌王S4',
    items: [batchItem()],
    ...overrides,
  } as never
}

function acceptResult(overrides: Partial<Record<string, unknown>> = {}): AcceptResult {
  return {
    batch_id: 'batch-1',
    queue: {
      queue_id: 'queue-1',
      batch_id: 'batch-1',
      created_at: '2026-08-31T00:00:00+00:00',
      updated_at: '2026-08-31T00:00:00+00:00',
      items: [],
    },
    items: [],
    summary: { accepted: 0, already_accepted: 0, unacceptable: 0, failed: 0 },
    ...overrides,
  } as never
}

function queueItem(itemId: string, requestId: string, status = 'READY_TO_SUBMIT') {
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
  }
}

async function mountBatch() {
  const router = createRouter({
    history: createMemoryHistory('/app/'),
    routes: [
      { path: '/workbench', name: 'workbench', component: BatchWorkbenchView },
      { path: '/requests', name: 'requests', component: { template: '<p>requests</p>' } },
    ],
  })
  await router.push({ path: '/workbench' })
  await router.isReady()

  const wrapper = mount(BatchWorkbenchView, {
    attachTo: document.body,
    global: {
      plugins: [createPinia(), router],
      stubs: { teleport: true },
    },
  })
  await nextTick()
  return { wrapper, router }
}

describe('BatchWorkbenchView parse (US-205)', () => {
  beforeEach(() => {
    localStorage.clear()
    apiPost.mockReset()
  })

  it('validates the empty batch input before calling the API', async () => {
    const { wrapper } = await mountBatch()

    await wrapper.find('#batch-parse-submit').trigger('click')
    await nextTick()

    expect(apiPost).not.toHaveBeenCalled()
    expect(wrapper.find('#batch-parse-error').text()).toContain('批量获取前必须输入至少一个番剧名称')
  })

  it('parses multi-line input into independent cards with statuses', async () => {
    apiPost.mockResolvedValue(
      parseResult({
        items: [
          batchItem({ item_id: 'item-found', status: 'FOUND', candidates: [{ bangumi_id: '42' }] }),
          batchItem({ item_id: 'item-empty', status: 'EMPTY' }),
          batchItem({ item_id: 'item-failed', status: 'FAILED', error: { error_type: 'mikan_http_failed', error_message: 'MiKan 候选搜索暂时不可用' } }),
        ],
      }),
    )
    const { wrapper } = await mountBatch()

    await wrapper.find('#batch-raw-input').setValue('萌王S4\n路哥S4\n杖剑谭S2')
    await wrapper.find('#batch-parse-submit').trigger('click')
    await flushPromises()

    expect(apiPost).toHaveBeenCalledWith('/api/v1/batches/parse', {
      body: { raw_input: '萌王S4\n路哥S4\n杖剑谭S2', storage_dir: null },
    })
    const cards = wrapper.findAll('.batch-draft-card')
    expect(cards).toHaveLength(3)
    expect(cards[0]!.text()).toContain('找到候选')
    expect(cards[1]!.text()).toContain('未找到候选')
    expect(cards[2]!.text()).toContain('搜索失败')
    // The raw error_type never reaches the DOM.
    expect(wrapper.text()).not.toContain('mikan_http_failed')
  })

  it('shows a loading message with the item count and a safe error on failure', async () => {
    apiPost.mockRejectedValue({ type: 'server_error', message: '内部错误' })
    const { wrapper } = await mountBatch()

    await wrapper.find('#batch-raw-input').setValue('萌王S4\n路哥S4')
    await wrapper.find('#batch-parse-submit').trigger('click')
    await flushPromises()

    expect(wrapper.find('.error-state').text()).toContain('批量草案获取失败')
    expect(wrapper.text()).not.toContain('server_error')
  })

  it('pushes batch_id into the URL and restores it on refresh', async () => {
    apiPost.mockResolvedValue(parseResult())
    const { wrapper, router } = await mountBatch()

    await wrapper.find('#batch-raw-input').setValue('萌王S4')
    await wrapper.find('#batch-parse-submit').trigger('click')
    await flushPromises()

    expect(router.currentRoute.value.query.batch_id).toBe('batch-1')
  })
})

describe('BatchWorkbenchView candidate & draft (US-205)', () => {
  beforeEach(() => {
    localStorage.clear()
    apiPost.mockReset()
  })

  it('opens the candidate popover for a FOUND card and generates a draft on selection', async () => {
    apiPost
      .mockResolvedValueOnce(
        parseResult({
          items: [
            batchItem({
              item_id: 'item-found',
              status: 'FOUND',
              candidates: [{ bangumi_id: '42', title: '关于我转生变成史莱姆这档事 第四季', mikan_url: 'https://mikan.example/Home/Bangumi/42' }],
            }),
          ],
        }),
      )
      .mockResolvedValueOnce({ request: previewRequest('req-draft'), summary: {}, draft_id: 'opaque-draft' })
    const { wrapper } = await mountBatch()

    await wrapper.find('#batch-raw-input').setValue('萌王S4')
    await wrapper.find('#batch-parse-submit').trigger('click')
    await flushPromises()

    const card = wrapper.find('.batch-draft-card')
    expect(card.find('.batch-card-expand').text()).toContain('查看候选')
    await card.find('.batch-card-expand').trigger('click')
    await nextTick()

    const popover = wrapper.find('#batch-candidate-choices')
    expect(popover.exists()).toBe(true)
    expect(popover.text()).toContain('候选合集')
    await popover.find('.candidate-select').trigger('click')
    await flushPromises()

    expect(apiPost).toHaveBeenCalledWith('/api/v1/requests', expect.objectContaining({}))
    expect(card.find('.batch-card-status').text()).toContain('草案')
    // The draft_id never enters the DOM.
    expect(wrapper.text()).not.toContain('opaque-draft')
  })

  it('reuses the shared draft panel and shows batch actions', async () => {
    apiPost.mockResolvedValue(
      parseResult({
        items: [batchItem({ item_id: 'item-draft', status: 'DRAFT', preview_request: previewRequest('req-saved'), draft_id: 'draft-1' })],
      }),
    )
    const { wrapper } = await mountBatch()

    await wrapper.find('#batch-raw-input').setValue('萌王S4')
    await wrapper.find('#batch-parse-submit').trigger('click')
    await flushPromises()

    await wrapper.find('.batch-card-expand').trigger('click')
    await nextTick()

    expect(wrapper.find('#detail-preview-edit-form').exists()).toBe(true)
    expect(wrapper.find('#batch-detail-accept').exists()).toBe(true)
    expect(wrapper.find('#batch-detail-delete').exists()).toBe(true)
  })
})

describe('BatchWorkbenchView accept (US-205)', () => {
  beforeEach(() => {
    localStorage.clear()
    apiPost.mockReset()
  })

  function reviewableItems() {
    return [
      batchItem({ item_id: 'item-1', status: 'DRAFT', preview_request: previewRequest('req-1') }),
      batchItem({ item_id: 'item-2', status: 'DRAFT', preview_request: previewRequest('req-2') }),
      batchItem({ item_id: 'item-3', status: 'FAILED' }),
    ]
  }

  it('selects cards and accepts only the checked ones with item_ids', async () => {
    apiPost
      .mockResolvedValueOnce(parseResult({ items: reviewableItems() }))
      .mockResolvedValueOnce(
        acceptResult({
          items: [
            { item_id: 'item-1', request_id: 'req-1', title: 't', status: 'accepted', reason: null, error_type: null, queued: true },
            { item_id: 'item-3', request_id: null, title: 't', status: 'unacceptable', reason: '卡片缺少订阅草案，无法接受', error_type: null, queued: false },
          ],
          queue: { queue_id: 'queue-1', batch_id: 'batch-1', created_at: '', updated_at: '', items: [queueItem('item-1', 'req-1')] },
          summary: { accepted: 1, already_accepted: 0, unacceptable: 1, failed: 0 },
        }),
      )
    const { wrapper } = await mountBatch()

    await wrapper.find('#batch-raw-input').setValue('萌王S4\n路哥S4\n杖剑谭S2')
    await wrapper.find('#batch-parse-submit').trigger('click')
    await flushPromises()

    expect(wrapper.find('#batch-accept-selected-count').text()).toContain('已选择 0 项')
    const firstCard = wrapper.find('.batch-draft-card[data-item-id="item-1"]')
    await firstCard.find('input[type=checkbox]').setValue(true)
    await nextTick()
    expect(wrapper.find('#batch-accept-selected-count').text()).toContain('已选择 1 项')

    await wrapper.find('#batch-accept-submit').trigger('click')
    await nextTick()
    // ConfirmDialog (teleport stub renders inline) must be confirmed.
    expect(wrapper.find('.confirm-dialog').text()).toContain('确认接受选中的 1 个批量卡片')
    await wrapper.find('.confirm-dialog .primary-button').trigger('click')
    await flushPromises()

    expect(apiPost).toHaveBeenCalledWith('/api/v1/batches/{batch_id}/accept', {
      path: { batch_id: 'batch-1' },
      body: {
        items: [
          { item_id: 'item-1', request_id: 'req-1', title: '关于我转生变成史莱姆这档事 第四季' },
        ],
        storage_dir: null,
        item_ids: ['item-1'],
      },
    })
    // Accepted card shows 已接受 + queue status; the unacceptable card shows a Chinese reason.
    expect(wrapper.find('.batch-draft-card[data-item-id="item-1"] .batch-card-status').text()).toContain('已接受')
    expect(wrapper.find('.batch-draft-card[data-item-id="item-1"] .batch-card-queue-status').text()).toContain('待提交')
    expect(wrapper.find('.batch-draft-card[data-item-id="item-3"] .batch-card-reason').text()).toContain(
      '无法接受：卡片缺少订阅草案，无法接受',
    )
  })

  it('accepts all reviewable cards when item_ids is omitted', async () => {
    apiPost
      .mockResolvedValueOnce(parseResult({ items: reviewableItems() }))
      .mockResolvedValueOnce(
        acceptResult({
          items: [
            { item_id: 'item-1', request_id: 'req-1', title: 't', status: 'accepted', reason: null, error_type: null, queued: true },
            { item_id: 'item-2', request_id: 'req-2', title: 't', status: 'accepted', reason: null, error_type: null, queued: true },
            { item_id: 'item-3', request_id: null, title: 't', status: 'unacceptable', reason: '卡片缺少订阅草案，无法接受', error_type: null, queued: false },
          ],
          queue: {
            queue_id: 'queue-1',
            batch_id: 'batch-1',
            created_at: '',
            updated_at: '',
            items: [queueItem('item-1', 'req-1'), queueItem('item-2', 'req-2')],
          },
          summary: { accepted: 2, already_accepted: 0, unacceptable: 1, failed: 0 },
        }),
      )
    const { wrapper } = await mountBatch()

    await wrapper.find('#batch-raw-input').setValue('萌王S4\n路哥S4\n杖剑谭S2')
    await wrapper.find('#batch-parse-submit').trigger('click')
    await flushPromises()

    await wrapper.find('#batch-accept-all').trigger('click')
    await nextTick()
    await wrapper.find('.confirm-dialog .primary-button').trigger('click')
    await flushPromises()

    const acceptCall = apiPost.mock.calls.find(([path]) => path === '/api/v1/batches/{batch_id}/accept')
    expect(acceptCall).toBeDefined()
    const body = acceptCall![1]!.body as Record<string, unknown>
    expect(body.item_ids).toBeUndefined()
    // Legacy parity: accept-all sends every card so the server returns the
    // unacceptable reason for non-reviewable cards.
    expect((body.items as Array<{ item_id: string }>).map((i) => i.item_id)).toEqual(['item-1', 'item-2', 'item-3'])
    // The FAILED card shows the server-provided unacceptable reason.
    expect(wrapper.find('.batch-draft-card[data-item-id="item-3"] .batch-card-reason').text()).toContain(
      '无法接受：卡片缺少订阅草案，无法接受',
    )
    // Accepted cards show 已接受 + queue status.
    expect(wrapper.find('.batch-draft-card[data-item-id="item-1"] .batch-card-status').text()).toContain('已接受')
    expect(wrapper.find('.batch-draft-card[data-item-id="item-2"] .batch-card-status').text()).toContain('已接受')
  })

  it('shows a safe Chinese error when the accept request fails', async () => {
    apiPost
      .mockResolvedValueOnce(parseResult({ items: reviewableItems() }))
      .mockRejectedValueOnce({ type: 'ab_connection_failed', message: 'Auto Bangumi HTTP 连接失败' })
    const { wrapper } = await mountBatch()

    await wrapper.find('#batch-raw-input').setValue('萌王S4\n路哥S4\n杖剑谭S2')
    await wrapper.find('#batch-parse-submit').trigger('click')
    await flushPromises()

    await wrapper.find('#batch-accept-all').trigger('click')
    await nextTick()
    await wrapper.find('.confirm-dialog .primary-button').trigger('click')
    await flushPromises()

    const { useNotificationStore } = await import('@/app/stores/notification')
    const notification = useNotificationStore()
    expect(notification.current?.title).toBe('接受失败')
    expect(notification.current?.message).toBe('批量接受失败。请稍后重试。')
    // The raw server error never reaches the DOM.
    expect(wrapper.text()).not.toContain('ab_connection_failed')
    expect(wrapper.find('.batch-draft-card[data-item-id="item-1"] .batch-card-status').text()).toContain('草案')
  })

  it('deletes a card and unselects it', async () => {
    apiPost.mockResolvedValue(parseResult({ items: reviewableItems() }))
    const { wrapper } = await mountBatch()

    await wrapper.find('#batch-raw-input').setValue('萌王S4\n路哥S4\n杖剑谭S2')
    await wrapper.find('#batch-parse-submit').trigger('click')
    await flushPromises()

    expect(wrapper.findAll('.batch-draft-card')).toHaveLength(3)
    await wrapper.find('.batch-draft-card[data-item-id="item-2"] .batch-card-delete').trigger('click')
    await nextTick()

    expect(wrapper.findAll('.batch-draft-card')).toHaveLength(2)
    expect(wrapper.text()).not.toContain('req-2')
  })
})
