import { flushPromises, mount } from '@vue/test-utils'
import { createRouter, createMemoryHistory } from 'vue-router'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { api } from '@/api/client'
import { clearReuseHandoff, consumeReuseHandoff } from '@/features/requests/reuseHandoff'
import TrackingInspector from './TrackingInspector.vue'
import { createCheckSession } from './trackingProjection'
import type { CapabilityResult, TrackingCheckSession, TrackingManagementScope } from './trackingProjection'
import type {
  TrackingManagementActionCode,
  TrackingWriteSession,
  TrackingWriteSessionSet,
} from './useTrackingWriteSession'

/** The fixed manual-conclusion notice, pinned here as characterization. */
const RECOVERY_NEEDS_MANUAL_NOTICE =
  '需要人工核验：请先在 Auto Bangumi 中独立核对该追番的实际状态，再选择“标记为成功”或“标记为失败”；本页不会代替你判断，也不会自动提交。'

/** One page-level write session of any family, as the page hands it over. */
function sessionFixture(overrides: Partial<TrackingWriteSession> = {}): TrackingWriteSession {
  return {
    trackingId: 'tracking-1', operation: 'SUBMIT', family: 'SUBMIT', targetScope: null,
    state: 'ACTIVE', message: '提交成功：已在 Auto Bangumi 创建外部订阅。', issues: [],
    failureCategory: null, diagnostics: { httpStatus: null, messageZh: null, messageEn: null },
    needsManual: false, manualNotice: null, keepsIntent: false,
    ...overrides,
  }
}

/** The page's single session entry, with only the families a test provides. */
function sessions(parts: Partial<TrackingWriteSessionSet> = {}): TrackingWriteSessionSet {
  return { submit: null, recovery: null, management: null, ...parts }
}

function managementSessionFixture(options: {
  operation: TrackingManagementActionCode
  targetScope: TrackingManagementScope
  state: TrackingWriteSession['state']
  message: string
  needsManual?: boolean
  trackingId?: string
}): TrackingWriteSession {
  return sessionFixture({
    ...(options.trackingId === undefined ? {} : { trackingId: options.trackingId }),
    operation: options.operation,
    family: 'MANAGEMENT',
    targetScope: options.targetScope,
    state: options.state,
    message: options.message,
    needsManual: options.needsManual ?? false,
    manualNotice: options.needsManual
      ? '需要人工核验：请先在 Auto Bangumi 中独立核对该追番的实际状态，再决定是否重新发起修改；本页不会代替你判断，也不会自动重试。'
      : null,
    keepsIntent: options.state === 'UNKNOWN',
  })
}

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


function inspectorRouter() {
  return createRouter({ history: createMemoryHistory('/app/'), routes: [
    { path: '/tracking', component: TrackingInspector }, { path: '/plans', component: { template: '<div />' } },
  ] })
}

