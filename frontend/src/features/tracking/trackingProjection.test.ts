import { describe, expect, it } from 'vitest'

import {
  canVerifyExternally,
  createResubmitConfirmationBody,
  createResubmitSession,
  projectResubmitOffer,
  RESUBMIT_BLOCKED_FALLBACK_MESSAGE,
  RESUBMIT_BLOCKED_REASONS,
  RESUBMIT_CANCELLED_MESSAGE,
  RESUBMIT_CONFLICT_FALLBACK_MESSAGE,
  RESUBMIT_PENDING_UNKNOWN_RISK_MESSAGE,
  resubmitBindingFrom,
  resubmitConflictMessage,
  resubmitOfferState,
  resubmitRiskMessage,
  TRACKING_RESUBMIT_ENDPOINT,
  type TrackingResubmitResult,
  capabilityStateLabel,
  capabilityVersionLabel,
  DELETE_EXTERNAL_HELP,
  executableTrackingActions,
  filterTrackingItems,
  formatSubmissionMode,
  formatTrackingUpdatedAt,
  MANAGEMENT_ACTIONS_HELP,
  MODIFY_FORM_HELP,
  probeStatusLabel,
  projectCapabilitySummary,
  projectRevalidateIssues,
  projectStatusGroups,
  projectTrackingOverview,
  sortTrackingItems,
  type CapabilityResult,
  type TrackingItem,
  CHECK_PENDING_UNKNOWN_MESSAGE,
  checkSessionIsCurrent,
  createCheckSession,
  isPendingSubmission,
  isPendingSubmissionStatus,
  projectCheckResult,
  trackingCheckReason,
  trackingCheckReasonMessage,
  TRACKING_CHECK_ENDPOINT,
  TRACKING_CHECK_REASONS,
  type TrackingCheckResult,
} from './trackingProjection'

type ItemAction = NonNullable<TrackingItem['available_actions']>[number]

