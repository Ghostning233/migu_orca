import { flushPromises, mount } from '@vue/test-utils'
import { createRouter, createMemoryHistory } from 'vue-router'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { api } from '@/api/client'
import TrackingInspector from './TrackingInspector.vue'
import { createManagementSession, RECOVERY_NEEDS_MANUAL_NOTICE } from './trackingProjection'
import type { CapabilityResult, TrackingRecoverySession, TrackingWriteSession } from './trackingProjection'

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
    expect(wrapper.text()).toContain('待开发')
    expect(wrapper.find('.tracking-plan-link').exists()).toBe(true)
    expect(wrapper.text()).not.toContain('request-1')
    expect(wrapper.text()).toContain('第一集.mkv')
  })

  it('hides local plan link for external-only records', async () => {
    apiGet.mockResolvedValue(detail({ status: 'EXTERNAL_ONLY', request_id: 'request-1' }) as never)
    const wrapper = await mountInspector()
    expect(wrapper.find('.tracking-plan-link').exists()).toBe(false)
    expect(wrapper.text()).toContain('没有可返回的本地订阅方案')
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

function writeSession(overrides: Record<string, unknown> = {}): TrackingWriteSession {
  return {
    trackingId: 'tracking-1', action: 'SUBMIT', state: 'ACTIVE',
    message: '提交成功：已在 Auto Bangumi 创建外部订阅。', issues: [], failureCategory: null,
    ...overrides,
  } as TrackingWriteSession
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
    const wrapper = await mountInspector()
    // Issue #86: the server projects the action and re-validates everything in
    // the submit request, so no settings-page probe gates the button.
    expect(wrapper.find('#tracking-submit').exists()).toBe(true)
    expect(wrapper.find('#tracking-revalidate').exists()).toBe(false)
    expect(apiPost).not.toHaveBeenCalled()
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
    const wrapper = await mountSubmittable({ writeSession: writeSession({ state: 'IN_FLIGHT' }) })
    expect(wrapper.find('#tracking-submit').attributes('disabled')).toBeDefined()
    expect(wrapper.find('#tracking-submit').attributes('aria-busy')).toBe('true')
    await wrapper.find('#tracking-submit').trigger('click')
    await flushPromises()
    expect(wrapper.emitted('write-requested')).toBeUndefined()
    expect(apiPost).not.toHaveBeenCalled()
  })

  it('renders only the fixed write copy and the documented §11.5 issues', async () => {
    const wrapper = await mountSubmittable({ writeSession: writeSession({
      state: 'VERIFYING_EXTERNAL', message: '外部提交结果未知，正在只读回查；请勿重复提交。',
      issues: [{ code: 'OPERATION_IN_PROGRESS', message: '本地方案尚未通过提交前复核。' }],
    }) })
    const result = wrapper.find('#tracking-submit-result')
    expect(result.text()).toContain('外部提交结果未知')
    expect(result.text()).toContain('请勿重复提交')
    expect(result.find('.tracking-submit-issues').text()).toContain('本地方案尚未通过提交前复核')
    expect(wrapper.text()).not.toContain('VERIFYING_EXTERNAL')
  })

  it('never shows another item write result on this item', async () => {
    const wrapper = await mountSubmittable({ writeSession: writeSession({ trackingId: 'tracking-2' }) })
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
      writeSession: writeSession({
        action: 'RETRY', state: 'SUBMIT_FAILED',
        message: '提交明确失败，尚未创建外部订阅；可在确认后显式重试。',
      }),
    })
    expect(wrapper.find('#tracking-retry').attributes('disabled')).toBeUndefined()
    expect(wrapper.find('#tracking-submit-result').text()).toContain('提交明确失败')

    await wrapper.setProps({ writeSession: writeSession({ action: 'RETRY', state: 'IN_FLIGHT' }) })
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

function recoverySession(overrides: Record<string, unknown> = {}): TrackingRecoverySession {
  return {
    trackingId: 'tracking-1', action: 'RECOVER_AUTO', state: 'RECOVERY_REQUIRED',
    needsManual: true, message: '结果仍无法确认，保持恢复状态；未确认前不会自动提交。', ...overrides,
  } as TrackingRecoverySession
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
    const wrapper = await mountRecoverable({ recoverySession: recoverySession() })
    const result = wrapper.find('#tracking-recovery-result')
    expect(result.text()).toContain('结果仍无法确认')
    expect(result.find('#tracking-recovery-manual-notice').text()).toBe(RECOVERY_NEEDS_MANUAL_NOTICE)
    expect(result.text()).toContain('先在 Auto Bangumi 中独立核对')
    expect(wrapper.text()).not.toContain('RECOVERY_REQUIRED')
    expect(wrapper.text()).not.toContain('NEEDS_RECONFIRM')

    // A decided verdict never shows the manual-check requirement.
    await wrapper.setProps({ recoverySession: recoverySession({ state: 'ACTIVE', needsManual: false, message: '恢复完成：已确认该番在 Auto Bangumi 中存在外部订阅。' }) })
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
      { ...LIVE_SESSION, recoverySession: recoverySession({ state: 'IN_FLIGHT', needsManual: false }) },
      { ...LIVE_SESSION, writeSession: writeSession({ state: 'IN_FLIGHT' }) },
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
    const wrapper = await mountRecoverable({ recoverySession: recoverySession({ trackingId: 'tracking-2' }) })
    expect(wrapper.find('#tracking-recovery-result').exists()).toBe(false)
  })
})

