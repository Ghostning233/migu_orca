import { describe, expect, it } from 'vitest'

import { managementSessionKeepsIntent, type CapabilityResult, type TrackingItem } from './trackingProjection'
import {
  buildRssPatch,
  buildSubscriptionPatch,
  createManagementConflictSession,
  createManagementInFlightSession,
  createManagementRejectedSession,
  createManagementUnbuildableSession,
  createTrackingDeleteExternalIntent,
  createTrackingManagementActionIntent,
  createTrackingManagementBody,
  createTrackingManagementIntent,
  createTrackingRefreshRssIntent,
  createTrackingSetEnabledIntent,
  DELETE_EXTERNAL_HELP,
  emptyRssForm,
  emptySubscriptionForm,
  isModifyActionCode,
  isUnsafePatchValue,
  MANAGEMENT_ACTION_ENDPOINTS,
  managementConfirmation,
  managementPatchPresent,
  MODIFY_FORM_HELP,
  MODIFY_SCOPE_CONFIRMATIONS,
  projectManagementOutcome,
  rssTextValue,
  sameManagementRequest,
  setRssTextValue,
  setSubscriptionTextValue,
  subscriptionTextValue,
  type TrackingManagementResult,
  type TrackingRssForm,
  type TrackingSubscriptionForm,
} from './trackingManagement'

type ItemAction = NonNullable<TrackingItem['available_actions']>[number]

/** A JSON rendering of one request body, used to prove fields are absent. */
function serialize(value: unknown): string {
  return JSON.stringify(value ?? null)
}

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

function modifyResult(overrides: Partial<TrackingManagementResult> = {}): TrackingManagementResult {
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
    const rssPatch = rssBody && 'patch' in rssBody ? rssBody.patch : null
    expect(Object.keys(rssPatch ?? {})).toEqual(['name'])

    // A session without a server address is never turned into a request.
    expect(createTrackingManagementBody(subscription, { ...abConfig, base_url: undefined })).toBeNull()
  })
})

