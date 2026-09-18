import { flushPromises, mount } from '@vue/test-utils'
import { createPinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createMemoryHistory, createRouter } from 'vue-router'
import { nextTick } from 'vue'

import { api } from '@/api/client'
import type { operations } from '@/api/generated/api'
import BatchWorkbenchView from '@/features/workbench/BatchWorkbenchView.vue'
import { nextBatchException } from '@/features/workbench/batchWorkbench'

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
      ? error
      : { type: 'request_error', message: '请求失败，请重试' },
  isApiError: () => false,
  apiRequest: vi.fn(),
}))

const apiPost = vi.mocked(api.post)

type ParseResult = NonNullable<
  operations['parseBatchTitles']['responses']['200']['content']['application/json']['result']
>
type SaveConfirmResult = NonNullable<
  operations['saveConfirmBatchItems']['responses']['200']['content']['application/json']['result']
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

function saveConfirmResult(overrides: Partial<Record<string, unknown>> = {}): SaveConfirmResult {
  return {
    batch_id: 'batch-1',
    results: [],
    summary: { requested: 0, confirmed: 0, failed: 0 },
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
      { path: '/add', name: 'add', component: BatchWorkbenchView },
      { path: '/plans', name: 'plans', component: { template: '<p>requests</p>' } },
    ],
  })
  await router.push({ path: '/add' })
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
    expect(wrapper.find('#batch-parse-error').text()).toContain('0 部')
  })

  it('blocks batches above 36 normalized non-empty lines without changing the raw input', async () => {
    const { wrapper } = await mountBatch()
    const rawInput = Array.from({ length: 37 }, (_, index) => `番剧${index}`).join('\n')
    await wrapper.find('#batch-raw-input').setValue(rawInput)
    await wrapper.find('#batch-parse-submit').trigger('click')
    await nextTick()

    expect(apiPost).not.toHaveBeenCalled()
    expect(wrapper.find('#batch-parse-error').text()).toContain('37 部')
    expect((wrapper.find('#batch-raw-input').element as HTMLTextAreaElement).value).toBe(rawInput)
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
      timeoutMs: 420000,
    })
    const cards = wrapper.findAll('.batch-draft-card')
    expect(cards).toHaveLength(3)
    expect(wrapper.find('.batch-draft-card[data-item-id="item-found"]').text()).toContain('找到候选')
    expect(wrapper.find('.batch-draft-card[data-item-id="item-empty"]').text()).toContain('未找到候选')
    expect(wrapper.find('.batch-draft-card[data-item-id="item-failed"]').text()).toContain('搜索失败')
    // The raw error_type never reaches the DOM.
    expect(wrapper.text()).not.toContain('mikan_http_failed')
  })

  it('shows completion progress and marks a single parsed item current', async () => {
    apiPost.mockResolvedValue(parseResult())
    const { wrapper } = await mountBatch()
    await wrapper.find('#batch-raw-input').setValue('萌王S4')
    await wrapper.find('#batch-parse-submit').trigger('click')
    await flushPromises()

    expect(wrapper.find('#batch-parse-progress').text()).toContain('1 / 1 部')
    expect(wrapper.find('.batch-draft-card').classes()).toContain('is-current')
  })

  it('shows an honest long-running wait and blocks duplicate batch parses', async () => {
    let resolveParse!: (value: ParseResult) => void
    const pending = new Promise<ParseResult>((resolve) => { resolveParse = resolve })
    apiPost.mockImplementation(() => pending)
    const { wrapper } = await mountBatch()
    await wrapper.find('#batch-raw-input').setValue('萌王S4\n路哥S4')
    void wrapper.find('#batch-parse-submit').trigger('click')
    await nextTick()
    await wrapper.find('#batch-parse-submit').trigger('click')

    expect(apiPost).toHaveBeenCalledTimes(1)
    expect(wrapper.find('#batch-parse-result').text()).toContain('逐项处理')
    expect(wrapper.find('#batch-parse-result').text()).toContain('数分钟')
    resolveParse(parseResult())
    await flushPromises()
  })

  it('maps a per-item MiKan timeout to fixed feedback without raw error text', async () => {
    apiPost.mockResolvedValue(parseResult({
      items: [batchItem({
        status: 'FAILED',
        error: { error_type: 'mikan_timeout', details: { category: 'mikan_search' }, error_message: 'raw upstream text' },
      })],
    }))
    const { wrapper } = await mountBatch()
    await wrapper.find('#batch-raw-input').setValue('萌王S4')
    await wrapper.find('#batch-parse-submit').trigger('click')
    await flushPromises()
    expect(wrapper.find('.batch-candidate-feedback').text()).toContain('MiKan 上游响应超时')
    expect(wrapper.text()).not.toContain('raw upstream text')
  })

  it('filters visibility without clearing selection or the current detail', async () => {
    apiPost.mockResolvedValue(parseResult({
      items: [
        batchItem({ item_id: 'item-found', raw_title: '萌王', status: 'FOUND', candidates: [{ bangumi_id: '42' }] }),
        batchItem({ item_id: 'item-failed', raw_title: '路哥', canonical_title_candidates: [], status: 'FAILED' }),
      ],
    }))
    const { wrapper } = await mountBatch()
    await wrapper.find('#batch-raw-input').setValue('萌王\n路哥')
    await wrapper.find('#batch-parse-submit').trigger('click')
    await flushPromises()

    const failedCard = wrapper.find('.batch-draft-card[data-item-id="item-failed"]')
    await failedCard.trigger('click')
    await wrapper.find('#batch-review-search').setValue('萌王')
    await nextTick()

    expect(wrapper.findAll('.batch-draft-card')).toHaveLength(1)
    expect(wrapper.find('.batch-draft-card').attributes('data-item-id')).toBe('item-found')
    expect(wrapper.find('.batch-filter-hidden').text()).toContain('当前条目已被筛选隐藏')
    expect(wrapper.find('.batch-detail-title').text()).toContain('路哥')
    expect(wrapper.find('.batch-review-count').text()).toContain('共 2 部，当前显示 1 部')

    await wrapper.find('#batch-review-clear').trigger('click')
    await nextTick()
    expect(wrapper.findAll('.batch-draft-card')).toHaveLength(2)
  })

  it('sorts exceptions only when explicitly requested', async () => {
    apiPost.mockResolvedValue(parseResult({
      items: [
        batchItem({ item_id: 'item-normal', status: 'FOUND', raw_title: '正常' }),
        batchItem({ item_id: 'item-failed', status: 'FAILED', raw_title: '异常' }),
      ],
    }))
    const { wrapper } = await mountBatch()
    await wrapper.find('#batch-raw-input').setValue('正常\n异常')
    await wrapper.find('#batch-parse-submit').trigger('click')
    await flushPromises()
    expect(wrapper.findAll('.batch-draft-card')[0]?.attributes('data-item-id')).toBe('item-failed')
    await wrapper.find('#batch-review-sort-exceptions').trigger('click')
    expect(wrapper.find('.batch-review-count').text()).toContain('已按异常排序')
  })

  it('shows a loading message with the item count and a safe error on failure', async () => {
    apiPost.mockRejectedValue({ type: 'server_error', message: '内部错误' })
    const { wrapper } = await mountBatch()

    await wrapper.find('#batch-raw-input').setValue('萌王S4\n路哥S4')
    await wrapper.find('#batch-parse-submit').trigger('click')
    await flushPromises()

    expect(wrapper.find('.error-state').text()).toContain('批量草案获取失败')
    expect(wrapper.text()).toContain('应用内部处理异常')
    expect(wrapper.text()).not.toContain('server_error')
  })

  it.each([
    ['request_timeout', '等待超时'],
    ['network_error', '网络或连接不可用'],
    ['server_error', '应用内部处理异常'],
  ])('maps top-level %s to fixed batch feedback', async (type, expected) => {
    apiPost.mockRejectedValue({ type, message: `raw canary https://private.invalid/${type}` })
    const { wrapper } = await mountBatch()
    await wrapper.find('#batch-raw-input').setValue('萌王S4')
    await wrapper.find('#batch-parse-submit').trigger('click')
    await flushPromises()

    expect(wrapper.text()).toContain(expected)
    expect(wrapper.text()).not.toContain('private.invalid')
    expect(wrapper.text()).not.toContain(type)
  })

  it('pushes batch_id into the URL and restores it on refresh', async () => {
    apiPost.mockResolvedValue(parseResult())
    const { wrapper, router } = await mountBatch()

    await wrapper.find('#batch-raw-input').setValue('萌王S4')
    await wrapper.find('#batch-parse-submit').trigger('click')
    await flushPromises()

    expect(router.currentRoute.value.query.batch_id).toBe('batch-1')
  })

  it('cycles to the next exception and temporarily reveals a filtered target', async () => {
    apiPost.mockResolvedValue(parseResult({
      items: [
        batchItem({ item_id: 'item-normal', raw_title: '正常', status: 'FOUND' }),
        batchItem({ item_id: 'item-failed', raw_title: '异常', status: 'FAILED', canonical_title_candidates: [] }),
        batchItem({ item_id: 'item-empty', raw_title: '空结果', status: 'EMPTY', canonical_title_candidates: [] }),
      ],
    }))
    const { wrapper } = await mountBatch()
    await wrapper.find('#batch-raw-input').setValue('正常\n异常\n空结果')
    await wrapper.find('#batch-parse-submit').trigger('click')
    await flushPromises()

    expect(nextBatchException(
      [batchItem({ item_id: 'normal' }), batchItem({ item_id: 'failed', status: 'FAILED' })],
      'normal',
    )?.item_id).toBe('failed')
    await wrapper.find('.batch-draft-card[data-item-id="item-normal"]').trigger('click')
    await wrapper.find('#batch-review-search').setValue('正常')
    await nextTick()
    await wrapper.find('#batch-next-exception').trigger('click')
    await nextTick()

    expect(wrapper.find('.batch-draft-card[data-item-id="item-failed"]').exists()).toBe(true)
    expect(wrapper.find('.batch-review-navigation').text()).toContain('已临时显示异常条目')
    expect(document.activeElement).toBe(wrapper.find('.batch-draft-card[data-item-id="item-failed"]').element)
    await wrapper.find('#batch-next-exception').trigger('click')
    await nextTick()
    expect(wrapper.find('.batch-draft-card[data-item-id="item-empty"]').classes()).toContain('is-current')
  })

  it('uses arrow keys to move cards and Enter activates their primary action', async () => {
    apiPost.mockResolvedValue(parseResult({
      items: [
        batchItem({ item_id: 'item-one', raw_title: '一', status: 'FAILED' }),
        batchItem({ item_id: 'item-two', raw_title: '二', status: 'EMPTY' }),
      ],
    }))
    const { wrapper } = await mountBatch()
    await wrapper.find('#batch-raw-input').setValue('一\n二')
    await wrapper.find('#batch-parse-submit').trigger('click')
    await flushPromises()

    const first = wrapper.find('.batch-draft-card[data-item-id="item-one"]')
    await first.trigger('keydown', { key: 'ArrowDown' })
    await nextTick()
    expect(wrapper.find('.batch-draft-card[data-item-id="item-two"]').classes()).toContain('is-current')
    await wrapper.find('.batch-draft-card[data-item-id="item-two"]').trigger('keydown', { key: 'Enter' })
    expect(wrapper.find('.batch-detail-title').text()).toContain('关于我转生变成史莱姆这档事')
  })
})

