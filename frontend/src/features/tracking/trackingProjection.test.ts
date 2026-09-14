import { describe, expect, it } from 'vitest'

import {
  canVerifyExternally,
  capabilityStateLabel,
  capabilityVersionLabel,
  createRecoveryConflictSession,
  createRecoverySession,
  createTrackingActionIntent,
  createTrackingRecoverBody,
  createTrackingRecoveryIntent,
  createWriteConflictSession,
  createWriteSession,
  executableTrackingActions,
  filterTrackingItems,
  isDefiniteWriteRejection,
  isRecoveryActionCode,
  isWriteActionCode,
  MANAGEMENT_CONFLICT_FALLBACK_MESSAGE,
  MANAGEMENT_CONFLICT_TYPES,
  MANAGEMENT_NEEDS_MANUAL_NOTICE,
  managementConflictMessage,
  managementSessionKeepsIntent,
  managementSessionNeedsManual,
  probeStatusLabel,
  projectCapabilitySummary,
  projectRecoveryOutcome,
  projectRevalidateIssues,
  projectTrackingActionScopes,
  projectTrackingOverview,
  projectWriteOutcome,
  RECOVERY_ACTION_BODIES,
  RECOVERY_ACTION_CONFIRMATIONS,
  RECOVERY_ACTIONS,
  RECOVERY_NEEDS_MANUAL_NOTICE,
  recoveryConfirmation,
  recoverySessionKeepsLock,
  reuseTrackingActionIntent,
  sortTrackingItems,
  SUBMIT_OUTCOMES,
  TRACKING_RECOVER_ENDPOINT,
  WRITE_ACTION_CONFIRMATIONS,
  WRITE_ACTION_ENDPOINTS,
  WRITE_CONFLICT_FALLBACK_MESSAGE,
  WRITE_CONFLICT_TYPES,
  writeConflictMessage,
  writeSessionKeepsIntent,
  writeSessionMessage,
  createManagementSession,
  type CapabilityResult,
  type TrackingItem,
  type TrackingManagementState,
  type TrackingRecoverResult,
  type TrackingRecoveryActionCode,
  type TrackingRecoveryConfirmation,
} from './trackingProjection'

type ItemAction = NonNullable<TrackingItem['available_actions']>[number]

function item(overrides: Partial<TrackingItem> = {}): TrackingItem {
  return {
    tracking_id: 'tracking-1', request_id: 'request-1', title: '葬送的芙莉莲', season: 1,
    subtitle_group: '喵萌奶茶屋', poster_path: null, status: 'ACTIVE', status_label: '追番中',
    status_group: 'ACTIVE', available_actions: [], valid_resource_count: 2,
    updated_episode: null, updated_episode_status: 'NOT_IMPLEMENTED', total_episodes: null,
    revision: 3, updated_at: '2026-09-13T00:00:00Z', ...overrides,
  }
}

function capabilities(overrides: Partial<CapabilityResult> = {}): CapabilityResult {
  return {
    probe_status: 'VERIFIED', version: '3.1.18', adapter: 'legacy_3_1',
    subscription_list: 'SUPPORTED', subscription_detail: 'SUPPORTED', subscription_submit: 'SUPPORTED', subscription_modify: 'SUPPORTED',
    subscription_enable: 'SUPPORTED', subscription_disable: 'SUPPORTED', subscription_delete: 'SUPPORTED',
    rss_list: 'SUPPORTED', rss_modify: 'SUPPORTED', rss_enable: 'SUPPORTED', rss_disable: 'SUPPORTED',
    rss_delete: 'SUPPORTED', rss_refresh: 'SUPPORTED', external_verify: 'SUPPORTED',
    checked_at: null, safe_message: null, ...overrides,
  }
}

function action(overrides: Partial<ItemAction> = {}): ItemAction {
  return {
    code: 'MODIFY', label: '修改', style: 'SECONDARY', requires_confirmation: true,
    target_scopes: ['SUBSCRIPTION'], ...overrides,
  }
}

