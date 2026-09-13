import { describe, expect, it } from 'vitest'

import {
  capabilityStateLabel,
  capabilityVersionLabel,
  createTrackingActionIntent,
  createWriteConflictSession,
  createWriteSession,
  executableTrackingActions,
  filterTrackingItems,
  isWriteActionCode,
  probeStatusLabel,
  projectCapabilitySummary,
  projectRevalidateIssues,
  projectTrackingOverview,
  projectWriteOutcome,
  reuseTrackingActionIntent,
  sortTrackingItems,
  SUBMIT_OUTCOMES,
  WRITE_ACTION_CONFIRMATIONS,
  WRITE_ACTION_ENDPOINTS,
  WRITE_CONFLICT_FALLBACK_MESSAGE,
  WRITE_CONFLICT_TYPES,
  writeConflictMessage,
  writeSessionKeepsIntent,
  writeSessionMessage,
  type CapabilityResult,
  type TrackingItem,
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
    expect(writeSessionKeepsIntent('IN_FLIGHT')).toBe(false)
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