describe('BatchWorkbenchView candidate & draft (US-205)', () => {
  beforeEach(() => {
    localStorage.clear()
    apiPost.mockReset()
  })

  it('selects a FOUND candidate in the current detail pane and generates its draft', async () => {
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

    const detailCandidates = wrapper.find('.batch-detail-pane')
    expect(detailCandidates.text()).toContain('候选合集')
    await detailCandidates.find('.candidate-select').trigger('click')
    await flushPromises()

    expect(apiPost).toHaveBeenCalledWith('/api/v1/requests', expect.objectContaining({
      timeoutMs: 240000,
    }))
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
    // F4/US-345: 右栏只负责当前条目的查看与改选，固定操作栏是唯一的批量
    // 「保存并确认 N 部」主入口，右栏不再摆放第二个主按钮。
    expect(wrapper.find('#batch-detail-accept').classes()).toContain('secondary-button')
    expect(wrapper.find('#batch-preview-apply-button').classes()).toContain('secondary-button')
    expect(wrapper.find('#batch-accept-submit').classes()).toContain('primary-button')
    expect(wrapper.find('#batch-detail-pane').findAll('.primary-button')).toHaveLength(0)
  })

  it('blocks a dirty draft from detail selection and save-confirm', async () => {
    apiPost.mockResolvedValue(parseResult({
      items: [batchItem({ item_id: 'item-dirty', status: 'DRAFT', preview_request: previewRequest('req-dirty'), draft_id: 'draft-dirty' })],
    }))
    const { wrapper } = await mountBatch()
    await wrapper.find('#batch-raw-input').setValue('萌王S4')
    await wrapper.find('#batch-parse-submit').trigger('click')
    await flushPromises()
    await wrapper.find('.batch-card-expand').trigger('click')
    await wrapper.find('#batch-preview-must-contain').setValue('未应用修改')
    await nextTick()

    expect(wrapper.find('#batch-detail-accept').attributes('disabled')).toBeDefined()
    expect(wrapper.find('.batch-card-checkbox-row').attributes('disabled')).toBeDefined()
    expect(wrapper.text()).toContain('有尚未应用的编辑')
    expect(apiPost).toHaveBeenCalledTimes(1)
    // US-344: leaving the item disposes the pending 1.5s debounce window, so a
    // later test can never inherit this one's timer.
    wrapper.unmount()
  })

  it('blocks a draft with no effective resources', async () => {
    const request = previewRequest('req-empty-seeds')
    request.confirmable_config.effective_seed_names = []
    apiPost.mockResolvedValue(parseResult({
      items: [batchItem({ item_id: 'item-empty-seeds', status: 'DRAFT', preview_request: request, draft_id: 'draft-empty-seeds' })],
    }))
    const { wrapper } = await mountBatch()
    await wrapper.find('#batch-raw-input').setValue('萌王S4')
    await wrapper.find('#batch-parse-submit').trigger('click')
    await flushPromises()

    expect(wrapper.find('.batch-card-checkbox-row').attributes('disabled')).toBeDefined()
    expect(wrapper.text()).toContain('没有有效资源')
  })

  it('keeps the batch card and candidates when its draft expires', async () => {
    apiPost
      .mockResolvedValueOnce(parseResult({
        items: [batchItem({
          item_id: 'item-expired',
          status: 'DRAFT',
          candidates: [{ bangumi_id: '42', title: '候选合集' }],
          preview_request: previewRequest('req-expired'),
          draft_id: 'draft-expired',
        })],
      }))
      .mockResolvedValueOnce(saveConfirmResult({
        results: [{ item_id: 'item-expired', outcome: 'failed', request_id: null, status: null, error_type: 'draft_expired', error_message: null, tracking_id: null, tracking_ready: null }],
        summary: { requested: 1, confirmed: 0, failed: 1 },
      }))
      .mockRejectedValueOnce({ type: 'draft_expired', message: 'draft expired' })
    const { wrapper } = await mountBatch()

    await wrapper.find('#batch-raw-input').setValue('萌王S4')
    await wrapper.find('#batch-parse-submit').trigger('click')
    await flushPromises()
    await wrapper.find('.batch-draft-card input[type="checkbox"]').setValue(true)
    await wrapper.find('#batch-accept-submit').trigger('click')
    await nextTick()
    await wrapper.find('.confirm-dialog .primary-button').trigger('click')
    await flushPromises()
    expect(wrapper.find('.batch-card-reason').text()).toContain('订阅草案已失效')
    expect(wrapper.findAll('.batch-draft-card')).toHaveLength(1)
    expect(wrapper.find('.batch-card-status').text()).toContain('找到候选')
    expect(wrapper.find('#request-detail-container').exists()).toBe(false)
    expect(wrapper.find('.batch-card-expand').text()).toContain('查看候选')
    expect((wrapper.find('.batch-draft-card input[type="checkbox"]').element as HTMLInputElement).checked).toBe(false)
    expect(wrapper.find('#batch-detail-pane').text()).toContain('候选合集')
    expect(wrapper.text()).not.toContain('已删除批量卡片')
  })
})

