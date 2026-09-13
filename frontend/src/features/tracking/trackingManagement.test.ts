import { describe, expect, it } from 'vitest'

import type { CapabilityResult, TrackingItem } from './trackingProjection'
import {
  buildRssPatch,
  buildSubscriptionPatch,
  createModifyConflictSession,
  createModifyInFlightSession,
  createModifyRejectedSession,
  createTrackingManagementBody,
  createTrackingManagementIntent,
  emptyRssForm,
  emptySubscriptionForm,
  isModifyActionCode,
  isUnsafePatchValue,
  MANAGEMENT_ACTION_ENDPOINTS,
  managementPatchPresent,
  MODIFY_FORM_HELP,
  MODIFY_SCOPE_CONFIRMATIONS,
  projectModifyOutcome,
  rssTextValue,
  setRssTextValue,
  setSubscriptionTextValue,
  subscriptionTextValue,
  type TrackingModifyResult,
  type TrackingRssForm,
  type TrackingSubscriptionForm,
} from './trackingManagement'

type ItemAction = NonNullable<TrackingItem['available_actions']>[number]

function action(overrides: Partial<ItemAction> = {}): ItemAction {
  return {
    code: 'MODIFY', label: '修改外部方案', style: 'SECONDARY', requires_confirmation: true,
    target_scopes: ['SUBSCRIPTION', 'ASSOCIATED_RSS'], ...overrides,
  }
}

