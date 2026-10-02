import { enableAutoUnmount, flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import { createPinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { createMemoryHistory, createRouter } from 'vue-router'
import { nextTick } from 'vue'

import { api } from '@/api/client'
import type { operations } from '@/api/generated/api'
import AnimeModeSwitch from '@/features/workbench/AnimeModeSwitch.vue'
import WorkbenchView from '@/features/workbench/WorkbenchView.vue'
import { buildReuseHandoff, publishReuseHandoff, clearReuseHandoff } from '@/features/requests/reuseHandoff'

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

// Issue 110：每个用例都把工作台挂到 document.body。视图用 document.querySelector
// 聚焦全局唯一的结果标题／重试按钮，若旧用例的 DOM 仍在文档里，焦点会落到旧节点。
// 用例后统一卸载，保证这些全局查询只命中当前用例。
enableAutoUnmount(afterEach)
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

/** 手动控制的 promise：用于把异步请求卡在「进行中」状态。 */
function deferred<T>() {
  let resolve!: (value: T) => void
  const promise = new Promise<T>((res) => { resolve = res })
  return { promise, resolve }
}

/** 最小批量解析条目：状态与展示字段齐全，足以渲染卡片。 */
function batchParseItem(itemId: string, rawTitle: string, status = 'EMPTY') {
  return {
    item_id: itemId,
    raw_title: rawTitle,
    status,
    canonical_title_candidates: [],
    season_hint: null,
    search_queries: [rawTitle],
    confidence: 0.9,
    needs_user_review: false,
    source: 'fake',
    parse_result: null,
    attempted_queries: [],
    candidates: [],
    applied_preferences: null,
    preference_hits: [],
    preference_warnings: [],
    review_hints: [],
    enhanced_search_queries: [],
    preview_request: null,
    error: null,
  }
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
    clearReuseHandoff()
    apiPost.mockReset()
    apiGet.mockReset()
  })

  it('consumes a reuse handoff once and requires explicit search', async () => {
    const handoff = buildReuseHandoff({
      request_id: 'not-copied', status: 'ACCEPTED', raw_title: '原始', title: '葬送的芙莉莲',
      aliases: [], season: 1, season_raw: 'S1', season_evidence: 'evidence',
      mikan_collection: { title: '真实合集', bangumi_id: '2353' }, subtitle_groups: [],
      selected_subtitle_group: '字幕组', filter_rule: { must_contain: '1080p', must_not_contain: '', use_regex: false, case_sensitive: false },
      resources: { selected_subtitle_group: '字幕组', valid_resource_count: 1, invalid_resource_count: 0, complete_resource_count: 1 },
      folder_name: '葬送的芙莉莲', storage_profile: 'storage', total_episodes: null,
      updated_episode: null, updated_episode_status: 'NOT_IMPLEMENTED', history_summary: [],
      ab_status: { submitted: false, success: null, ab_subscription_id: null, error_type: null },
    })
    publishReuseHandoff(handoff!)
    const { wrapper } = await mountWorkbench()

    expect(wrapper.find('#mikan-candidate-query').element).toHaveProperty('value', '葬送的芙莉莲')
    expect(wrapper.find('#reuse-handoff-summary').text()).toContain('公开合集编号 2353')
    expect(apiPost).not.toHaveBeenCalled()
    expect(wrapper.find('#mikan-candidate-search-submit').attributes('disabled')).toBeUndefined()
    // The module-level handoff has already been consumed by this mount.
    expect((await import('@/features/requests/reuseHandoff')).consumeReuseHandoff()).toBeNull()
  })

  it('offers reuse suggestions only after a new draft is generated and explicit apply', async () => {
    const handoff = buildReuseHandoff({
      request_id: 'not-copied', status: 'ACCEPTED', raw_title: '原始', title: '葬送的芙莉莲',
      aliases: [], season: 1, season_raw: 'S1', season_evidence: 'evidence',
      mikan_collection: { title: '真实合集', bangumi_id: '2353' }, subtitle_groups: [],
      selected_subtitle_group: '字幕组', filter_rule: { must_contain: '', must_not_contain: '', use_regex: false, case_sensitive: false },
      resources: { selected_subtitle_group: '字幕组', valid_resource_count: 1, invalid_resource_count: 0, complete_resource_count: 1 },
      folder_name: '建议目录', storage_profile: 'storage', total_episodes: null,
      updated_episode: null, updated_episode_status: 'NOT_IMPLEMENTED', history_summary: [],
      ab_status: { submitted: false, success: null, ab_subscription_id: null, error_type: null },
    })
    publishReuseHandoff(handoff!)
    apiPost.mockResolvedValueOnce(candidateResult()).mockResolvedValueOnce(createDraftResult())
    const { wrapper } = await mountWorkbench()

    await wrapper.find('#mikan-candidate-search-submit').trigger('click')
    await flushPromises()
    await wrapper.find('.candidate-select').trigger('click')
    await flushPromises()

    expect(wrapper.find('#single-review-apply-reuse-suggestion').exists()).toBe(true)
    expect(wrapper.find('#preview-folder-name').element).toHaveProperty('value', '葬送的芙莉莲')
    await wrapper.find('#single-review-apply-reuse-suggestion').trigger('click')
    expect(wrapper.find('#preview-folder-name').element).toHaveProperty('value', '建议目录')
  })

  it('keeps the initial page to the name input and mode switch (no empty result panel)', async () => {
    const { wrapper } = await mountWorkbench()

    // F4/US-345: before any search there is no results panel, no empty-result
    // hint and no direct-collection rescue entry — only the search form.
    expect(wrapper.find('#mikan-candidate-search-form').exists()).toBe(true)
    expect(wrapper.find('#mikan-candidate-search-result').exists()).toBe(false)
    expect(wrapper.find('#mikan-fallback-enabled').exists()).toBe(false)
    expect(wrapper.find('#mikan-fallback-form').exists()).toBe(false)
    expect(wrapper.text()).not.toContain('输入番剧标题后搜索候选合集')
    expect(wrapper.find('#mikan-candidate-search-submit').attributes('disabled')).toBeDefined()
    expect(apiPost).not.toHaveBeenCalled()
  })

  it('presents one add-anime task heading, three steps, and a grouped search action', async () => {
    const { wrapper } = await mountWorkbench()

    expect(wrapper.find('#workbench-heading').element.tagName).toBe('H1')
    expect(wrapper.find('#workbench-heading').text()).toBe('添加番剧')
    expect(wrapper.find('.journey-steps').text()).toContain('输入名称')
    expect(wrapper.find('.journey-steps').text()).toContain('选择真实合集')
    expect(wrapper.find('.journey-steps').text()).toContain('审核并保存确认')
    expect(wrapper.find('.search-control-row #mikan-candidate-query').exists()).toBe(true)
    expect(wrapper.find('.search-control-row #mikan-candidate-search-submit').text()).toContain('搜索候选合集')
    expect(wrapper.text()).not.toContain('外部提交')
  })

  it('keeps the search input and returns to the first screen without clearing candidates', async () => {
    apiPost.mockResolvedValue(candidateResult())
    const { wrapper } = await mountWorkbench()

    await wrapper.find('#mikan-candidate-query').setValue('芙莉莲')
    await wrapper.find('#mikan-candidate-search-submit').trigger('click')
    await flushPromises()

    // Issue 110：第一屏常驻，候选工作台是第二屏；输入不被移除。
    expect(wrapper.find('#mikan-candidate-query').exists()).toBe(true)
    expect(wrapper.find('#candidate-search-heading').text()).toBe('选择真实合集')
    expect(wrapper.find('.candidate-search-summary').text()).toContain('已搜索「芙莉莲」')
    expect(wrapper.findAll('.candidate-card')).toHaveLength(1)

    await wrapper.find('#mikan-back-to-search').trigger('click')
    await flushPromises()
    // 「返回搜索首屏」只滚动与聚焦，不清空下方未保存的候选现场。
    expect(wrapper.findAll('.candidate-card')).toHaveLength(1)
    expect((wrapper.find('#mikan-candidate-query').element as HTMLInputElement).value).toBe('芙莉莲')
  })

  it('offers the direct-collection rescue only after a search found no candidates', async () => {
    apiPost.mockResolvedValueOnce(candidateResult({ candidates: [] }))
    const { wrapper } = await mountWorkbench()

    expect(wrapper.find('#mikan-fallback-enabled').exists()).toBe(false)
    await wrapper.find('#mikan-candidate-query').setValue('ghost')
    await wrapper.find('#mikan-candidate-search-submit').trigger('click')
    await flushPromises()
    expect(wrapper.find('#mikan-fallback-enabled').exists()).toBe(true)
    expect(wrapper.find('#mikan-fallback-form').exists()).toBe(false)

    // A search that does find candidates never offers the rescue path.
    apiPost.mockResolvedValueOnce(candidateResult())
    await wrapper.find('#mikan-candidate-query').setValue('芙莉莲')
    await nextTick()
    await wrapper.find('#mikan-candidate-search-submit').trigger('click')
    await flushPromises()
    expect(wrapper.findAll('.candidate-card')).toHaveLength(1)
    expect(wrapper.find('#mikan-fallback-enabled').exists()).toBe(false)
    // The view focuses the first candidate through `document.querySelector`, so
    // this wrapper must not stay attached to document.body with candidates.
    wrapper.unmount()
  })

  it('focuses the title input on entry and moves focus to the result heading', async () => {
    apiPost.mockResolvedValue(candidateResult())
    const { wrapper } = await mountWorkbench()

    await nextTick()
    expect(document.activeElement).toBe(wrapper.find('#mikan-candidate-query').element)

    await wrapper.find('#mikan-candidate-query').setValue('芙莉莲')
    await wrapper.find('#mikan-candidate-search-submit').trigger('click')
    await flushPromises()

    // Issue 110：成功后自动进入第二屏，焦点落在结果标题而不是某张候选卡。
    expect(document.activeElement).toBe(wrapper.find('#candidate-search-heading').element)
  })

  it('keeps the first screen with an in-place retry when the search fails', async () => {
    apiPost.mockRejectedValueOnce({ type: 'mikan_http_failed', message: '原始错误' })
    const { wrapper } = await mountWorkbench()

    await wrapper.find('#mikan-candidate-query').setValue('芙莉莲')
    await wrapper.find('#mikan-candidate-search-submit').trigger('click')
    await flushPromises()

    // 失败留在搜索首屏：候选屏不出现，输入保留，重试按钮就地可用。
    expect(wrapper.find('#candidate-search-heading').exists()).toBe(false)
    expect(wrapper.find('#mikan-candidate-query').exists()).toBe(true)
    expect(wrapper.find('#mikan-search-feedback-action').text()).toContain('重试搜索')
    // 就地重试可用，但失败不抢键盘焦点（Stage 42 无障碍保证）。
    expect(document.activeElement).not.toBe(wrapper.find('#mikan-search-feedback-action').element)
  })

  it('keeps the first screen and offers a re-search plus collapsed rescue when nothing matched', async () => {
    apiPost.mockResolvedValueOnce(candidateResult({ candidates: [] }))
    const { wrapper } = await mountWorkbench()

    await wrapper.find('#mikan-candidate-query').setValue('ghost')
    await wrapper.find('#mikan-candidate-search-submit').trigger('click')
    await flushPromises()

    expect(wrapper.find('#candidate-search-heading').exists()).toBe(false)
    expect(wrapper.find('#mikan-candidate-search-result .empty-state').text()).toContain('核对番剧名称或季度')
    expect(wrapper.find('#mikan-search-feedback-action').text()).toContain('重新搜索')
    // 直连救援入口默认收起。
    expect(wrapper.find('#mikan-fallback-enabled').exists()).toBe(true)
    expect(wrapper.find('#mikan-fallback-form').exists()).toBe(false)
  })

  it('searches candidates through the shared transport and renders cards', async () => {
    apiPost.mockResolvedValue(candidateResult())
    const { wrapper } = await mountWorkbench()

    await wrapper.find('#mikan-candidate-query').setValue('芙莉莲')
    await wrapper.find('#mikan-candidate-search-submit').trigger('click')
    await flushPromises()

    expect(apiPost).toHaveBeenCalledWith('/api/v1/mikan/candidates', {
      body: { query: '芙莉莲' },
      timeoutMs: 135000,
    })
    const cards = wrapper.findAll('.candidate-card')
    expect(cards).toHaveLength(1)
    expect(cards[0]!.text()).toContain('葬送的芙莉莲')
    expect(cards[0]!.text()).toContain('选择此合集')
    expect(cards[0]!.find('.candidate-progress').text()).toContain('总集数')
    // #142：卡片不再有「高级信息」入口或替代浮层；合集编号与解析搜索词只留在
    // 页面级搜索诊断里，卡片默认层不出现它们。
    expect(cards[0]!.find('details.candidate-advanced').exists()).toBe(false)
    expect(cards[0]!.text()).not.toContain('高级信息')
    expect(cards[0]!.text()).not.toContain('2353')
  })

  it('shows only the first four candidates with a short truncation note', async () => {
    apiPost.mockResolvedValueOnce(
      candidateResult({
        candidates: Array.from({ length: 5 }, (_, index) =>
          candidate({
            bangumi_id: String(3000 + index),
            title: `候选 ${index + 1}`,
            mikan_url: `https://mikan.example/Home/Bangumi/${3000 + index}`,
          }),
        ),
      }),
    )
    const { wrapper } = await mountWorkbench()
    await wrapper.find('#mikan-candidate-query').setValue('芙莉莲')
    await wrapper.find('#mikan-candidate-search-form').trigger('submit')
    await flushPromises()

    // Issue 110: 单番候选最多同排展示四项，不自动选择，也不虚构第五项。
    expect(wrapper.findAll('.candidate-card')).toHaveLength(4)
    const note = wrapper.find('#candidate-truncation-note')
    expect(note.exists()).toBe(true)
    expect(note.text()).toContain('仅显示前 4 个')
    expect(wrapper.findAll('.candidate-select')).toHaveLength(4)
  })

  it('shows every candidate and no truncation note at four or fewer', async () => {
    apiPost.mockResolvedValueOnce(
      candidateResult({
        candidates: Array.from({ length: 4 }, (_, index) =>
          candidate({
            bangumi_id: String(4000 + index),
            title: `候选 ${index + 1}`,
            mikan_url: `https://mikan.example/Home/Bangumi/${4000 + index}`,
          }),
        ),
      }),
    )
    const { wrapper } = await mountWorkbench()
    await wrapper.find('#mikan-candidate-query').setValue('芙莉莲')
    await wrapper.find('#mikan-candidate-search-form').trigger('submit')
    await flushPromises()

    expect(wrapper.findAll('.candidate-card')).toHaveLength(4)
    expect(wrapper.find('#candidate-truncation-note').exists()).toBe(false)
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

  it('does not mislabel a 200 FAILED candidate result as EMPTY', async () => {
    apiPost.mockResolvedValue(candidateResult({
      status: 'FAILED', candidates: [],
      error: { error_type: 'mikan_timeout', details: { category: 'mikan_search' } },
    }))
    const { wrapper } = await mountWorkbench()
    await wrapper.find('#mikan-candidate-query').setValue('芙莉莲')
    await wrapper.find('#mikan-candidate-search-submit').trigger('click')
    await flushPromises()
    expect(wrapper.find('#mikan-candidate-search-error').text()).toContain('MiKan 上游响应超时')
    expect(wrapper.find('#mikan-candidate-search-result .empty-state').exists()).toBe(false)
    expect(wrapper.text()).not.toContain('未找到候选合集')
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
    // F4/US-345: parse diagnostics are collapsed on the candidate step.
    expect((summary.element as HTMLDetailsElement).open).toBe(false)
    expect(summary.find('summary').text()).toContain('标题解析摘要')
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

  it('answers the review default layer from memory and keeps technical details collapsed', async () => {
    apiPost
      .mockResolvedValueOnce(
        candidateResult({
          candidates: [
            candidate({
              total_episodes: 28,
              season_evidence: { status: 'NEEDS_CONFIRMATION', season: 1, requires_review: true },
            }) as never,
          ],
        }),
      )
      .mockResolvedValueOnce(createDraftResult())
    const { wrapper } = await mountWorkbench()

    await wrapper.find('#mikan-candidate-query').setValue('芙莉莲')
    await wrapper.find('#mikan-candidate-search-submit').trigger('click')
    await flushPromises()
    await wrapper.find('.candidate-season-confirmation input').setValue(true)
    await wrapper.find('.candidate-select').trigger('click')
    await flushPromises()

    // F4/US-345: 默认层回答「已选哪部/哪一季、筛后有什么」——合集与季度来自
    // 宿主内存中的公开候选投影，不新增请求也不调用 safe-info。
    const summary = wrapper.find('.draft-review-summary')
    expect(summary.exists()).toBe(true)
    expect(summary.text()).toContain('已选合集')
    expect(summary.text()).toContain('葬送的芙莉莲')
    expect(summary.text()).toContain('第 1 季')
    expect(summary.text()).toContain('28 集')
    expect(summary.text()).toContain('喵萌奶茶屋')
    expect(summary.text()).toContain('筛选规则')
    // 资源摘要保留在默认层；内部 ID / 原始标题 / RSS 选择折叠在技术层。
    expect(wrapper.find('.resource-summary').exists()).toBe(true)
    const technical = wrapper.find('details.advanced-detail')
    expect(technical.exists()).toBe(true)
    expect((technical.element as HTMLDetailsElement).open).toBe(false)
    expect(technical.find('summary').text()).toContain('全部信息')
    expect(technical.text()).toContain('request_id')
    expect(apiGet.mock.calls.some(([url]) => String(url).includes('safe-info'))).toBe(false)
  })

  it('keeps candidates while editing the title and confirms a replacing re-search', async () => {
    apiPost.mockResolvedValue(candidateResult())
    const { wrapper } = await mountWorkbench()

    await wrapper.find('#mikan-candidate-query').setValue('芙莉莲')
    await wrapper.find('#mikan-candidate-search-submit').trigger('click')
    await flushPromises()
    expect(wrapper.findAll('.candidate-card')).toHaveLength(1)

    await wrapper.find('#mikan-back-to-search').trigger('click')
    await nextTick()
    await wrapper.find('#mikan-candidate-query').setValue('无职转生')
    await nextTick()

    // Issue 110：编辑输入不再静默清空第二屏现场。
    expect(wrapper.findAll('.candidate-card')).toHaveLength(1)

    // 重新搜索若会替换未保存工作，先给简短确认；取消则保持现场。
    await wrapper.find('#mikan-candidate-search-form').trigger('submit')
    await flushPromises()
    const dialog = wrapper.find('.confirm-dialog')
    expect(dialog.exists()).toBe(true)
    expect(dialog.text()).toContain('重新搜索会清除')
    await dialog.find('.secondary-button').trigger('click')
    await flushPromises()
    expect(wrapper.findAll('.candidate-card')).toHaveLength(1)
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
        mikan_bangumi: 'https://mikan.example/Home/Bangumi/2353',
        storage_dir: null,
      },
      timeoutMs: 240000,
    })
    // The draft preview panel mounts with the display snapshot.
    expect(wrapper.find('#detail-preview-edit-form').exists()).toBe(true)
    expect(wrapper.find('.preview-mode-note').text()).toContain('订阅草案（未保存）')
    expect(wrapper.find('#single-review-save-button').exists()).toBe(true)
    expect(wrapper.find('#preview-apply-button').classes()).toContain('secondary-button')
    expect(wrapper.find('#single-review-save-button').classes()).toContain('primary-button')
    expect(wrapper.find('.review-note').text()).toContain('保存修改仅更新当前服务端草案')
    expect(wrapper.find('.review-confirmation-boundary').text()).toContain('仅保存本地方案、我的追番再次确认外部提交')
    expect(wrapper.find('#detail-preview-edit-form').element.compareDocumentPosition(wrapper.find('#single-review-save-button').element) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
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

  it('keeps batch input, capacity feedback, and search in one operation area', async () => {
    apiPost.mockResolvedValue({ batch_id: 'batch-capacity', raw_input: '甲', items: [] } as never)
    const { wrapper } = await mountWorkbench()
    await wrapper.find('#anime-mode-batch').trigger('click')
    await nextTick()

    expect(wrapper.findAll('#batch-raw-input')).toHaveLength(1)
    expect(wrapper.findAll('#batch-parse-form')).toHaveLength(1)
    expect(wrapper.find('#batch-input-count').text()).toContain('当前 0 部')
    expect(wrapper.find('#batch-parse-submit').attributes('disabled')).toBeDefined()

    const rawInput = Array.from({ length: 37 }, (_, index) => `番剧${index}`).join('\n')
    await wrapper.find('#batch-raw-input').setValue(rawInput)
    expect(wrapper.find('#batch-input-count').text()).toContain('当前 37 部')
    expect(wrapper.find('#batch-parse-submit').attributes('disabled')).toBeDefined()

    await wrapper.find('#batch-raw-input').setValue('甲\n乙')
    expect(wrapper.find('#batch-parse-submit').attributes('disabled')).toBeUndefined()
    await wrapper.find('#batch-parse-submit').trigger('click')
    await flushPromises()
    expect(apiPost).toHaveBeenCalledWith('/api/v1/batches/parse', expect.objectContaining({
      body: expect.objectContaining({ raw_input: '甲\n乙' }),
    }))
  })

  it('#159: batch first screen mirrors the single task structure and centres the same anchors', async () => {
    const { wrapper } = await mountWorkbench()
    const order = (selector: string): string[] =>
      Array.from(wrapper.find(selector).element.children).map((child) => child.id || child.className)
    const singleOrder = order('.single-home-hero')
    expect(singleOrder[0]).toContain('single-home-intro')
    expect(singleOrder[1]).toContain('anime-mode-switch')
    expect(singleOrder).toContain('mikan-candidate-search-form')
    expect(singleOrder[singleOrder.length - 1]).toContain('journey-steps')

    await wrapper.find('#anime-mode-batch').trigger('click')
    await nextTick()
    const batch = wrapper.find('.batch-search-screen')
    expect(batch.exists()).toBe(true)
    // 同一套标题层级：标题 + 说明 + 模式切换；输入形态允许不同。
    expect(batch.find('.batch-search-intro .workbench-title').text()).toBe('添加番剧')
    expect(batch.find('.batch-search-intro .batch-search-subtitle').text()).toContain('粘贴番剧名称')
    const batchOrder = order('.batch-search-screen')
    expect(batchOrder[0]).toContain('batch-search-intro')
    expect(batchOrder[1]).toContain('anime-mode-switch')
    expect(batchOrder[2]).toBe('batch-parse-form')
    expect(batchOrder[batchOrder.length - 1]).toContain('journey-steps')
    expect(batch.find('.batch-search-steps .is-current').text()).toBe('输入名称')
    // 空闲态不套用搜索态样式；搜索进行中才回到文档流顶部。
    expect(batch.classes()).not.toContain('is-searching')
  })

  it('#159: batch search re-enters the flow at the top while a search is in flight', async () => {
    const releaseParse = deferred<unknown>()
    apiPost.mockImplementationOnce(() => releaseParse.promise as never)
    const { wrapper } = await mountWorkbench()
    await wrapper.find('#anime-mode-batch').trigger('click')
    await wrapper.find('#batch-raw-input').setValue('甲')
    await wrapper.find('#batch-parse-submit').trigger('click')
    await nextTick()

    expect(wrapper.find('.batch-search-screen').classes()).toContain('is-searching')
    expect(wrapper.find('#batch-search-progress').exists()).toBe(true)

    releaseParse.resolve({ batch_id: 'batch-flow', raw_input: '甲', items: [], summary: {} })
    await flushPromises()
    await nextTick()
    // 零条目仍留在搜索首屏：任务区保持顶部对齐（与单番「已搜索但无候选」同规则）。
    expect(wrapper.find('#batch-empty-result').exists()).toBe(true)
    expect(wrapper.find('.batch-search-screen').classes()).toContain('is-searching')
  })

  it('restores a finished batch result when the mode comes back to batch', async () => {
    // #145 B：请求完成后才切回 batch（其他合法入口）时，必须明确恢复已完成的结果，
    // 而不是依赖偶然的焦点滚动；搜索期间切换控件本身是禁用的。
    const releaseParse = deferred<unknown>()
    apiPost.mockImplementationOnce(() => releaseParse.promise as never)
    const { wrapper } = await mountWorkbench()
    await wrapper.find('#anime-mode-batch').trigger('click')
    await wrapper.find('#batch-raw-input').setValue('甲')
    await wrapper.find('#batch-parse-submit').trigger('click')
    await nextTick()

    // 搜索进行中：两个方向的切换控件都被禁用。
    expect((wrapper.find('#anime-mode-single').element as HTMLButtonElement).disabled).toBe(true)
    expect((wrapper.find('#anime-mode-batch').element as HTMLButtonElement).disabled).toBe(true)

    // 模拟「另一个合法入口」在请求完成前切到单番：这不改变已完成结果的归属。
    wrapper.findComponent(AnimeModeSwitch).vm.$emit('update:modelValue', 'single')
    await nextTick()
    expect(wrapper.find('#mikan-candidate-query').exists()).toBe(true)

    releaseParse.resolve({
      batch_id: 'batch-restore',
      raw_input: '甲',
      items: [batchParseItem('item-1', '甲')],
    })
    await flushPromises()
    await nextTick()
    // 不在 batch 模式时不抢占屏幕：工作台屏保持隐藏。
    expect(wrapper.find('.batch-draft-card').exists()).toBe(true)
    expect((wrapper.find('.batch-workbench-screen').element as HTMLElement).style.display).toBe('none')
    expect(wrapper.find('#batch-empty-result').exists()).toBe(false)

    // 切回 batch：已完成结果必须被明确恢复。
    wrapper.findComponent(AnimeModeSwitch).vm.$emit('update:modelValue', 'batch')
    await flushPromises()
    await nextTick()
    expect((wrapper.find('.batch-workbench-screen').element as HTMLElement).style.display).not.toBe('none')
    expect(wrapper.find('.batch-draft-card').exists()).toBe(true)
    expect(wrapper.find('#batch-raw-input').element).toHaveProperty('value', '甲')
  })

  it('shows an honest empty-result notice instead of entering an empty workbench', async () => {
    // #145 F：HTTP 200 但 items=[] → 留在搜索首屏就地说明，不是 MiKan 故障。
    apiPost.mockResolvedValueOnce({ batch_id: 'batch-empty', raw_input: '甲', items: [] } as never)
    const { wrapper } = await mountWorkbench()
    await wrapper.find('#anime-mode-batch').trigger('click')
    await wrapper.find('#batch-raw-input').setValue('甲')
    await wrapper.find('#batch-parse-submit').trigger('click')
    await flushPromises()
    await nextTick()

    expect(wrapper.find('#batch-empty-result').text()).toContain('服务端没有返回任何条目')
    expect(wrapper.find('#batch-empty-result').text()).not.toContain('故障')
    expect((wrapper.find('.batch-workbench-screen').element as HTMLElement).style.display).toBe('none')
    expect(wrapper.find('.batch-draft-card').exists()).toBe(false)
  })

  it('still enters the workbench when every item is EMPTY or FAILED', async () => {
    apiPost.mockResolvedValueOnce({
      batch_id: 'batch-all-failed',
      raw_input: '甲\n乙',
      items: [
        batchParseItem('item-1', '甲', 'EMPTY'),
        batchParseItem('item-2', '乙', 'FAILED'),
      ],
    } as never)
    const { wrapper } = await mountWorkbench()
    await wrapper.find('#anime-mode-batch').trigger('click')
    await wrapper.find('#batch-raw-input').setValue('甲\n乙')
    await wrapper.find('#batch-parse-submit').trigger('click')
    await flushPromises()
    await nextTick()

    expect(wrapper.find('.batch-draft-card').exists()).toBe(true)
    expect((wrapper.find('.batch-workbench-screen').element as HTMLElement).style.display).not.toBe('none')
    expect(wrapper.find('#batch-empty-result').exists()).toBe(false)
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
          request_id: 'req-confirmed', status: 'ACCEPTED', next_action: 'OPEN_TRACKING',
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

  it('rejects the retired CONFIRMED/TRACKING handoff enums with safe notification and alert', async () => {
    apiPost
      .mockResolvedValueOnce(candidateResult())
      .mockResolvedValueOnce(createDraftResult())
      .mockResolvedValueOnce({
        outcome: 'CONFIRMED', request: { request_id: 'req-old' },
        handoff: {
          request_id: 'req-old', status: 'CONFIRMED', next_action: 'TRACKING',
          tracking_id: 'tracking-old', tracking_status: 'PENDING_SUBMIT', tracking_ready: true, safe_message: null,
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
    const { useNotificationStore } = await import('@/app/stores/notification')
    expect(router.currentRoute.value.name).not.toBe('tracking')
    expect(useNotificationStore().current?.title).toBe('保存并确认失败')
    expect(wrapper.find('#single-review-save-error.status-alert').exists()).toBe(true)
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
    expect(notification.current?.message).toBe('从 MiKan 合集生成订阅草案失败：MiKan 页面格式异常，请稍后重试。')
    expect(wrapper.findAll('.candidate-card')).toHaveLength(1)
    expect(wrapper.find('#detail-preview-edit-form').exists()).toBe(false)
  })
})

describe('WorkbenchView draft-modify save-confirm reliability (US-341)', () => {
  beforeEach(() => {
    localStorage.clear()
    apiPost.mockReset()
    apiGet.mockReset()
  })

  const saveButton = (wrapper: VueWrapper) => wrapper.find('#single-review-save-button')
  const saveNote = (wrapper: VueWrapper) => wrapper.find('#single-review-save-blockers')

  /** Both the disabled state and the in-place reason must come from one source. */
  function expectConsistentSaveState(wrapper: VueWrapper, expected: 'available' | 'blocked'): string {
    const disabled = saveButton(wrapper).attributes('disabled') !== undefined
    const note = saveNote(wrapper).text()
    // Assert the reason first so a mismatch reports the contradictory text.
    if (expected === 'available') expect(note).toContain('保存并确认可用')
    else expect(note).toContain('保存并确认暂不可用')
    expect({ disabled, note }).toMatchObject({ disabled: expected === 'blocked' })
    return note
  }

  async function openDraftReview(wrapper: VueWrapper): Promise<void> {
    await wrapper.find('#mikan-candidate-query').setValue('芙莉莲')
    await wrapper.find('#mikan-candidate-search-submit').trigger('click')
    await flushPromises()
    await wrapper.find('.candidate-select').trigger('click')
    await flushPromises()
  }

  /** The server echo after applying `must_not_contain=V2` at revision 2. */
  function modifiedSnapshot() {
    return previewSnapshot({
      confirmable_config: {
        ...previewSnapshot().confirmable_config,
        filter_rule: { must_contain: '', must_not_contain: 'V2', use_regex: false, case_sensitive: false },
      },
    })
  }

  function saveConfirmResult() {
    return {
      outcome: 'CONFIRMED',
      request: { request_id: 'req-confirmed' },
      handoff: {
        request_id: 'req-confirmed', status: 'ACCEPTED', next_action: 'OPEN_TRACKING',
        tracking_id: 'tracking-confirmed', tracking_status: 'PENDING_SUBMIT',
        tracking_ready: true, safe_message: null,
      },
    }
  }

  it('restores the button and reason together after a held preview-modify returns revision=2', async () => {
    let releaseModify!: (value: unknown) => void
    const modifyPending = new Promise((resolve) => { releaseModify = resolve })
    apiPost
      .mockResolvedValueOnce(candidateResult())
      .mockResolvedValueOnce(createDraftResult())
      // Held preview-modify: the route is stored, never slept in.
      .mockReturnValueOnce(modifyPending as never)
    const { wrapper } = await mountWorkbench()
    await openDraftReview(wrapper)

    expectConsistentSaveState(wrapper, 'available')

    // 1) A pending form edit blocks the save with its own reason.
    await wrapper.find('#preview-must-not-contain').setValue('V2')
    await nextTick()
    expect(expectConsistentSaveState(wrapper, 'blocked')).toContain('有尚未应用的编辑')

    // 2) The in-flight recompute blocks it, still consistently.
    await wrapper.find('#preview-apply-button').trigger('click')
    await nextTick()
    const inFlightNote = expectConsistentSaveState(wrapper, 'blocked')
    expect(inFlightNote).toContain('正在重新计算订阅方案')

    // 3) The server returns the same draft capability at revision 2.
    releaseModify({ request: modifiedSnapshot(), summary: {}, draft_id: 'opaque-draft-token', draft_revision: 2 })
    await flushPromises()

    expectConsistentSaveState(wrapper, 'available')
    expect(saveNote(wrapper).text()).not.toContain('正在重新计算订阅方案')
    expect(saveNote(wrapper).text()).not.toContain('有尚未应用的编辑')

    apiPost.mockResolvedValueOnce(saveConfirmResult() as never)
    await saveButton(wrapper).trigger('click')
    await flushPromises()

    const saveCalls = apiPost.mock.calls.filter(([path]) => path === '/api/v1/requests/save-confirm')
    expect(saveCalls).toHaveLength(1)
    expect(saveCalls[0]![1]?.body).toMatchObject({
      draft_id: 'opaque-draft-token',
      base_revision: 2,
      storage_dir: null,
    })
    expect(saveCalls[0]![1]?.body).toHaveProperty('idempotency_key')
    expect(saveCalls[0]![1]?.body).not.toHaveProperty('request')
    expect(saveCalls[0]![1]?.body).not.toHaveProperty('summary')
  })

  it('blocks the save with a reason when a successful modify leaves no effective resource', async () => {
    apiPost
      .mockResolvedValueOnce(candidateResult())
      .mockResolvedValueOnce(createDraftResult())
      .mockResolvedValueOnce({
        request: previewSnapshot({
          source_info: {
            matched_bangumi: previewSnapshot().source_info.matched_bangumi,
            rss_sources: [],
          },
          confirmable_config: {
            ...previewSnapshot().confirmable_config,
            effective_seed_names: [],
          },
        }),
        summary: {},
        draft_id: 'opaque-draft-token',
        draft_revision: 2,
      })
    const { wrapper } = await mountWorkbench()
    await openDraftReview(wrapper)

    await wrapper.find('#preview-must-not-contain').setValue('V2')
    await wrapper.find('#preview-apply-button').trigger('click')
    await flushPromises()

    const note = expectConsistentSaveState(wrapper, 'blocked')
    expect(note).toContain('没有有效资源')
  })

  it('keeps the button and reason aligned on a retryable modify failure and its recovery', async () => {
    apiPost
      .mockResolvedValueOnce(candidateResult())
      .mockResolvedValueOnce(createDraftResult())
      .mockRejectedValueOnce({ type: 'network_error', message: '原始网络错误' })
      .mockResolvedValueOnce({ request: modifiedSnapshot(), summary: {}, draft_id: 'opaque-draft-token', draft_revision: 2 })
    const { wrapper } = await mountWorkbench()
    await openDraftReview(wrapper)

    await wrapper.find('#preview-must-not-contain').setValue('V2')
    await wrapper.find('#preview-apply-button').trigger('click')
    await flushPromises()

    const failedNote = expectConsistentSaveState(wrapper, 'blocked')
    expect(failedNote).toContain('存在未恢复的字段修改失败')
    expect(wrapper.text()).not.toContain('原始网络错误')

    await wrapper.find('#preview-retry-button').trigger('click')
    await flushPromises()
    expectConsistentSaveState(wrapper, 'available')
  })
})

describe('WorkbenchView direct fallback (US-204)', () => {
  beforeEach(() => {
    localStorage.clear()
    apiPost.mockReset()
  })

  /**
   * F4/US-345: the direct-collection form is a secondary rescue entry that only
   * exists after a started search produced no candidates, so every direct-path
   * test reaches that state first.
   */
  async function startEmptySearch(wrapper: VueWrapper, query = '芙莉莲'): Promise<void> {
    apiPost.mockResolvedValueOnce(candidateResult({ candidates: [] }))
    await wrapper.find('#mikan-candidate-query').setValue(query)
    await wrapper.find('#mikan-candidate-search-submit').trigger('click')
    await flushPromises()
  }

  /** The long-running create requests, excluding the candidate search. */
  function createCalls(): unknown[] {
    return apiPost.mock.calls.filter(([url]) => url === '/api/v1/requests')
  }

  it('reveals the fallback form only when the checkbox is checked', async () => {
    const { wrapper } = await mountWorkbench()

    expect(wrapper.find('#mikan-fallback-enabled').exists()).toBe(false)
    await startEmptySearch(wrapper)
    expect(wrapper.find('#mikan-fallback-enabled').exists()).toBe(true)
    expect(wrapper.find('#mikan-fallback-form').exists()).toBe(false)
    await wrapper.find('#mikan-fallback-enabled').setValue(true)
    await nextTick()
    expect(wrapper.find('#mikan-fallback-form').exists()).toBe(true)
  })

  it('validates the fallback value before calling the API', async () => {
    const { wrapper } = await mountWorkbench()
    await startEmptySearch(wrapper)
    await wrapper.find('#mikan-fallback-enabled').setValue(true)
    await nextTick()

    await wrapper.find('#mikan-fallback-generate').trigger('click')
    await nextTick()

    expect(createCalls()).toHaveLength(0)
    expect(wrapper.find('#mikan-fallback-error').text()).toContain('生成前必须填写 MiKan 合集 URL 或 ID')

    await wrapper.find('#mikan-fallback-bangumi').setValue('not a url or id')
    await wrapper.find('#mikan-fallback-generate').trigger('click')
    await nextTick()
    expect(wrapper.find('#mikan-fallback-error').text()).toContain('必须是数字 ID 或 HTTP(S) URL')
  })

  it('generates a draft from a bare ID and leaves no direct-collection input behind', async () => {
    apiPost.mockResolvedValue(createDraftResult())
    const { wrapper } = await mountWorkbench()

    await startEmptySearch(wrapper)
    await wrapper.find('#mikan-fallback-enabled').setValue(true)
    await nextTick()
    await wrapper.find('#mikan-fallback-bangumi').setValue('2353')
    await wrapper.find('#mikan-fallback-generate').trigger('click')
    await flushPromises()

    expect(apiPost).toHaveBeenCalledWith('/api/v1/requests', {
      body: {
        title: '芙莉莲',
        mikan_bangumi: '2353',
        storage_dir: null,
      },
      timeoutMs: 240000,
    })
    expect(wrapper.find('#detail-preview-edit-form').exists()).toBe(true)
    // The draft replaces the whole search step, so neither the rescue entry nor
    // its input can survive into the review step.
    expect(wrapper.find('#mikan-candidate-search-result').exists()).toBe(false)
    expect(wrapper.find('#mikan-fallback-bangumi').exists()).toBe(false)
  })

  it('keeps the direct-collection input when generation fails', async () => {
    apiPost.mockRejectedValueOnce({ type: 'mikan_http_failed', message: 'MiKan HTTP 请求失败' })
    const { wrapper } = await mountWorkbench()

    await startEmptySearch(wrapper)
    await wrapper.find('#mikan-fallback-enabled').setValue(true)
    await nextTick()
    await wrapper.find('#mikan-fallback-bangumi').setValue('2353')
    await wrapper.find('#mikan-fallback-generate').trigger('click')
    await flushPromises()

    expect(wrapper.find('#detail-preview-edit-form').exists()).toBe(false)
    expect((wrapper.find('#mikan-fallback-bangumi').element as HTMLInputElement).value).toBe('2353')
    expect(createCalls()).toHaveLength(1)
  })

  it('prevents duplicate direct generation while the long request is pending', async () => {
    let resolveRequest!: (value: unknown) => void
    const pending = new Promise((resolve) => { resolveRequest = resolve })
    apiPost.mockReturnValue(pending as never)
    const { wrapper } = await mountWorkbench()

    await startEmptySearch(wrapper)
    await wrapper.find('#mikan-fallback-enabled').setValue(true)
    await nextTick()
    await wrapper.find('#mikan-fallback-bangumi').setValue('2353')
    const submit = wrapper.find('#mikan-fallback-generate')
    void submit.trigger('click')
    await nextTick()
    await submit.trigger('click')

    expect(createCalls()).toHaveLength(1)
    expect(submit.attributes('disabled')).toBeDefined()
    resolveRequest({ draft_id: 'opaque', request: {} })
    await flushPromises()
  })

  it('shares the direct-generation busy lock with candidate search', async () => {
    let resolveRequest!: (value: CreateResult) => void
    const pending = new Promise<CreateResult>((resolve) => { resolveRequest = resolve })
    apiPost.mockImplementation(() => pending)
    const { wrapper } = await mountWorkbench()

    await startEmptySearch(wrapper)
    await wrapper.find('#mikan-fallback-enabled').setValue(true)
    await nextTick()
    await wrapper.find('#mikan-fallback-bangumi').setValue('2353')
    void wrapper.find('#mikan-fallback-generate').trigger('click')
    await nextTick()
    await wrapper.find('#mikan-candidate-search-submit').trigger('click')

    expect(createCalls()).toHaveLength(1)
    expect(wrapper.find('#mikan-candidate-search-submit').attributes('disabled')).toBeDefined()
    resolveRequest(createDraftResult())
    await flushPromises()
  })
})

// WP-41-B / US-343: an explicit, in-place, recoverable loading state beside the
// clicked candidate. Only one candidate generation runs at a time; the other
// candidates are temporarily unavailable but never labelled as loading.
describe('WorkbenchView candidate loading feedback (US-343)', () => {
  beforeEach(() => {
    localStorage.clear()
    apiPost.mockReset()
  })

  function twoCandidates() {
    return candidateResult({
      candidates: [
        candidate(),
        candidate({ bangumi_id: '3072', title: '葬送的芙莉莲 第二季' }),
      ],
    })
  }

  it('labels only the clicked candidate while its draft request is in flight', async () => {
    let resolveRequest!: (value: CreateResult) => void
    const pending = new Promise<CreateResult>((resolve) => { resolveRequest = resolve })
    apiPost.mockResolvedValueOnce(twoCandidates())
    apiPost.mockImplementationOnce(() => pending)
    const { wrapper } = await mountWorkbench()

    await wrapper.find('#mikan-candidate-query').setValue('芙莉莲')
    await wrapper.find('#mikan-candidate-search-submit').trigger('click')
    await flushPromises()

    const cards = wrapper.findAll('.candidate-card')
    expect(cards).toHaveLength(2)
    await cards[0]!.find('.candidate-select').trigger('click')
    await nextTick()

    // The clicked candidate carries the in-place loading state.
    const loadingButton = cards[0]!.find('.candidate-select')
    expect(loadingButton.attributes('aria-busy')).toBe('true')
    expect(loadingButton.text()).toContain('正在生成草案')
    expect((loadingButton.element as HTMLButtonElement).disabled).toBe(true)
    expect(cards[0]!.text()).toContain('正在生成订阅草案')

    // A second generation cannot start, but the other candidate is only
    // disabled — it is never marked as loading.
    const idleButton = cards[1]!.find('.candidate-select')
    expect((idleButton.element as HTMLButtonElement).disabled).toBe(true)
    expect(idleButton.attributes('aria-busy')).toBeUndefined()
    expect(idleButton.text()).toContain('选择此合集')
    expect(cards[1]!.text()).not.toContain('正在生成草案')
    expect(apiPost).toHaveBeenCalledTimes(2)

    resolveRequest(createDraftResult())
    await flushPromises()

    // Success is atomic: the candidate step is replaced by the draft review.
    expect(wrapper.find('#detail-preview-edit-form').exists()).toBe(true)
    expect(wrapper.find('.candidate-card').exists()).toBe(false)
  })

  it('keeps a sanitized failure beside the clicked candidate and retries in place', async () => {
    apiPost.mockResolvedValueOnce(twoCandidates())
    apiPost.mockRejectedValueOnce({ type: 'mikan_parse_failed', message: 'MiKan 番剧页解析失败' })
    apiPost.mockResolvedValueOnce(createDraftResult())
    const { wrapper } = await mountWorkbench()

    await wrapper.find('#mikan-candidate-query').setValue('芙莉莲')
    await wrapper.find('#mikan-candidate-search-submit').trigger('click')
    await flushPromises()

    const cards = wrapper.findAll('.candidate-card')
    await cards[0]!.find('.candidate-select').trigger('click')
    await flushPromises()

    // The failure stays in that candidate's card and never shows raw server text.
    expect(cards[0]!.text()).toContain('从 MiKan 合集生成订阅草案失败：MiKan 页面格式异常，请稍后重试。')
    expect(cards[0]!.text()).not.toContain('MiKan 番剧页解析失败')
    expect(cards[0]!.find('[role="alert"]').exists()).toBe(true)
    expect(cards[1]!.text()).not.toContain('生成订阅草案失败')
    // The candidate step is preserved: the list is still there and no draft exists.
    expect(wrapper.findAll('.candidate-card')).toHaveLength(2)
    expect(wrapper.find('#detail-preview-edit-form').exists()).toBe(false)

    const { useNotificationStore } = await import('@/app/stores/notification')
    expect(useNotificationStore().current?.title).toBe('生成失败')

    // The same candidate can retry in place and then succeed.
    const retry = cards[0]!.find('.candidate-select')
    expect(retry.attributes('aria-busy')).toBeUndefined()
    expect(retry.text()).toContain('重试生成草案')
    await retry.trigger('click')
    await flushPromises()

    expect(wrapper.find('#detail-preview-edit-form').exists()).toBe(true)
    const generateCalls = apiPost.mock.calls.filter(([path]) => path === '/api/v1/requests')
    expect(generateCalls).toHaveLength(2)
  })

  it('clears the candidate failure when the search results are replaced', async () => {
    apiPost.mockResolvedValueOnce(candidateResult())
    apiPost.mockRejectedValueOnce({ type: 'network_error', message: '原始网络错误' })
    apiPost.mockResolvedValueOnce(candidateResult())
    const { wrapper } = await mountWorkbench()

    await wrapper.find('#mikan-candidate-query').setValue('芙莉莲')
    await wrapper.find('#mikan-candidate-search-submit').trigger('click')
    await flushPromises()
    await wrapper.find('.candidate-select').trigger('click')
    await flushPromises()
    expect(wrapper.find('.candidate-card').text()).toContain('生成订阅草案失败')

    await wrapper.find('#mikan-back-to-search').trigger('click')
    await wrapper.find('#mikan-candidate-query').setValue('无职转生')
    await wrapper.find('#mikan-candidate-search-form').trigger('submit')
    await flushPromises()
    // Issue 110：已有候选时重新搜索先确认，再替换结果并清掉旧失败。
    await wrapper.find('.confirm-dialog .primary-button').trigger('click')
    await flushPromises()

    expect(wrapper.findAll('.candidate-card')).toHaveLength(1)
    expect(wrapper.find('.candidate-card').text()).not.toContain('生成订阅草案失败')
    expect(wrapper.find('.candidate-card').text()).not.toContain('原始网络错误')
  })
})