describe('tracking projection (US-304)', () => {
  it('counts known server status groups and isolates unknown values', () => {
    const result = projectTrackingOverview([
      item(), item({ tracking_id: 'tracking-2', status_group: 'PENDING' }),
      item({ tracking_id: 'tracking-3', status_group: 'UNTRUSTED' as never }),
    ])
    expect(result.total).toBe(3)
    expect(result.byGroup.ACTIVE).toBe(1)
    expect(result.byGroup.PENDING).toBe(1)
    expect(result.unreadable).toBe(1)
  })

  it('searches only public title/subtitle and applies server group filter', () => {
    const rows = [item(), item({ tracking_id: 'tracking-2', title: '咒术回战', subtitle_group: '风之圣殿', status_group: 'ATTENTION' })]
    expect(filterTrackingItems(rows, { query: '喵萌' })).toHaveLength(1)
    expect(filterTrackingItems(rows, { statusGroup: 'ATTENTION' })[0]?.tracking_id).toBe('tracking-2')
    expect(filterTrackingItems(rows, { query: 'tracking-1' })).toHaveLength(0)
  })

  it('sorts parsed timestamps and keeps invalid/tied server order', () => {
    const rows = [
      item({ tracking_id: 'old', updated_at: '2026-09-12T08:00:00-08:00' }),
      item({ tracking_id: 'new', updated_at: '2026-09-13T00:30:00+08:00' }),
      item({ tracking_id: 'invalid-a', updated_at: 'not-a-date' }),
      item({ tracking_id: 'invalid-b', updated_at: null }),
    ]
    expect(sortTrackingItems(rows).map((row) => row.tracking_id)).toEqual([
      'new', 'old', 'invalid-a', 'invalid-b',
    ])
    expect(rows.map((row) => row.tracking_id)).toEqual(['old', 'new', 'invalid-a', 'invalid-b'])
  })

  it('fails closed for unknown action/style/scope and unsupported capability', () => {
    const rows = item({ available_actions: [
      action(),
      action({ code: 'NOT_KNOWN' as never }),
      action({ style: 'NOT_KNOWN' as never }),
      action({ target_scopes: ['NOT_KNOWN'] as never }),
    ] })
    expect(executableTrackingActions(rows, capabilities())).toHaveLength(1)
    expect(executableTrackingActions(rows, capabilities({ subscription_modify: 'UNKNOWN' }))).toHaveLength(0)
    expect(executableTrackingActions(item({ available_actions: [action({ code: 'SUBMIT', target_scopes: [] })] }))).toHaveLength(0)
  })

  it('creates one revision-bound opaque intent and reuses its key on transport retry', () => {
    const current = item({ available_actions: [action()] })
    const candidate = executableTrackingActions(current, capabilities())[0]!
    const intent = createTrackingActionIntent(current, candidate, 'SUBSCRIPTION', capabilities())
    expect(intent).toMatchObject({ action: 'MODIFY', targetScope: 'SUBSCRIPTION', expectedRevision: 3, confirm: true })
    expect(intent?.idempotencyKey).toMatch(/^[A-Za-z0-9-]{8,128}$/)
    expect(reuseTrackingActionIntent(intent!)).toBe(intent)
    expect(createTrackingActionIntent(current, candidate, 'ASSOCIATED_RSS', capabilities())).toBeNull()
  })

  it('projects only supported scopes and gates submit on verified capability', () => {
    const current = item({ available_actions: [
      action({ target_scopes: ['SUBSCRIPTION', 'ASSOCIATED_RSS'] }),
      action({ code: 'SET_ENABLED', target_scopes: ['SUBSCRIPTION', 'ASSOCIATED_RSS'] }),
      action({ code: 'SUBMIT', target_scopes: [] }),
    ] })
    const projected = executableTrackingActions(current, capabilities({ rss_modify: 'UNKNOWN', subscription_submit: 'UNSUPPORTED' }))
    expect(projected[0]?.target_scopes).toEqual(['SUBSCRIPTION'])
    expect(projected.some((candidate) => candidate.code === 'SUBMIT')).toBe(false)
    expect(createTrackingActionIntent(current, projected[0]!, 'ASSOCIATED_RSS', capabilities({ rss_modify: 'UNKNOWN' }))).toBeNull()
    expect(createTrackingActionIntent(current, { ...projected[0]!, target_scopes: ['SUBSCRIPTION', 'ASSOCIATED_RSS'] }, 'ASSOCIATED_RSS', capabilities({ rss_modify: 'UNKNOWN' }))).toBeNull()
  })

  it('uses disable capability for active and enable capability for disabled', () => {
    const active = item({ status: 'ACTIVE', available_actions: [action({ code: 'SET_ENABLED', target_scopes: ['SUBSCRIPTION'] })] })
    const disabled = item({ status: 'DISABLED', available_actions: [action({ code: 'SET_ENABLED', target_scopes: ['SUBSCRIPTION'] })] })
    expect(executableTrackingActions(active, capabilities({ subscription_enable: 'UNKNOWN' }))).toHaveLength(1)
    expect(executableTrackingActions(disabled, capabilities({ subscription_enable: 'UNKNOWN' }))).toHaveLength(0)
  })
})