async function mountInspector(trackingId = 'tracking-1', props: Record<string, unknown> = {}) {
  const wrapper = mount(TrackingInspector, {
    props: { trackingId, ...props }, global: { plugins: [inspectorRouter()] },
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
    expect(wrapper.text()).toContain('未开发')
    // Issue #93: the retired 追番方案 page is gone; reuse travels through the
    // add journey instead of a link back to the old page.
    expect(wrapper.find('.tracking-plan-link').exists()).toBe(false)
    expect(wrapper.text()).not.toContain('request-1')
    expect(wrapper.text()).toContain('第一集.mkv')
  })

  it('states the missing local plan instead of linking to a retired page', async () => {
    apiGet.mockResolvedValue(detail({ status: 'EXTERNAL_ONLY', request_id: null }) as never)
    const wrapper = await mountInspector()
    expect(wrapper.find('.tracking-plan-link').exists()).toBe(false)
    expect(wrapper.text()).toContain('没有关联的本地追番方案')
  })

  it('renders the persisted same-origin cover in the tracking detail', async () => {
    const cover = `/api/v1/mikan/posters/${'c'.repeat(64)}`
    apiGet.mockResolvedValue(detail({ poster_path: cover }) as never)

    const wrapper = await mountInspector()

    const poster = wrapper.find('.tracking-inspector-identity .tracking-poster')
    expect(poster.attributes('data-poster-state')).toBe('ready')
    expect(poster.find('img').attributes('src')).toBe(cover)
    expect(wrapper.html()).not.toContain('mikan.example')
  })

  it('keeps a stable placeholder when the detail has no cover', async () => {
    apiGet.mockResolvedValue(detail() as never)

    const wrapper = await mountInspector()

    const poster = wrapper.find('.tracking-inspector-identity .tracking-poster')
    expect(poster.attributes('data-poster-state')).toBe('placeholder')
    expect(poster.find('img').exists()).toBe(false)
  })

  it('names the panel 追番详情 and folds activity/technical detail by default', async () => {
    apiGet.mockResolvedValue(detail({
      current_operation: { operation_id: 'op-1', state: 'UNKNOWN', operation: 'SUBMIT', attempt: 1 },
      audit_events: [{ action: 'SUBMIT', safe_message: '已提交', created_at: '2026-09-13T00:00:00Z' }],
      external_mapping: { match_reason: '标题', enabled: true, external_deleted: false },
    }) as never)

    const wrapper = await mountInspector()

    expect(wrapper.find('#tracking-inspector-heading').text()).toBe('追番详情')
    const activity = wrapper.find('#tracking-activity-log')
    const diagnostics = wrapper.find('#tracking-tech-diagnostics')
    expect(activity.exists()).toBe(true)
    expect(diagnostics.exists()).toBe(true)
    // Collapsed by default: the user must opt in to operational detail.
    expect(activity.attributes('open')).toBeUndefined()
    expect(diagnostics.attributes('open')).toBeUndefined()
    expect(activity.find('summary').text()).toBe('操作记录')
    expect(diagnostics.find('summary').text()).toBe('技术诊断')

    // Everyday essentials stay directly visible.
    const summary = wrapper.find('.tracking-inspector-summary')
    expect(summary.text()).toContain('有效资源')
    expect(summary.text()).toContain('字幕组')
    expect(summary.text()).toContain('追番中')
  })

  it('keeps an unknown server status label without rebuilding the state machine', async () => {
    apiGet.mockResolvedValue(detail({
      status: 'UNTRUSTED' as never,
      status_label: '未知状态',
      status_group: 'UNTRUSTED' as never,
    }) as never)

    const wrapper = await mountInspector()

    // The page renders the server projection verbatim; it neither guesses a
    // familiar group nor offers actions for a state it does not understand.
    expect(wrapper.find('.tracking-inspector-summary').text()).toContain('未知状态')
    expect(wrapper.find('#tracking-submit').exists()).toBe(false)
    expect(wrapper.find('#tracking-revalidate').exists()).toBe(false)
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

function writeSession(overrides: Partial<TrackingWriteSession> = {}): TrackingWriteSession {
  return sessionFixture({ family: 'SUBMIT', operation: 'SUBMIT', ...overrides })
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
    props: { trackingId: 'tracking-1', connectionReady: true, capabilities: capabilities(), ...props },
    global: { plugins: [router] },
  })
  await flushPromises()
  return wrapper
}

describe('TrackingInspector explicit submission (US-310)', () => {
  beforeEach(() => { apiGet.mockReset(); apiPost.mockReset() })

  it('offers SUBMIT from the saved connection without requiring a probe', async () => {
    apiGet.mockResolvedValue(detail({ available_actions: [submitAction] }) as never)
    const wrapper = await mountInspector('tracking-1', { connectionReady: true })
    // Issue #86: the server projects the action and re-validates everything in
    // the submit request, so no settings-page probe gates the button.
    expect(wrapper.find('#tracking-submit').exists()).toBe(true)
    // 只要存在已保存连接就可用（探测结果不作为前端门槛）。
    expect(wrapper.find('#tracking-submit').attributes('disabled')).toBeUndefined()
    expect(wrapper.find('#tracking-submit-connection-required').exists()).toBe(false)
    expect(wrapper.find('#tracking-revalidate').exists()).toBe(false)
    expect(apiPost).not.toHaveBeenCalled()
  })

  it('keeps external writes visible but disabled with an in-place hint without a saved connection', async () => {
    const setEnabled = {
      code: 'SET_ENABLED', label: '停用外部订阅', style: 'SECONDARY',
      requires_confirmation: true, target_scopes: ['SUBSCRIPTION'],
    }
    const refreshRss = {
      code: 'REFRESH_RSS', label: '刷新关联 RSS', style: 'SECONDARY',
      requires_confirmation: false, target_scopes: ['ASSOCIATED_RSS'],
    }
    const deleteExternal = {
      code: 'DELETE_EXTERNAL', label: '删除外部订阅', style: 'DANGER',
      requires_confirmation: true, target_scopes: ['SUBSCRIPTION', 'ASSOCIATED_RSS'],
    }
    apiGet.mockResolvedValue(
      detail({ available_actions: [submitAction, setEnabled, refreshRss, deleteExternal] }) as never,
    )
    const wrapper = await mountInspector('tracking-1', {
      connectionReady: false,
      capabilities: capabilities(),
    })

    // Issue 116：缺少已保存连接时提交入口可见但禁用，并有就地下一步提示。
    expect(wrapper.find('#tracking-submit').exists()).toBe(true)
    expect(wrapper.find('#tracking-submit').attributes('disabled')).toBeDefined()
    const hint = wrapper.find('#tracking-submit-connection-required')
    expect(hint.exists()).toBe(true)
    expect(hint.text()).toContain('先在设置中连接 Auto Bangumi')

    // 外部管理操作同样禁用并提示。
    expect(wrapper.find('#tracking-set-enabled-submit').attributes('disabled')).toBeDefined()
    expect(wrapper.find('#tracking-refresh-rss-submit').attributes('disabled')).toBeDefined()
    expect(wrapper.find('#tracking-management-connection-required').exists()).toBe(true)
    expect(wrapper.find('#tracking-delete-external-submit').attributes('disabled')).toBeDefined()
    expect(wrapper.find('#tracking-delete-connection-required').exists()).toBe(true)
    expect(apiPost).not.toHaveBeenCalled()
  })

  it('enables external writes with a saved connection even when the probe reports no capability', async () => {
    apiGet.mockResolvedValue(detail({ available_actions: [submitAction] }) as never)
    const wrapper = await mountInspector('tracking-1', {
      connectionReady: true,
      capabilities: capabilities({ subscription_submit: 'UNSUPPORTED' }),
    })
    // Issue 116 AC2：已保存连接就够；最近探测失败不预先禁用，服务端请求内复核。
    expect(wrapper.find('#tracking-submit').attributes('disabled')).toBeUndefined()
    expect(wrapper.find('#tracking-submit-connection-required').exists()).toBe(false)
  })

  it('keeps SUBMIT available when the diagnostic probe reports no capability', async () => {
    const wrapper = await mountSubmittable(
      { capabilities: capabilities({ subscription_submit: 'UNSUPPORTED' }) },
    )
    expect(wrapper.find('#tracking-submit').exists()).toBe(true)
  })

  it('leaves the request to the page and emits the action with the latest revision', async () => {
    const wrapper = await mountSubmittable()
    await wrapper.find('#tracking-submit').trigger('click')
    await flushPromises()
    // The inspector never performs the external write itself.
    expect(apiPost).not.toHaveBeenCalled()
    const payload = wrapper.emitted('write-requested')?.at(-1)?.[0] as {
      action: { code: string }; item: { revision: number; tracking_id: string }
    }
    expect(payload.action.code).toBe('SUBMIT')
    expect(payload.item.tracking_id).toBe('tracking-1')
    expect(payload.item.revision).toBe(2)
  })

  it('locks the conflicting actions of this item while the write is in flight', async () => {
    const wrapper = await mountSubmittable({ sessions: sessions({ submit: writeSession({ state: 'IN_FLIGHT' }) }) })
    expect(wrapper.find('#tracking-submit').attributes('disabled')).toBeDefined()
    expect(wrapper.find('#tracking-submit').attributes('aria-busy')).toBe('true')
    await wrapper.find('#tracking-submit').trigger('click')
    await flushPromises()
    expect(wrapper.emitted('write-requested')).toBeUndefined()
    expect(apiPost).not.toHaveBeenCalled()
  })

  it('renders only the fixed write copy and the documented §11.5 issues', async () => {
    const wrapper = await mountSubmittable({ sessions: sessions({ submit: writeSession({
      state: 'VERIFYING_EXTERNAL', message: '外部提交结果待确认，正在只读回查；请勿重复提交。',
      issues: [{ code: 'OPERATION_IN_PROGRESS', message: '本地方案尚未通过提交前复核。' }],
    }) }) })
    const result = wrapper.find('#tracking-submit-result')
    expect(result.text()).toContain('外部提交结果待确认')
    expect(result.text()).toContain('请勿重复提交')
    expect(result.find('.tracking-submit-issues').text()).toContain('本地方案尚未通过提交前复核')
    expect(wrapper.text()).not.toContain('VERIFYING_EXTERNAL')
  })

  it('never shows another item write result on this item', async () => {
    const wrapper = await mountSubmittable({ sessions: sessions({ submit: writeSession({ trackingId: 'tracking-2' }) }) })
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

const retryAction = {
  code: 'RETRY', label: '重试提交', style: 'SECONDARY',
  requires_confirmation: true, target_scopes: [],
}

const LIVE_SESSION = { connectionReady: true, capabilities: capabilities() }

describe('TrackingInspector explicit retry (US-311)', () => {
  beforeEach(() => { apiGet.mockReset(); apiPost.mockReset() })

  it('offers RETRY from the saved connection without requiring a probe', async () => {
    apiGet.mockResolvedValue(detail({ available_actions: [retryAction] }) as never)
    const wrapper = await mountInspector()
    // Issue #86: a definitely-failed record always offers its retry.
    expect(wrapper.find('#tracking-retry').exists()).toBe(true)
  })

  it('keeps RETRY available when the diagnostic probe reports no capability', async () => {
    apiGet.mockResolvedValue(detail({ available_actions: [retryAction] }) as never)
    const wrapper = await mountInspector('tracking-1', {
      ...LIVE_SESSION, capabilities: capabilities({ subscription_submit: 'UNSUPPORTED' }),
    })
    expect(wrapper.find('#tracking-retry').exists()).toBe(true)
  })

  it('emits the retry action with the latest revision and never writes itself', async () => {
    apiGet.mockResolvedValue(detail({
      revision: 7, available_actions: [revalidateAction, retryAction],
    }) as never)
    const wrapper = await mountInspector('tracking-1', LIVE_SESSION)
    // SUBMIT is not offered on this record, so the section shows retry only.
    expect(wrapper.find('#tracking-submit').exists()).toBe(false)
    expect(wrapper.text()).toContain('上次提交明确失败')
    await wrapper.find('#tracking-retry').trigger('click')
    await flushPromises()
    // The inspector never performs the external write itself.
    expect(apiPost).not.toHaveBeenCalled()
    const payload = wrapper.emitted('write-requested')?.at(-1)?.[0] as {
      action: { code: string }; item: { revision: number; tracking_id: string }
    }
    expect(payload.action.code).toBe('RETRY')
    expect(payload.item.revision).toBe(7)
    expect(payload.item.tracking_id).toBe('tracking-1')
  })

  it('locks retry while a write is in flight and renders the page result', async () => {
    apiGet.mockResolvedValue(detail({ available_actions: [revalidateAction, retryAction] }) as never)
    const wrapper = await mountInspector('tracking-1', {
      ...LIVE_SESSION,
      sessions: sessions({ submit: writeSession({
        operation: 'RETRY', state: 'SUBMIT_FAILED',
        message: '提交明确失败，尚未创建外部订阅；可在确认后显式重试。',
      }) }),
    })
    expect(wrapper.find('#tracking-retry').attributes('disabled')).toBeUndefined()
    expect(wrapper.find('#tracking-submit-result').text()).toContain('提交明确失败')

    await wrapper.setProps({ sessions: sessions({ submit: writeSession({ operation: 'RETRY', state: 'IN_FLIGHT' }) }) })
    await flushPromises()
    expect(wrapper.find('#tracking-retry').attributes('disabled')).toBeDefined()
    expect(wrapper.find('#tracking-retry').attributes('aria-busy')).toBe('true')
    await wrapper.find('#tracking-retry').trigger('click')
    await flushPromises()
    expect(wrapper.emitted('write-requested')).toBeUndefined()
  })

  it('never projects RETRY for an unknown action code', async () => {
    apiGet.mockResolvedValue(detail({
      available_actions: [{ ...retryAction, code: 'RETRY_AGAIN' }],
    }) as never)
    const wrapper = await mountInspector('tracking-1', LIVE_SESSION)
    expect(wrapper.find('#tracking-retry').exists()).toBe(false)
    expect(wrapper.text()).toContain('当前状态不可提交或重试外部订阅')
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

function recoverySessionFixture(overrides: Partial<TrackingWriteSession> = {}): TrackingWriteSession {
  return sessionFixture({
    family: 'RECOVERY',
    operation: 'RECOVER_AUTO',
    state: 'RECOVERY_REQUIRED',
    needsManual: true,
    manualNotice: RECOVERY_NEEDS_MANUAL_NOTICE,
    keepsIntent: true,
    message: '结果仍无法确认，保持恢复状态；未确认前不会自动提交。',
    ...overrides,
  })
}

async function mountRecoverable(
  props: Record<string, unknown> = {},
  detailOverrides: Record<string, unknown> = {},
) {
  apiGet.mockResolvedValue(detail({
    status: 'RECOVERY_REQUIRED', status_label: '需要恢复', available_actions: recoveryActions,
    ...detailOverrides,
  }) as never)
  return mountInspector('tracking-1', props)
}

describe('TrackingInspector unknown-result recovery (US-312)', () => {
  beforeEach(() => { apiGet.mockReset(); apiPost.mockReset() })

  it('projects only the server-computed local actions and needs no credential', async () => {
    const wrapper = await mountRecoverable()
    // AUTO/MARK are pure-local: no page session, no capability, no scope.
    expect(wrapper.find('#tracking-recover-auto').text()).toBe('自动恢复')
    expect(wrapper.find('#tracking-recover-succeeded').text()).toBe('标记为成功')
    expect(wrapper.find('#tracking-recover-failed').text()).toBe('标记为失败')
    // Read-only external verification is not offered without the live session.
    expect(wrapper.find('#tracking-recover-verify').exists()).toBe(false)
    expect(wrapper.text()).toContain('只读外部核验需要先在页面连接 Auto Bangumi')

    const failedClass = wrapper.find('#tracking-recover-failed').classes()
    expect(failedClass).toContain('danger-button')
    await wrapper.find('#tracking-recover-auto').trigger('click')
    await flushPromises()
    // The inspector never performs a recovery itself.
    expect(apiPost).not.toHaveBeenCalled()
    const payload = wrapper.emitted('recovery-requested')?.at(-1)?.[0] as {
      action: string; item: { revision: number; tracking_id: string }
    }
    expect(payload.action).toBe('RECOVER_AUTO')
    expect(payload.item.tracking_id).toBe('tracking-1')
    expect(payload.item.revision).toBe(2)
  })

  it('offers the read-only external verification only with a proven capability', async () => {
    const withSession = await mountRecoverable(LIVE_SESSION)
    expect(withSession.find('#tracking-recover-verify').text()).toBe('只读核验外部状态')
    await withSession.find('#tracking-recover-verify').trigger('click')
    await flushPromises()
    expect(withSession.emitted('recovery-requested')?.at(-1)?.[0]).toMatchObject({ action: 'VERIFY_EXTERNAL' })

    for (const degraded of [
      { credentialReady: true, capabilities: capabilities({ external_verify: 'UNSUPPORTED' }) },
      { credentialReady: true, capabilities: capabilities({ probe_status: 'PARTIAL' }) },
      { credentialReady: false, capabilities: capabilities() },
      {},
    ]) {
      apiGet.mockReset()
      const wrapper = await mountRecoverable(degraded)
      expect(wrapper.find('#tracking-recover-verify').exists()).toBe(false)
      // The local recovery actions stay available; only the external read is gone.
      expect(wrapper.find('#tracking-recover-auto').exists()).toBe(true)
      wrapper.unmount()
    }
  })

  it('never projects an unknown or non-recovery action as a recovery', async () => {
    const wrapper = await mountRecoverable({}, { available_actions: [
      { ...recoverAutoAction, code: 'RECOVER_LATER' },
      { ...recoverAutoAction, style: 'NOT_A_STYLE' },
      { code: 'SUBMIT', label: '提交追番', style: 'PRIMARY', requires_confirmation: true, target_scopes: [] },
    ] })
    expect(wrapper.find('.tracking-recovery').exists()).toBe(false)
    expect(wrapper.text()).not.toContain('RECOVER_LATER')
    expect(apiPost).not.toHaveBeenCalled()
  })

  it('renders the page recovery verdict and the manual-check notice, never the raw state', async () => {
    const wrapper = await mountRecoverable({ sessions: sessions({ recovery: recoverySessionFixture() }) })
    const result = wrapper.find('#tracking-recovery-result')
    expect(result.text()).toContain('结果仍无法确认')
    expect(result.find('#tracking-recovery-manual-notice').text()).toBe(RECOVERY_NEEDS_MANUAL_NOTICE)
    expect(result.text()).toContain('先在 Auto Bangumi 中独立核对')
    expect(wrapper.text()).not.toContain('RECOVERY_REQUIRED')
    expect(wrapper.text()).not.toContain('NEEDS_RECONFIRM')

    // A decided verdict never shows the manual-check requirement.
    await wrapper.setProps({ sessions: sessions({ recovery: recoverySessionFixture({ state: 'ACTIVE', needsManual: false, manualNotice: null, keepsIntent: false, message: '恢复完成：已确认该番在 Auto Bangumi 中存在外部订阅。' }) }) })
    await flushPromises()
    expect(wrapper.find('#tracking-recovery-result').text()).toContain('恢复完成')
    expect(wrapper.find('#tracking-recovery-manual-notice').exists()).toBe(false)
  })

  it('locks every recovery action while the page intent is busy and never emits', async () => {
    const busy = await mountRecoverable({ writeBusy: true })
    for (const id of ['#tracking-recover-auto', '#tracking-recover-succeeded', '#tracking-recover-failed']) {
      expect(busy.find(id).attributes('disabled')).toBeDefined()
      await busy.find(id).trigger('click')
    }
    await flushPromises()
    expect(busy.emitted('recovery-requested')).toBeUndefined()
    busy.unmount()

    // In flight for this item, and while its own write is running.
    for (const props of [
      { ...LIVE_SESSION, sessions: sessions({ recovery: recoverySessionFixture({ state: 'IN_FLIGHT', needsManual: false, manualNotice: null, keepsIntent: false }) }) },
      { ...LIVE_SESSION, sessions: sessions({ submit: writeSession({ state: 'IN_FLIGHT' }) }) },
    ]) {
      const wrapper = await mountRecoverable(props)
      expect(wrapper.find('#tracking-recover-auto').attributes('disabled')).toBeDefined()
      expect(wrapper.find('#tracking-recover-succeeded').attributes('disabled')).toBeDefined()
      // The read-only external check is locked by the same page intent.
      expect(wrapper.find('#tracking-recover-verify').attributes('disabled')).toBeDefined()
      await wrapper.find('#tracking-recover-auto').trigger('click')
      await flushPromises()
      expect(wrapper.emitted('recovery-requested')).toBeUndefined()
      wrapper.unmount()
    }
  })

  it('never shows another item recovery result on this item', async () => {
    const wrapper = await mountRecoverable({ sessions: sessions({ recovery: recoverySessionFixture({ trackingId: 'tracking-2' }) }) })
    expect(wrapper.find('#tracking-recovery-result').exists()).toBe(false)
  })
})

describe('TrackingInspector per-record external delete (US-315)', () => {
  beforeEach(() => { apiGet.mockReset(); apiPost.mockReset() })

  const deleteAction = {
    code: 'DELETE_EXTERNAL', label: '删除外部订阅', style: 'DANGER',
    requires_confirmation: true, target_scopes: ['SUBSCRIPTION', 'ASSOCIATED_RSS'],
  }

  it('offers the delete from the server projection alone', async () => {
    apiGet.mockResolvedValue(detail({ available_actions: [deleteAction] }) as never)

    // No probe and no live page session is required (issue #89).
    const wrapper = await mountInspector()
    expect(wrapper.find('#tracking-delete-external-submit').exists()).toBe(true)

    // A diagnostic "unsupported" probe never hides a projected delete either.
    const degraded = await mountInspector('tracking-1', {
      ...LIVE_SESSION, capabilities: capabilities({ subscription_delete: 'UNSUPPORTED' }),
    })
    expect(degraded.find('#tracking-delete-external-scope-SUBSCRIPTION').exists()).toBe(true)
    expect(degraded.find('#tracking-delete-external-scope-ASSOCIATED_RSS').exists()).toBe(true)

    // A record the server does not project the action for keeps it hidden.
    apiGet.mockResolvedValue(detail() as never)
    const unoffered = await mountInspector()
    expect(unoffered.find('#tracking-delete-external-submit').exists()).toBe(false)
  })

  it('never projects an unknown, out-of-family or scope-less delete', async () => {
    for (const action of [
      { ...deleteAction, code: 'DELETE_EVERYTHING' },
      { ...deleteAction, target_scopes: [] },
      { ...deleteAction, target_scopes: ['EVERYTHING'] },
      { ...deleteAction, style: 'MYSTERY' },
    ]) {
      apiGet.mockResolvedValue(detail({ available_actions: [action] }) as never)
      const wrapper = await mountInspector('tracking-1', LIVE_SESSION)
      expect(wrapper.find('#tracking-delete-external-submit').exists()).toBe(false)
      expect(wrapper.find('#tracking-delete-external-scope-SUBSCRIPTION').exists()).toBe(false)
      // The rejected value is never echoed back into the DOM either.
      expect(wrapper.text()).not.toContain('EVERYTHING')
      expect(wrapper.text()).not.toContain('MYSTERY')
      wrapper.unmount()
    }
  })

  it('emits the chosen scope with the latest revision and never posts itself', async () => {
    apiGet.mockResolvedValue(detail({
      revision: 6, available_actions: [deleteAction],
    }) as never)
    const wrapper = await mountInspector('tracking-1', LIVE_SESSION)
    // Nothing is pre-selected, so no request can be emitted by accident.
    await wrapper.find('#tracking-delete-external-submit').trigger('submit')
    expect(wrapper.emitted('management-requested')).toBeUndefined()

    await wrapper.find('#tracking-delete-external-scope-ASSOCIATED_RSS').setValue()
    await wrapper.find('#tracking-delete-external-submit').trigger('submit')
    const emitted = wrapper.emitted('management-requested') as unknown[][]
    expect(emitted).toHaveLength(1)
    expect(emitted[0]?.[0]).toMatchObject({
      action: deleteAction, targetScope: 'ASSOCIATED_RSS', patch: null,
    })
    expect((emitted[0]?.[0] as { item: { revision: number } }).item.revision).toBe(6)
    // The page owns the request: the inspector never sends anything itself.
    expect(apiPost).not.toHaveBeenCalled()
  })

  it('renders this item delete result in its own panel only', async () => {
    apiGet.mockResolvedValue(detail({ available_actions: [deleteAction] }) as never)
    const session = managementSessionFixture({
      operation: 'DELETE_EXTERNAL', targetScope: 'SUBSCRIPTION', state: 'SUCCEEDED',
      message: '外部删除已完成：Auto Bangumi 已删除该外部对象；MiGuOrca 本地订阅方案、追番记录、审计记录、下载任务和已下载媒体文件均保留。',
    })
    const wrapper = await mountInspector('tracking-1', { ...LIVE_SESSION, sessions: sessions({ management: session }) })
    const result = wrapper.find('#tracking-delete-external-result')
    expect(result.text()).toContain('外部删除已完成')
    expect(result.text()).toContain('本次目标：外部番剧订阅')
    expect(result.text()).not.toContain('SUCCEEDED')
    // The delete verdict never leaks into the enable/refresh panel.
    expect(wrapper.find('#tracking-management-result').exists()).toBe(false)

    const other = await mountInspector('tracking-1', {
      ...LIVE_SESSION,
      sessions: sessions({ management: managementSessionFixture({ operation: 'DELETE_EXTERNAL', targetScope: 'SUBSCRIPTION', state: 'SUCCEEDED', message: '外部删除已完成：Auto Bangumi 已删除该外部对象；MiGuOrca 本地订阅方案、追番记录、审计记录、下载任务和已下载媒体文件均保留。', trackingId: 'tracking-2' }) }),
    })
    expect(other.find('#tracking-delete-external-result').exists()).toBe(false)
  })
})

function requestSnapshot() {
  return {
    request: {
      request_id: 'request-1',
      status: 'ACCEPTED',
      input: { raw_title: '芙莉莲' },
      source_info: {
        matched_bangumi: { title: '葬送的芙莉莲', season: 1, aliases: [], mikan_url: null, match_score: 1 },
        rss_sources: [{
          subtitle_group: '喵萌奶茶屋', rss_url: null, source_type: 'rss',
          valid_seed_names: ['第一集.mkv'], excluded_seed_names: [],
        }],
      },
      confirmable_config: {
        selected_subtitle_group: '喵萌奶茶屋',
        selected_rss_url: null,
        filter_rule: { must_contain: '', must_not_contain: '', use_regex: false, case_sensitive: false },
        effective_seed_names: ['第一集.mkv'],
        expected_folder_name: '芙莉莲',
        warnings: [],
      },
      ab_submit_result: null,
      created_at: '2026-09-01T00:00:00Z',
      updated_at: '2026-09-01T00:00:00Z',
    },
  } as never
}

describe('TrackingInspector saved plan editing (issue #90)', () => {
  beforeEach(() => { apiGet.mockReset(); apiPost.mockReset() })

  it('edits a pending plan in place with the shared editor core', async () => {
    apiGet.mockImplementation(async (path: string) => (
      path === '/api/v1/requests/{request_id}'
        ? requestSnapshot()
        : detail({ status: 'PENDING_SUBMIT', status_label: '待提交' }) as never
    ))
    apiPost.mockResolvedValue({} as never)

    const wrapper = await mountInspector()

    const editButton = wrapper.find('#tracking-edit-plan')
    expect(editButton.exists()).toBe(true)
    expect(editButton.text()).toBe('修改追番方案')
    // The editor stays collapsed until the user asks for it.
    expect(wrapper.find('#tracking-plan-editor').exists()).toBe(false)

    await editButton.trigger('click')
    await flushPromises()

    expect(wrapper.find('#tracking-plan-editor').exists()).toBe(true)
    expect(apiGet).toHaveBeenCalledWith('/api/v1/requests/{request_id}', expect.objectContaining({
      path: { request_id: 'request-1' },
    }))
  })

  it('offers no plan editing for a record that is not pending', async () => {
    apiGet.mockResolvedValue(detail({ status: 'ACTIVE', status_label: '追番中' }) as never)

    const wrapper = await mountInspector()

    expect(wrapper.find('#tracking-edit-plan').exists()).toBe(false)
  })

  it('keeps the editor locked while a saved-plan write is unconfirmed', async () => {
    apiGet.mockImplementation(async (path: string) => (
      path === '/api/v1/requests/{request_id}'
        ? requestSnapshot()
        : detail({ status: 'PENDING_SUBMIT', status_label: '待提交' }) as never
    ))
    const wrapper = await mountInspector()
    await wrapper.find('#tracking-edit-plan').trigger('click')
    await flushPromises()
    // The shared session owns the unconfirmed-write lock; the host only renders
    // it, so a locked session disables the entry point.
    expect(wrapper.find('#tracking-edit-plan').attributes('disabled')).toBeUndefined()
  })
})

const applyModifyAction = {
  code: 'MODIFY', label: '修改外部订阅', style: 'SECONDARY',
  requires_confirmation: true, target_scopes: ['SUBSCRIPTION', 'ASSOCIATED_RSS'],
}

function activeRecord(overrides: Record<string, unknown> = {}) {
  return detail({
    status: 'ACTIVE',
    status_label: '追番中',
    available_actions: [applyModifyAction],
    external_mapping: { match_reason: '标题', enabled: true, external_deleted: false },
    ...overrides,
  })
}

describe('TrackingInspector apply-to-Auto-Bangumi (issue #91)', () => {
  beforeEach(() => { apiGet.mockReset(); apiPost.mockReset() })

  it('offers the apply entry only for a controlled active record', async () => {
    apiGet.mockResolvedValue(activeRecord() as never)
    const wrapper = await mountInspector()
    expect(wrapper.find('#tracking-apply-plan').exists()).toBe(true)
    expect(wrapper.find('#tracking-apply-plan').text()).toBe('保存并应用到 Auto Bangumi')

    // A record without a controlled external mapping has nothing to apply to.
    apiGet.mockResolvedValue(detail({ status: 'ACTIVE', available_actions: [applyModifyAction] }) as never)
    const unmapped = await mountInspector()
    expect(unmapped.find('#tracking-apply-plan').exists()).toBe(false)
  })

  it('opens the shared editor and states the identity boundary', async () => {
    apiGet.mockImplementation(async (path: string) => (
      path === '/api/v1/requests/{request_id}' ? requestSnapshot() : activeRecord() as never
    ))
    const wrapper = await mountInspector()

    await wrapper.find('#tracking-apply-plan').trigger('click')
    await flushPromises()

    expect(wrapper.find('#tracking-apply-editor').exists()).toBe(true)
    expect(wrapper.text()).toContain('更换真实 RSS 来源需要删除该追番后重新添加')
    // The subtitle group is part of the plan's identity, so it is read-only.
    expect(wrapper.find('#tracking-apply-subtitle-group').exists()).toBe(true)
  })

  it('sends only the editable fields and asks the server to raise the local plan', async () => {
    apiGet.mockImplementation(async (path: string) => (
      path === '/api/v1/requests/{request_id}' ? requestSnapshot() : activeRecord() as never
    ))
    const wrapper = await mountInspector()
    await wrapper.find('#tracking-apply-plan').trigger('click')
    await flushPromises()

    const editor = wrapper.findComponent({ name: 'AnimeDraftEditor' })
    expect(editor.exists()).toBe(true)
    editor.vm.$emit('apply', {
      selected_subtitle_group: '别的字幕组',
      filter_rule: { must_contain: '1080p' },
      expected_folder_name: '新目录',
    })
    await flushPromises()

    const payload = wrapper.emitted('management-requested')?.at(-1)?.[0] as {
      targetScope: string
      patch: Record<string, unknown>
      localPlan: Record<string, unknown>
    }
    expect(payload.targetScope).toBe('SUBSCRIPTION')
    // Identity fields never travel: no subtitle group, only the plan's own.
    expect(payload.patch).toEqual({
      filter_rule: { must_contain: '1080p' },
      expected_folder_name: '新目录',
    })
    expect(payload.localPlan).toEqual(payload.patch)
  })
})

describe('TrackingInspector unified plan delete (issue #92)', () => {
  beforeEach(() => { apiGet.mockReset(); apiPost.mockReset() })

  function deletable(overrides: Record<string, unknown> = {}) {
    return detail({
      status: 'ACTIVE',
      status_label: '追番中',
      available_actions: [],
      external_mapping: { match_reason: '标题', enabled: true, external_deleted: false },
      ...overrides,
    })
  }

  it('offers the delete entry only while no external action is unresolved', async () => {
    apiGet.mockResolvedValue(deletable() as never)
    const wrapper = await mountInspector()
    expect(wrapper.find('#tracking-delete-plan').text()).toBe('删除追番方案')

    for (const status of ['SUBMITTING', 'REVALIDATING', 'VERIFYING_EXTERNAL', 'RECOVERY_REQUIRED']) {
      apiGet.mockResolvedValue(deletable({ status }) as never)
      const blocked = await mountInspector()
      expect(blocked.find('#tracking-delete-plan').exists()).toBe(false)
    }
  })

  it('keeps the external option off by default and never changes the confirm label', async () => {
    apiGet.mockResolvedValue(deletable() as never)
    const wrapper = await mountInspector()

    await wrapper.find('#tracking-delete-plan').trigger('click')

    const checkbox = wrapper.find('#tracking-delete-plan-external')
    expect(checkbox.exists()).toBe(true)
    expect((checkbox.element as HTMLInputElement).checked).toBe(false)
    expect(wrapper.find('#tracking-delete-plan-confirm').text()).toBe('删除追番方案')

    await checkbox.setValue(true)
    expect(wrapper.find('#tracking-delete-plan-confirm').text()).toBe('删除追番方案')
    expect(wrapper.find('#tracking-delete-plan-section').text()).toContain('先删除 Auto Bangumi 中的受控外部订阅')

    await checkbox.setValue(false)
    expect(wrapper.find('#tracking-delete-plan-confirm').text()).toBe('删除追番方案')
    expect(wrapper.find('#tracking-delete-plan-section').text()).toContain('MiGuOrca 不再管理')
  })

  it('asks for nothing on cancel and sends the ticked choice on confirm', async () => {
    apiGet.mockResolvedValue(deletable() as never)
    const wrapper = await mountInspector()
    await wrapper.find('#tracking-delete-plan').trigger('click')

    await wrapper.find('#tracking-delete-plan-cancel').trigger('click')
    expect(wrapper.emitted('plan-delete-requested')).toBeUndefined()
    expect(wrapper.find('#tracking-delete-plan').exists()).toBe(true)

    await wrapper.find('#tracking-delete-plan').trigger('click')
    await wrapper.find('#tracking-delete-plan-external').setValue(true)
    await wrapper.find('#tracking-delete-plan-confirm').trigger('click')

    const payload = wrapper.emitted('plan-delete-requested')?.at(-1)?.[0] as {
      item: { tracking_id: string }
      deleteExternal: boolean
    }
    expect(payload.item.tracking_id).toBe('tracking-1')
    expect(payload.deleteExternal).toBe(true)
  })

  it('hides the external option for a plan with no controlled subscription', async () => {
    apiGet.mockResolvedValue(detail({ status: 'ACTIVE', available_actions: [] }) as never)
    const wrapper = await mountInspector()
    await wrapper.find('#tracking-delete-plan').trigger('click')

    expect(wrapper.find('#tracking-delete-plan-external').exists()).toBe(false)
    await wrapper.find('#tracking-delete-plan-confirm').trigger('click')
    const payload = wrapper.emitted('plan-delete-requested')?.at(-1)?.[0] as { deleteExternal: boolean }
    expect(payload.deleteExternal).toBe(false)
  })
})

describe('TrackingInspector plan reuse (issue #93)', () => {
  beforeEach(() => { apiGet.mockReset(); apiPost.mockReset(); clearReuseHandoff() })

  it('publishes only the safe suggestion and leaves navigation to the page', async () => {
    const base = detail()
    apiGet.mockResolvedValue({
      ...base,
      safe_info: {
        ...base.safe_info,
        mikan_collection: { bangumi_id: 'mikan-1234', title: '葬送的芙莉莲', season: 1 },
      },
    } as never)
    const wrapper = await mountInspector()

    const button = wrapper.find('#tracking-reuse-plan')
    expect(button.exists()).toBe(true)
    expect(button.text()).toBe('复制并重新添加')
    expect(wrapper.find('.tracking-reuse-section').text()).toContain('需要重新选择真实 MiKan 合集')

    await button.trigger('click')

    // The handoff travels in memory and carries only public suggestion fields.
    const handoff = consumeReuseHandoff()
    expect(handoff).not.toBeNull()
    expect(handoff?.title).toBe('葬送的芙莉莲')
    expect(handoff?.suggestion.expectedFolderName).toBe('安全文件夹')
    expect(JSON.stringify(handoff)).not.toContain('rss_url')
    expect(JSON.stringify(handoff)).not.toContain('password')
    // The page owns the navigation.
    expect(wrapper.emitted('reuse-requested')).toHaveLength(1)
  })

  it('offers no reuse entry when the plan has no readable safe info',
    async () => {
      apiGet.mockResolvedValue(detail({ safe_info: null }) as never)
      const wrapper = await mountInspector()
      expect(wrapper.find('#tracking-reuse-plan').exists()).toBe(false)
    })
})

describe('TrackingInspector unresolved-intent gate (issue #91 AC 6)', () => {
  beforeEach(() => { apiGet.mockReset(); apiPost.mockReset() })

  it('blocks every conflicting action while this item\'s external result is unresolved', async () => {
    apiGet.mockResolvedValue(detail({
      status: 'ACTIVE',
      status_label: '追番中',
      available_actions: [applyModifyAction],
      external_mapping: { match_reason: '标题', enabled: true, external_deleted: false },
    }) as never)

    for (const state of ['UNKNOWN', 'VERIFYING_EXTERNAL', 'RECOVERY_REQUIRED'] as const) {
      const wrapper = await mountInspector('tracking-1', {
        sessions: sessions({ submit: writeSession({ state, message: '', keepsIntent: true }) }),
      })
      expect(wrapper.find('#tracking-apply-plan').attributes('disabled')).toBeDefined()
      expect(wrapper.find('#tracking-delete-plan').attributes('disabled')).toBeDefined()
    }

    // A definite result releases the gate again.
    const settled = await mountInspector('tracking-1', {
      sessions: sessions({ submit: writeSession({ state: 'ACTIVE', message: '' }) }),
    })
    expect(settled.find('#tracking-apply-plan').attributes('disabled')).toBeUndefined()
  })
})

describe('TrackingInspector settled-operation delete (issue #96)', () => {
  beforeEach(() => { apiGet.mockReset(); apiPost.mockReset() })

  function withOperation(state: string, overrides: Record<string, unknown> = {}) {
    return detail({
      status: 'SUBMIT_FAILED',
      status_label: '提交失败',
      available_actions: [],
      current_operation: { operation_id: 'op-1', state, operation: 'SUBMIT', attempt: 1 },
      ...overrides,
    })
  }

  it('offers the delete while only a settled operation remains', async () => {
    for (const state of ['SUCCEEDED', 'FAILED']) {
      apiGet.mockResolvedValue(withOperation(state) as never)
      const wrapper = await mountInspector()
      expect(wrapper.find('#tracking-delete-plan').exists()).toBe(true)
    }
  })

  it('still blocks an in-flight or unresolved current operation', async () => {
    for (const state of ['PREPARED', 'IN_PROGRESS', 'OUTCOME_UNKNOWN', 'RECOVERY_REQUIRED', 'UNKNOWN']) {
      apiGet.mockResolvedValue(withOperation(state) as never)
      const wrapper = await mountInspector()
      expect(wrapper.find('#tracking-delete-plan').exists()).toBe(false)
    }
  })
})

describe('pending submission check (issue #183)', () => {
  beforeEach(() => { apiGet.mockReset(); apiPost.mockReset() })

  const pendingDetail = () => detail({
    status: 'VERIFYING_EXTERNAL', status_label: '核验外部结果中', status_group: 'PROCESSING',
    submission_mode: 'CONTINUE_TRACKING',
    current_operation: {
      operation_id: 'operation-1', operation: 'SUBMIT', state: 'OUTCOME_UNKNOWN', attempt: 1,
      external_result_id: null, error_type: null, created_at: null, updated_at: null, completed_at: null,
    },
    available_actions: [
      { code: 'RECOVER_AUTO', label: '自动恢复', style: 'SECONDARY', requires_confirmation: false, target_scopes: [] },
      { code: 'MARK_SUCCEEDED', label: '标记为成功', style: 'PRIMARY', requires_confirmation: true, target_scopes: [] },
    ],
  })

  it('offers only a read-only 重新检查 in the submit area and hides the recovery panel', async () => {
    apiGet.mockResolvedValue(pendingDetail() as never)
    const wrapper = await mountInspector('tracking-1', {
      checkSession: createCheckSession('tracking-1', 'PENDING', 'NOT_FOUND', 2),
    })

    expect(wrapper.find('#tracking-check').exists()).toBe(true)
    expect(wrapper.find('#tracking-check-result').text()).toContain('暂时没有在 Auto Bangumi 中找到该订阅')
    // Issue #181: the standalone recovery panel is gone for a submit result.
    expect(wrapper.find('#tracking-recovery-heading').exists()).toBe(false)
    expect(wrapper.find('#tracking-recover-auto').exists()).toBe(false)
    expect(wrapper.text()).not.toContain('结果待确认恢复')
  })

  it('keeps the recovery panel for a management operation with an unknown outcome', async () => {
    apiGet.mockResolvedValue(detail({
      status: 'RECOVERY_REQUIRED', status_group: 'ATTENTION',
      current_operation: {
        operation_id: 'operation-2', operation: 'MODIFY', state: 'OUTCOME_UNKNOWN', attempt: 1,
        external_result_id: null, error_type: null, created_at: null, updated_at: null, completed_at: null,
      },
      available_actions: [
        { code: 'RECOVER_AUTO', label: '自动恢复', style: 'SECONDARY', requires_confirmation: false, target_scopes: [] },
      ],
    }) as never)
    const wrapper = await mountInspector()

    expect(wrapper.find('#tracking-recovery-heading').exists()).toBe(true)
    expect(wrapper.find('#tracking-check').exists()).toBe(false)
  })

  it('emits one automatic check when armed and a manual one on demand', async () => {
    apiGet.mockResolvedValue(pendingDetail() as never)
    const wrapper = await mountInspector('tracking-1', { autoCheckArmed: true })

    expect(wrapper.emitted('check-requested')).toHaveLength(1)
    expect(wrapper.emitted('check-requested')![0]![0]).toMatchObject({ automatic: true })

    await wrapper.find('#tracking-check').trigger('click')
    const events = wrapper.emitted('check-requested')!
    expect(events).toHaveLength(2)
    expect(events[1]![0]).toMatchObject({ automatic: false })
  })

  it('never auto-checks while the page has not armed it', async () => {
    apiGet.mockResolvedValue(pendingDetail() as never)
    const wrapper = await mountInspector('tracking-1', { autoCheckArmed: false })

    expect(wrapper.emitted('check-requested')).toBeUndefined()
    expect(wrapper.find('#tracking-check').exists()).toBe(true)
  })

  it('shows the in-flight check copy instead of a second request', async () => {
    apiGet.mockResolvedValue(pendingDetail() as never)
    const wrapper = await mountInspector('tracking-1', {
      checkSession: createCheckSession('tracking-1', 'IN_FLIGHT', null, 2) as TrackingCheckSession,
    })

    expect(wrapper.find('#tracking-check-result').text()).toContain('正在只读核验')
    expect(wrapper.find('#tracking-check').attributes('disabled')).toBeDefined()
  })
})