function item(overrides: Partial<TrackingItem> = {}): TrackingItem {
  return {
    tracking_id: 'tracking-1', request_id: 'request-1', title: '葬送的芙莉莲', season: 1,
    subtitle_group: '喵萌奶茶屋', poster_path: null, status: 'ACTIVE', status_label: '追番中',
    status_group: 'ACTIVE', submission_mode: null,
    available_actions: [], valid_resource_count: 2,
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
  it('keeps the overview total authoritative and never recounts loaded rows', () => {
    const result = projectTrackingOverview({
      total: 7, pending: 2, processing: 1, active: 3, added_to_download: 1,
      inactive: 1, needs_attention: 0, unreadable: 1,
    })
    expect(result.total).toBe(7)
    expect(result.unreadable).toBe(1)
  })

  it('fails closed to zero for a missing or malformed summary', () => {
    expect(projectTrackingOverview(null)).toEqual({ total: 0, unreadable: 0 })
    const malformed = projectTrackingOverview({
      total: -1, pending: 'x', active: Number.NaN, inactive: null, needs_attention: 2,
      processing: 0, unreadable: undefined,
    } as never)
    expect(malformed.total).toBe(0)
    expect(malformed.unreadable).toBe(0)
  })

  it('reads group labels, counts and card membership from server metadata (#224 A7)', () => {
    const groups = projectStatusGroups([
      { group: 'PENDING', label: '待处理', count: 4, has_overview_card: true },
      { group: 'PROCESSING', label: '处理中', count: 2, has_overview_card: false },
      { group: 'ACTIVE', label: '追番中', count: 3, has_overview_card: true },
      { group: 'ATTENTION', label: '需处理', count: 1, has_overview_card: true },
      { group: 'INACTIVE', label: '已停用', count: 1, has_overview_card: true },
    ])
    // Server order is preserved and exactly four groups render as cards.
    expect(groups.map((entry) => entry.label)).toEqual([
      '待处理', '处理中', '追番中', '需处理', '已停用',
    ])
    expect(groups.filter((entry) => entry.isCard).map((entry) => entry.group)).toEqual([
      'PENDING', 'ACTIVE', 'ATTENTION', 'INACTIVE',
    ])
    expect(groups[2]!.count).toBe(3)
  })

  it('fails closed on malformed group metadata instead of inventing labels', () => {
    expect(projectStatusGroups(null)).toEqual([])
    expect(projectStatusGroups([])).toEqual([])
    expect(projectStatusGroups([
      { group: 'BOGUS', label: '伪造', count: 1, has_overview_card: true },
      { group: 'ACTIVE', label: '', count: 1, has_overview_card: true },
      { group: 'ATTENTION', label: '需处理', count: -3, has_overview_card: 'yes' },
      { group: 'ATTENTION', label: '重复', count: 9, has_overview_card: true },
    ] as never)).toEqual([
      // Unknown group + empty label are dropped; the first valid entry wins for
      // a duplicated group, the count clamps to 0 and the card flag is strict.
      { group: 'ATTENTION', label: '需处理', count: 0, isCard: false },
    ])
  })

  it('formats a usable updated-at label and fails closed on bad values', () => {
    expect(formatTrackingUpdatedAt('2026-09-14T00:00:00Z')).toContain('2026')
    expect(formatTrackingUpdatedAt(null)).toBe('更新时间不可用')
    expect(formatTrackingUpdatedAt('')).toBe('更新时间不可用')
    expect(formatTrackingUpdatedAt('not-a-date')).toBe('更新时间不可用')
  })

  it('searches only public title/subtitle and applies server group filter', () => {
    const rows = [item(), item({ tracking_id: 'tracking-2', title: '咒术回战', subtitle_group: '风之圣殿', status_group: 'ATTENTION' })]
    expect(filterTrackingItems(rows, { query: '喵萌' })).toHaveLength(1)
    expect(filterTrackingItems(rows, { statusGroup: 'ATTENTION' })[0]?.tracking_id).toBe('tracking-2')
    expect(filterTrackingItems(rows, { query: 'tracking-1' })).toHaveLength(0)
  })

  it('keeps a retired EXTERNAL_ONLY archive out of every group filter (#224 A4)', () => {
    const rows = [
      item(),
      item({
        tracking_id: 'tracking-archive', title: '历史归档番', status: 'EXTERNAL_ONLY',
        status_label: '仅外部', status_group: 'INACTIVE',
      }),
    ]
    // 全部 (no group filter) still shows the historical record with its real label.
    expect(filterTrackingItems(rows, {})).toHaveLength(2)
    expect(filterTrackingItems(rows, {}).map((row) => row.status_label)).toContain('仅外部')
    // No card/group filter may return it, even though it maps to INACTIVE.
    expect(filterTrackingItems(rows, { statusGroup: 'INACTIVE' })).toHaveLength(0)
    // A plain search still runs over 全部, so the archive stays findable by name.
    expect(filterTrackingItems(rows, { query: '葬送' })).toHaveLength(1)
    expect(filterTrackingItems(rows, { query: '归档' })[0]?.tracking_id).toBe('tracking-archive')
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

  it('fails closed for unknown action/style/scope values', () => {
    const rows = item({ available_actions: [
      action(),
      action({ code: 'NOT_KNOWN' as never }),
      action({ style: 'NOT_KNOWN' as never }),
      action({ target_scopes: ['NOT_KNOWN'] as never }),
    ] })
    // Only the fully known action survives; unknown values are never guessed.
    expect(executableTrackingActions(rows)).toHaveLength(1)
    // Issues #86/#89: submission and management are never gated on a probe.
    expect(executableTrackingActions(item({ available_actions: [action({ code: 'SUBMIT', target_scopes: [] })] }))).toHaveLength(1)
  })

  it('projects every server-offered scope and keeps actions independent of the probe', () => {
    const current = item({ available_actions: [
      action({ target_scopes: ['SUBSCRIPTION', 'ASSOCIATED_RSS'] }),
      action({ code: 'SET_ENABLED', target_scopes: ['SUBSCRIPTION', 'ASSOCIATED_RSS'] }),
      action({ code: 'SUBMIT', target_scopes: [] }),
    ] })
    const projected = executableTrackingActions(current)
    // Issue #89: the server-projected scopes survive unchanged.
    expect(projected[0]?.target_scopes).toEqual(['SUBSCRIPTION', 'ASSOCIATED_RSS'])
    expect(projected.some((candidate) => candidate.code === 'SUBMIT')).toBe(true)
    // A scope-less management action has no control at all.
    expect(executableTrackingActions(item({ available_actions: [action({ target_scopes: [] })] }))).toHaveLength(0)
  })

  it('keeps enable and disable actions available for both directions', () => {
    const active = item({ status: 'ACTIVE', available_actions: [action({ code: 'SET_ENABLED', target_scopes: ['SUBSCRIPTION'] })] })
    const disabled = item({ status: 'DISABLED', available_actions: [action({ code: 'SET_ENABLED', target_scopes: ['SUBSCRIPTION'] })] })
    expect(executableTrackingActions(active)).toHaveLength(1)
    // The direction comes from the record's status, not from a probe.
    expect(executableTrackingActions(disabled)).toHaveLength(1)
    // A status that implies no direction keeps the action out.
    const pending = item({ status: 'PENDING_SUBMIT', available_actions: [action({ code: 'SET_ENABLED', target_scopes: ['SUBSCRIPTION'] })] })
    expect(executableTrackingActions(pending)).toHaveLength(1)
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

  it('offers the read-only external check only while a verified probe proves it', () => {
    expect(canVerifyExternally(capabilities())).toBe(true)
    expect(canVerifyExternally(null)).toBe(false)
    expect(canVerifyExternally(capabilities({ probe_status: 'FAILED' }))).toBe(false)
    expect(canVerifyExternally(capabilities({ external_verify: 'UNKNOWN' }))).toBe(false)
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

describe('submission mode display (issue #99 AC 6/7)', () => {
  it('labels a real operation-level mode and fails closed for everything else', () => {
    expect(formatSubmissionMode('CONTINUE_TRACKING')).toBe('持续追番')
    expect(formatSubmissionMode('DOWNLOAD_EXISTING')).toBe('下载现有资源')
    // 待提交/需修改 send null, and any unknown value must never be shown.
    for (const value of [null, undefined, '', 'UNKNOWN', 'SUBMIT', 42, {}]) {
      expect(formatSubmissionMode(value)).toBeNull()
    }
  })

  it('keeps the fixed, write-only help copy of every management section', () => {
    expect(MODIFY_FORM_HELP).toContain('不读取 Auto Bangumi 的当前值')
    expect(MANAGEMENT_ACTIONS_HELP).toContain('不修改 MiGuOrca 本地方案')
    expect(DELETE_EXTERNAL_HELP).toContain('没有勾选、批量或全局删除')
    expect(DELETE_EXTERNAL_HELP).toContain('不会删除任何媒体文件')
  })
})

const recoverableAction: ItemAction = {
  code: 'RECOVER_AUTO', label: '自动恢复', style: 'SECONDARY',
  requires_confirmation: false, target_scopes: [],
}

/** A recoverable record: the check projection only needs the item's shape. */
function recoverableItem(overrides: Partial<TrackingItem> = {}): TrackingItem {
  return item({
    status: 'RECOVERY_REQUIRED', status_label: '需要恢复', status_group: 'ATTENTION',
    available_actions: [recoverableAction], ...overrides,
  })
}

function checkResult(overrides: Partial<TrackingCheckResult> = {}): TrackingCheckResult {
  return {
    tracking_id: 'tracking-1', action: 'VERIFY_EXTERNAL', outcome: 'RECOVERY_REQUIRED',
    checked_revision: 3, next_revision: 4, checked_at: '2026-10-11T00:00:00Z',
    operation_id: 'operation-1', needs_manual: true, verification_reason: 'NOT_FOUND',
    tracking: recoverableItem({ revision: 4 }), ...overrides,
  }
}

describe('bounded read-only check projection (issue #183)', () => {
  it('binds one read-only endpoint and one proven reason vocabulary', () => {
    expect(TRACKING_CHECK_ENDPOINT).toBe('/api/v1/tracking/items/{tracking_id}/check')
    expect(TRACKING_CHECK_REASONS).toContain('CONNECTION_CHANGED')
    expect(trackingCheckReason('NOT_FOUND')).toBe('NOT_FOUND')
    // An unpublished reason never becomes a cause.
    for (const value of ['nope', '', null, undefined, 7, {}]) {
      expect(trackingCheckReason(value)).toBeNull()
      expect(trackingCheckReasonMessage(trackingCheckReason(value))).toBe(CHECK_PENDING_UNKNOWN_MESSAGE)
    }
  })

  it('routes only a persistent submit with an unproven result to the check flow', () => {
    expect(isPendingSubmission('VERIFYING_EXTERNAL', 'SUBMIT', 'CONTINUE_TRACKING')).toBe(true)
    expect(isPendingSubmission('RECOVERY_REQUIRED', 'SUBMIT', null)).toBe(true)
    // A decided result, another operation kind and a one-time request never do.
    expect(isPendingSubmission('ACTIVE', 'SUBMIT', 'CONTINUE_TRACKING')).toBe(false)
    expect(isPendingSubmission('SUBMIT_FAILED', 'SUBMIT', 'CONTINUE_TRACKING')).toBe(false)
    expect(isPendingSubmission('RECOVERY_REQUIRED', 'MODIFY', 'CONTINUE_TRACKING')).toBe(false)
    expect(isPendingSubmission('RECOVERY_REQUIRED', 'SUBMIT', 'DOWNLOAD_EXISTING')).toBe(false)
    expect(isPendingSubmissionStatus('RECOVERY_REQUIRED')).toBe(true)
    expect(isPendingSubmissionStatus('ACTIVE')).toBe(false)
  })

  it('projects a confirmed check without a reason and a pending one with it', () => {
    const confirmed = projectCheckResult('tracking-1', checkResult({ outcome: 'ACTIVE', verification_reason: null }), 3)
    expect(confirmed.state).toBe('CONFIRMED')
    expect(confirmed.reason).toBeNull()
    expect(confirmed.message).toContain('已确认')

    const pending = projectCheckResult('tracking-1', checkResult(), 3)
    expect(pending.state).toBe('PENDING')
    expect(pending.reason).toBe('NOT_FOUND')
    expect(pending.message).toBe(trackingCheckReasonMessage('NOT_FOUND'))

    const disabled = projectCheckResult('tracking-1', checkResult({ outcome: 'DISABLED', verification_reason: null }), 3)
    expect(disabled.state).toBe('CONFIRMED')
  })

  it('never lets a stale check result count as the current one', () => {
    const session = createCheckSession('tracking-1', 'PENDING', 'NOT_FOUND', 3)
    expect(checkSessionIsCurrent(session, 'tracking-1', 3)).toBe(true)
    expect(checkSessionIsCurrent(session, 'tracking-1', 4)).toBe(false)
    expect(checkSessionIsCurrent(session, 'tracking-2', 3)).toBe(false)
    expect(checkSessionIsCurrent(null, 'tracking-1', 3)).toBe(false)
  })

  it('states the in-flight and unreadable cases honestly', () => {
    expect(createCheckSession('tracking-1', 'IN_FLIGHT', null, 3).message).toContain('正在只读核验')
    expect(createCheckSession('tracking-1', 'UNKNOWN', null, 3).message).toContain('未确认前不会再次提交')
    expect(createCheckSession('tracking-1', 'CONFLICT', null, 3).message).toContain('最新详情')
  })
})


/**
 * Issue #184: the risk-confirmed resubmission's pure projections. The page never
 * invents a cause: every sentence comes from the server's proven code.
 */
function resubmitResult(overrides: Partial<TrackingResubmitResult> = {}): TrackingResubmitResult {
  return {
    tracking_id: 'tracking-1', confirm: false, check_status: 'UNRESOLVED',
    outcome: 'RECOVERY_REQUIRED', requires_risk_confirmation: true, blocked_reason: null,
    verification_reason: 'NOT_FOUND',
    binding: {
      expected_revision: 4,
      previous_operation_id: 'operation-1',
      connection_ref: '11111111-1111-4111-8111-111111111111',
    },
    checked_revision: 3, next_revision: 4, checked_at: '2026-10-11T00:00:00Z',
    operation_id: 'operation-1', previous_operation_id: null, failure_category: null,
    diagnostics: { http_status: null, message_zh: null, message_en: null },
    issues: [], tracking: item({ revision: 4 }), ...overrides,
  } as TrackingResubmitResult
}

describe('risk-confirmed resubmission projection (issue #184)', () => {
  it('binds one resubmit endpoint and fixed risk copy per proven reason', () => {
    expect(TRACKING_RESUBMIT_ENDPOINT).toBe('/api/v1/tracking/items/{tracking_id}/resubmit')
    expect(resubmitRiskMessage('NOT_FOUND')).toContain('重复订阅')
    expect(resubmitRiskMessage('UNREADABLE')).toContain('重复')
    expect(resubmitRiskMessage(null)).toBe(RESUBMIT_PENDING_UNKNOWN_RISK_MESSAGE)
    // A reason that can only be a refusal is never presented as a risk dialog.
    expect(resubmitRiskMessage('CONNECTION_CHANGED')).toBe(RESUBMIT_PENDING_UNKNOWN_RISK_MESSAGE)
    expect(resubmitRiskMessage('AUTHENTICATION')).toBe(RESUBMIT_PENDING_UNKNOWN_RISK_MESSAGE)
  })

  it('only treats an unresolved, explicitly offered binding as an authorization', () => {
    expect(resubmitBindingFrom(resubmitResult())).toEqual(resubmitResult().binding)
    expect(resubmitBindingFrom(resubmitResult({ check_status: 'CONFIRMED' }))).toBeNull()
    expect(resubmitBindingFrom(resubmitResult({ check_status: 'BLOCKED' }))).toBeNull()
    expect(resubmitBindingFrom(resubmitResult({ requires_risk_confirmation: false }))).toBeNull()
    expect(resubmitBindingFrom(resubmitResult({ binding: null }))).toBeNull()
  })

  it('builds the confirmation body from the server binding only', () => {
    const binding = resubmitResult().binding!
    expect(createResubmitConfirmationBody(binding, undefined)).toEqual({
      expected_revision: 4, confirm: true,
      previous_operation_id: 'operation-1',
      connection_ref: '11111111-1111-4111-8111-111111111111',
    })
    expect(createResubmitConfirmationBody(binding, 'profile-a')).toMatchObject({
      storage_dir: 'profile-a',
    })
  })

  it('routes a confirmed and a blocked read-only phase without a write', () => {
    const confirmed = projectResubmitOffer(
      'tracking-1',
      resubmitResult({ check_status: 'CONFIRMED', outcome: 'ACTIVE', verification_reason: null, requires_risk_confirmation: false }),
      3,
    )
    expect(confirmed.state).toBe('CONFIRMED')
    expect(confirmed.message).toContain('没有重新提交')

    const blocked = projectResubmitOffer(
      'tracking-1',
      resubmitResult({ check_status: 'BLOCKED', blocked_reason: 'EXTERNAL_WRITE_IN_PROGRESS', requires_risk_confirmation: false }),
      3,
    )
    expect(blocked.state).toBe('BLOCKED')
    expect(blocked.blockedReason).toBe('EXTERNAL_WRITE_IN_PROGRESS')
    expect(blocked.message).toContain('可能仍在执行')

    const oneTime = projectResubmitOffer(
      'tracking-1',
      resubmitResult({ check_status: 'BLOCKED', blocked_reason: 'ONE_TIME_SUBMISSION', requires_risk_confirmation: false }),
      3,
    )
    expect(oneTime.message).toContain('下载现有资源')
  })

  it('never publishes an unknown blocked reason as a specific cause', () => {
    const blocked = projectResubmitOffer(
      'tracking-1', resubmitResult({ check_status: 'BLOCKED', blocked_reason: 'something_new' }), 3,
    )
    expect(blocked.blockedReason).toBeNull()
    expect(blocked.message).toBe(RESUBMIT_BLOCKED_FALLBACK_MESSAGE)
  })

  it('maps every documented 409 to its own proven next step', () => {
    expect(resubmitConflictMessage('tracking_operation_in_progress'))
      .toContain('存在尚未完成的提交操作')
    expect(resubmitConflictMessage('tracking_state_conflict')).toContain('恢复核验')
    expect(resubmitConflictMessage('tracking_resubmit_binding_conflict')).toContain('绑定的操作或连接已变化')
    expect(resubmitConflictMessage('tracking_check_in_progress')).toContain('只读检查正在进行')
    for (const value of ['something_new', null, undefined, 7]) {
      expect(resubmitConflictMessage(value)).toBe(RESUBMIT_CONFLICT_FALLBACK_MESSAGE)
    }
  })

  it('never publishes an unproven refusal as an offerable reason', () => {
    expect(RESUBMIT_BLOCKED_REASONS).toContain('RESULT_UNPROVEN')
    expect(RESUBMIT_BLOCKED_REASONS).not.toContain('UNREADABLE')
    const blocked = projectResubmitOffer(
      'tracking-1', resubmitResult({ check_status: 'BLOCKED', blocked_reason: 'RESULT_UNPROVEN' }), 3,
    )
    expect(blocked.message).toContain('无法用已证实的原因')
  })

  it('states cancellation without claiming any external effect', () => {
    const cancelled = createResubmitSession('tracking-1', 'CANCELLED', 'NOT_FOUND', 3)
    expect(cancelled.message).toBe(RESUBMIT_CANCELLED_MESSAGE)
    expect(cancelled.message).toContain('没有向 Auto Bangumi 发起新的提交')
  })

  it('offers the resubmit only for a checkable pending submit', () => {
    expect(resubmitOfferState('VERIFYING_EXTERNAL', 'SUBMIT', 'OUTCOME_UNKNOWN', 'CONTINUE_TRACKING'))
      .toEqual({ available: true, hint: '' })
    expect(resubmitOfferState('RECOVERY_REQUIRED', 'SUBMIT', 'RECOVERY_REQUIRED', 'CONTINUE_TRACKING'))
      .toEqual({ available: true, hint: '' })
    // The external write may still be running, the operation is not a pending
    // submit, or the result is already decided: never offered, and the proven
    // next step is stated instead.
    expect(resubmitOfferState('VERIFYING_EXTERNAL', 'SUBMIT', 'IN_PROGRESS', 'CONTINUE_TRACKING'))
      .toEqual({ available: false, hint: expect.stringContaining('可能仍在执行') })
    expect(resubmitOfferState('VERIFYING_EXTERNAL', 'SUBMIT', 'PREPARED', 'CONTINUE_TRACKING').available).toBe(false)
    expect(resubmitOfferState('VERIFYING_EXTERNAL', 'MODIFY', 'OUTCOME_UNKNOWN', 'CONTINUE_TRACKING').available).toBe(false)
    expect(resubmitOfferState('ACTIVE', 'SUBMIT', 'SUCCEEDED', 'CONTINUE_TRACKING')).toEqual({ available: false, hint: '' })
    expect(resubmitOfferState('VERIFYING_EXTERNAL', 'SUBMIT', 'OUTCOME_UNKNOWN', 'DOWNLOAD_EXISTING').available).toBe(false)
  })
})