describe('tracking modify result (US-313)', () => {
  it('reports the server management status as fixed Chinese copy only', () => {
    const succeeded = projectManagementOutcome('tracking-1', 'MODIFY', 'SUBSCRIPTION', modifyResult())
    expect(succeeded).toMatchObject({ state: 'SUCCEEDED', targetScope: 'SUBSCRIPTION', needsManual: false })
    expect(succeeded.message).toContain('已应用本次修改')
    expect(succeeded.message).not.toContain('SUCCEEDED')
    expect(succeeded.message).not.toContain('管理操作已完成')

    const failed = projectManagementOutcome('tracking-1', 'MODIFY', 'ASSOCIATED_RSS', modifyResult({
      management_status: 'FAILED', safe_message: 'Auto Bangumi 未应用管理操作',
    }))
    expect(failed).toMatchObject({ state: 'FAILED', targetScope: 'ASSOCIATED_RSS' })
    expect(failed.message).toContain('未应用本次修改')
    expect(failed.message).not.toContain('FAILED')
  })

  it('treats every other management status as an unresolved result', () => {
    for (const status of ['PREPARED', 'IN_PROGRESS', 'OUTCOME_UNKNOWN', 'RECOVERY_REQUIRED']) {
      const session = projectManagementOutcome('tracking-1', 'MODIFY', 'SUBSCRIPTION', modifyResult({
        management_status: status as never,
      }))
      expect(session.state).toBe('UNKNOWN')
      expect(session.needsManual).toBe(true)
      expect(session.message).toContain('只读回查')
      expect(session.message).not.toContain('已应用')
      expect(session.message).not.toContain(status)
    }
    // A management_status outside the documented enum is never a success.
    const unknown = projectManagementOutcome('tracking-1', 'MODIFY', 'SUBSCRIPTION', modifyResult({
      management_status: 'SOMETHING_NEW' as never,
    }))
    expect(unknown.state).toBe('UNKNOWN')
    expect(unknown.message).not.toContain('SOMETHING_NEW')
  })

  it('keeps the raw conflict type and raw status out of the page copy', () => {
    const conflict = createManagementConflictSession('tracking-1', 'MODIFY', 'SUBSCRIPTION', 'tracking_target_drift')
    expect(conflict.state).toBe('CONFLICT')
    expect(conflict.message).toContain('外部对象已变化')
    expect(conflict.message).not.toContain('tracking_target_drift')
    const fallback = createManagementConflictSession('tracking-1', 'MODIFY', 'SUBSCRIPTION', 'brand_new_conflict')
    expect(fallback.message).toContain('未提交到 Auto Bangumi')
    expect(fallback.message).not.toContain('brand_new_conflict')

    const rejected = createManagementRejectedSession('tracking-1', 'MODIFY', 'ASSOCIATED_RSS')
    expect(rejected.state).toBe('REJECTED')
    expect(rejected.message).toContain('未修改 Auto Bangumi 外部订阅')

    const inFlight = createManagementInFlightSession('tracking-1', 'MODIFY', 'SUBSCRIPTION')
    expect(inFlight.state).toBe('IN_FLIGHT')
    expect(inFlight.message).toContain('正在提交外部修改')
  })

  it('converges an unbuildable request on a definite failure instead of in-flight', () => {
    // ``createTrackingManagementBody`` refuses a session without a server
    // address; the page must never keep such a request in IN_FLIGHT.
    const intent = createTrackingManagementIntent(
      item(), 'MODIFY', 'SUBSCRIPTION', { title: 'x' }, capabilities(),
    )!
    expect(createTrackingManagementBody(intent, { ...abConfig, base_url: undefined })).toBeNull()

    const session = createManagementUnbuildableSession('tracking-1', 'MODIFY', 'SUBSCRIPTION')
    expect(session.state).not.toBe('IN_FLIGHT')
    expect(managementSessionKeepsIntent(session)).toBe(false)
    expect(session.message).toContain('未向 Auto Bangumi 发送任何请求')
    expect(session.message).not.toContain('IN_FLIGHT')
    expect(session.message).not.toContain('base_url')
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

// -- US-314: enable/disable and associated-RSS refresh -----------------------

const ENABLE_ACTION = {
  code: 'SET_ENABLED', label: '启用外部订阅', style: 'PRIMARY',
  requires_confirmation: true, target_scopes: ['SUBSCRIPTION', 'ASSOCIATED_RSS'],
} satisfies ItemAction
const DISABLE_ACTION = { ...ENABLE_ACTION, label: '停用外部订阅', style: 'SECONDARY' } satisfies ItemAction
const REFRESH_ACTION = {
  code: 'REFRESH_RSS', label: '刷新关联 RSS', style: 'SECONDARY',
  requires_confirmation: true, target_scopes: ['ASSOCIATED_RSS'],
} satisfies ItemAction

function enableDetail(overrides: Partial<TrackingItem> = {}): TrackingItem {
  return item({ status: 'DISABLED', status_label: '已停用', available_actions: [ENABLE_ACTION], ...overrides })
}

describe('tracking set-enabled request (US-314)', () => {
  it('derives the direction from the record status, never from the caller', () => {
    expect(createTrackingSetEnabledIntent(enableDetail(), 'SUBSCRIPTION', capabilities()))
      .toMatchObject({ action: 'SET_ENABLED', targetScope: 'SUBSCRIPTION', enabled: true, patch: null })

    for (const status of ['ACTIVE', 'EXTERNAL_ONLY'] as const) {
      expect(createTrackingSetEnabledIntent(
        item({ status, available_actions: [DISABLE_ACTION] }), 'SUBSCRIPTION', capabilities(),
      )).toMatchObject({ enabled: false })
    }
    // A status that names no direction never becomes a request even when the
    // action object claims to offer one.
    for (const status of ['PENDING_SUBMIT', 'SUBMITTING', 'UNKNOWN'] as const) {
      expect(createTrackingSetEnabledIntent(
        item({ status, available_actions: [ENABLE_ACTION] }), 'SUBSCRIPTION', capabilities(),
      )).toBeNull()
    }
    expect(createTrackingSetEnabledIntent(item({ revision: 0, status: 'DISABLED' }), 'SUBSCRIPTION', capabilities()))
      .toBeNull()
  })

  it('intersects the server-offered scope with the capability of that direction', () => {
    const record = enableDetail()
    expect(createTrackingSetEnabledIntent(
      record, 'ASSOCIATED_RSS', capabilities({ rss_enable: 'UNSUPPORTED' }),
    )).toBeNull()
    expect(createTrackingSetEnabledIntent(
      record, 'ASSOCIATED_RSS', capabilities({ rss_enable: 'UNKNOWN' }),
    )).toBeNull()
    expect(createTrackingSetEnabledIntent(record, 'ASSOCIATED_RSS', capabilities()))
      .toMatchObject({ targetScope: 'ASSOCIATED_RSS', enabled: true })
    // A scope the server did not offer is refused even with the capability.
    expect(createTrackingSetEnabledIntent(
      enableDetail({ available_actions: [{ ...ENABLE_ACTION, target_scopes: ['SUBSCRIPTION'] }] }),
      'ASSOCIATED_RSS', capabilities(),
    )).toBeNull()
    // The enable direction needs the *enable* capability; the disable direction
    // needs only the disable one, so a proven enable alone cannot disable.
    const active = item({ status: 'ACTIVE', available_actions: [DISABLE_ACTION] })
    expect(createTrackingSetEnabledIntent(active, 'SUBSCRIPTION', capabilities({
      subscription_enable: 'UNSUPPORTED',
    }))).toMatchObject({ enabled: false })
    expect(createTrackingSetEnabledIntent(active, 'SUBSCRIPTION', capabilities({
      subscription_disable: 'UNSUPPORTED',
    }))).toBeNull()
    expect(createTrackingSetEnabledIntent(active, 'SUBSCRIPTION', null)).toBeNull()
  })

  it('builds only the boolean direction for the chosen scope', () => {
    const intent = createTrackingSetEnabledIntent(enableDetail(), 'SUBSCRIPTION', capabilities())!
    const body = createTrackingManagementBody(intent, abConfig, 'profile')
    expect(body).toEqual({
      target_scope: 'SUBSCRIPTION',
      enabled: true,
      expected_revision: 4,
      idempotency_key: intent.idempotencyKey,
      confirm: true,
      ab_config: abConfig,
      storage_dir: 'profile',
    })
    // The body has no patch field at all: an enable can never carry form fields.
    expect(Object.keys(body ?? {}).sort()).toEqual(
      ['target_scope', 'enabled', 'expected_revision', 'idempotency_key', 'confirm', 'ab_config', 'storage_dir'].sort(),
    )
    expect(createTrackingManagementBody(intent, { ...abConfig, base_url: undefined })).toBeNull()
  })
})

describe('tracking refresh request (US-314)', () => {
  it('only ever targets the current record own associated RSS', () => {
    const intent = createTrackingRefreshRssIntent(item({ available_actions: [REFRESH_ACTION] }), capabilities())
    expect(intent).toMatchObject({
      action: 'REFRESH_RSS', targetScope: 'ASSOCIATED_RSS', patch: null, enabled: null,
    })
    const body = createTrackingManagementBody(intent!, abConfig)
    expect(body).toEqual({
      target_scope: 'ASSOCIATED_RSS',
      expected_revision: 4,
      idempotency_key: intent!.idempotencyKey,
      confirm: true,
      ab_config: abConfig,
    })
    // No patch, no enabled, no scope choice: the refresh body cannot express
    // another target, and there is no global refresh route to fall back to.
    expect(Object.keys(body ?? {}).sort()).toEqual(
      ['target_scope', 'expected_revision', 'idempotency_key', 'confirm', 'ab_config'].sort(),
    )
  })

  it('fails closed without the server action or the proven refresh capability', () => {
    expect(createTrackingRefreshRssIntent(item(), capabilities())).toBeNull()
    for (const value of ['UNSUPPORTED', 'UNKNOWN'] as const) {
      expect(createTrackingRefreshRssIntent(item({ available_actions: [REFRESH_ACTION] }),
        capabilities({ rss_refresh: value }))).toBeNull()
    }
    expect(createTrackingRefreshRssIntent(
      item({ available_actions: [REFRESH_ACTION] }), capabilities({ probe_status: 'PARTIAL' }),
    )).toBeNull()
    // The server would never offer a subscription refresh; if it did, the scope
    // intersection drops it instead of sending it.
    expect(createTrackingRefreshRssIntent(
      item({ available_actions: [{ ...REFRESH_ACTION, target_scopes: ['SUBSCRIPTION'] }] }), capabilities(),
    )).toBeNull()
    expect(createTrackingRefreshRssIntent(
      item({ revision: 0, available_actions: [REFRESH_ACTION] }), capabilities(),
    )).toBeNull()
  })
})

describe('tracking management dispatch and locking (US-314)', () => {
  it('dispatches every action this page sends to its own builder', () => {
    const record = item({
      available_actions: [DELETE_ACTION, DISABLE_ACTION, REFRESH_ACTION],
    })
    expect(createTrackingManagementActionIntent(record, 'DELETE_EXTERNAL', 'SUBSCRIPTION', null, capabilities()))
      .toMatchObject({ action: 'DELETE_EXTERNAL', targetScope: 'SUBSCRIPTION' })
    expect(createTrackingManagementActionIntent(record, 'SET_ENABLED', 'SUBSCRIPTION', null, capabilities()))
      .toMatchObject({ action: 'SET_ENABLED', enabled: false })
    expect(createTrackingManagementActionIntent(record, 'REFRESH_RSS', 'ASSOCIATED_RSS', null, capabilities()))
      .toMatchObject({ action: 'REFRESH_RSS', targetScope: 'ASSOCIATED_RSS' })
  })

  it('replays a locked intent only for the identical request, revision aside', () => {
    const record = enableDetail()
    const first = createTrackingSetEnabledIntent(record, 'SUBSCRIPTION', capabilities())!
    // The record moved on while the first request was in flight, so the fresh
    // intent carries another revision and another key. The request itself is
    // unchanged, which is exactly what a locked replay must recognise.
    const bumped = createTrackingSetEnabledIntent(
      { ...record, revision: 9 }, 'SUBSCRIPTION', capabilities(),
    )!
    expect(bumped.expectedRevision).toBe(9)
    expect(bumped.idempotencyKey).not.toBe(first.idempotencyKey)
    expect(sameManagementRequest(first, bumped)).toBe(true)

    // A different scope, a different direction or a different action is not the
    // same request, however identical the rest of the envelope looks.
    const otherScope = createTrackingSetEnabledIntent(record, 'ASSOCIATED_RSS', capabilities())!
    expect(sameManagementRequest(first, otherScope)).toBe(false)
    const otherDirection = createTrackingSetEnabledIntent(
      item({ status: 'ACTIVE', available_actions: [DISABLE_ACTION] }), 'ASSOCIATED_RSS', capabilities(),
    )!
    expect(otherDirection.enabled).toBe(false)
    expect(sameManagementRequest(otherScope, otherDirection)).toBe(false)
    const modify = createTrackingManagementIntent(item(), 'MODIFY', 'SUBSCRIPTION', { title: 'x' }, capabilities())!
    expect(sameManagementRequest(first, modify)).toBe(false)

    const otherPatch = createTrackingManagementIntent(item(), 'MODIFY', 'SUBSCRIPTION', { title: 'y' }, capabilities())!
    const samePatchLater = createTrackingManagementIntent(
      item({ revision: 9 }), 'MODIFY', 'SUBSCRIPTION', { title: 'x' }, capabilities(),
    )!
    expect(sameManagementRequest(modify, otherPatch)).toBe(false)
    expect(sameManagementRequest(modify, samePatchLater)).toBe(true)
  })
})

// -- US-315: per-record external delete --------------------------------------

const DELETE_ACTION = {
  code: 'DELETE_EXTERNAL', label: '删除外部订阅', style: 'DANGER',
  requires_confirmation: true, target_scopes: ['SUBSCRIPTION', 'ASSOCIATED_RSS'],
} satisfies ItemAction

describe('tracking external delete request (US-315)', () => {
  it('deletes exactly one explicitly chosen external object of this record', () => {
    const record = item({ available_actions: [DELETE_ACTION] })
    const intent = createTrackingDeleteExternalIntent(record, 'SUBSCRIPTION', capabilities())!
    expect(intent).toMatchObject({
      action: 'DELETE_EXTERNAL', targetScope: 'SUBSCRIPTION', patch: null, enabled: null,
      expectedRevision: 4, confirm: true,
    })
    const body = createTrackingManagementBody(intent, abConfig)
    expect(body).toEqual({
      target_scope: 'SUBSCRIPTION',
      expected_revision: 4,
      idempotency_key: intent.idempotencyKey,
      confirm: true,
      ab_config: abConfig,
    })
    // The generated delete body has no ``file`` field at all, and the intent
    // cannot carry a patch, a direction or a second scope.
    expect(Object.keys(body ?? {}).sort()).toEqual(
      ['target_scope', 'expected_revision', 'idempotency_key', 'confirm', 'ab_config'].sort(),
    )
    expect(serialize(body)).not.toContain('file')

    // A different scope is a different request, so a locked delete is replayed
    // only for the very scope the user confirmed.
    const rss = createTrackingDeleteExternalIntent(record, 'ASSOCIATED_RSS', capabilities())!
    expect(rss.targetScope).toBe('ASSOCIATED_RSS')
    expect(sameManagementRequest(intent, rss)).toBe(false)
    expect(sameManagementRequest(intent, createTrackingDeleteExternalIntent(
      { ...record, revision: 9 }, 'SUBSCRIPTION', capabilities(),
    )!)).toBe(true)
  })

  it('fails closed without the server action, the chosen scope or the capability', () => {
    // The server does not offer the delete for this record at all.
    expect(createTrackingDeleteExternalIntent(item(), 'SUBSCRIPTION', capabilities())).toBeNull()
    // The server offers only the subscription scope; the RSS choice is dropped.
    expect(createTrackingDeleteExternalIntent(
      item({ available_actions: [{ ...DELETE_ACTION, target_scopes: ['SUBSCRIPTION'] }] }),
      'ASSOCIATED_RSS', capabilities(),
    )).toBeNull()
    // A delete capability that is not proven for this very scope is no delete.
    for (const value of ['UNSUPPORTED', 'UNKNOWN'] as const) {
      expect(createTrackingDeleteExternalIntent(
        item({ available_actions: [DELETE_ACTION] }), 'SUBSCRIPTION',
        capabilities({ subscription_delete: value }),
      )).toBeNull()
      expect(createTrackingDeleteExternalIntent(
        item({ available_actions: [DELETE_ACTION] }), 'ASSOCIATED_RSS',
        capabilities({ rss_delete: value }),
      )).toBeNull()
    }
    expect(createTrackingDeleteExternalIntent(
      item({ available_actions: [DELETE_ACTION] }), 'SUBSCRIPTION',
      capabilities({ probe_status: 'PARTIAL' }),
    )).toBeNull()
    expect(createTrackingDeleteExternalIntent(
      item({ revision: 0, available_actions: [DELETE_ACTION] }), 'SUBSCRIPTION', capabilities(),
    )).toBeNull()
    // A scope the generated contract does not know can never become a request.
    expect(createTrackingDeleteExternalIntent(
      item({ available_actions: [DELETE_ACTION] }), 'EVERYTHING' as never, capabilities(),
    )).toBeNull()
  })

  it('confirms the delete as a danger that keeps every local record', () => {
    const intent = createTrackingDeleteExternalIntent(
      item({ available_actions: [DELETE_ACTION] }), 'SUBSCRIPTION', capabilities(),
    )!
    const copy = managementConfirmation(intent)
    expect(copy.danger).toBe(true)
    expect(copy.confirmLabel).toBe('确认删除外部对象')
    expect(copy.message).toContain('不会删除任何媒体文件')
    for (const kept of ['本地订阅方案', '追番记录', '审计记录', '下载任务', '已下载媒体文件']) {
      expect(copy.message).toContain(kept)
    }
    // The other management dialogs stay non-dangerous.
    const refresh = createTrackingRefreshRssIntent(item({ available_actions: [REFRESH_ACTION] }), capabilities())!
    expect(managementConfirmation(refresh).danger).toBeUndefined()
    expect(managementConfirmation(
      createTrackingSetEnabledIntent(enableDetail(), 'SUBSCRIPTION', capabilities())!,
    ).danger).toBeUndefined()
    expect(DELETE_EXTERNAL_HELP).toContain('没有勾选、批量或全局删除')
  })

  it('reports the delete outcome in its own wording and never claims a media delete', () => {
    const succeeded = projectManagementOutcome('tracking-1', 'DELETE_EXTERNAL', 'SUBSCRIPTION', modifyResult({
      action: 'DELETE_EXTERNAL', management_status: 'SUCCEEDED',
    }))
    expect(succeeded).toMatchObject({ action: 'DELETE_EXTERNAL', state: 'SUCCEEDED', needsManual: false })
    expect(succeeded.message).toContain('外部删除已完成')
    expect(succeeded.message).toContain('均保留')
    expect(succeeded.message).not.toContain('修改')

    const failed = projectManagementOutcome('tracking-1', 'DELETE_EXTERNAL', 'SUBSCRIPTION', modifyResult({
      action: 'DELETE_EXTERNAL', management_status: 'FAILED',
    }))
    expect(failed.state).toBe('FAILED')
    expect(failed.message).toContain('未删除该外部对象')

    // A partial or undocumented delete result stays unresolved and keeps the
    // page's single intent instead of being read as a successful delete.
    for (const status of ['PREPARED', 'IN_PROGRESS', 'OUTCOME_UNKNOWN', 'RECOVERY_REQUIRED']) {
      const session = projectManagementOutcome('tracking-1', 'DELETE_EXTERNAL', 'SUBSCRIPTION', modifyResult({
        action: 'DELETE_EXTERNAL', management_status: status as never,
      }))
      expect(session.state).toBe('UNKNOWN')
      expect(managementSessionKeepsIntent(session)).toBe(true)
      expect(session.message).not.toContain('已删除')
      expect(session.message).not.toContain(status)
    }

    const conflict = createManagementConflictSession(
      'tracking-1', 'DELETE_EXTERNAL', 'SUBSCRIPTION', 'tracking_target_missing',
    )
    expect(conflict.state).toBe('CONFLICT')
    expect(conflict.message).toContain('本次未删除任何外部对象')
    expect(managementSessionKeepsIntent(conflict)).toBe(false)
    const rejected = createManagementRejectedSession('tracking-1', 'DELETE_EXTERNAL', 'SUBSCRIPTION')
    expect(rejected.message).toContain('未删除 Auto Bangumi 外部对象')
  })
})

describe('tracking management copy and results (US-314)', () => {
  it('names the action, the scope and the direction in each confirmation', () => {
    const enable = createTrackingSetEnabledIntent(enableDetail(), 'SUBSCRIPTION', capabilities())!
    expect(managementConfirmation(enable)).toEqual({
      title: '启用 Auto Bangumi 番剧订阅',
      message: expect.stringContaining('不修改 MiGuOrca 本地方案'),
      confirmLabel: '确认启用订阅',
    })
    const disable = createTrackingSetEnabledIntent(
      item({ status: 'ACTIVE', available_actions: [DISABLE_ACTION] }), 'ASSOCIATED_RSS', capabilities(),
    )!
    const disableCopy = managementConfirmation(disable)
    expect(disableCopy.title).toContain('停用')
    expect(disableCopy.message).toContain('关联 RSS')
    expect(disableCopy.confirmLabel).toBe('确认停用 RSS')

    const refresh = createTrackingRefreshRssIntent(item({ available_actions: [REFRESH_ACTION] }), capabilities())!
    const refreshCopy = managementConfirmation(refresh)
    expect(refreshCopy.message).toContain('不会刷新全局 RSS')
    expect(refreshCopy.confirmLabel).toBe('确认刷新关联 RSS')

    const modify = createTrackingManagementIntent(item(), 'MODIFY', 'SUBSCRIPTION', { title: 'x' }, capabilities())!
    expect(managementConfirmation(modify)).toEqual(MODIFY_SCOPE_CONFIRMATIONS.SUBSCRIPTION)
  })

  it('reports success and definite failure in the wording of the action that was sent', () => {
    const enabled = projectManagementOutcome('tracking-1', 'SET_ENABLED', 'SUBSCRIPTION', modifyResult({
      action: 'SET_ENABLED', management_status: 'SUCCEEDED',
    }))
    expect(enabled).toMatchObject({ action: 'SET_ENABLED', state: 'SUCCEEDED', needsManual: false })
    expect(enabled.message).toContain('已应用本次启用或停用')
    expect(enabled.message).not.toContain('修改')

    const refreshed = projectManagementOutcome('tracking-1', 'REFRESH_RSS', 'ASSOCIATED_RSS', modifyResult({
      action: 'REFRESH_RSS', management_status: 'FAILED', safe_message: 'Auto Bangumi 未应用管理操作',
    }))
    expect(refreshed).toMatchObject({ action: 'REFRESH_RSS', state: 'FAILED' })
    expect(refreshed.message).toContain('未接受本次刷新')
    expect(refreshed.message).not.toContain('FAILED')
  })

  it('treats a partial, in-flight or undocumented result as unknown for every action', () => {
    for (const action of ['MODIFY', 'SET_ENABLED', 'REFRESH_RSS'] as const) {
      for (const status of ['PREPARED', 'IN_PROGRESS', 'OUTCOME_UNKNOWN', 'RECOVERY_REQUIRED']) {
        const session = projectManagementOutcome('tracking-1', action, 'SUBSCRIPTION', modifyResult({
          management_status: status as never,
        }))
        expect(session.state).toBe('UNKNOWN')
        expect(session.needsManual).toBe(true)
        expect(session.message).toContain('只读回查')
        expect(session.message).not.toContain('已应用')
        expect(session.message).not.toContain(status)
      }
    }
  })

  it('keeps the raw conflict type and the modify-only wording out of enable/refresh copy', () => {
    const conflict = createManagementConflictSession(
      'tracking-1', 'REFRESH_RSS', 'ASSOCIATED_RSS', 'tracking_management_patch_invalid',
    )
    expect(conflict.state).toBe('CONFLICT')
    expect(conflict.message).toContain('本次刷新请求未通过服务端校验')
    expect(conflict.message).not.toContain('修改内容')
    expect(conflict.message).not.toContain('tracking_management_patch_invalid')

    const enableConflict = createManagementConflictSession(
      'tracking-1', 'SET_ENABLED', 'SUBSCRIPTION', 'tracking_target_drift',
    )
    expect(enableConflict.message).toContain('外部对象已变化')
    expect(enableConflict.message).not.toContain('tracking_target_drift')

    const rejected = createManagementRejectedSession('tracking-1', 'SET_ENABLED', 'SUBSCRIPTION')
    expect(rejected.state).toBe('REJECTED')
    expect(rejected.message).toContain('未改变 Auto Bangumi 的启用状态')
    expect(rejected.message).not.toContain('修改')

    const inFlight = createManagementInFlightSession('tracking-1', 'REFRESH_RSS', 'ASSOCIATED_RSS')
    expect(inFlight.state).toBe('IN_FLIGHT')
    expect(inFlight.message).toContain('正在请求刷新关联 RSS')
  })
})
