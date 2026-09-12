import { flushPromises, mount } from '@vue/test-utils'
import { createPinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createMemoryHistory, createRouter } from 'vue-router'
import { nextTick } from 'vue'

import { api } from '@/api/client'
import type { operations } from '@/api/generated/api'
import WorkbenchView from '@/features/workbench/WorkbenchView.vue'

// US-204: workbench single-search migration. The view searches MiKan
// candidates through the shared transport, renders explicit candidate cards
// (no auto-selection), supports the direct fallback, and opens the
// server-authoritative draft preview (draft_id in memory only).

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
      ? (error as { type: string; message: string; details?: Record<string, unknown> })
      : { type: 'request_error', message: '请求失败，请重试' },
  isApiError: () => false,
  apiRequest: vi.fn(),
}))

const apiPost = vi.mocked(api.post)
const apiGet = vi.mocked(api.get)

type CandidateResult = NonNullable<
  operations['searchMikanCandidates']['responses']['200']['content']['application/json']['result']
>
type CreateResult = NonNullable<
  operations['createRequest']['responses']['200']['content']['application/json']['result']
>

function candidate(overrides: Record<string, unknown> = {}) {
  return {
    bangumi_id: '2353',
    title: '葬送的芙莉莲',
    mikan_url: 'https://mikan.example/Home/Bangumi/2353',
    poster_url: null,
    source_query: '芙莉莲',
    aliases: [],
    recommendation: null,
    total_episodes: null,
    season_evidence: null,
    candidate_context: null,
    ...overrides,
  }
}

function candidateResult(overrides: Partial<Record<string, unknown>> = {}): CandidateResult {
  return {
    query: '芙莉莲',
    status: 'FOUND',
    parse_result: {
      normalized_title: '葬送的芙莉莲',
      base_title: '葬送的芙莉莲',
      season: { number: null, raw: null, normalized: null, source: 'none' },
      source: 'rule',
      needs_user_review: false,
      review_hints: [],
      query_plan: [{ query: '芙莉莲', source: 'rule', priority: 1 }],
    },
    attempted_queries: [{ query: '芙莉莲', source: 'rule', priority: 1 }],
    candidates: [candidate() as never],
    error: null,
    ...overrides,
  } as never
}

function previewSnapshot(overrides: Record<string, unknown> = {}) {
  return {
    request_id: 'req-draft-1',
    status: 'PENDING_CONFIRM',
    input: { raw_title: '葬送的芙莉莲' },
    source_info: {
      matched_bangumi: { title: '葬送的芙莉莲', aliases: [], mikan_url: null, match_score: 1, poster_url: null },
      rss_sources: [
        {
          subtitle_group: '喵萌奶茶屋',
          rss_url: 'https://example.invalid/rss/moe.xml',
          source_type: 'mikan',
          total_seed_count: 2,
          seed_names: ['[喵萌] 芙莉莲 01.mkv'],
          valid_seed_count: 1,
          invalid_seed_count: 1,
          valid_seed_names: ['[喵萌] 芙莉莲 01.mkv'],
          excluded_seed_names: [{ name: '[喵萌] 芙莉莲 SP.mkv', reason: '命中排除规则：SP', rule: 'must_not_contain' }],
          warnings: [],
        },
      ],
    },
    confirmable_config: {
      selected_subtitle_group: '喵萌奶茶屋',
      selected_rss_url: 'https://example.invalid/rss/moe.xml',
      filter_rule: { must_contain: '', must_not_contain: '', use_regex: false, case_sensitive: false },
      effective_seed_names: ['[喵萌] 芙莉莲 01.mkv'],
      expected_folder_name: '葬送的芙莉莲',
      warnings: [],
    },
    ab_submit_result: null,
    created_at: '2026-08-31T00:00:00+00:00',
    updated_at: '2026-08-31T00:00:00+00:00',
    user_action: null,
    ...overrides,
  }
}