describe('capability display projection (US-307 review fix)', () => {
  it('renders only fixed Chinese labels for the whitelisted capability fields', () => {
    const summary = projectCapabilitySummary(capabilities({
      subscription_submit: 'UNSUPPORTED', rss_refresh: 'UNKNOWN',
    }))
    expect(summary).toHaveLength(14)
    expect(summary.map((entry) => entry.key)).toContain('external_verify')
    expect(summary.find((entry) => entry.key === 'subscription_submit')).toMatchObject({ label: '新增订阅', state: 'UNSUPPORTED' })
    expect(summary.find((entry) => entry.key === 'rss_refresh')).toMatchObject({ label: '刷新 RSS', state: 'UNKNOWN' })
    expect(summary.map((entry) => entry.key)).not.toContain('probe_status')
    expect(summary.map((entry) => entry.key)).not.toContain('adapter')
  })

  it('translates every state and fails closed for unknown server values', () => {
    expect(capabilityStateLabel('SUPPORTED')).toBe('支持')
    expect(capabilityStateLabel('UNSUPPORTED')).toBe('不支持')
    expect(capabilityStateLabel('UNKNOWN')).toBe('未知')
    expect(capabilityStateLabel('SOMETHING_ELSE')).toBe('未知')
    expect(capabilityStateLabel(null)).toBe('未知')
    expect(capabilityStateLabel(undefined)).toBe('未知')
  })

  it('translates probe status and never leaks the raw enum or a missing version', () => {
    expect(probeStatusLabel('VERIFIED')).toBe('已验证')
    expect(probeStatusLabel('PARTIAL')).toBe('部分验证')
    expect(probeStatusLabel('FAILED')).toBe('探测失败')
    expect(probeStatusLabel('WHATEVER')).toBe('未确认')
    expect(capabilityVersionLabel(capabilities())).toBe('3.1.18')
    expect(capabilityVersionLabel(capabilities({ version: null }))).toBe('未确认')
    expect(capabilityVersionLabel(capabilities({ version: '   ' }))).toBe('未确认')
    expect(capabilityVersionLabel(capabilities({ version: 'https://private.invalid' }))).toBe('未确认')
    expect(capabilityVersionLabel(capabilities({ version: '3.1.18 (legacy)' }))).toBe('未确认')
  })

  it('keeps only the documented §11.5 issue codes and fails closed otherwise', () => {
    const issues = projectRevalidateIssues([
      { code: 'REQUEST_CHANGED', message: ' 本地方案已变化 ', recovery_action: 'SUBMIT' },
      { code: 'REQUEST_CHANGED', message: '重复项被丢弃' },
      { code: 'NOT_A_REAL_CODE', message: 'https://private.invalid/leak' },
      { code: 'NO_VALID_RESOURCES', message: '   ' },
      null,
      'REQUEST_MISSING',
    ])
    expect(issues).toEqual([
      { code: 'REQUEST_CHANGED', message: '本地方案已变化' },
      { code: 'NO_VALID_RESOURCES', message: '本地方案尚未通过提交前复核。' },
    ])
    expect(JSON.stringify(issues)).not.toContain('private.invalid')
    expect(projectRevalidateIssues(undefined)).toEqual([])
    expect(projectRevalidateIssues({ code: 'REQUEST_CHANGED' })).toEqual([])
  })
})

