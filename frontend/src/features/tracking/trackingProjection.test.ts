import { describe, expect, it } from 'vitest'

import {
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
  projectTrackingOverview,
  sortTrackingItems,
  type CapabilityResult,
  type TrackingItem,
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
  it('projects the overview from the server summary, never from loaded rows', () => {
    const result = projectTrackingOverview({
      total: 7, pending: 2, processing: 1, active: 3, added_to_download: 1,
      inactive: 1, needs_attention: 0, unreadable: 1,
    })
    expect(result.total).toBe(7)
    // Issue #99: 已加入下载 is the fifth fixed overview category, counted
    // separately from 追番中 by the server.
    expect(result.byGroup).toEqual({
      PENDING: 2, ACTIVE: 3, INACTIVE: 1, ADDED_TO_DOWNLOAD: 1, ATTENTION: 0,
    })
    expect(result.unreadable).toBe(1)
  })

  it('fails closed to zero for a missing or malformed summary', () => {
    expect(projectTrackingOverview(null)).toEqual({
      total: 0,
      byGroup: { PENDING: 0, ACTIVE: 0, INACTIVE: 0, ADDED_TO_DOWNLOAD: 0, ATTENTION: 0 },
      unreadable: 0,
    })
    const malformed = projectTrackingOverview({
      total: -1, pending: 'x', active: Number.NaN, inactive: null, needs_attention: 2,
      processing: 0, unreadable: undefined,
    } as never)
    expect(malformed.total).toBe(0)
    expect(malformed.byGroup).toEqual({
      PENDING: 0, ACTIVE: 0, INACTIVE: 0, ADDED_TO_DOWNLOAD: 0, ATTENTION: 2,
    })
    expect(malformed.unreadable).toBe(0)
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