function createDraftResult(overrides: Partial<Record<string, unknown>> = {}): CreateResult {
  return {
    request: previewSnapshot() as never,
    summary: { request_id: 'req-draft-1', status: 'PENDING_CONFIRM', bangumi_title: '葬送的芙莉莲', candidate_subtitle_groups: [], selected_subtitle_group: '喵萌奶茶屋', effective_seed_count: 1, expected_folder_name: '葬送的芙莉莲', warnings: [] } as never,
    saved_request: null,
    draft_id: 'opaque-draft-token',
    draft_revision: 1,
    ...overrides,
  } as never
}

async function mountWorkbench() {
  const router = createRouter({
    history: createMemoryHistory('/app/'),
    routes: [
      { path: '/add', name: 'add', component: WorkbenchView },
      { path: '/plans', name: 'plans', component: { template: '<p>requests</p>' } },
      { path: '/settings', name: 'settings', component: { template: '<p>settings</p>' } },
      { path: '/tracking', name: 'tracking', component: { template: '<p>tracking</p>' } },
    ],
  })
  await router.push({ path: '/add' })
  await router.isReady()

  const wrapper = mount(WorkbenchView, {
    attachTo: document.body,
    global: {
      plugins: [createPinia(), router],
      stubs: { teleport: true },
    },
  })
  await nextTick()
  return { wrapper, router }
}