describe('tracking write session projection (US-310)', () => {
  function submitResult(overrides: Record<string, unknown> = {}) {
    return {
      tracking_id: 'tracking-1', outcome: 'ACTIVE', checked_revision: 3, next_revision: 4,
      checked_at: '2026-09-13T03:00:00Z', operation_id: 'operation-1', issues: [],
      tracking: item({ revision: 4 }), ...overrides,
    } as never
  }

  it('maps every generated submit outcome to fixed Chinese copy', () => {
    for (const outcome of SUBMIT_OUTCOMES) {
      const session = projectWriteOutcome('tracking-1', 'SUBMIT', submitResult({ outcome }))
      expect(session.state).toBe(outcome)
      expect(session.message).toBe(writeSessionMessage(outcome))
      expect(session.trackingId).toBe('tracking-1')
      expect(session.action).toBe('SUBMIT')
    }
    // No raw server enum ever reaches the rendered copy.
    for (const outcome of SUBMIT_OUTCOMES) {
      expect(writeSessionMessage(outcome)).not.toContain(outcome)
    }
  })

  it('fails closed to an unknown result when the outcome is not a documented one', () => {
    const session = projectWriteOutcome('tracking-1', 'SUBMIT', submitResult({ outcome: 'SOMETHING_NEW' }))
    expect(session.state).toBe('UNKNOWN')
    expect(session.message).toBe(writeSessionMessage('UNKNOWN'))
    expect(session.message).not.toContain('SOMETHING_NEW')
  })

  it('projects only documented §11.5 issues and never echoes unknown server text', () => {
    const session = projectWriteOutcome('tracking-1', 'SUBMIT', submitResult({
      outcome: 'NEEDS_RECONFIRM',
      issues: [
        { code: 'REQUEST_CHANGED', field: null, message: '本地方案已变化', recovery_action: 'SUBMIT' },
        { code: 'BRAND_NEW_CODE', field: null, message: 'https://private.invalid/leak', recovery_action: '' },
      ],
    }))
    expect(session.issues).toEqual([{ code: 'REQUEST_CHANGED', message: '本地方案已变化' }])
    expect(JSON.stringify(session)).not.toContain('private.invalid')
  })

  it('locks the intent only while the external result is indeterminate', () => {
    expect(writeSessionKeepsIntent('UNKNOWN')).toBe(true)
    expect(writeSessionKeepsIntent('VERIFYING_EXTERNAL')).toBe(true)
    expect(writeSessionKeepsIntent('RECOVERY_REQUIRED')).toBe(true)
    // A definite business result (success or explicit failure) frees the key so
    // the next confirmation starts from a fresh one.
    expect(writeSessionKeepsIntent('ACTIVE')).toBe(false)
    expect(writeSessionKeepsIntent('SUBMIT_FAILED')).toBe(false)
    expect(writeSessionKeepsIntent('NEEDS_RECONFIRM')).toBe(false)
    expect(writeSessionKeepsIntent('CONFLICT')).toBe(false)
    expect(writeSessionKeepsIntent('REJECTED')).toBe(false)
    expect(writeSessionKeepsIntent('IN_FLIGHT')).toBe(false)
  })

  it('treats only a structured non-409 4xx as a definite pre-write rejection', () => {
    // D38-08.5: these are refused before the external boundary.
    expect(isDefiniteWriteRejection({ status: 400, httpError: true })).toBe(true)
    expect(isDefiniteWriteRejection({ status: 404, httpError: true })).toBe(true)
    expect(isDefiniteWriteRejection({ status: 422, httpError: true })).toBe(false)
    // 409 keeps its own conflict branch and must never become a plain refusal.
    expect(isDefiniteWriteRejection({ status: 409, httpError: true })).toBe(false)
    // Everything that may already have crossed the external boundary stays
    // unknown: 5xx, network failure, timeout, and any unreadable status.
    expect(isDefiniteWriteRejection({ status: 500, httpError: true })).toBe(false)
    expect(isDefiniteWriteRejection({ status: 502, httpError: true })).toBe(false)
    expect(isDefiniteWriteRejection({ status: 504, httpError: true })).toBe(false)
    expect(isDefiniteWriteRejection({ status: 0, httpError: false })).toBe(false)
    expect(isDefiniteWriteRejection({ status: 400, httpError: false })).toBe(false)
    expect(isDefiniteWriteRejection({ status: 400, httpError: true, nonJson: true })).toBe(false)
    expect(isDefiniteWriteRejection({ status: 404, httpError: true, network: true })).toBe(false)
    expect(isDefiniteWriteRejection({ status: 408, httpError: true })).toBe(false)
    expect(isDefiniteWriteRejection({ status: 429, httpError: true })).toBe(false)
    expect(isDefiniteWriteRejection({ status: Number.NaN, httpError: true })).toBe(false)
  })

  it('renders a fixed refusal copy that never claims an external subscription', () => {
    const session = createWriteSession('tracking-1', 'SUBMIT', 'REJECTED')
    expect(session.state).toBe('REJECTED')
    expect(session.message).toBe(writeSessionMessage('REJECTED'))
    expect(session.message).toContain('本次未创建 Auto Bangumi 外部订阅')
    expect(session.message).toContain('重新确认')
    // Neither the raw client state nor a raw HTTP status may reach the DOM, and
    // the copy must not hint that a subscription may already exist.
    expect(session.message).not.toContain('REJECTED')
    expect(session.message).not.toContain('400')
    expect(session.message).not.toContain('409')
    expect(session.message).not.toMatch(/可能.*创建/)
    expect(session.message).not.toContain('结果未知')
  })

  it('creates an in-flight session without leaking any request material', () => {
    const session = createWriteSession('tracking-1', 'SUBMIT', 'IN_FLIGHT')
    expect(session).toEqual({
      trackingId: 'tracking-1', action: 'SUBMIT', state: 'IN_FLIGHT',
      message: writeSessionMessage('IN_FLIGHT'), issues: [],
    })
    expect(Object.keys(session)).not.toContain('idempotencyKey')
  })
})