function item(overrides: Partial<TrackingItem> = {}): TrackingItem {
  return {
    tracking_id: 'tracking-1', request_id: 'request-1', title: '葬送的芙莉莲', season: 1,
    subtitle_group: '喵萌奶茶屋', poster_path: null, status: 'ACTIVE', status_label: '追番中',
    status_group: 'ACTIVE', available_actions: [action()], valid_resource_count: 2,
    updated_episode: null, updated_episode_status: 'NOT_IMPLEMENTED', total_episodes: null,
    revision: 4, updated_at: '2026-09-13T00:00:00Z', ...overrides,
  }
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

const abConfig = {
  auth_mode: 'password' as const, base_url: 'https://ab.invalid', username: 'user',
  password: 'secret', fallback_enabled: false,
}

function modifyResult(overrides: Partial<TrackingModifyResult> = {}): TrackingModifyResult {
  return {
    action: 'MODIFY', management_status: 'SUCCEEDED', needs_manual: false, safe_message: '管理操作已完成',
    operation_id: 'operation-1', operation: null,
    tracking: item({ revision: 5 }), ...overrides,
  }
}

function subscriptionForm(overrides: Partial<TrackingSubscriptionForm> = {}): TrackingSubscriptionForm {
  return { ...emptySubscriptionForm(), ...overrides }
}

function rssForm(overrides: Partial<TrackingRssForm> = {}): TrackingRssForm {
  return { ...emptyRssForm(), ...overrides }
}

describe('tracking modify form model (US-313)', () => {
  it('refuses an empty patch, so every scope needs an explicit field', () => {
    expect(buildSubscriptionPatch(subscriptionForm())).toBeNull()
    expect(buildRssPatch(rssForm())).toBeNull()
    // Selecting a field is what makes a patch non-empty; the value may be an
    // explicit clear (null) and the patch is still a real, non-empty patch.
    const cleared = buildSubscriptionPatch(subscriptionForm({ enabled: { title: true } }))
    expect(cleared).toEqual({ title: null })
  })

  it('keeps the two scope field sets apart on both builders', () => {
    const subscription = buildSubscriptionPatch(subscriptionForm({
      enabled: { title: true, season: true, subtitle_group: true, offset: true, expected_folder_name: true },
      title: '新标题', season: '2', subtitleGroup: '新字幕组', offset: '3', expectedFolderName: '新文件夹',
    }))
    expect(subscription).toEqual({
      title: '新标题', season: 2, subtitle_group: '新字幕组', offset: 3, expected_folder_name: '新文件夹',
    })
    // A subscription patch can never carry an RSS field, and the reverse holds
    // too: the builders only read their own scope's fields.
    expect(Object.keys(subscription ?? {})).not.toContain('name')
    expect(Object.keys(subscription ?? {})).not.toContain('parser')

    const rss = buildRssPatch(rssForm({ enabled: { name: true, aggregate: true, parser: true }, name: 'RSS 名称', aggregate: true, parser: 'mikan' }))
    expect(rss).toEqual({ name: 'RSS 名称', aggregate: true, parser: 'mikan' })
    expect(Object.keys(rss ?? {})).not.toContain('title')
    expect(Object.keys(rss ?? {})).not.toContain('season')
    // An RSS value can be an explicit clear as well.
    expect(buildRssPatch(rssForm({ enabled: { name: true } }))).toEqual({ name: null })
  })

  it('sends the filter rule as a complete exclusion expression', () => {
    const rule = buildSubscriptionPatch(subscriptionForm({
      enabled: { filter_rule: true },
      filter: { must_contain: true, must_not_contain: true },
      mustContain: '简体', mustNotContain: '合集',
    }))
    expect(rule).toEqual({
      filter_rule: { use_regex: false, case_sensitive: false, must_contain: '简体', must_not_contain: '合集' },
    })
    // The two switches always travel together; the text terms only when their
    // own switch is on, so an untouched term keeps its Auto Bangumi value.
    expect(buildSubscriptionPatch(subscriptionForm({
      enabled: { filter_rule: true }, filter: { must_contain: true }, mustContain: '简体',
    }))).toEqual({ filter_rule: { use_regex: false, case_sensitive: false, must_contain: '简体' } })
    // A switched-on but empty term is an explicit clear, not an omission.
    expect(buildSubscriptionPatch(subscriptionForm({
      enabled: { filter_rule: true }, filter: { must_contain: true },
    }))).toEqual({ filter_rule: { use_regex: false, case_sensitive: false, must_contain: null } })
    expect(buildSubscriptionPatch(subscriptionForm({
      enabled: { filter_rule: true }, useRegex: true, caseSensitive: true,
    }))).toEqual({ filter_rule: { use_regex: true, case_sensitive: true } })
  })

  it('refuses malformed numbers, traversal-unsafe text and unknown fields', () => {
    for (const season of ['abc', '1.5', '-1', '101']) {
      expect(buildSubscriptionPatch(subscriptionForm({
        enabled: { season: true }, season,
      }))).toBeNull()
    }
    for (const offset of ['abc', '-2']) {
      expect(buildSubscriptionPatch(subscriptionForm({ enabled: { offset: true }, offset }))).toBeNull()
    }
    // The server refuses URLs and absolute paths in patch text, so those values
    // never leave the page either. (Path traversal is deliberately left to the
    // server: it is legal inside a folder name, and the server is authoritative.)
    for (const value of ['https://private.invalid', 'www.example.com', '/etc/passwd', 'C:\\secret']) {
      expect(isUnsafePatchValue(value)).toBe(true)
      expect(buildSubscriptionPatch(subscriptionForm({ enabled: { title: true }, title: value }))).toBeNull()
      expect(buildRssPatch(rssForm({ enabled: { name: true }, name: value }))).toBeNull()
    }
    expect(isUnsafePatchValue('安全的文件夹名')).toBe(false)
    expect(isUnsafePatchValue('第 1 季')).toBe(false)

    // The patch presence check is scope-strict: a cross-scope key is refused.
    expect(managementPatchPresent('SUBSCRIPTION', { title: 'x' })).toBe(true)
    expect(managementPatchPresent('SUBSCRIPTION', { name: 'x' })).toBe(false)
    expect(managementPatchPresent('ASSOCIATED_RSS', { name: 'x' })).toBe(true)
    expect(managementPatchPresent('ASSOCIATED_RSS', { title: 'x' })).toBe(false)
    expect(managementPatchPresent('SUBSCRIPTION', {})).toBe(false)
    expect(managementPatchPresent('SUBSCRIPTION', { title: 'x', name: 'y' })).toBe(false)
    expect(managementPatchPresent('SUBSCRIPTION', null)).toBe(false)
  })

  it('reads and writes only the public patch field names', () => {
    const form = subscriptionForm()
    setSubscriptionTextValue(form, 'subtitle_group', '新字幕组')
    expect(subscriptionTextValue(form, 'subtitle_group')).toBe('新字幕组')
    expect(form.subtitleGroup).toBe('新字幕组')
    // The internal camelCase keys never become patch keys.
    expect(buildSubscriptionPatch({ ...form, enabled: { subtitle_group: true } }))
      .toEqual({ subtitle_group: '新字幕组' })

    const rss = rssForm()
    setRssTextValue(rss, 'parser', 'mikan')
    expect(rssTextValue(rss, 'parser')).toBe('mikan')
    expect(rssTextValue(rss, 'name')).toBe('')
  })
})

describe('tracking modify request (US-313)', () => {
  it('binds the management endpoint to the server-computed action code', () => {
    expect(isModifyActionCode('MODIFY')).toBe(true)
    expect(MANAGEMENT_ACTION_ENDPOINTS.MODIFY).toBe('/api/v1/tracking/items/{tracking_id}/modify')
  })

  it('accepts only an action and scope the live session still projects', () => {
    const record = item()
    const intent = createTrackingManagementIntent(
      record, 'MODIFY', 'SUBSCRIPTION', { title: '新标题' }, capabilities(),
    )
    expect(intent).toMatchObject({
      action: 'MODIFY', targetScope: 'SUBSCRIPTION', patch: { title: '新标题' },
      expectedRevision: 4, confirm: true,
    })
    expect(intent?.idempotencyKey.length).toBeGreaterThanOrEqual(8)

    // A scope the server did not offer is refused even when the capability is
    // proven, and a scope whose capability is unproven is refused too.
    expect(createTrackingManagementIntent(
      item({ available_actions: [action({ target_scopes: ['SUBSCRIPTION'] })] }),
      'MODIFY', 'ASSOCIATED_RSS', { name: 'x' }, capabilities(),
    )).toBeNull()
    expect(createTrackingManagementIntent(
      record, 'MODIFY', 'ASSOCIATED_RSS', { name: 'x' }, capabilities({ rss_modify: 'UNSUPPORTED' }),
    )).toBeNull()
    // An empty or cross-scope patch never becomes an intent.
    expect(createTrackingManagementIntent(record, 'MODIFY', 'SUBSCRIPTION', {}, capabilities())).toBeNull()
    expect(createTrackingManagementIntent(record, 'MODIFY', 'SUBSCRIPTION', { name: 'x' }, capabilities())).toBeNull()
    expect(createTrackingManagementIntent(record, 'MODIFY', 'SUBSCRIPTION', { title: 'x' }, null)).toBeNull()
    // A revision the server could not have issued is refused.
    expect(createTrackingManagementIntent(
      item({ revision: 0 }), 'MODIFY', 'SUBSCRIPTION', { title: 'x' }, capabilities(),
    )).toBeNull()
  })

  it('builds the scope-discriminated body once, with one credential and one key', () => {
    const subscription = createTrackingManagementIntent(
      item(), 'MODIFY', 'SUBSCRIPTION', { title: '新标题', season: 2 }, capabilities(),
    )!
    const body = createTrackingManagementBody(subscription, abConfig, 'profile')
    expect(body).toEqual({
      target_scope: 'SUBSCRIPTION',
      patch: { title: '新标题', season: 2 },
      expected_revision: 4,
      idempotency_key: subscription.idempotencyKey,
      confirm: true,
      ab_config: abConfig,
      storage_dir: 'profile',
    })
    // The same intent replays the very same key and revision binding.
    expect(createTrackingManagementBody(subscription, abConfig, 'profile')).toEqual(body)

    const rss = createTrackingManagementIntent(item(), 'MODIFY', 'ASSOCIATED_RSS', { name: 'x' }, capabilities())!
    const rssBody = createTrackingManagementBody(rss, abConfig)
    expect(rssBody).toEqual({
      target_scope: 'ASSOCIATED_RSS',
      patch: { name: 'x' },
      expected_revision: 4,
      idempotency_key: rss.idempotencyKey,
      confirm: true,
      ab_config: abConfig,
    })
    // The body shape cannot express an external id, URL or raw response.
    expect(Object.keys(rssBody ?? {}).sort()).toEqual(
      ['target_scope', 'patch', 'expected_revision', 'idempotency_key', 'confirm', 'ab_config'].sort(),
    )
    expect(Object.keys(rssBody?.patch ?? {})).toEqual(['name'])

    // A session without a server address is never turned into a request.
    expect(createTrackingManagementBody(subscription, { ...abConfig, base_url: undefined })).toBeNull()
  })
})

describe('tracking modify result (US-313)', () => {
  it('reports the server management status as fixed Chinese copy only', () => {
    const succeeded = projectModifyOutcome('tracking-1', 'SUBSCRIPTION', modifyResult())
    expect(succeeded).toMatchObject({ state: 'SUCCEEDED', targetScope: 'SUBSCRIPTION', needsManual: false })
    expect(succeeded.message).toContain('已应用本次修改')
    expect(succeeded.message).not.toContain('SUCCEEDED')
    expect(succeeded.message).not.toContain('管理操作已完成')

    const failed = projectModifyOutcome('tracking-1', 'ASSOCIATED_RSS', modifyResult({
      management_status: 'FAILED', safe_message: 'Auto Bangumi 未应用管理操作',
    }))
    expect(failed).toMatchObject({ state: 'FAILED', targetScope: 'ASSOCIATED_RSS' })
    expect(failed.message).toContain('未应用本次修改')
    expect(failed.message).not.toContain('FAILED')
  })

  it('treats every other management status as an unresolved result', () => {
    for (const status of ['PREPARED', 'IN_PROGRESS', 'OUTCOME_UNKNOWN', 'RECOVERY_REQUIRED']) {
      const session = projectModifyOutcome('tracking-1', 'SUBSCRIPTION', modifyResult({
        management_status: status as never,
      }))
      expect(session.state).toBe('UNKNOWN')
      expect(session.needsManual).toBe(true)
      expect(session.message).toContain('只读回查')
      expect(session.message).not.toContain('已应用')
      expect(session.message).not.toContain(status)
    }
    // A management_status outside the documented enum is never a success.
    const unknown = projectModifyOutcome('tracking-1', 'SUBSCRIPTION', modifyResult({
      management_status: 'SOMETHING_NEW' as never,
    }))
    expect(unknown.state).toBe('UNKNOWN')
    expect(unknown.message).not.toContain('SOMETHING_NEW')
  })

  it('keeps the raw conflict type and raw status out of the page copy', () => {
    const conflict = createModifyConflictSession('tracking-1', 'SUBSCRIPTION', 'tracking_target_drift')
    expect(conflict.state).toBe('CONFLICT')
    expect(conflict.message).toContain('外部对象已变化')
    expect(conflict.message).not.toContain('tracking_target_drift')
    const fallback = createModifyConflictSession('tracking-1', 'SUBSCRIPTION', 'brand_new_conflict')
    expect(fallback.message).toContain('未提交到 Auto Bangumi')
    expect(fallback.message).not.toContain('brand_new_conflict')

    const rejected = createModifyRejectedSession('tracking-1', 'ASSOCIATED_RSS')
    expect(rejected.state).toBe('REJECTED')
    expect(rejected.message).toContain('未修改 Auto Bangumi 外部订阅')

    const inFlight = createModifyInFlightSession('tracking-1', 'SUBSCRIPTION')
    expect(inFlight.state).toBe('IN_FLIGHT')
    expect(inFlight.message).toContain('正在提交外部修改')
  })

  it('binds each scope to its own impact confirmation without any external id', () => {
    for (const scope of ['SUBSCRIPTION', 'ASSOCIATED_RSS'] as const) {
      const confirmation = MODIFY_SCOPE_CONFIRMATIONS[scope]
      expect(confirmation.message).toContain('不修改 MiGuOrca 本地方案')
      expect(confirmation.message.length).toBeGreaterThan(0)
      expect(confirmation.title).not.toContain(scope)
      expect(confirmation.confirmLabel.length).toBeGreaterThan(0)
    }
    expect(MODIFY_SCOPE_CONFIRMATIONS.SUBSCRIPTION.message).toContain('可能改变后续下载')
    expect(MODIFY_SCOPE_CONFIRMATIONS.ASSOCIATED_RSS.message).toContain('关联 RSS')
    expect(MODIFY_FORM_HELP).toContain('不读取 Auto Bangumi 的当前值')
  })
})