describe('WorkbenchView single search (US-204)', () => {
  beforeEach(() => {
    localStorage.clear()
    apiPost.mockReset()
    apiGet.mockReset()
  })

  it('disables search for empty input before calling the API', async () => {
    const { wrapper } = await mountWorkbench()

    expect(wrapper.find('#mikan-candidate-search-result').text()).toContain('输入番剧标题后搜索候选合集')
    expect(wrapper.find('#mikan-candidate-search-submit').attributes('disabled')).toBeDefined()
    expect(apiPost).not.toHaveBeenCalled()
  })

  it('focuses the title input on entry and moves focus to the first candidate', async () => {
    apiPost.mockResolvedValue(candidateResult())
    const { wrapper } = await mountWorkbench()

    await nextTick()
    expect(document.activeElement).toBe(wrapper.find('#mikan-candidate-query').element)

    await wrapper.find('#mikan-candidate-query').setValue('芙莉莲')
    await wrapper.find('#mikan-candidate-search-submit').trigger('click')
    await flushPromises()

    expect(document.activeElement).toBe(wrapper.find('.candidate-select').element)
  })

  it('searches candidates through the shared transport and renders cards', async () => {
    apiPost.mockResolvedValue(candidateResult())
    const { wrapper } = await mountWorkbench()

    await wrapper.find('#mikan-candidate-query').setValue('芙莉莲')
    await wrapper.find('#mikan-candidate-search-submit').trigger('click')
    await flushPromises()

    expect(apiPost).toHaveBeenCalledWith('/api/v1/mikan/candidates', {
      body: { query: '芙莉莲' },
    })
    const cards = wrapper.findAll('.candidate-card')
    expect(cards).toHaveLength(1)
    expect(cards[0]!.text()).toContain('葬送的芙莉莲')
    expect(cards[0]!.text()).toContain('MiKan ID: 2353')
    expect(cards[0]!.text()).toContain('选择此合集')
  })

  it('never auto-selects a candidate even when only one matches', async () => {
    apiPost.mockResolvedValue(candidateResult())
    const { wrapper } = await mountWorkbench()

    await wrapper.find('#mikan-candidate-query').setValue('芙莉莲')
    await wrapper.find('#mikan-candidate-search-submit').trigger('click')
    await flushPromises()

    expect(wrapper.findAll('.candidate-card')).toHaveLength(1)
    // The explicit selection button is offered but nothing was generated.
    expect(wrapper.findAll('.candidate-select')).toHaveLength(1)
    expect(apiPost).toHaveBeenCalledTimes(1)
  })

  it('renders the auditable title-parse summary with Chinese labels', async () => {
    apiPost.mockResolvedValue(
      candidateResult({
        query: '无职转生s4',
        parse_result: {
          normalized_title: '无职转生 第四季',
          base_title: '无职转生',
          season: { number: 4, raw: 's4', normalized: '第四季', source: 'title_marker' },
          source: 'alias',
          needs_user_review: true,
          review_hints: ['别名匹配结果，请人工核对。'],
          query_plan: [
            { query: '无职转生 第四季', source: 'alias', priority: 1 },
            { query: '无职转生 S4', source: 'rule', priority: 2 },
          ],
        },
        attempted_queries: [{ query: '无职转生 第四季', source: 'alias', priority: 1 }],
      }),
    )
    const { wrapper } = await mountWorkbench()

    await wrapper.find('#mikan-candidate-query').setValue('无职转生s4')
    await wrapper.find('#mikan-candidate-search-submit').trigger('click')
    await flushPromises()

    const summary = wrapper.find('.title-parse-summary')
    expect(summary.text()).toContain('标题解析摘要')
    expect(summary.text()).toContain('识别标题')
    expect(summary.text()).toContain('无职转生 第四季')
    expect(summary.text()).toContain('识别季度')
    expect(summary.text()).toContain('第4季')
    expect(summary.text()).toContain('解析来源')
    expect(summary.text()).toContain('别名匹配')
    expect(summary.text()).toContain('实际搜索词')
    expect(summary.text()).toContain('需人工核对')
    // The raw source code never reaches the DOM.
    expect(summary.text()).not.toContain('alias')
  })

  it('shows the empty-result hint and never renders raw candidate URLs', async () => {
    apiPost.mockResolvedValue(candidateResult({ candidates: [] }))
    const { wrapper } = await mountWorkbench()

    await wrapper.find('#mikan-candidate-query').setValue('ghost')
    await wrapper.find('#mikan-candidate-search-submit').trigger('click')
    await flushPromises()

    expect(wrapper.find('#mikan-candidate-search-result').text()).toContain('未找到候选合集')
    expect(wrapper.find('#mikan-candidate-search-result').text()).toContain('直连合集')
  })

  it('clears stale candidates when the search title is edited', async () => {
    apiPost.mockResolvedValue(candidateResult())
    const { wrapper } = await mountWorkbench()

    await wrapper.find('#mikan-candidate-query').setValue('芙莉莲')
    await wrapper.find('#mikan-candidate-search-submit').trigger('click')
    await flushPromises()
    expect(wrapper.findAll('.candidate-card')).toHaveLength(1)

    await wrapper.find('#mikan-edit-search').trigger('click')
    await nextTick()
    await wrapper.find('#mikan-candidate-query').setValue('无职转生')
    await nextTick()

    expect(wrapper.findAll('.candidate-card')).toHaveLength(0)
    expect(wrapper.find('#mikan-candidate-search-result').text()).toContain('输入番剧标题后搜索候选合集')
    expect((wrapper.find('#mikan-candidate-query').element as HTMLInputElement).value).toBe('无职转生')
  })

  it('shows a safe Chinese error state on search failure and keeps the query', async () => {
    apiPost.mockRejectedValue({ type: 'mikan_http_failed', message: 'MiKan HTTP 请求失败' })
    const { wrapper } = await mountWorkbench()

    await wrapper.find('#mikan-candidate-query').setValue('芙莉莲')
    await wrapper.find('#mikan-candidate-search-submit').trigger('click')
    await flushPromises()

    expect(wrapper.find('.error-state').text()).toContain('候选搜索失败')
    // The raw error_type/message never leaks into the DOM.
    expect(wrapper.text()).not.toContain('mikan_http_failed')
    expect(wrapper.find('#mikan-candidate-query').element as HTMLInputElement).toHaveProperty('value', '芙莉莲')
  })

  it('locks the season-confirmation candidate until the checkbox is checked', async () => {
    apiPost.mockResolvedValue(
      candidateResult({
        candidates: [
          candidate({
            season_evidence: { status: 'NEEDS_CONFIRMATION', season: 4, requires_review: true },
            candidate_context: 'opaque-context',
          }) as never,
        ],
      }),
    )
    const { wrapper } = await mountWorkbench()

    await wrapper.find('#mikan-candidate-query').setValue('芙莉莲')
    await wrapper.find('#mikan-candidate-search-submit').trigger('click')
    await flushPromises()

    const card = wrapper.find('.candidate-card')
    const select = card.find('.candidate-select')
    const checkbox = card.find('.candidate-season-confirmation input')
    expect(checkbox.exists()).toBe(true)
    expect(select.attributes('disabled')).toBeDefined()
    expect(select.attributes('aria-disabled')).toBe('true')

    await checkbox.setValue(true)
    await nextTick()
    expect(select.attributes('disabled')).toBeUndefined()
    expect(select.attributes('aria-disabled')).toBe('false')

    await checkbox.setValue(false)
    await nextTick()
    expect(select.attributes('disabled')).toBeDefined()
  })
})