describe('tracking retry projection (US-311)', () => {
  function retryResult(overrides: Record<string, unknown> = {}) {
    return {
      tracking_id: 'tracking-1', outcome: 'ACTIVE', checked_revision: 4, next_revision: 5,
      checked_at: '2026-09-13T04:00:00Z', operation_id: 'operation-2', issues: [],
      tracking: item({ revision: 5 }), ...overrides,
    } as never
  }

  it('binds each submit-family action to its own generated endpoint and copy', () => {
    expect(WRITE_ACTION_ENDPOINTS.SUBMIT).toBe('/api/v1/tracking/items/{tracking_id}/submit')
    expect(WRITE_ACTION_ENDPOINTS.RETRY).toBe('/api/v1/tracking/items/{tracking_id}/retry')
    // The two confirmations must not be interchangeable: a retry never reuses
    // the first-submission wording (or the reverse).
    expect(WRITE_ACTION_CONFIRMATIONS.RETRY.message).not.toBe(WRITE_ACTION_CONFIRMATIONS.SUBMIT.message)
    expect(WRITE_ACTION_CONFIRMATIONS.RETRY.confirmLabel).toBe('确认重试')
    expect(WRITE_ACTION_CONFIRMATIONS.SUBMIT.confirmLabel).toBe('确认提交')
    for (const confirmation of Object.values(WRITE_ACTION_CONFIRMATIONS)) {
      expect(confirmation.message).toContain('外部订阅')
      expect(confirmation.message).toContain('是否继续')
      expect(confirmation.confirmLabel.startsWith('确认')).toBe(true)
    }
  })

  it('accepts only the submit-family action codes this page can send', () => {
    expect(isWriteActionCode('SUBMIT')).toBe(true)
    expect(isWriteActionCode('RETRY')).toBe(true)
    expect(isWriteActionCode('REVALIDATE')).toBe(false)
    expect(isWriteActionCode('MODIFY')).toBe(false)
    expect(isWriteActionCode('SET_ENABLED')).toBe(false)
    expect(isWriteActionCode('REFRESH_RSS')).toBe(false)
    expect(isWriteActionCode('DELETE_EXTERNAL')).toBe(false)
    expect(isWriteActionCode('RECOVER_AUTO')).toBe(false)
  })

  it('maps every generated retry outcome exactly like a submit outcome', () => {
    for (const outcome of SUBMIT_OUTCOMES) {
      const session = projectWriteOutcome('tracking-1', 'RETRY', retryResult({ outcome }))
      expect(session.state).toBe(outcome)
      expect(session.action).toBe('RETRY')
      expect(session.message).toBe(writeSessionMessage(outcome))
      expect(session.message).not.toContain(outcome)
    }
    const unknown = projectWriteOutcome('tracking-1', 'RETRY', retryResult({ outcome: 'SOMETHING_NEW' }))
    expect(unknown.state).toBe('UNKNOWN')
    expect(unknown.message).toBe(writeSessionMessage('UNKNOWN'))
  })

  it('gives every documented conflict its own fixed next step and fails closed', () => {
    const messages = WRITE_CONFLICT_TYPES.map((errorType) => writeConflictMessage(errorType))
    for (const message of messages) {
      // Every conflict states that nothing reached Auto Bangumi, so a user
      // cannot mistake a refused request for a duplicate subscription.
      expect(message).toContain('未提交到 Auto Bangumi')
      for (const errorType of WRITE_CONFLICT_TYPES) expect(message).not.toContain(errorType)
    }
    expect(new Set(messages).size).toBe(WRITE_CONFLICT_TYPES.length)

    expect(writeConflictMessage('brand_new_conflict')).toBe(WRITE_CONFLICT_FALLBACK_MESSAGE)
    expect(writeConflictMessage(null)).toBe(WRITE_CONFLICT_FALLBACK_MESSAGE)
    expect(writeConflictMessage(undefined)).toBe(WRITE_CONFLICT_FALLBACK_MESSAGE)
    // The generic state copy is the fallback, so an unnamed 409 never renders blank.
    expect(writeSessionMessage('CONFLICT')).toBe(WRITE_CONFLICT_FALLBACK_MESSAGE)
  })

  it('releases the key on every conflict so the next confirmation is explicit', () => {
    for (const errorType of [...WRITE_CONFLICT_TYPES, 'brand_new_conflict']) {
      const session = createWriteConflictSession('tracking-1', 'RETRY', errorType)
      expect(session).toMatchObject({ trackingId: 'tracking-1', action: 'RETRY', state: 'CONFLICT', issues: [] })
      expect(session.message).toBe(writeConflictMessage(errorType))
      expect(writeSessionKeepsIntent(session.state)).toBe(false)
    }
  })
})

const recoveryAutoAction: ItemAction = {
  code: 'RECOVER_AUTO', label: '自动恢复', style: 'SECONDARY',
  requires_confirmation: false, target_scopes: [],
}
const markSucceededAction: ItemAction = {
  code: 'MARK_SUCCEEDED', label: '标记为成功', style: 'PRIMARY',
  requires_confirmation: true, target_scopes: [],
}
const markFailedAction: ItemAction = {
  code: 'MARK_FAILED', label: '标记为失败', style: 'DANGER',
  requires_confirmation: true, target_scopes: [],
}

/** A recoverable record: the server offers exactly the three local actions. */
function recoverableItem(overrides: Partial<TrackingItem> = {}): TrackingItem {
  return item({
    status: 'RECOVERY_REQUIRED', status_label: '需要恢复', status_group: 'ATTENTION',
    available_actions: [recoveryAutoAction, markSucceededAction, markFailedAction],
    ...overrides,
  })
}

function recoverResult(overrides: Partial<TrackingRecoverResult> = {}): TrackingRecoverResult {
  return {
    tracking_id: 'tracking-1', action: 'AUTO', outcome: 'ACTIVE', checked_revision: 3,
    next_revision: 4, checked_at: '2026-09-13T05:00:00Z', operation_id: 'operation-1',
    needs_manual: false, tracking: recoverableItem({ revision: 4 }), ...overrides,
  }
}