describe('BatchWorkbenchView accept (US-205)', () => {
  beforeEach(() => {
    localStorage.clear()
    apiPost.mockReset()
    vi.mocked(api.get).mockReset()
  })

  function reviewableItems() {
    return [
      batchItem({ item_id: 'item-1', status: 'DRAFT', preview_request: previewRequest('req-1'), draft_id: 'draft-1', draft_revision: 1 }),
      batchItem({ item_id: 'item-2', status: 'DRAFT', preview_request: previewRequest('req-2'), draft_id: 'draft-2', draft_revision: 1 }),
      batchItem({ item_id: 'item-3', status: 'FAILED' }),
    ]
  }

  it('selects cards and accepts only the checked ones with item_ids', async () => {
    apiPost
      .mockResolvedValueOnce(parseResult({ items: reviewableItems() }))
      .mockResolvedValueOnce(
        saveConfirmResult({
          results: [
            { item_id: 'item-1', request_id: 'req-1', status: 'CONFIRMED', outcome: 'CONFIRMED', error_type: null, error_message: null, tracking_id: null, tracking_ready: false },
          ],
          queue: { queue_id: 'queue-1', batch_id: 'batch-1', created_at: '', updated_at: '', items: [queueItem('item-1', 'req-1')] },
          summary: { requested: 2, confirmed: 1, failed: 1 },
        }),
      )
    const { wrapper } = await mountBatch()

    await wrapper.find('#batch-raw-input').setValue('萌王S4\n路哥S4\n杖剑谭S2')
    await wrapper.find('#batch-parse-submit').trigger('click')
    await flushPromises()

    expect(wrapper.find('#batch-accept-selected-count').text()).toContain('已选且可确认 0 项')
    const firstCard = wrapper.find('.batch-draft-card[data-item-id="item-1"]')
    await firstCard.find('input[type=checkbox]').setValue(true)
    await nextTick()
    expect(wrapper.find('#batch-accept-selected-count').text()).toContain('已选且可确认 1 项')

    await wrapper.find('#batch-accept-submit').trigger('click')
    await nextTick()
    // ConfirmDialog (teleport stub renders inline) must be confirmed.
    expect(wrapper.find('.confirm-dialog').text()).toContain('确认保存并确认选中的 1 个批量草案')
    await wrapper.find('.confirm-dialog .primary-button').trigger('click')
    await flushPromises()

    expect(apiPost).toHaveBeenCalledWith('/api/v1/batches/{batch_id}/save-confirm', {
      path: { batch_id: 'batch-1' },
      body: {
        items: [
          { item_id: 'item-1', draft_id: 'draft-1', base_revision: 1, idempotency_key: expect.any(String) },
        ],
        storage_dir: null,
        item_ids: ['item-1'],
      },
    })
    expect(wrapper.find('.batch-draft-card[data-item-id="item-1"] .batch-card-status').text()).toContain('已确认待提交')
  })

  it('accepts all reviewable cards when item_ids is omitted', async () => {
    apiPost
      .mockResolvedValueOnce(parseResult({ items: reviewableItems() }))
      .mockResolvedValueOnce(
        saveConfirmResult({
          results: [
            { item_id: 'item-1', outcome: 'CONFIRMED', request_id: 'req-1', status: 'CONFIRMED', error_type: null, error_message: null, tracking_id: 'track-1', tracking_ready: true },
            { item_id: 'item-2', outcome: 'CONFIRMED', request_id: 'req-2', status: 'CONFIRMED', error_type: null, error_message: null, tracking_id: 'track-2', tracking_ready: true },
          ],
          summary: { requested: 2, confirmed: 2, failed: 0 },
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

    const acceptCall = apiPost.mock.calls.find(([path]) => path === '/api/v1/batches/{batch_id}/save-confirm')
    expect(acceptCall).toBeDefined()
    const body = acceptCall![1]!.body as Record<string, unknown>
    expect(body.item_ids).toBeUndefined()
    expect((body.items as Array<{ item_id: string }>).map((i) => i.item_id)).toEqual(['item-1', 'item-2'])
    expect(wrapper.find('.batch-draft-card[data-item-id="item-1"] .batch-card-status').text()).toContain('已确认待提交')
    expect(wrapper.find('.batch-draft-card[data-item-id="item-2"] .batch-card-status').text()).toContain('已确认待提交')
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
    expect(notification.current?.title).toBe('保存确认失败')
    expect(notification.current?.message).toBe('保存确认失败，请根据条目提示处理。')
    // The raw server error never reaches the DOM.
    expect(wrapper.text()).not.toContain('ab_connection_failed')
    expect(wrapper.find('.batch-draft-card[data-item-id="item-1"] .batch-card-status').text()).toContain('草案')
  })

  it('freezes a malformed 200 result for the same-operation retry', async () => {
    apiPost
      .mockResolvedValueOnce(parseResult({ items: [reviewableItems()[0]] }))
      .mockResolvedValueOnce(saveConfirmResult({ results: [], summary: { requested: 1, confirmed: 0, failed: 1 } }))
    const { wrapper } = await mountBatch()
    await wrapper.find('#batch-raw-input').setValue('萌王S4')
    await wrapper.find('#batch-parse-submit').trigger('click')
    await flushPromises()
    await wrapper.find('#batch-accept-all').trigger('click')
    await nextTick()
    await wrapper.find('.confirm-dialog .primary-button').trigger('click')
    await flushPromises()

    expect(wrapper.find('.batch-card-status').text()).toContain('结果待核验')
    expect(wrapper.find('#batch-retry-frozen-operation').exists()).toBe(true)
  })

  it('ends a frozen retry in a deterministic draft failure state', async () => {
    apiPost
      .mockResolvedValueOnce(parseResult({ items: [reviewableItems()[0]] }))
      .mockRejectedValueOnce({ network: true, type: 'network_error', message: 'network' })
      .mockRejectedValueOnce({ type: 'conflict', status: 409, message: 'private detail' })
    const { wrapper } = await mountBatch()
    await wrapper.find('#batch-raw-input').setValue('萌王S4')
    await wrapper.find('#batch-parse-submit').trigger('click')
    await flushPromises()
    await wrapper.find('#batch-accept-all').trigger('click')
    await nextTick()
    await wrapper.find('.confirm-dialog .primary-button').trigger('click')
    await flushPromises()
    await wrapper.find('#batch-retry-frozen-operation').trigger('click')
    await flushPromises()

    expect(wrapper.text()).not.toContain('结果待核验')
    expect(wrapper.find('.batch-card-status').text()).toContain('草案')
    expect(wrapper.text()).not.toContain('private detail')
  })

  it('retries a deterministic idempotency conflict with a newly generated key', async () => {
    apiPost
      .mockResolvedValueOnce(parseResult({ items: [reviewableItems()[0]] }))
      .mockRejectedValueOnce({ type: 'idempotency_conflict', status: 409, message: 'private detail' })
      .mockResolvedValueOnce(saveConfirmResult({
        results: [{ item_id: 'item-1', outcome: 'CONFIRMED', request_id: 'req-1', status: 'CONFIRMED', error_type: null, error_message: null, tracking_id: null, tracking_ready: false }],
        summary: { requested: 1, confirmed: 1, failed: 0 },
      }))
    const { wrapper } = await mountBatch()
    await wrapper.find('#batch-raw-input').setValue('萌王S4')
    await wrapper.find('#batch-parse-submit').trigger('click')
    await flushPromises()
    await wrapper.find('#batch-accept-all').trigger('click')
    await nextTick()
    await wrapper.find('.confirm-dialog .primary-button').trigger('click')
    await flushPromises()
    const first = apiPost.mock.calls.find(([path]) => path === '/api/v1/batches/{batch_id}/save-confirm')
    expect(wrapper.find('#batch-retry-frozen-operation').exists()).toBe(false)
    await wrapper.find('#batch-accept-all').trigger('click')
    await nextTick()
    await wrapper.find('.confirm-dialog .primary-button').trigger('click')
    await flushPromises()
    const saves = apiPost.mock.calls.filter(([path]) => path === '/api/v1/batches/{batch_id}/save-confirm')
    expect(saves).toHaveLength(2)
    expect(saves[1]?.[1]).not.toEqual(first?.[1])
    expect((saves[1]?.[1] as { body: { items: Array<{ idempotency_key: string }> } }).body.items[0]?.idempotency_key)
      .not.toBe((first?.[1] as { body: { items: Array<{ idempotency_key: string }> } }).body.items[0]?.idempotency_key)
  })

  it('freezes an unknown outcome or invalid saved-confirm identity without partial application', async () => {
    apiPost
      .mockResolvedValueOnce(parseResult({ items: reviewableItems().slice(0, 1) }))
      .mockResolvedValueOnce(saveConfirmResult({
        results: [{ item_id: 'item-1', outcome: 'SKIPPED', request_id: 'https://private.invalid/x', status: null, error_type: 'save_confirm_failed', error_message: 'secret', tracking_id: null, tracking_ready: null }],
        summary: { requested: 1, confirmed: 0, failed: 1 },
      }))
    const { wrapper } = await mountBatch()
    await wrapper.find('#batch-raw-input').setValue('萌王S4')
    await wrapper.find('#batch-parse-submit').trigger('click')
    await flushPromises()
    await wrapper.find('#batch-accept-all').trigger('click')
    await nextTick()
    await wrapper.find('.confirm-dialog .primary-button').trigger('click')
    await flushPromises()
    expect(wrapper.find('.batch-card-status').text()).toContain('结果待核验')
    expect(wrapper.find('#batch-retry-frozen-operation').exists()).toBe(true)
    expect(wrapper.text()).not.toContain('secret')
    expect(wrapper.text()).not.toContain('private.invalid')
  })

  it.each(['invalid_request_status', 'unexpected_error', 'backend_new_error'])('treats deterministic failed %s as safe retryable failure', async (errorType) => {
    apiPost
      .mockResolvedValueOnce(parseResult({ items: reviewableItems().slice(0, 1) }))
      .mockResolvedValueOnce(saveConfirmResult({
        results: [{ item_id: 'item-1', outcome: 'failed', request_id: null, status: null, error_type: errorType, error_message: 'poisoned server detail', tracking_id: null, tracking_ready: null }],
        summary: { requested: 1, confirmed: 0, failed: 1 },
      }))
    const { wrapper } = await mountBatch()
    await wrapper.find('#batch-raw-input').setValue('萌王S4')
    await wrapper.find('#batch-parse-submit').trigger('click')
    await flushPromises()
    await wrapper.find('#batch-accept-all').trigger('click')
    await nextTick()
    await wrapper.find('.confirm-dialog .primary-button').trigger('click')
    await flushPromises()
    expect(wrapper.find('.batch-card-status').text()).toContain('草案')
    expect(wrapper.find('#batch-retry-frozen-operation').exists()).toBe(false)
    expect(wrapper.text()).not.toContain('poisoned server detail')
    expect(wrapper.text()).not.toContain(errorType)
  })

  it.each([
    ['confirmed-with-error', { item_id: 'item-1', outcome: 'CONFIRMED', request_id: 'req-1', status: null, error_type: null, error_message: 'poisoned', tracking_id: null, tracking_ready: null }],
    ['failed-with-status', { item_id: 'item-1', outcome: 'failed', request_id: null, status: 'FAILED', error_type: 'unexpected_error', error_message: null, tracking_id: 'tracking-leak', tracking_ready: true }],
  ])('freezes branch-inconsistent result: %s', async (_label, resultItem) => {
    apiPost
      .mockResolvedValueOnce(parseResult({ items: reviewableItems().slice(0, 1) }))
      .mockResolvedValueOnce(saveConfirmResult({ results: [resultItem], summary: { requested: 1, confirmed: 0, failed: 1 } }))
    const { wrapper } = await mountBatch()
    await wrapper.find('#batch-raw-input').setValue('萌王S4')
    await wrapper.find('#batch-parse-submit').trigger('click')
    await flushPromises()
    await wrapper.find('#batch-accept-all').trigger('click')
    await nextTick()
    await wrapper.find('.confirm-dialog .primary-button').trigger('click')
    await flushPromises()
    expect(wrapper.find('.batch-card-status').text()).toContain('结果待核验')
    expect(wrapper.find('#batch-retry-frozen-operation').exists()).toBe(true)
    expect(wrapper.text()).not.toContain('poisoned')
    expect(wrapper.text()).not.toContain('tracking-leak')
  })

  it('retries an unknown batch response with the exact frozen request body', async () => {
    apiPost
      .mockResolvedValueOnce(parseResult({ items: reviewableItems().slice(0, 1) }))
      .mockRejectedValueOnce({ network: true, type: 'network_error', message: 'network' })
      .mockResolvedValueOnce(saveConfirmResult({
        results: [{ item_id: 'item-1', request_id: 'req-1', outcome: 'CONFIRMED', status: 'CONFIRMED', error_type: null }],
        summary: { requested: 1, confirmed: 1, failed: 0 },
      }))
    const { wrapper } = await mountBatch()
    await wrapper.find('#batch-raw-input').setValue('萌王S4')
    await wrapper.find('#batch-parse-submit').trigger('click')
    await flushPromises()
    await wrapper.find('#batch-accept-all').trigger('click')
    await nextTick()
    await wrapper.find('.confirm-dialog .primary-button').trigger('click')
    await flushPromises()

    const first = apiPost.mock.calls.find(([path]) => path === '/api/v1/batches/{batch_id}/save-confirm')
    expect(wrapper.find('#batch-retry-frozen-operation').exists()).toBe(true)
    expect(wrapper.find('.batch-draft-card[data-item-id="item-1"] .batch-card-expand').attributes('disabled')).toBeDefined()
    await wrapper.find('#batch-retry-frozen-operation').trigger('click')
    await flushPromises()
    const saveCalls = apiPost.mock.calls.filter(([path]) => path === '/api/v1/batches/{batch_id}/save-confirm')
    expect(saveCalls).toHaveLength(2)
    expect(saveCalls[1]?.[1]).toEqual(first?.[1])
  })

  it('returns an expired frozen retry to candidates and permits a new draft', async () => {
    apiPost
      .mockResolvedValueOnce(parseResult({
        items: [batchItem({
          item_id: 'item-1',
          status: 'DRAFT',
          candidates: [{ bangumi_id: '42', title: '候选合集', mikan_url: 'https://mikan.example/Home/Bangumi/42' }],
          preview_request: previewRequest('req-1'),
          draft_id: 'draft-1',
        })],
      }))
      .mockRejectedValueOnce({ network: true, type: 'network_error', message: 'network' })
      .mockResolvedValueOnce(saveConfirmResult({
        results: [{ item_id: 'item-1', outcome: 'failed', request_id: null, status: null, error_type: 'draft_expired', error_message: null, tracking_id: null, tracking_ready: null }],
        summary: { requested: 1, confirmed: 0, failed: 1 },
      }))
      .mockResolvedValueOnce({ request: previewRequest('req-new'), summary: {}, draft_id: 'draft-new', draft_revision: 1 })
    const { wrapper } = await mountBatch()
    await wrapper.find('#batch-raw-input').setValue('萌王S4')
    await wrapper.find('#batch-parse-submit').trigger('click')
    await flushPromises()
    await wrapper.find('#batch-accept-all').trigger('click')
    await nextTick()
    await wrapper.find('.confirm-dialog .primary-button').trigger('click')
    await flushPromises()
    await wrapper.find('#batch-retry-frozen-operation').trigger('click')
    await flushPromises()
    expect(wrapper.find('.batch-card-status').text()).toContain('找到候选')
    expect(wrapper.find('#batch-retry-frozen-operation').exists()).toBe(false)
    await wrapper.find('.batch-card-expand').trigger('click')
    await nextTick()
    await wrapper.find('.candidate-select').trigger('click')
    await flushPromises()
    expect(wrapper.find('.batch-card-status').text()).toContain('草案')
  })

  it('keeps hidden selections while selecting the visible filtered item', async () => {
    apiPost.mockResolvedValue(parseResult({
      items: [
        batchItem({ item_id: 'item-a', raw_title: '甲', status: 'DRAFT', preview_request: previewRequest('req-a'), draft_id: 'draft-a' }),
        batchItem({ item_id: 'item-b', raw_title: '乙', status: 'DRAFT', preview_request: previewRequest('req-b'), draft_id: 'draft-b' }),
      ],
    }))
    const { wrapper } = await mountBatch()
    await wrapper.find('#batch-raw-input').setValue('甲\n乙')
    await wrapper.find('#batch-parse-submit').trigger('click')
    await flushPromises()
    await wrapper.find('.batch-draft-card[data-item-id="item-a"] input[type="checkbox"]').setValue(true)
    await wrapper.find('#batch-review-search').setValue('乙')
    await nextTick()
    await wrapper.find('#batch-select-all-checkbox').setValue(true)
    await nextTick()
    await wrapper.find('#batch-review-clear').trigger('click')
    await nextTick()
    expect((wrapper.find('.batch-draft-card[data-item-id="item-a"] input[type="checkbox"]').element as HTMLInputElement).checked).toBe(true)
    expect((wrapper.find('.batch-draft-card[data-item-id="item-b"] input[type="checkbox"]').element as HTMLInputElement).checked).toBe(true)
  })

  it('recovers a saved-but-unconfirmed card with accept and read-only tracking lookup', async () => {
    apiPost
      .mockResolvedValueOnce(parseResult({ items: [reviewableItems()[0]] }))
      .mockResolvedValueOnce(saveConfirmResult({
        results: [{ item_id: 'item-1', outcome: 'failed', request_id: 'saved-request-1', status: null, error_type: 'save_confirm_failed', error_message: '确认未完成', tracking_id: null, tracking_ready: null }],
        summary: { requested: 1, confirmed: 0, failed: 1 },
      }))
      .mockResolvedValueOnce({ request: { request_id: 'saved-request-1' } } as never)
    vi.mocked(api.get).mockResolvedValueOnce({
      items: [{ tracking_id: 'tracking-1', request_id: 'saved-request-1' }],
      summary: { total: 1, pending: 1, processing: 0, active: 0, needs_attention: 0, unreadable: 0 },
    } as never)
    const { wrapper } = await mountBatch()

    await wrapper.find('#batch-raw-input').setValue('萌王S4')
    await wrapper.find('#batch-parse-submit').trigger('click')
    await flushPromises()
    await wrapper.find('.batch-draft-card input[type=checkbox]').setValue(true)
    await wrapper.find('#batch-accept-submit').trigger('click')
    await wrapper.find('.confirm-dialog .primary-button').trigger('click')
    await flushPromises()

    expect(wrapper.find('#batch-retry-accept-item-1').exists()).toBe(true)
    await wrapper.find('#batch-retry-accept-item-1').trigger('click')
    await flushPromises()

    expect(apiPost).toHaveBeenLastCalledWith('/api/v1/requests/{request_id}/accept', {
      path: { request_id: 'saved-request-1' },
      body: { storage_dir: null },
    })
    expect(wrapper.find('.batch-card-status').text()).toContain('已确认待提交')
    expect(wrapper.find('#batch-open-tracking-item-1').exists()).toBe(true)
    expect(apiPost.mock.calls.filter(([path]) => path === '/api/v1/batches/{batch_id}/save-confirm')).toHaveLength(1)
  })

  it('keeps accept unknown in response_unknown until a later tracking lookup finds it', async () => {
    apiPost
      .mockResolvedValueOnce(parseResult({ items: [reviewableItems()[0]] }))
      .mockResolvedValueOnce(saveConfirmResult({
        results: [{ item_id: 'item-1', outcome: 'failed', request_id: 'saved-request-unknown', status: null, error_type: 'save_confirm_failed', error_message: '固定安全错误', tracking_id: null, tracking_ready: null }],
        summary: { requested: 1, confirmed: 0, failed: 1 },
      }))
      .mockRejectedValueOnce({ status: 409, type: 'invalid_request_status', message: 'private accept error' })
    vi.mocked(api.get)
      .mockRejectedValueOnce({ network: true, type: 'network_error', message: 'private lookup error' })
      .mockResolvedValueOnce({ items: [{ request_id: 'saved-request-unknown', tracking_id: 'tracking-found' }] } as never)
    const { wrapper } = await mountBatch()
    await wrapper.find('#batch-raw-input').setValue('萌王S4')
    await wrapper.find('#batch-parse-submit').trigger('click')
    await flushPromises()
    await wrapper.find('.batch-draft-card input[type=checkbox]').setValue(true)
    await wrapper.find('#batch-accept-submit').trigger('click')
    await wrapper.find('.confirm-dialog .primary-button').trigger('click')
    await flushPromises()
    await wrapper.find('#batch-retry-accept-item-1').trigger('click')
    await flushPromises()

    expect(wrapper.find('.batch-card-status').text()).toContain('结果待核验')
    expect(wrapper.find('#batch-retry-locate-item-1').exists()).toBe(true)
    expect(wrapper.find('#batch-retry-accept-item-1').exists()).toBe(false)
    expect(wrapper.text()).not.toContain('private accept error')
    await wrapper.find('#batch-retry-locate-item-1').trigger('click')
    await flushPromises()
    expect(wrapper.find('.batch-card-status').text()).toContain('已确认待提交')
    expect(wrapper.find('#batch-open-tracking-item-1').exists()).toBe(true)
    expect(apiPost.mock.calls.filter(([path]) => path === '/api/v1/batches/{batch_id}/save-confirm')).toHaveLength(1)
    expect(apiPost.mock.calls.filter(([path]) => path === '/api/v1/requests/{request_id}/accept')).toHaveLength(1)
  })

  it('returns an unknown accept to saved_pending_confirm when lookup is not_found', async () => {
    apiPost
      .mockResolvedValueOnce(parseResult({ items: [reviewableItems()[0]] }))
      .mockResolvedValueOnce(saveConfirmResult({
        results: [{ item_id: 'item-1', outcome: 'failed', request_id: 'saved-request-missing', status: null, error_type: 'save_confirm_failed', error_message: null, tracking_id: null, tracking_ready: null }],
        summary: { requested: 1, confirmed: 0, failed: 1 },
      }))
      .mockRejectedValueOnce({ status: 409, type: 'invalid_request_status', message: 'private accept error' })
    vi.mocked(api.get)
      .mockRejectedValueOnce({ network: true, type: 'network_error' })
      .mockResolvedValueOnce({ items: [{ request_id: 'other-request', tracking_id: 'other-tracking' }] } as never)
    const { wrapper } = await mountBatch()
    await wrapper.find('#batch-raw-input').setValue('萌王S4')
    await wrapper.find('#batch-parse-submit').trigger('click')
    await flushPromises()
    await wrapper.find('.batch-draft-card input[type=checkbox]').setValue(true)
    await wrapper.find('#batch-accept-submit').trigger('click')
    await wrapper.find('.confirm-dialog .primary-button').trigger('click')
    await flushPromises()
    await wrapper.find('#batch-retry-accept-item-1').trigger('click')
    await flushPromises()
    await wrapper.find('#batch-retry-locate-item-1').trigger('click')
    await flushPromises()
    expect(wrapper.find('.batch-card-status').text()).toContain('已保存待确认')
    expect(wrapper.find('#batch-retry-accept-item-1').exists()).toBe(true)
    expect(apiPost.mock.calls.filter(([path]) => path === '/api/v1/batches/{batch_id}/save-confirm')).toHaveLength(1)
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

// WP-41-B / US-343: batch candidate generation locks only the current item.
// The clicked candidate loads in place; every other item stays viewable,
// selectable and editable and is never marked as loading.
// Stage 43 / WP-43-A / US-347: 筛选只影响浏览。确认全部的资格集合是完整批次，
// 不是当前可见子集；按钮可用性、M 计数、弹窗数量和描述符必须同源。
describe('BatchWorkbenchView confirm-all scope (US-347)', () => {
  beforeEach(() => {
    localStorage.clear()
    apiPost.mockReset()
  })

  function twoDrafts() {
    return [
      batchItem({ item_id: 'item-a', raw_title: '甲', status: 'DRAFT', canonical_title_candidates: [], preview_request: previewRequest('req-a'), draft_id: 'draft-a', draft_revision: 1 }),
      batchItem({ item_id: 'item-b', raw_title: '乙', status: 'DRAFT', canonical_title_candidates: [], preview_request: previewRequest('req-b'), draft_id: 'draft-b', draft_revision: 1 }),
    ]
  }

  function twoConfirmedResults() {
    return saveConfirmResult({
      results: [
        { item_id: 'item-a', outcome: 'CONFIRMED', request_id: 'req-a', status: 'CONFIRMED', error_type: null, error_message: null, tracking_id: 'tracking-a', tracking_ready: true },
        { item_id: 'item-b', outcome: 'CONFIRMED', request_id: 'req-b', status: 'CONFIRMED', error_type: null, error_message: null, tracking_id: 'tracking-b', tracking_ready: true },
      ],
      summary: { requested: 2, confirmed: 2, failed: 0 },
    })
  }

  let wrapperUnderTest: Awaited<ReturnType<typeof mountBatch>>['wrapper']

  async function mountAndParse(rawInput: string) {
    const mounted = await mountBatch()
    wrapperUnderTest = mounted.wrapper
    await wrapperUnderTest.find('#batch-raw-input').setValue(rawInput)
    await wrapperUnderTest.find('#batch-parse-submit').trigger('click')
    await flushPromises()
    return mounted
  }

  async function confirmAllAndReadBody() {
    await wrapperUnderTest.find('#batch-accept-all').trigger('click')
    await nextTick()
    await wrapperUnderTest.find('.confirm-dialog .primary-button').trigger('click')
    await flushPromises()
    const acceptCall = apiPost.mock.calls.find(([path]) => path === '/api/v1/batches/{batch_id}/save-confirm')
    expect(acceptCall).toBeDefined()
    return acceptCall![1]!.body as Record<string, unknown>
  }

  it('sends every eligible item when the filter hides one of them', async () => {
    apiPost
      .mockResolvedValueOnce(parseResult({ items: twoDrafts() }))
      .mockResolvedValueOnce(twoConfirmedResults())
    await mountAndParse('甲\n乙')

    await wrapperUnderTest.find('#batch-review-search').setValue('乙')
    await nextTick()
    expect(wrapperUnderTest.findAll('.batch-draft-card')).toHaveLength(1)
    expect(wrapperUnderTest.find('.batch-draft-card').attributes('data-item-id')).toBe('item-b')
    expect((wrapperUnderTest.find('.batch-draft-card input[type="checkbox"]').element as HTMLInputElement).checked).toBe(false)

    const body = await confirmAllAndReadBody()
    expect(body.item_ids).toBeUndefined()
    expect((body.items as Array<{ item_id: string }>).map((entry) => entry.item_id)).toEqual(['item-a', 'item-b'])
    // 扩大的集合仍只发送生成的能力描述符，不带完整 Request 或额外字段。
    expect(Object.keys(body).sort()).toEqual(['items', 'storage_dir'])
    for (const entry of body.items as Array<Record<string, unknown>>) {
      expect(Object.keys(entry).sort()).toEqual(['base_revision', 'draft_id', 'idempotency_key', 'item_id'])
    }
  })

  it('keeps confirm-all usable and complete when the filter hides every item', async () => {
    apiPost
      .mockResolvedValueOnce(parseResult({ items: twoDrafts() }))
      .mockResolvedValueOnce(twoConfirmedResults())
    await mountAndParse('甲\n乙')

    await wrapperUnderTest.find('#batch-review-search').setValue('不存在的标题')
    await nextTick()
    expect(wrapperUnderTest.findAll('.batch-draft-card')).toHaveLength(0)
    expect(wrapperUnderTest.find('#batch-accept-all').attributes('disabled')).toBeUndefined()
    expect(wrapperUnderTest.find('#batch-accept-all-scope').text()).toContain('完整批次 2 项中的 2 项可确认条目')

    const body = await confirmAllAndReadBody()
    expect(body.item_ids).toBeUndefined()
    expect((body.items as Array<{ item_id: string }>).map((entry) => entry.item_id)).toEqual(['item-a', 'item-b'])
  })

  it('disables confirm-all with a visible reason when the complete batch has no eligible item', async () => {
    const noSeeds = twoDrafts()
    for (const item of noSeeds) {
      ;(item as { preview_request: { confirmable_config: { effective_seed_names: string[] } } }).preview_request.confirmable_config.effective_seed_names = []
    }
    apiPost.mockResolvedValueOnce(parseResult({ items: noSeeds }))
    await mountAndParse('甲\n乙')

    expect(wrapperUnderTest.find('#batch-accept-all').attributes('disabled')).toBeDefined()
    expect(wrapperUnderTest.find('#batch-accept-all-scope').text()).toContain('完整批次 2 项均不可确认')
  })

  it('keeps confirm-all available for the eligible items and states the exclusions', async () => {
    apiPost
      .mockResolvedValueOnce(parseResult({
        items: [
          ...twoDrafts().slice(0, 1),
          batchItem({ item_id: 'item-failed', raw_title: '丙', status: 'FAILED', canonical_title_candidates: [] }),
        ],
      }))
      .mockResolvedValueOnce(saveConfirmResult({
        results: [{ item_id: 'item-a', outcome: 'CONFIRMED', request_id: 'req-a', status: 'CONFIRMED', error_type: null, error_message: null, tracking_id: 'tracking-a', tracking_ready: true }],
        summary: { requested: 1, confirmed: 1, failed: 0 },
      }))
    await mountAndParse('甲\n丙')

    expect(wrapperUnderTest.find('#batch-accept-all').attributes('disabled')).toBeUndefined()
    const scope = wrapperUnderTest.find('#batch-accept-all-scope').text()
    expect(scope).toContain('完整批次 2 项中的 1 项可确认条目')
    expect(scope).toContain('排除 1 项')

    const body = await confirmAllAndReadBody()
    expect((body.items as Array<{ item_id: string }>).map((entry) => entry.item_id)).toEqual(['item-a'])
  })

  it('reveals and focuses a filter-hidden item whose confirm failed', async () => {
    apiPost
      .mockResolvedValueOnce(parseResult({ items: twoDrafts() }))
      .mockResolvedValueOnce(saveConfirmResult({
        results: [
          { item_id: 'item-a', outcome: 'failed', request_id: null, status: null, error_type: 'invalid_request_status', error_message: 'poisoned detail', tracking_id: null, tracking_ready: null },
          { item_id: 'item-b', outcome: 'CONFIRMED', request_id: 'req-b', status: 'CONFIRMED', error_type: null, error_message: null, tracking_id: 'tracking-b', tracking_ready: true },
        ],
        summary: { requested: 2, confirmed: 1, failed: 1 },
      }))
    await mountAndParse('甲\n乙')

    await wrapperUnderTest.find('#batch-review-search').setValue('乙')
    await nextTick()
    expect(wrapperUnderTest.findAll('.batch-draft-card')).toHaveLength(1)

    await wrapperUnderTest.find('#batch-accept-all').trigger('click')
    await nextTick()
    await wrapperUnderTest.find('.confirm-dialog .primary-button').trigger('click')
    await flushPromises()

    // 隐藏失败项先可见化再聚焦，安全原因留在卡片原位。
    expect(wrapperUnderTest.findAll('.batch-draft-card')).toHaveLength(2)
    const failedCard = wrapperUnderTest.find('.batch-draft-card[data-item-id="item-a"]')
    expect(failedCard.find('.batch-card-status').text()).toContain('草案')
    expect(failedCard.find('.batch-card-reason').text()).toContain('保存确认失败，请重试。')
    expect(wrapperUnderTest.find('.batch-review-navigation').text()).toContain('已定位到首个失败条目')
    expect(document.activeElement).toBe(failedCard.element)
    expect(wrapperUnderTest.text()).not.toContain('poisoned detail')
    // 成功项不再参与全部范围，失败项仍需重新处理。
    expect(wrapperUnderTest.find('.batch-draft-card[data-item-id="item-b"] .batch-card-status').text()).toContain('已确认待提交')
    expect(wrapperUnderTest.find('#batch-accept-all').text()).toContain('1 部')
  })
})

// Stage 43 / WP-43-A / US-348: 二次确认看到的数量和集合就是最终发送的对象。
// 打开弹窗时把完整批次的参与集合与绑定版本冻结在内存 intent 里；确认前重新核对，
// 任何资格/版本/batch 变化都不发送，改为在固定业务区常驻说明。
describe('BatchWorkbenchView confirm-all dialog intent (US-348)', () => {
  beforeEach(() => {
    localStorage.clear()
    apiPost.mockReset()
  })

  let wrapperUnderTest: Awaited<ReturnType<typeof mountBatch>>['wrapper']

  function twoDrafts() {
    return [
      batchItem({ item_id: 'item-a', raw_title: '甲', status: 'DRAFT', canonical_title_candidates: [], preview_request: previewRequest('req-a'), draft_id: 'draft-a', draft_revision: 1 }),
      batchItem({ item_id: 'item-b', raw_title: '乙', status: 'DRAFT', canonical_title_candidates: [], preview_request: previewRequest('req-b'), draft_id: 'draft-b', draft_revision: 1 }),
    ]
  }

  function twoConfirmedResults() {
    return saveConfirmResult({
      results: [
        { item_id: 'item-a', outcome: 'CONFIRMED', request_id: 'req-a', status: 'CONFIRMED', error_type: null, error_message: null, tracking_id: 'tracking-a', tracking_ready: true },
        { item_id: 'item-b', outcome: 'CONFIRMED', request_id: 'req-b', status: 'CONFIRMED', error_type: null, error_message: null, tracking_id: 'tracking-b', tracking_ready: true },
      ],
      summary: { requested: 2, confirmed: 2, failed: 0 },
    })
  }

  function saveConfirmCalls() {
    return apiPost.mock.calls.filter(([path]) => path === '/api/v1/batches/{batch_id}/save-confirm')
  }

  async function mountAndParse(rawInput: string) {
    const mounted = await mountBatch()
    wrapperUnderTest = mounted.wrapper
    await wrapperUnderTest.find('#batch-raw-input').setValue(rawInput)
    await wrapperUnderTest.find('#batch-parse-submit').trigger('click')
    await flushPromises()
    return mounted
  }

  async function openAllDialog() {
    await wrapperUnderTest.find('#batch-accept-all').trigger('click')
    await nextTick()
  }

  async function confirmDialog() {
    await wrapperUnderTest.find('.confirm-dialog .primary-button').trigger('click')
    await flushPromises()
  }

  it('states the frozen all scope in the dialog and sends exactly that set', async () => {
    apiPost
      .mockResolvedValueOnce(parseResult({
        items: [...twoDrafts(), batchItem({ item_id: 'item-c', raw_title: '丙', status: 'FAILED', canonical_title_candidates: [] })],
      }))
      .mockResolvedValueOnce(twoConfirmedResults())
    await mountAndParse('甲\n乙\n丙')
    await openAllDialog()

    const dialog = wrapperUnderTest.find('.confirm-dialog')
    expect(dialog.find('.confirm-dialog-title').text()).toBe('保存并确认全部 2 部')
    expect(dialog.find('.primary-button').text()).toContain('保存并确认全部 2 部')
    const message = dialog.find('.confirm-dialog-message').text()
    expect(message).toContain('完整批次 3 部中当前可确认 2 部')
    expect(message).toContain('已排除 1 部')
    expect(message).toContain('仅保存本地订阅方案')
    expect(message).toContain('追番管理再次确认')
    // 能力只留在内存 intent 里，不进入弹窗文案。
    expect(dialog.text()).not.toContain('draft-a')
    expect(dialog.text()).not.toContain('draft-b')

    await confirmDialog()
    expect(saveConfirmCalls()).toHaveLength(1)
    const body = saveConfirmCalls()[0]![1]!.body as Record<string, unknown>
    expect(body.item_ids).toBeUndefined()
    expect((body.items as Array<{ item_id: string }>).map((entry) => entry.item_id)).toEqual(['item-a', 'item-b'])
  })

  it('sends nothing on cancel and keeps the batch scene unchanged', async () => {
    apiPost.mockResolvedValueOnce(parseResult({ items: twoDrafts() }))
    await mountAndParse('甲\n乙')
    await wrapperUnderTest.find('.batch-draft-card[data-item-id="item-a"] input[type="checkbox"]').setValue(true)
    await wrapperUnderTest.find('.batch-draft-card[data-item-id="item-b"] .batch-card-expand').trigger('click')
    await nextTick()
    await openAllDialog()

    await wrapperUnderTest.find('.confirm-dialog .secondary-button').trigger('click')
    await flushPromises()

    expect(saveConfirmCalls()).toHaveLength(0)
    expect(wrapperUnderTest.find('.confirm-dialog').exists()).toBe(false)
    expect(wrapperUnderTest.find('#batch-accept-all-recheck').exists()).toBe(false)
    expect(wrapperUnderTest.findAll('.batch-draft-card')).toHaveLength(2)
    expect((wrapperUnderTest.find('.batch-draft-card[data-item-id="item-a"] input[type="checkbox"]').element as HTMLInputElement).checked).toBe(true)
    expect(wrapperUnderTest.find('#batch-detail-pane').text()).toContain('编辑订阅草案')
  })

  it('closes the all dialog on Escape without sending or flagging a recheck', async () => {
    apiPost.mockResolvedValueOnce(parseResult({ items: twoDrafts() }))
    await mountAndParse('甲\n乙')
    await openAllDialog()
    expect(wrapperUnderTest.find('.confirm-dialog').exists()).toBe(true)

    document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }))
    await flushPromises()

    expect(wrapperUnderTest.find('.confirm-dialog').exists()).toBe(false)
    expect(saveConfirmCalls()).toHaveLength(0)
    expect(wrapperUnderTest.find('#batch-accept-all-recheck').exists()).toBe(false)
    expect(wrapperUnderTest.findAll('.batch-draft-card')).toHaveLength(2)
  })

  it('rechecks the frozen versions and refuses to send when a draft revision changed', async () => {
    let resolveModify!: (value: unknown) => void
    const pendingModify = new Promise((resolve) => { resolveModify = resolve })
    apiPost
      .mockResolvedValueOnce(parseResult({ items: twoDrafts() }))
      .mockImplementationOnce(() => pendingModify as never)
      .mockResolvedValueOnce(twoConfirmedResults())
    await mountAndParse('甲\n乙')
    await wrapperUnderTest.find('.batch-draft-card[data-item-id="item-a"] .batch-card-expand').trigger('click')
    await nextTick()

    await openAllDialog()
    expect(wrapperUnderTest.find('.confirm-dialog').exists()).toBe(true)

    // 弹窗打开期间，已在途的修改响应把该条目的草案版本推进到 2。
    await wrapperUnderTest.find('#batch-preview-must-contain').setValue('新筛选')
    await wrapperUnderTest.find('#detail-preview-edit-form').trigger('submit')
    await nextTick()
    const applied = previewRequest('req-a')
    applied.confirmable_config.filter_rule.must_contain = '新筛选'
    resolveModify({ request: applied, draft_id: 'draft-a', draft_revision: 2 })
    await flushPromises()

    await confirmDialog()

    expect(saveConfirmCalls()).toHaveLength(0)
    expect(wrapperUnderTest.find('.confirm-dialog').exists()).toBe(false)
    const notice = wrapperUnderTest.find('#batch-accept-all-recheck')
    expect(notice.exists()).toBe(true)
    expect(notice.text()).toContain('资格或草案版本已变化')
    expect(notice.text()).toContain('重新确认全部')
    expect(document.activeElement).toBe(notice.element)
    // 校验失败不改变现场，也不自动重新打开确认。
    expect(wrapperUnderTest.findAll('.batch-draft-card')).toHaveLength(2)

    // 重新确认：新 intent 记录最新版本，发送精确 body。
    await openAllDialog()
    expect(wrapperUnderTest.find('#batch-accept-all-recheck').exists()).toBe(false)
    await confirmDialog()
    const body = saveConfirmCalls()[0]![1]!.body as Record<string, unknown>
    expect((body.items as Array<{ item_id: string; base_revision: number }>).map((entry) => [entry.item_id, entry.base_revision]))
      .toEqual([['item-a', 2], ['item-b', 1]])
  })

  it('refuses to send when another item becomes confirmable while the dialog is open', async () => {
    apiPost
      .mockResolvedValueOnce(parseResult({
        items: [
          ...twoDrafts(),
          batchItem({
            item_id: 'item-c',
            raw_title: '丙',
            status: 'FOUND',
            canonical_title_candidates: [],
            candidates: [{ bangumi_id: '77', title: '候选丙', mikan_url: 'https://mikan.example/Home/Bangumi/77' }],
          }),
        ],
      }))
      .mockResolvedValueOnce({ request: previewRequest('req-c'), summary: {}, draft_id: 'draft-c', draft_revision: 1 })
    await mountAndParse('甲\n乙\n丙')
    await openAllDialog()

    // 弹窗打开期间，第三个条目生成了可审核草案并加入资格集合。
    await wrapperUnderTest.find('.batch-draft-card[data-item-id="item-c"] .batch-card-expand').trigger('click')
    await nextTick()
    await wrapperUnderTest.find('#batch-detail-pane .candidate-select').trigger('click')
    await flushPromises()

    await confirmDialog()

    expect(saveConfirmCalls()).toHaveLength(0)
    expect(wrapperUnderTest.find('.confirm-dialog').exists()).toBe(false)
    const notice = wrapperUnderTest.find('#batch-accept-all-recheck')
    expect(notice.exists()).toBe(true)
    expect(notice.text()).toContain('资格或草案版本已变化')
    // 不自动补新 rows：三个条目都还在，只有明确重新确认才会发送。
    expect(wrapperUnderTest.findAll('.batch-draft-card')).toHaveLength(3)
    expect(wrapperUnderTest.find('#batch-accept-all').text()).toContain('3 部')
  })

  it('keeps the frozen all set when only the filter and the checkboxes change', async () => {
    apiPost
      .mockResolvedValueOnce(parseResult({ items: twoDrafts() }))
      .mockResolvedValueOnce(twoConfirmedResults())
    await mountAndParse('甲\n乙')
    await openAllDialog()

    // 可见性与勾选变化不改变已冻结的 all 集合。
    await wrapperUnderTest.find('#batch-review-search').setValue('乙')
    await wrapperUnderTest.find('.batch-draft-card[data-item-id="item-b"] input[type="checkbox"]').setValue(true)
    await nextTick()

    await confirmDialog()

    expect(saveConfirmCalls()).toHaveLength(1)
    const body = saveConfirmCalls()[0]![1]!.body as Record<string, unknown>
    expect(body.item_ids).toBeUndefined()
    expect((body.items as Array<{ item_id: string }>).map((entry) => entry.item_id)).toEqual(['item-a', 'item-b'])
  })

  it('refuses to send when the batch was re-parsed while the dialog was open', async () => {
    apiPost
      .mockResolvedValueOnce(parseResult({ items: twoDrafts() }))
      .mockResolvedValueOnce(parseResult({
        batch_id: 'batch-2',
        items: [batchItem({ item_id: 'item-x', raw_title: '新甲', status: 'DRAFT', canonical_title_candidates: [], preview_request: previewRequest('req-x'), draft_id: 'draft-x', draft_revision: 1 })],
      }))
    await mountAndParse('甲\n乙')
    await openAllDialog()

    // 弹窗打开期间重新解析：batch 与参与集合都已改变。
    await wrapperUnderTest.find('#batch-raw-input').setValue('新甲')
    await wrapperUnderTest.find('#batch-parse-submit').trigger('click')
    await flushPromises()

    await confirmDialog()

    expect(saveConfirmCalls()).toHaveLength(0)
    expect(wrapperUnderTest.find('.confirm-dialog').exists()).toBe(false)
    expect(wrapperUnderTest.find('#batch-accept-all-recheck').text()).toContain('资格或草案版本已变化')
    expect(wrapperUnderTest.findAll('.batch-draft-card')).toHaveLength(1)
  })

  it('ignores a second open while the all dialog is still open', async () => {
    apiPost
      .mockResolvedValueOnce(parseResult({ items: twoDrafts() }))
      .mockResolvedValueOnce(twoConfirmedResults())
    await mountAndParse('甲\n乙')
    await wrapperUnderTest.find('.batch-draft-card[data-item-id="item-a"] .batch-card-expand').trigger('click')
    await nextTick()
    await openAllDialog()

    // 弹窗打开期间第一个条目变成不可确认；第二次进入必须被函数入口挡掉，
    // 弹窗仍保持打开时冻结的 2 部，而不是按新资格静默缩成 1 部。
    await wrapperUnderTest.find('#batch-preview-must-contain').setValue('未应用修改')
    await nextTick()
    await wrapperUnderTest.find('#batch-accept-all').trigger('click')
    await nextTick()

    expect(wrapperUnderTest.findAll('.confirm-dialog')).toHaveLength(1)
    expect(wrapperUnderTest.find('.confirm-dialog .confirm-dialog-title').text()).toBe('保存并确认全部 2 部')

    await confirmDialog()
    expect(saveConfirmCalls()).toHaveLength(0)
    expect(wrapperUnderTest.find('#batch-accept-all-recheck').exists()).toBe(true)
  })

  it('keeps an unknown save result on the original frozen request without a new intent', async () => {
    apiPost
      .mockResolvedValueOnce(parseResult({ items: twoDrafts() }))
      .mockRejectedValueOnce({ network: true, type: 'network_error', message: 'network' })
      .mockResolvedValueOnce(twoConfirmedResults())
    await mountAndParse('甲\n乙')
    await openAllDialog()
    await confirmDialog()

    const first = saveConfirmCalls()[0]
    expect(wrapperUnderTest.find('#batch-retry-frozen-operation').exists()).toBe(true)
    expect(wrapperUnderTest.find('#batch-accept-all-recheck').exists()).toBe(false)

    await wrapperUnderTest.find('#batch-retry-frozen-operation').trigger('click')
    await flushPromises()
    // 未知重试沿用原冻结 body/key/revision，不新建 intent 也不弹确认框。
    expect(wrapperUnderTest.find('.confirm-dialog').exists()).toBe(false)
    expect(saveConfirmCalls()).toHaveLength(2)
    expect(saveConfirmCalls()[1]?.[1]).toEqual(first?.[1])
  })
})

describe('BatchWorkbenchView candidate loading feedback (US-343)', () => {
  beforeEach(() => {
    localStorage.clear()
    apiPost.mockReset()
  })

  const candidateFor = (bangumiId: string, title: string) => ({
    bangumi_id: bangumiId,
    title,
    mikan_url: `https://mikan.example/Home/Bangumi/${bangumiId}`,
  })

  function twoFoundItems() {
    return parseResult({
      items: [
        batchItem({
          item_id: 'item-a',
          raw_title: '甲',
          status: 'FOUND',
          candidates: [candidateFor('42', '候选甲')],
        }),
        batchItem({
          item_id: 'item-b',
          raw_title: '乙',
          status: 'FOUND',
          candidates: [candidateFor('77', '候选乙')],
        }),
      ],
    })
  }

  it('loads only the current item candidate and keeps the other item operable', async () => {
    let resolveRequest!: (value: unknown) => void
    const pending = new Promise((resolve) => { resolveRequest = resolve })
    apiPost.mockResolvedValueOnce(twoFoundItems())
    apiPost.mockImplementationOnce(() => pending as never)
    const { wrapper } = await mountBatch()

    await wrapper.find('#batch-raw-input').setValue('甲\n乙')
    await wrapper.find('#batch-parse-submit').trigger('click')
    await flushPromises()

    await wrapper.find('.batch-draft-card[data-item-id="item-a"] .batch-card-expand').trigger('click')
    await nextTick()
    const pane = wrapper.find('#batch-detail-pane')
    await pane.find('.candidate-select').trigger('click')
    await nextTick()

    const loadingButton = wrapper.find('#batch-detail-pane .candidate-select')
    expect(loadingButton.attributes('aria-busy')).toBe('true')
    expect(loadingButton.text()).toContain('正在生成草案')
    expect((loadingButton.element as HTMLButtonElement).disabled).toBe(true)
    // The generating item shows the in-place status; the other item never does.
    expect(wrapper.find('.batch-draft-card[data-item-id="item-a"]').text()).toContain('正在生成订阅草案')
    expect(wrapper.find('.batch-draft-card[data-item-id="item-b"]').text()).not.toContain('正在生成订阅草案')

    // The other item stays viewable and selectable: switch its detail pane and
    // pick another candidate; nothing there is marked as loading.
    const expandB = wrapper.find('.batch-draft-card[data-item-id="item-b"] .batch-card-expand')
    expect((expandB.element as HTMLButtonElement).disabled).toBe(false)
    await expandB.trigger('click')
    await nextTick()

    const paneB = wrapper.find('#batch-detail-pane')
    expect(paneB.text()).toContain('候选乙')
    const idleButton = paneB.find('.candidate-select')
    expect(idleButton.attributes('aria-busy')).toBeUndefined()
    expect((idleButton.element as HTMLButtonElement).disabled).toBe(false)
    expect(idleButton.text()).toContain('选择此合集')
    expect(paneB.text()).not.toContain('正在生成草案')

    resolveRequest({ request: previewRequest('req-a'), summary: {}, draft_id: 'draft-a', draft_revision: 1 })
    await flushPromises()

    // Success is atomic for the generating item only.
    const cardA = wrapper.find('.batch-draft-card[data-item-id="item-a"]')
    expect(cardA.find('.batch-card-status').text()).toContain('草案')
    expect(wrapper.find('.batch-draft-card[data-item-id="item-b"] .batch-card-status').text()).toContain('找到候选')
  })

  it('keeps a sanitized candidate failure beside that item only', async () => {
    apiPost.mockResolvedValueOnce(twoFoundItems())
    apiPost.mockRejectedValueOnce({ type: 'network_error', message: '原始网络错误' })
    const { wrapper } = await mountBatch()

    await wrapper.find('#batch-raw-input').setValue('甲\n乙')
    await wrapper.find('#batch-parse-submit').trigger('click')
    await flushPromises()

    await wrapper.find('.batch-draft-card[data-item-id="item-a"] .batch-card-expand').trigger('click')
    await nextTick()
    await wrapper.find('#batch-detail-pane .candidate-select').trigger('click')
    await flushPromises()

    const pane = wrapper.find('#batch-detail-pane')
    expect(pane.text()).toContain('从 MiKan 合集生成订阅草案失败：网络或连接不可用，请检查网络后重试。')
    expect(pane.text()).not.toContain('原始网络错误')
    const retry = pane.find('.candidate-select')
    expect(retry.attributes('aria-busy')).toBeUndefined()
    expect(retry.text()).toContain('重试生成草案')
    expect((retry.element as HTMLButtonElement).disabled).toBe(false)

    const cardB = wrapper.find('.batch-draft-card[data-item-id="item-b"]')
    expect(cardB.text()).not.toContain('生成订阅草案失败')
    expect(cardB.find('.batch-card-status').text()).toContain('找到候选')
    expect(wrapper.find('#batch-parse-submit').attributes('disabled')).toBeUndefined()
  })
})