describe('WorkbenchView candidate selection & draft (US-204)', () => {
  beforeEach(() => {
    localStorage.clear()
    apiPost.mockReset()
  })

  it('generates a server-authoritative draft on explicit selection', async () => {
    apiPost.mockResolvedValueOnce(candidateResult())
    apiPost.mockResolvedValueOnce(createDraftResult())
    const { wrapper } = await mountWorkbench()

    await wrapper.find('#mikan-candidate-query').setValue('芙莉莲')
    await wrapper.find('#mikan-candidate-search-submit').trigger('click')
    await flushPromises()

    await wrapper.find('.candidate-select').trigger('click')
    await flushPromises()

    expect(apiPost).toHaveBeenLastCalledWith('/api/v1/requests', {
      body: {
        title: '葬送的芙莉莲',
        source: 'mikan',
        mikan_bangumi: 'https://mikan.example/Home/Bangumi/2353',
        storage_dir: null,
        save_request: false,
      },
    })
    // The draft preview panel mounts with the display snapshot.
    expect(wrapper.find('#detail-preview-edit-form').exists()).toBe(true)
    expect(wrapper.find('.preview-mode-note').text()).toContain('订阅草案（未保存）')
    expect(wrapper.find('#single-review-save-button').exists()).toBe(true)
    // The draft_id never enters the DOM.
    expect(wrapper.text()).not.toContain('opaque-draft-token')
  })

  it('protects review navigation and restores candidates after confirmed discard', async () => {
    apiPost.mockResolvedValueOnce(candidateResult()).mockResolvedValueOnce(createDraftResult())
    const { wrapper } = await mountWorkbench()

    await wrapper.find('#mikan-candidate-query').setValue('芙莉莲')
    await wrapper.find('#mikan-candidate-search-submit').trigger('click')
    await flushPromises()
    await wrapper.find('.candidate-select').trigger('click')
    await flushPromises()

    await wrapper.find('#single-review-back-candidates').trigger('click')
    expect(wrapper.find('.confirm-dialog').exists()).toBe(true)
    await wrapper.find('.confirm-dialog .secondary-button').trigger('click')
    expect(wrapper.find('#single-anime-review-step').exists()).toBe(true)

    await wrapper.find('#single-review-back-candidates').trigger('click')
    await wrapper.find('.confirm-dialog .danger-button').trigger('click')
    await flushPromises()
    expect(wrapper.find('#single-anime-review-step').exists()).toBe(false)
    expect(wrapper.find('.candidate-card').exists()).toBe(true)
  })

  it('isolates batch mode from the single draft panel and keeps the draft in memory', async () => {
    apiPost.mockResolvedValueOnce(candidateResult()).mockResolvedValueOnce(createDraftResult())
    const { wrapper } = await mountWorkbench()

    await wrapper.find('#mikan-candidate-query').setValue('芙莉莲')
    await wrapper.find('#mikan-candidate-search-submit').trigger('click')
    await flushPromises()
    await wrapper.find('.candidate-select').trigger('click')
    await flushPromises()
    expect(wrapper.find('#detail-preview-edit-form').exists()).toBe(true)

    await wrapper.find('#anime-mode-batch').trigger('click')
    await nextTick()
    expect(wrapper.find('#detail-preview-edit-form').exists()).toBe(false)
    expect(wrapper.findAll('label[for="batch-raw-input"]')).toHaveLength(1)
    expect(wrapper.findAll('#batch-raw-input-help')).toHaveLength(1)

    await wrapper.find('#anime-mode-single').trigger('click')
    await nextTick()
    expect(wrapper.find('#detail-preview-edit-form').exists()).toBe(true)
  })

  it('restores the single input cursor after switching modes', async () => {
    const { wrapper } = await mountWorkbench()
    const input = wrapper.find('#mikan-candidate-query').element as HTMLInputElement
    await wrapper.find('#mikan-candidate-query').setValue('葬送的芙莉莲')
    input.setSelectionRange(2, 4)

    await wrapper.find('#anime-mode-batch').trigger('click')
    await wrapper.find('#anime-mode-single').trigger('click')
    await nextTick()

    const restored = wrapper.find('#mikan-candidate-query').element as HTMLInputElement
    expect(document.activeElement).toBe(restored)
    expect(restored.selectionStart).toBe(2)
    expect(restored.selectionEnd).toBe(4)
  })

  it('applies preview-modify edits and recomputes the display', async () => {
    apiPost
      .mockResolvedValueOnce(candidateResult())
      .mockResolvedValueOnce(createDraftResult())
      .mockResolvedValueOnce({
        request: previewSnapshot({
          confirmable_config: {
            ...previewSnapshot().confirmable_config,
            filter_rule: { must_contain: '', must_not_contain: 'V2', use_regex: false, case_sensitive: false },
          },
        }),
        summary: {},
        draft_id: 'opaque-draft-token',
        draft_revision: 2,
      })
    const { wrapper } = await mountWorkbench()

    await wrapper.find('#mikan-candidate-query').setValue('芙莉莲')
    await wrapper.find('#mikan-candidate-search-submit').trigger('click')
    await flushPromises()
    await wrapper.find('.candidate-select').trigger('click')
    await flushPromises()

    await wrapper.find('#preview-must-not-contain').setValue('V2')
    await wrapper.find('#preview-apply-button').trigger('click')
    await flushPromises()

    expect(apiPost).toHaveBeenCalledWith('/api/v1/requests/preview-modify', {
      body: {
        draft_id: 'opaque-draft-token',
        base_revision: 1,
        patch: { filter_rule: { must_not_contain: 'V2', use_regex: false, case_sensitive: false } },
        storage_dir: null,
      },
    })
    expect(wrapper.find('#detail-preview-edit-form').text()).toContain('编辑订阅草案')
  })

  it('carries the bumped base_revision on the next preview-modify', async () => {
    apiPost
      .mockResolvedValueOnce(candidateResult())
      .mockResolvedValueOnce(createDraftResult())
      // First modify returns revision 2.
      .mockResolvedValueOnce({
        request: previewSnapshot(),
        summary: {},
        draft_id: 'opaque-draft-token',
        draft_revision: 2,
      })
      // Second modify returns revision 3.
      .mockResolvedValueOnce({
        request: previewSnapshot(),
        summary: {},
        draft_id: 'opaque-draft-token',
        draft_revision: 3,
      })
    const { wrapper } = await mountWorkbench()

    await wrapper.find('#mikan-candidate-query').setValue('芙莉莲')
    await wrapper.find('#mikan-candidate-search-submit').trigger('click')
    await flushPromises()
    await wrapper.find('.candidate-select').trigger('click')
    await flushPromises()

    await wrapper.find('#preview-must-not-contain').setValue('V2')
    await wrapper.find('#preview-apply-button').trigger('click')
    await flushPromises()
    // Panel still open; change folder and apply again.
    await wrapper.find('#preview-folder-name').setValue('自定义目录')
    await wrapper.find('#preview-apply-button').trigger('click')
    await flushPromises()

    const modifyCalls = apiPost.mock.calls.filter(([path]) => path === '/api/v1/requests/preview-modify')
    expect(modifyCalls).toHaveLength(2)
    const [firstBody, secondBody] = modifyCalls.map(([, options]) => options?.body)
    expect(firstBody).toMatchObject({ base_revision: 1, draft_id: 'opaque-draft-token' })
    // The second modify uses the revision returned by the first modify.
    expect(secondBody).toMatchObject({ base_revision: 2, draft_id: 'opaque-draft-token' })
  })

  it('treats draft_revision_conflict as a regeneration hint', async () => {
    apiPost
      .mockResolvedValueOnce(candidateResult())
      .mockResolvedValueOnce(createDraftResult())
      .mockRejectedValueOnce({
        type: 'draft_revision_conflict',
        message: '草案已被更新，请基于最新版本重试',
        status: 409,
        details: { failed_step: 'compare_and_swap_draft', details: { field: 'base_revision', current_revision: 2 } },
      })
    const { wrapper } = await mountWorkbench()

    await wrapper.find('#mikan-candidate-query').setValue('芙莉莲')
    await wrapper.find('#mikan-candidate-search-submit').trigger('click')
    await flushPromises()
    await wrapper.find('.candidate-select').trigger('click')
    await flushPromises()

    await wrapper.find('#preview-must-not-contain').setValue('V2')
    await wrapper.find('#preview-apply-button').trigger('click')
    await flushPromises()

    const { useNotificationStore } = await import('@/app/stores/notification')
    const notification = useNotificationStore()
    expect(notification.current?.title).toBe('订阅草案已失效')
    // The draft panel was dismissed (regeneration hint) and the raw conflict
    // message never reaches the DOM.
    expect(wrapper.find('#detail-preview-edit-form').exists()).toBe(false)
    expect(wrapper.text()).not.toContain('draft_revision_conflict')
  })

  it('enables atomic save-confirm when the review is valid', async () => {
    apiPost.mockResolvedValueOnce(candidateResult()).mockResolvedValueOnce(createDraftResult())
    const { wrapper } = await mountWorkbench()

    await wrapper.find('#mikan-candidate-query').setValue('芙莉莲')
    await wrapper.find('#mikan-candidate-search-submit').trigger('click')
    await flushPromises()
    await wrapper.find('.candidate-select').trigger('click')
    await flushPromises()

    expect(wrapper.find('#single-review-save-button').attributes('disabled')).toBeUndefined()
    expect(apiPost).toHaveBeenCalledTimes(2)
  })

  it('sends only the generated save-confirm capability and consumes it on success', async () => {
    apiPost
      .mockResolvedValueOnce(candidateResult())
      .mockResolvedValueOnce(createDraftResult())
      .mockResolvedValueOnce({
        outcome: 'CONFIRMED',
        request: { request_id: 'req-confirmed' },
        handoff: {
          request_id: 'req-confirmed', status: 'CONFIRMED', next_action: 'TRACKING',
          tracking_id: 'tracking-confirmed', tracking_status: 'PENDING_SUBMIT',
          tracking_ready: true, safe_message: null,
        },
      } as never)
    const { wrapper, router } = await mountWorkbench()

    await wrapper.find('#mikan-candidate-query').setValue('芙莉莲')
    await wrapper.find('#mikan-candidate-search-submit').trigger('click')
    await flushPromises()
    await wrapper.find('.candidate-select').trigger('click')
    await flushPromises()
    await wrapper.find('#single-review-save-button').trigger('click')
    await flushPromises()

    const saveCall = apiPost.mock.calls.find(([path]) => path === '/api/v1/requests/save-confirm')
    expect(saveCall?.[1]?.body).toMatchObject({
      draft_id: 'opaque-draft-token',
      base_revision: 1,
      storage_dir: null,
    })
    expect(saveCall?.[1]?.body).toHaveProperty('idempotency_key')
    expect(saveCall?.[1]?.body).not.toHaveProperty('request')
    expect(router.currentRoute.value.name).toBe('tracking')
    expect(router.currentRoute.value.query).toEqual({ tracking_id: 'tracking-confirmed' })
    expect(apiPost.mock.calls.filter(([path]) => path === '/api/v1/requests/save-confirm')).toHaveLength(1)
  })

  it('keeps the review panel open after entering the save-confirm host', async () => {
    apiPost
      .mockResolvedValueOnce(candidateResult())
      .mockResolvedValueOnce(createDraftResult())

    const { wrapper } = await mountWorkbench()

    await wrapper.find('#mikan-candidate-query').setValue('芙莉莲')
    await wrapper.find('#mikan-candidate-search-submit').trigger('click')
    await flushPromises()
    await wrapper.find('.candidate-select').trigger('click')
    await flushPromises()

    expect(wrapper.find('#single-review-save-button').attributes('disabled')).toBeUndefined()
    expect(wrapper.find('#detail-preview-edit-form').exists()).toBe(true)
    expect(apiPost).toHaveBeenCalledTimes(2)
  })

  it('recovers a saved-but-unconfirmed request with accept and locates tracking safely', async () => {
    apiPost
      .mockResolvedValueOnce(candidateResult())
      .mockResolvedValueOnce(createDraftResult())
      .mockRejectedValueOnce({
        type: 'save_confirm_failed',
        message: '不要渲染此服务端消息',
        details: { details: { outcome: 'SAVED_CONFIRM_FAILED', request_id: 'saved-request-1', retry_action: 'ACCEPT_SAVED_REQUEST', secret: 'hidden' } },
      })
      .mockRejectedValueOnce({ type: 'network_error' })
      .mockResolvedValueOnce({ request: { request_id: 'saved-request-1' } } as never)
    apiGet.mockRejectedValueOnce({ type: 'network_error' }).mockResolvedValueOnce({
      items: [],
    } as never).mockResolvedValueOnce({
      items: [
        { tracking_id: 'tracking-from-server', request_id: 'saved-request-1' },
        { tracking_id: 'wrong-item', request_id: 'another-request' },
      ],
    } as never)
    const { wrapper } = await mountWorkbench()

    await wrapper.find('#mikan-candidate-query').setValue('芙莉莲')
    await wrapper.find('#mikan-candidate-search-submit').trigger('click')
    await flushPromises()
    await wrapper.find('.candidate-select').trigger('click')
    await flushPromises()
    await wrapper.find('#single-review-save-button').trigger('click')
    await flushPromises()

    expect(wrapper.find('#single-review-retry-accept').exists()).toBe(true)
    expect(wrapper.text()).toContain('不会重复保存')
    expect(wrapper.text()).not.toContain('不要渲染此服务端消息')

    await wrapper.find('#single-review-retry-accept').trigger('click')
    await flushPromises()

    expect(apiPost).toHaveBeenLastCalledWith('/api/v1/requests/{request_id}/accept', expect.objectContaining({
      path: { request_id: 'saved-request-1' },
      body: { storage_dir: null },
    }))
    expect(apiPost.mock.calls.filter(([path]) => path === '/api/v1/requests/{request_id}/accept')).toHaveLength(1)
    expect(wrapper.find('#single-review-retry-accept').exists()).toBe(false)
    expect(wrapper.find('#single-review-retry-locate').exists()).toBe(true)

    await wrapper.find('#single-review-retry-locate').trigger('click')
    await flushPromises()

    expect(wrapper.find('#single-review-retry-accept').exists()).toBe(true)
    expect(wrapper.text()).toContain('可明确重试确认')

    await wrapper.find('#single-review-retry-accept').trigger('click')
    await flushPromises()

    expect(apiGet).toHaveBeenCalledWith('/api/v1/tracking/items', { query: {} })
    expect(wrapper.find('#single-review-tracking-success').text()).toContain('已定位')
  })

  it.each(['not_found', 'failed'] as const)('keeps accept closed after successful accept with %s tracking lookup', async (lookup) => {
    apiPost
      .mockResolvedValueOnce(candidateResult())
      .mockResolvedValueOnce(createDraftResult())
      .mockRejectedValueOnce({
        type: 'save_confirm_failed',
        details: { details: { outcome: 'SAVED_CONFIRM_FAILED', request_id: 'saved-request-2', retry_action: 'ACCEPT_SAVED_REQUEST' } },
      })
      .mockResolvedValueOnce({ request: { request_id: 'saved-request-2' } } as never)
    if (lookup === 'failed') apiGet.mockRejectedValueOnce({ type: 'network_error' })
    else apiGet.mockResolvedValueOnce({ items: [] } as never)
    const { wrapper } = await mountWorkbench()

    await wrapper.find('#mikan-candidate-query').setValue('芙莉莲')
    await wrapper.find('#mikan-candidate-search-submit').trigger('click')
    await flushPromises()
    await wrapper.find('.candidate-select').trigger('click')
    await flushPromises()
    await wrapper.find('#single-review-save-button').trigger('click')
    await flushPromises()
    await wrapper.find('#single-review-retry-accept').trigger('click')
    await flushPromises()

    expect(wrapper.find('#single-review-retry-accept').exists()).toBe(false)
    expect(wrapper.find('#single-review-retry-locate').exists()).toBe(true)
    expect(wrapper.find('#single-review-open-unlocated').exists()).toBe(true)
  })

  it('shows a safe error and keeps the search state when generation fails', async () => {
    apiPost.mockResolvedValueOnce(candidateResult())
    apiPost.mockRejectedValueOnce({ type: 'mikan_parse_failed', message: 'MiKan 番剧页解析失败' })
    const { wrapper } = await mountWorkbench()

    await wrapper.find('#mikan-candidate-query').setValue('芙莉莲')
    await wrapper.find('#mikan-candidate-search-submit').trigger('click')
    await flushPromises()

    await wrapper.find('.candidate-select').trigger('click')
    await flushPromises()

    const { useNotificationStore } = await import('@/app/stores/notification')
    const notification = useNotificationStore()
    expect(notification.current?.title).toBe('生成失败')
    expect(notification.current?.message).toBe('从 MiKan 合集生成订阅草案失败。请重试。')
    expect(wrapper.findAll('.candidate-card')).toHaveLength(1)
    expect(wrapper.find('#detail-preview-edit-form').exists()).toBe(false)
  })
})