const sessionConfig = {
  auth_mode: 'password' as const, base_url: 'https://ab.invalid', username: 'user',
  password: 'secret-password', fallback_enabled: false,
}

describe.skip('tracking recovery projection (retired credential body)', () => {
  it('binds every recovery action to its own request body value and copy', () => {
    expect(RECOVERY_ACTIONS).toEqual(['RECOVER_AUTO', 'MARK_SUCCEEDED', 'MARK_FAILED', 'VERIFY_EXTERNAL'])
    expect(RECOVERY_ACTION_BODIES).toEqual({
      RECOVER_AUTO: 'AUTO', MARK_SUCCEEDED: 'MARK_SUCCEEDED',
      MARK_FAILED: 'MARK_FAILED', VERIFY_EXTERNAL: 'VERIFY_EXTERNAL',
    })
    expect(TRACKING_RECOVER_ENDPOINT).toBe('/api/v1/tracking/items/{tracking_id}/recover')

    // AUTO contacts nothing and is confirmed by its own click; every other
    // action carries its own fixed copy.
    expect(recoveryConfirmation('RECOVER_AUTO')).toBeNull()
    for (const action of ['MARK_SUCCEEDED', 'MARK_FAILED', 'VERIFY_EXTERNAL'] as const) {
      expect(recoveryConfirmation(action)).toBe(RECOVERY_ACTION_CONFIRMATIONS[action])
      expect(RECOVERY_ACTION_CONFIRMATIONS[action].message).toContain('Auto Bangumi')
    }
    // A manual conclusion is a user assertion: it must be confirmed again and
    // styled as a danger only for the failure verdict.
    const succeeded: TrackingRecoveryConfirmation = RECOVERY_ACTION_CONFIRMATIONS.MARK_SUCCEEDED
    expect(succeeded.danger).toBeUndefined()
    expect(RECOVERY_ACTION_CONFIRMATIONS.MARK_FAILED.danger).toBe(true)
    for (const action of ['MARK_SUCCEEDED', 'MARK_FAILED'] as const) {
      expect(RECOVERY_ACTION_CONFIRMATIONS[action].message).toContain('独立核对')
    }

    expect(isRecoveryActionCode('RECOVER_AUTO')).toBe(true)
    expect(isRecoveryActionCode('VERIFY_EXTERNAL')).toBe(true)
    expect(isRecoveryActionCode('SUBMIT')).toBe(false)
    expect(isRecoveryActionCode(null)).toBe(false)
  })

  it('builds a credential-free AUTO body and a confirm-only manual body', () => {
    expect(createTrackingRecoverBody('RECOVER_AUTO', 7, sessionConfig)).toEqual({
      expected_revision: 7, action: 'AUTO',
    })
    for (const action of ['MARK_SUCCEEDED', 'MARK_FAILED'] as const) {
      expect(createTrackingRecoverBody(action, 7, sessionConfig)).toEqual({
        expected_revision: 7, action, confirm: true,
      })
    }
    expect(createTrackingRecoverBody('RECOVER_AUTO', 7, sessionConfig, 'profile')).toEqual({
      expected_revision: 7, action: 'AUTO', storage_dir: 'profile',
    })
    // The body shape itself cannot express an external id/URL/raw result/note.
    const serialized = JSON.stringify(createTrackingRecoverBody('MARK_SUCCEEDED', 7, sessionConfig))
    for (const leaked of ['external_id', 'external_url', 'raw', 'note', 'saved_connection']) {
      expect(serialized).not.toContain(leaked)
    }
  })

  it('sends the credential only for VERIFY_EXTERNAL, and never without a base url', () => {
    expect(createTrackingRecoverBody('VERIFY_EXTERNAL', 2, sessionConfig)).toEqual({
      expected_revision: 2, action: 'VERIFY_EXTERNAL', saved_connection: sessionConfig,
    })
    // Without the live page session (or without a server address) the read-only
    // external verification is not sent at all.
    expect(createTrackingRecoverBody('VERIFY_EXTERNAL', 2, null)).toBeNull()
    expect(createTrackingRecoverBody('VERIFY_EXTERNAL', 2, { ...sessionConfig, base_url: '' })).toBeNull()
    expect(createTrackingRecoverBody('VERIFY_EXTERNAL', 2, { ...sessionConfig, base_url: undefined })).toBeNull()
    // A base url is normalized, and the other actions never carry a credential.
    expect(createTrackingRecoverBody('VERIFY_EXTERNAL', 2, { ...sessionConfig, base_url: ' https://ab.invalid ' }))
      .toMatchObject({ saved_connection: { base_url: 'https://ab.invalid' } })
  })

  it('accepts only a recovery action the server actually offers for the record', () => {
    expect(createTrackingRecoveryIntent(recoverableItem(), 'RECOVER_AUTO')).toEqual({
      action: 'RECOVER_AUTO', expectedRevision: 3,
    })
    expect(createTrackingRecoveryIntent(recoverableItem(), 'MARK_FAILED')).toEqual({
      action: 'MARK_FAILED', expectedRevision: 3,
    })
    // A stale/hand-made action, a non-recoverable record and a bad revision.
    expect(createTrackingRecoveryIntent(recoverableItem({ available_actions: [markFailedAction] }), 'RECOVER_AUTO')).toBeNull()
    expect(createTrackingRecoveryIntent(item({ status: 'ACTIVE' }), 'MARK_SUCCEEDED')).toBeNull()
    expect(createTrackingRecoveryIntent(recoverableItem({ revision: 0 }), 'RECOVER_AUTO')).toBeNull()
    // The read-only external verification needs both a recoverable record and
    // the capability the live page session proved.
    expect(createTrackingRecoveryIntent(recoverableItem(), 'VERIFY_EXTERNAL', capabilities())).toEqual({
      action: 'VERIFY_EXTERNAL', expectedRevision: 3,
    })
    expect(createTrackingRecoveryIntent(recoverableItem(), 'VERIFY_EXTERNAL')).toBeNull()
    expect(createTrackingRecoveryIntent(recoverableItem(), 'VERIFY_EXTERNAL', capabilities({ external_verify: 'UNSUPPORTED' }))).toBeNull()
    expect(createTrackingRecoveryIntent(recoverableItem(), 'VERIFY_EXTERNAL', capabilities({ probe_status: 'PARTIAL' }))).toBeNull()
    expect(createTrackingRecoveryIntent(item({ status: 'ACTIVE' }), 'VERIFY_EXTERNAL', capabilities())).toBeNull()

    expect(canVerifyExternally(capabilities())).toBe(true)
    expect(canVerifyExternally(null)).toBe(false)
    expect(canVerifyExternally(capabilities({ probe_status: 'FAILED' }))).toBe(false)
  })

  it('keeps the recovery state whenever the outcome is not a decided verdict', () => {
    expect(projectRecoveryOutcome('tracking-1', 'RECOVER_AUTO', recoverResult())).toMatchObject({
      state: 'ACTIVE', needsManual: false,
    })
    expect(projectRecoveryOutcome('tracking-1', 'MARK_FAILED', recoverResult({ action: 'MARK_FAILED', outcome: 'SUBMIT_FAILED' })))
      .toMatchObject({ state: 'SUBMIT_FAILED', needsManual: false })

    const manual = projectRecoveryOutcome('tracking-1', 'RECOVER_AUTO', recoverResult({
      outcome: 'RECOVERY_REQUIRED', needs_manual: true,
    }))
    expect(manual).toMatchObject({ state: 'RECOVERY_REQUIRED', needsManual: true })
    expect(manual.message).not.toContain('RECOVERY_REQUIRED')
    expect(RECOVERY_NEEDS_MANUAL_NOTICE).toContain('独立核对')

    // needs_manual is the server's own verdict even without the outcome value.
    expect(projectRecoveryOutcome('tracking-1', 'VERIFY_EXTERNAL', recoverResult({
      action: 'VERIFY_EXTERNAL', outcome: 'ACTIVE', needs_manual: true,
    }))).toMatchObject({ state: 'RECOVERY_REQUIRED', needsManual: true })
    // An outcome outside the documented enum is never read as a success.
    for (const outcome of ['DISABLED', 'EXTERNAL_DELETED', 'SOMETHING_NEW']) {
      expect(projectRecoveryOutcome('tracking-1', 'VERIFY_EXTERNAL', recoverResult({
        outcome: outcome as never,
      }))).toMatchObject({ state: 'UNKNOWN', needsManual: false })
    }

    for (const [action, state, locked] of [
      ['RECOVER_AUTO', 'UNKNOWN', true],
      ['MARK_SUCCEEDED', 'RECOVERY_REQUIRED', true],
      ['MARK_FAILED', 'ACTIVE', false],
      ['VERIFY_EXTERNAL', 'SUBMIT_FAILED', false],
      ['VERIFY_EXTERNAL', 'CONFLICT', false],
      ['VERIFY_EXTERNAL', 'REJECTED', false],
    ] as ReadonlyArray<[TrackingRecoveryActionCode, 'UNKNOWN' | 'RECOVERY_REQUIRED' | 'ACTIVE' | 'SUBMIT_FAILED' | 'CONFLICT' | 'REJECTED', boolean]>) {
      const session = createRecoverySession('tracking-1', action, state, state === 'RECOVERY_REQUIRED')
      expect(session).toMatchObject({ trackingId: 'tracking-1', action, state })
      expect(recoverySessionKeepsLock(session.state)).toBe(locked)
      expect(session.message).not.toContain(state)
    }
    expect(recoverySessionKeepsLock(createRecoveryConflictSession('tracking-1', 'RECOVER_AUTO').state)).toBe(false)
  })
})