describe('TrackingInspector per-record external delete (US-315)', () => {
  beforeEach(() => { apiGet.mockReset(); apiPost.mockReset() })

  const deleteAction = {
    code: 'DELETE_EXTERNAL', label: '删除外部订阅', style: 'DANGER',
    requires_confirmation: true, target_scopes: ['SUBSCRIPTION', 'ASSOCIATED_RSS'],
  }

  it('offers the delete only with a live session and a proven per-scope capability', async () => {
    apiGet.mockResolvedValue(detail({ available_actions: [deleteAction] }) as never)
    const wrapper = await mountInspector()
    expect(wrapper.find('#tracking-delete-external-submit').exists()).toBe(false)
    expect(wrapper.find('.tracking-delete-external-section').text())
      .toContain('需要先在页面连接 Auto Bangumi')

    const connected = await mountInspector('tracking-1', LIVE_SESSION)
    expect(connected.find('#tracking-delete-external-submit').exists()).toBe(true)

    // Only the scope whose own delete capability is proven keeps a control.
    const degraded = await mountInspector('tracking-1', {
      ...LIVE_SESSION, capabilities: capabilities({ subscription_delete: 'UNSUPPORTED' }),
    })
    expect(degraded.find('#tracking-delete-external-scope-SUBSCRIPTION').exists()).toBe(false)
    expect(degraded.find('#tracking-delete-external-scope-ASSOCIATED_RSS').exists()).toBe(true)
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
    const session = createManagementSession(
      'tracking-1', 'DELETE_EXTERNAL', 'SUBSCRIPTION', 'SUCCEEDED',
    )
    const wrapper = await mountInspector('tracking-1', { ...LIVE_SESSION, managementSession: session })
    const result = wrapper.find('#tracking-delete-external-result')
    expect(result.text()).toContain('外部删除已完成')
    expect(result.text()).toContain('本次目标：外部番剧订阅')
    expect(result.text()).not.toContain('SUCCEEDED')
    // The delete verdict never leaks into the enable/refresh panel.
    expect(wrapper.find('#tracking-management-result').exists()).toBe(false)

    const other = await mountInspector('tracking-1', {
      ...LIVE_SESSION,
      managementSession: createManagementSession('tracking-2', 'DELETE_EXTERNAL', 'SUBSCRIPTION', 'SUCCEEDED'),
    })
    expect(other.find('#tracking-delete-external-result').exists()).toBe(false)
  })
})