describe('WorkbenchView direct fallback (US-204)', () => {
  beforeEach(() => {
    localStorage.clear()
    apiPost.mockReset()
  })

  it('reveals the fallback form only when the checkbox is checked', async () => {
    const { wrapper } = await mountWorkbench()

    expect(wrapper.find('#mikan-fallback-form').exists()).toBe(false)
    await wrapper.find('#mikan-fallback-enabled').setValue(true)
    await nextTick()
    expect(wrapper.find('#mikan-fallback-form').exists()).toBe(true)
  })

  it('validates the fallback value before calling the API', async () => {
    const { wrapper } = await mountWorkbench()
    await wrapper.find('#mikan-fallback-enabled').setValue(true)
    await nextTick()

    await wrapper.find('#mikan-fallback-generate').trigger('click')
    await nextTick()

    expect(apiPost).not.toHaveBeenCalled()
    expect(wrapper.find('#mikan-fallback-error').text()).toContain('生成前必须填写 MiKan 合集 URL 或 ID')

    await wrapper.find('#mikan-fallback-bangumi').setValue('not a url or id')
    await wrapper.find('#mikan-fallback-generate').trigger('click')
    await nextTick()
    expect(wrapper.find('#mikan-fallback-error').text()).toContain('必须是数字 ID 或 HTTP(S) URL')
  })

  it('generates a draft from a bare ID and clears the input on success', async () => {
    apiPost.mockResolvedValue(createDraftResult())
    const { wrapper } = await mountWorkbench()

    await wrapper.find('#mikan-candidate-query').setValue('芙莉莲')
    await wrapper.find('#mikan-fallback-enabled').setValue(true)
    await nextTick()
    await wrapper.find('#mikan-fallback-bangumi').setValue('2353')
    await wrapper.find('#mikan-fallback-generate').trigger('click')
    await flushPromises()

    expect(apiPost).toHaveBeenCalledWith('/api/v1/requests', {
      body: {
        title: '芙莉莲',
        source: 'mikan',
        mikan_bangumi: '2353',
        storage_dir: null,
        save_request: false,
      },
    })
    expect(wrapper.find('#detail-preview-edit-form').exists()).toBe(true)
    expect((wrapper.find('#mikan-fallback-bangumi').element as HTMLInputElement).value).toBe('')
  })
})