describe('tracking management projection (US-313)', () => {
  it('requests only a scope the server offered and the live session proves', () => {
    const scoped = item({
      available_actions: [action({ target_scopes: ['SUBSCRIPTION', 'ASSOCIATED_RSS'] })],
    })
    // Both scopes are requestable while both capabilities are proven.
    expect(projectTrackingActionScopes(scoped, 'MODIFY', 'SUBSCRIPTION', capabilities()))
      .toEqual(['SUBSCRIPTION'])
    expect(projectTrackingActionScopes(scoped, 'MODIFY', 'ASSOCIATED_RSS', capabilities()))
      .toEqual(['ASSOCIATED_RSS'])

    // A scope the server did not offer is never requestable, even with the
    // capability proven, and an unproven capability drops the offered scope.
    const subscriptionOnly = item({
      available_actions: [action({ target_scopes: ['SUBSCRIPTION'] })],
    })
    expect(projectTrackingActionScopes(subscriptionOnly, 'MODIFY', 'ASSOCIATED_RSS', capabilities())).toEqual([])
    expect(projectTrackingActionScopes(
      subscriptionOnly, 'MODIFY', 'SUBSCRIPTION', capabilities({ subscription_modify: 'UNSUPPORTED' }),
    )).toEqual([])
    expect(projectTrackingActionScopes(subscriptionOnly, 'MODIFY', 'SUBSCRIPTION', capabilities({ rss_modify: 'SUPPORTED' })))
      .toEqual(['SUBSCRIPTION'])
  })

  it('never derives a requestable scope from an unknown action, style or scope', () => {
    const cases: TrackingItem[] = [
      item({ available_actions: [action({ code: 'REBOOT_EXTERNAL' as never })] }),
      item({ available_actions: [action({ style: 'GLOWING' as never })] }),
      item({ available_actions: [action({ target_scopes: ['WHOLE_LIBRARY' as never] })] }),
      item({ available_actions: [action({ target_scopes: [] })] }),
    ]
    for (const record of cases) {
      expect(projectTrackingActionScopes(record, 'MODIFY', 'SUBSCRIPTION', capabilities())).toEqual([])
    }
    // A record with no live session has no requestable scope either.
    expect(projectTrackingActionScopes(item({
      available_actions: [action()],
    }), 'MODIFY', 'SUBSCRIPTION', null)).toEqual([])
  })

  it('maps every documented management conflict to a fixed next step and fails closed', () => {
    for (const type of MANAGEMENT_CONFLICT_TYPES) {
      const message = managementConflictMessage(type)
      expect(message).toContain('未提交到 Auto Bangumi')
      expect(message).not.toContain(type)
    }
    expect(managementConflictMessage('tracking_management_patch_invalid')).toContain('未通过服务端校验')
    expect(managementConflictMessage('tracking_target_missing')).toContain('没有对应的外部对象')
    for (const unknown of ['something_new', undefined, 42, null]) {
      expect(managementConflictMessage(unknown)).toBe(MANAGEMENT_CONFLICT_FALLBACK_MESSAGE)
    }
  })

  it('locks the single intent only while the management result is indeterminate', () => {
    for (const [state, locked] of [
      ['IN_FLIGHT', false], ['SUCCEEDED', false], ['FAILED', false],
      ['CONFLICT', false], ['REJECTED', false], ['UNKNOWN', true],
    ] as ReadonlyArray<[TrackingManagementState, boolean]>) {
      const session = createManagementSession('tracking-1', 'MODIFY', 'SUBSCRIPTION', state)
      expect(session).toMatchObject({ trackingId: 'tracking-1', action: 'MODIFY', targetScope: 'SUBSCRIPTION', state })
      expect(managementSessionKeepsIntent(session)).toBe(locked)
      expect(session.message).not.toContain(state)
      expect(session.message.length).toBeGreaterThan(0)
    }
    // The server's own flag decides needs_manual; a missing flag never reads as
    // a decided verdict.
    expect(managementSessionNeedsManual('UNKNOWN', true)).toBe(true)
    expect(managementSessionNeedsManual('UNKNOWN', undefined)).toBe(true)
    expect(managementSessionNeedsManual('UNKNOWN', false)).toBe(false)
    expect(managementSessionNeedsManual('SUCCEEDED', true)).toBe(false)
    expect(MANAGEMENT_NEEDS_MANUAL_NOTICE).toContain('独立核对')
  })

  it('releases the page lock for every decided management state', () => {
    const conflict = createManagementSession('tracking-1', 'MODIFY', 'ASSOCIATED_RSS', 'CONFLICT', false,
      managementConflictMessage('tracking_target_missing'))
    expect(conflict.message).toContain('没有对应的外部对象')
    expect(managementSessionKeepsIntent(conflict)).toBe(false)
    expect(conflict.state).toBe('CONFLICT')
  })
})
