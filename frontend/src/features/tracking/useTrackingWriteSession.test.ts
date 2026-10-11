/**
 * One local session for every tracking external write (issue #168).
 *
 * This file is the *characterization* of the merged write session: it drives the
 * public surface (`useTrackingWriteSession()`) exactly as the page does — guard,
 * answer the dialog, send the returned request, settle the answer — and pins the
 * user-visible copy, the idempotency/lock rules and the convergence effects that
 * were previously asserted one constructor at a time.
 */
import { describe, expect, it } from 'vitest'

import {
  isSendableManagementAction,
  projectTrackingActionScopes,
  useTrackingWriteSession,
  type TrackingSubmissionMode,
  type TrackingWriteSession,
} from './useTrackingWriteSession'
import {
  isTrackingManagementScope,
  type CapabilityResult,
  type TrackingItem,
} from './trackingProjection'

type ItemAction = NonNullable<TrackingItem['available_actions']>[number]
type Body = Record<string, unknown>

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
    code: 'SUBMIT', label: '提交', style: 'PRIMARY', requires_confirmation: true,
    target_scopes: [], ...overrides,
  }
}

const CONNECTION = {
  connection_ref: '11111111-1111-4111-8111-111111111111',
  configuration_revision: 3,
}
const STORAGE = 'profile'

/**
 * The page's transport lifecycle: it always ends the attempt in the `finally`
 * of the request, so a settled command is immediately followed by
 * ``finishAttempt()`` here — exactly as the page does it.
 */
function session() {
  const writes = useTrackingWriteSession()
  return {
    ...writes,
    finishSubmit: (result: Parameters<typeof writes.finishSubmit>[0]) => {
      const effects = writes.finishSubmit(result)
      writes.finishAttempt()
      return effects
    },
    failSubmit: (error: Parameters<typeof writes.failSubmit>[0]) => {
      const effects = writes.failSubmit(error)
      writes.finishAttempt()
      return effects
    },
    finishRecovery: (result: Parameters<typeof writes.finishRecovery>[0]) => {
      const effects = writes.finishRecovery(result)
      writes.finishAttempt()
      return effects
    },
    failRecovery: (error: Parameters<typeof writes.failRecovery>[0]) => {
      const effects = writes.failRecovery(error)
      writes.finishAttempt()
      return effects
    },
    finishManagement: (result: Parameters<typeof writes.finishManagement>[0]) => {
      const effects = writes.finishManagement(result)
      writes.finishAttempt()
      return effects
    },
    failManagement: (error: Parameters<typeof writes.failManagement>[0]) => {
      const effects = writes.failManagement(error)
      writes.finishAttempt()
      return effects
    },
  }
}

/** The exact body one accepted command handed the page. */
function bodyOf(result: { request: { body: unknown } | null }): Body {
  return result.request!.body as Body
}

// ---------------------------------------------------------------------------
// Fixed copy, pinned here: the page must render these sentences verbatim.
// ---------------------------------------------------------------------------

const SUBMIT_MESSAGES: Record<string, string> = {
  IN_FLIGHT: '正在提交到 Auto Bangumi，请稍候…',
  ACTIVE: '提交成功：已在 Auto Bangumi 创建外部订阅。',
  ADDED_TO_DOWNLOAD: '已加入下载：Auto Bangumi 已接受本次下载现有资源的请求，不代表资源已下载完成。',
  SUBMIT_FAILED: '提交明确失败，尚未创建外部订阅；可在确认后显式重试。',
  NEEDS_RECONFIRM: '本地方案已变化，本次尚未创建外部订阅；请返回修改方案后重新确认。',
  VERIFYING_EXTERNAL: '外部提交结果未知，正在只读回查；请勿重复提交。',
  RECOVERY_REQUIRED: '本地结果未完成落盘，需要恢复；请勿重复提交。',
  CONFLICT: '追番记录已变化或当前状态不允许提交，本次未提交到 Auto Bangumi；正在刷新最新详情，请重新确认后再提交。',
  REJECTED: '服务端明确拒绝了本次请求，本次未创建 Auto Bangumi 外部订阅；正在刷新最新详情，请重新确认后再提交。',
  UNKNOWN: '提交结果未知，正在只读回查；未确认生效前不会再次提交。',
}

const WRITE_CONFLICT_MESSAGES: Record<string, string> = {
  tracking_revision_conflict:
    '追番记录已变化，本次未提交到 Auto Bangumi；正在刷新最新详情，请重新确认后再提交。',
  tracking_idempotency_conflict:
    '本次提交标识已失效，未提交到 Auto Bangumi；正在刷新最新详情，请重新确认后再提交。',
  tracking_state_conflict:
    '当前追番状态不允许本次提交，未提交到 Auto Bangumi；正在刷新最新详情，请按最新状态重新确认。',
  tracking_operation_in_progress:
    '存在尚未完成的提交操作，本次未提交到 Auto Bangumi；正在刷新最新详情，请先完成恢复后再提交。',
}
// The generic 409 next step is the submit family's own CONFLICT sentence.
const WRITE_CONFLICT_FALLBACK = SUBMIT_MESSAGES.CONFLICT!

const MANAGEMENT_MESSAGES: Record<string, Record<string, string>> = {
  MODIFY: {
    IN_FLIGHT: '正在提交外部修改，请稍候…',
    SUCCEEDED: '外部修改已完成：Auto Bangumi 已应用本次修改。',
    FAILED: '外部修改明确失败，Auto Bangumi 未应用本次修改；可核对后重新发起。',
    UNKNOWN: '外部修改结果未知，正在只读回查；未确认生效前不会自动重试。',
  },
  SET_ENABLED: {
    IN_FLIGHT: '正在提交外部启停，请稍候…',
    SUCCEEDED: '外部启停已完成：Auto Bangumi 已应用本次启用或停用。',
    FAILED: '外部启停明确失败，Auto Bangumi 未应用本次启用或停用；可核对后重新发起。',
    REJECTED: '服务端明确拒绝了本次启停请求，本次未改变 Auto Bangumi 的启用状态；正在刷新最新详情，请重新确认。',
    UNKNOWN: '外部启停结果未知，正在只读回查；未确认生效前不会自动重试。',
  },
  REFRESH_RSS: {
    IN_FLIGHT: '正在请求立即刷新资源，请稍候…',
    FAILED: '关联 RSS 刷新明确失败，Auto Bangumi 未接受本次刷新；可核对后重新发起。',
    UNKNOWN: '关联 RSS 刷新结果未知，正在只读回查；未确认完成前不会自动重试。',
  },
  DELETE_EXTERNAL: {
    SUCCEEDED: '外部删除已完成：Auto Bangumi 已删除该外部对象；MiGuOrca 本地订阅方案、追番记录、审计记录、下载任务和已下载媒体文件均保留。',
    FAILED: '外部删除明确失败，Auto Bangumi 未删除该外部对象；本地方案与已下载媒体未受影响，可核对后重新发起。',
    REJECTED: '服务端明确拒绝了本次删除请求，本次未删除 Auto Bangumi 外部对象；正在刷新最新详情，请重新确认。',
  },
}

const RECOVERY_MESSAGES: Record<string, string> = {
  IN_FLIGHT: '正在恢复该追番的结果，请稍候…',
  ACTIVE: '恢复完成：已确认该追番在 Auto Bangumi 中存在外部订阅。',
  SUBMIT_FAILED: '恢复完成：已确认本次未创建外部订阅，可在确认后显式重试提交。',
  RECOVERY_REQUIRED: '结果仍无法确认，保持恢复状态；未确认前不会自动提交。',
  CONFLICT: '追番记录已变化或当前状态不允许恢复，本次未执行恢复；正在刷新最新详情，请重新确认。',
  REJECTED: '服务端明确拒绝了本次恢复请求，本次未执行任何外部操作；正在刷新最新详情，请重新确认。',
  UNKNOWN: '恢复结果未知，正在只读回查；未确认前不会自动重发。',
}

const MANAGEMENT_UNBUILDABLE_MESSAGE =
  '本次管理请求缺少可安全发送的必要信息，未向 Auto Bangumi 发送任何请求；已重新读取最新详情，请重新确认后再试。'

const RECOVERY_MANUAL_NOTICE =
  '需要人工核验：请先在 Auto Bangumi 中独立核对该追番的实际状态，再选择“标记为成功”或“标记为失败”；本页不会代替你判断，也不会自动提交。'
const MANAGEMENT_CONFLICT_MESSAGES: Record<string, string> = {
  tracking_revision_conflict: '追番记录已变化，本次未提交到 Auto Bangumi；正在刷新最新详情，请重新确认。',
  tracking_idempotency_conflict: '本次管理请求标识已失效，未提交到 Auto Bangumi；正在刷新最新详情，请重新确认。',
  tracking_management_state_conflict: '存在尚未完成的管理操作，本次未提交到 Auto Bangumi；正在刷新最新详情，请先完成恢复。',
  tracking_management_patch_invalid: '本次修改内容未通过服务端校验，未提交到 Auto Bangumi；正在刷新最新详情，请重新确认后再修改。',
  tracking_target_missing: '该记录当前没有对应的外部对象，本次未提交到 Auto Bangumi；正在刷新最新详情。',
  tracking_target_drift: '外部对象已变化，本次未提交到 Auto Bangumi；正在刷新最新详情，请重新确认。',
  tracking_target_ambiguous: '匹配到多个外部对象，本次未提交到 Auto Bangumi；正在刷新最新详情，请重新确认。',
  tracking_mapping_missing: '该记录缺少外部关联信息，本次未提交到 Auto Bangumi；正在刷新最新详情。',
}
const MANAGEMENT_CONFLICT_FALLBACK =
  '追番记录已变化或当前状态不允许本次管理操作，本次未提交到 Auto Bangumi；正在刷新最新详情，请重新确认。'

const MANAGEMENT_MANUAL_NOTICE =
  '需要人工核验：请先在 Auto Bangumi 中独立核对该追番的实际状态，再决定是否重新发起修改；本页不会代替你判断，也不会自动重试。'

const SUBMIT_OUTCOMES = [
  'ACTIVE', 'SUBMIT_FAILED', 'NEEDS_RECONFIRM', 'VERIFYING_EXTERNAL', 'RECOVERY_REQUIRED',
  'ADDED_TO_DOWNLOAD',
] as const

function submitResult(overrides: Record<string, unknown> = {}) {
  return {
    tracking_id: 'tracking-1', outcome: 'ACTIVE', checked_revision: 3, next_revision: 4,
    checked_at: '2026-09-13T03:00:00Z', operation_id: 'operation-1', issues: [],
    tracking: item({ revision: 4 }), ...overrides,
  } as never
}

function recoverResult(overrides: Record<string, unknown> = {}) {
  return {
    tracking_id: 'tracking-1', action: 'AUTO', outcome: 'ACTIVE', checked_revision: 3,
    next_revision: 4, checked_at: '2026-09-13T05:00:00Z', operation_id: 'operation-1',
    needs_manual: false, tracking: recoverableItem({ revision: 4 }), ...overrides,
  } as never
}

function modifyResult(overrides: Record<string, unknown> = {}) {
  return {
    action: 'MODIFY', management_status: 'SUCCEEDED', needs_manual: false, safe_message: '管理操作已完成',
    operation_id: 'operation-1', operation: null,
    tracking: item({ revision: 5 }), ...overrides,
  } as never
}

/** Start one submit-family write and return the page-visible result. */
function beginSubmitWrite(options: {
  item?: Partial<TrackingItem>
  action?: Partial<ItemAction>
  mode?: TrackingSubmissionMode | null
  confirmed?: boolean
  connection?: typeof CONNECTION | null
  storageDir?: string
} = {}) {
  const writes = session()
  const requested = action(options.action)
  // The page always emits one of the actions the server projected for the row.
  const target = { item: item({ available_actions: [requested], ...options.item }), action: requested }
  const started = writes.beginSubmit(target, {
    mode: options.mode === undefined ? 'CONTINUE_TRACKING' : options.mode,
    confirmed: options.confirmed ?? true,
    connection: options.connection === undefined ? CONNECTION : options.connection,
    storageDir: options.storageDir,
  })
  return { writes, started }
}

/** One accepted submit attempt with its request already in flight. */
function inFlightSubmit(options: Parameters<typeof beginSubmitWrite>[0] = {}) {
  const { writes, started } = beginSubmitWrite(options)
  expect(started.accepted).toBe(true)
  return { writes, started, body: bodyOf(started) }
}

// ---------------------------------------------------------------------------
// Submit family (US-310, US-311).
// ---------------------------------------------------------------------------

describe('tracking submit-family write session (US-310, US-311)', () => {
  it('binds each submit-family action to its own generated endpoint and copy', () => {
    const submit = beginSubmitWrite()
    expect(submit.started.request?.endpoint).toBe('/api/v1/tracking/items/{tracking_id}/submit')
    // The request carries the path parameters its own template needs.
    expect(submit.started.request?.path).toEqual({ tracking_id: 'tracking-1' })
    const retry = beginSubmitWrite({ action: { code: 'RETRY', label: '重试提交', style: 'SECONDARY' } })
    expect(retry.started.request?.endpoint).toBe('/api/v1/tracking/items/{tracking_id}/retry')

    // The two confirmations must not be interchangeable: a retry never reuses
    // the first-submission wording (or the reverse).
    const submitCopy = session().beginSubmit({ item: item(), action: action() }, {
      mode: 'CONTINUE_TRACKING', connection: CONNECTION,
    })
    const retryCopy = session().beginSubmit(
      { item: item(), action: action({ code: 'RETRY', label: '重试提交', style: 'SECONDARY' }) },
      { mode: 'CONTINUE_TRACKING', connection: CONNECTION },
    )
    expect(submitCopy.ask).toBe('IMPACT')
    expect(retryCopy.ask).toBe('IMPACT')
    expect(retryCopy.confirmation!.message).not.toBe(submitCopy.confirmation!.message)
    expect(retryCopy.confirmation!.confirmLabel).toBe('确认重试')
    expect(submitCopy.confirmation!.confirmLabel).toBe('确认提交')
    for (const confirmation of [submitCopy.confirmation!, retryCopy.confirmation!]) {
      expect(confirmation.message).toContain('外部订阅')
      expect(confirmation.message).toContain('是否继续')
      expect(confirmation.confirmLabel.startsWith('确认')).toBe(true)
    }
  })

  it('accepts only the submit-family action codes this page can send', () => {
    for (const code of ['REVALIDATE', 'MODIFY', 'SET_ENABLED', 'REFRESH_RSS', 'DELETE_EXTERNAL', 'RECOVER_AUTO']) {
      const started = beginSubmitWrite({ action: { code: code as never } }).started
      expect(started.accepted).toBe(false)
      expect(started.request).toBeNull()
    }
  })

  it('maps every generated submit outcome to its fixed Chinese copy', () => {
    for (const outcome of SUBMIT_OUTCOMES) {
      const { writes, started } = inFlightSubmit()
      expect(writes.sessions.value.submit!.message).toBe(SUBMIT_MESSAGES.IN_FLIGHT)
      expect(writes.sessions.value.submit!.keepsIntent).toBe(false)
      const effects = writes.finishSubmit(submitResult({ outcome }))
      const settled = writes.sessions.value.submit!
      expect(settled.state).toBe(outcome)
      expect(settled.message).toBe(SUBMIT_MESSAGES[outcome])
      expect(settled.trackingId).toBe('tracking-1')
      expect(settled.operation).toBe('SUBMIT')
      // No raw server enum ever reaches the rendered copy.
      expect(settled.message).not.toContain(outcome)
      expect(bodyOf(started).expected_revision).toBe(3)
      expect(effects).toContainEqual({ kind: 'recheck', trackingId: 'tracking-1', refreshList: false })
      // Only a real success is announced; every other outcome stays on the row.
      expect(effects.some((effect) => effect.kind === 'notify')).toBe(outcome === 'ACTIVE')
    }
  })

  it('fails closed to an unknown result when the outcome is not documented', () => {
    const { writes } = inFlightSubmit()
    writes.finishSubmit(submitResult({ outcome: 'SOMETHING_NEW' }))
    const settled = writes.sessions.value.submit!
    expect(settled.state).toBe('UNKNOWN')
    expect(settled.message).toBe(SUBMIT_MESSAGES.UNKNOWN)
    expect(settled.message).not.toContain('SOMETHING_NEW')
    expect(settled.keepsIntent).toBe(true)
  })

  it('projects only documented §11.5 issues and never echoes unknown server text', () => {
    const { writes } = inFlightSubmit()
    writes.finishSubmit(submitResult({
      outcome: 'NEEDS_RECONFIRM',
      issues: [
        { code: 'REQUEST_CHANGED', field: null, message: '本地方案已变化', recovery_action: 'SUBMIT' },
        { code: 'BRAND_NEW_CODE', field: null, message: 'https://private.invalid/leak', recovery_action: '' },
      ],
    }))
    const settled = writes.sessions.value.submit!
    expect(settled.issues).toEqual([{ code: 'REQUEST_CHANGED', message: '本地方案已变化' }])
    expect(JSON.stringify(settled)).not.toContain('private.invalid')
  })

  it('locks the intent only while the external result is indeterminate', () => {
    for (const [outcome, locked] of [
      ['UNKNOWN', true], ['VERIFYING_EXTERNAL', true], ['RECOVERY_REQUIRED', true],
      ['ACTIVE', false], ['SUBMIT_FAILED', false], ['NEEDS_RECONFIRM', false],
      ['ADDED_TO_DOWNLOAD', false], ['CONFLICT', false], ['REJECTED', false],
    ] as ReadonlyArray<[string, boolean]>) {
      const { writes } = inFlightSubmit()
      if (outcome === 'CONFLICT') {
        writes.failSubmit({ status: 409, httpError: true, type: 'tracking_revision_conflict' })
      } else if (outcome === 'REJECTED') {
        writes.failSubmit({ status: 400, httpError: true })
      } else {
        writes.finishSubmit(submitResult({ outcome }))
      }
      expect(writes.sessions.value.submit!.state).toBe(outcome)
      expect(writes.sessions.value.submit!.keepsIntent).toBe(locked)
    }
    // An in-flight request never owns an unresolved intent.
    const { writes } = inFlightSubmit()
    expect(writes.sessions.value.submit!.state).toBe('IN_FLIGHT')
    expect(writes.sessions.value.submit!.keepsIntent).toBe(false)
  })

  it('treats only a structured non-409 4xx as a definite pre-write rejection', () => {
    const rejected: ReadonlyArray<[number, boolean]> = [
      // D38-08.5: these are refused before the external boundary.
      [400, true], [404, true],
      // A 409 keeps its own conflict branch; 422 and everything that may already
      // have crossed the boundary stays unknown.
      [422, false], [409, false], [500, false], [502, false], [504, false], [408, false], [429, false],
      [Number.NaN, false],
    ]
    for (const [status, definite] of rejected) {
      const { writes } = inFlightSubmit()
      writes.failSubmit({ status, httpError: true })
      const settled = writes.sessions.value.submit!
      expect(settled.state).toBe(status === 409 ? 'CONFLICT' : definite ? 'REJECTED' : 'UNKNOWN')
      expect(settled.keepsIntent).toBe(!definite && status !== 409)
    }
    for (const error of [
      { status: 0, httpError: false },
      { status: 400, httpError: false },
      { status: 400, httpError: true, nonJson: true },
      { status: 404, httpError: true, network: true },
    ]) {
      const { writes } = inFlightSubmit()
      writes.failSubmit(error)
      expect(writes.sessions.value.submit!.state).toBe('UNKNOWN')
    }
  })

  it('renders a fixed refusal copy that never claims an external subscription', () => {
    const { writes } = inFlightSubmit()
    const effects = writes.failSubmit({ status: 404, httpError: true })
    const settled = writes.sessions.value.submit!
    expect(settled.state).toBe('REJECTED')
    expect(settled.message).toBe(SUBMIT_MESSAGES.REJECTED)
    expect(settled.message).toContain('本次未创建 Auto Bangumi 外部订阅')
    expect(settled.message).toContain('重新确认')
    // Neither the raw client state nor a raw HTTP status may reach the DOM, and
    // the copy must not hint that a subscription may already exist.
    expect(settled.message).not.toContain('REJECTED')
    expect(settled.message).not.toContain('400')
    expect(settled.message).not.toContain('409')
    expect(settled.message).not.toMatch(/可能.*创建/)
    expect(settled.message).not.toContain('结果未知')
    expect(effects).toEqual([{ kind: 'recheck', trackingId: 'tracking-1', refreshList: true }])
  })

  it('creates an in-flight session without leaking any request material', () => {
    const { writes } = inFlightSubmit()
    const current = writes.sessions.value.submit!
    expect(current).toEqual({
      trackingId: 'tracking-1', operation: 'SUBMIT', family: 'SUBMIT', targetScope: null,
      state: 'IN_FLIGHT', message: SUBMIT_MESSAGES.IN_FLIGHT, issues: [], failureCategory: null,
      // Issue #101: an empty diagnostics object means "no reason given".
      diagnostics: { httpStatus: null, messageZh: null, messageEn: null },
      needsManual: false, manualNotice: null, keepsIntent: false,
    })
    expect(Object.keys(current)).not.toContain('idempotencyKey')
  })

  it('gives every documented conflict its own fixed next step and fails closed', () => {
    for (const [errorType, message] of Object.entries(WRITE_CONFLICT_MESSAGES)) {
      const { writes } = inFlightSubmit()
      writes.failSubmit({ status: 409, httpError: true, type: errorType })
      const settled = writes.sessions.value.submit!
      expect(settled).toMatchObject({ trackingId: 'tracking-1', operation: 'SUBMIT', state: 'CONFLICT', issues: [] })
      expect(settled.message).toBe(message)
      // Every conflict states that nothing reached Auto Bangumi, so a user
      // cannot mistake a refused request for a duplicate subscription.
      expect(message).toContain('未提交到 Auto Bangumi')
      expect(message).not.toContain(errorType)
      expect(settled.keepsIntent).toBe(false)
    }
    expect(new Set(Object.values(WRITE_CONFLICT_MESSAGES)).size).toBe(4)

    for (const errorType of ['brand_new_conflict', null, undefined, 42]) {
      const { writes } = inFlightSubmit()
      writes.failSubmit({ status: 409, httpError: true, type: errorType })
      expect(writes.sessions.value.submit!.message).toBe(WRITE_CONFLICT_FALLBACK)
    }
  })

  it('keeps the session and its key when the transport was cancelled before any answer', () => {
    const { writes, body } = inFlightSubmit()
    expect(writes.failSubmit({ status: 0, httpError: false, cancelled: true })).toEqual([])
    expect(writes.sessions.value.submit!.state).toBe('IN_FLIGHT')
    // The very same locked intent (key and revision binding) is replayed.
    const retry = writes.beginSubmit({ item: item({ revision: 9 }), action: action() }, {
      mode: 'CONTINUE_TRACKING', confirmed: true, connection: CONNECTION,
    })
    expect(bodyOf(retry).idempotency_key).toBe(body.idempotency_key)
    expect(bodyOf(retry).expected_revision).toBe(3)
  })

  it('creates one revision-bound opaque intent and replays it for a transport retry', () => {
    const { writes, started, body } = inFlightSubmit({ storageDir: STORAGE })
    expect(body).toMatchObject({
      expected_revision: 3, confirm: true, configuration_revision: 3,
      connection_ref: CONNECTION.connection_ref, submission_mode: 'CONTINUE_TRACKING',
      storage_dir: STORAGE,
    })
    expect(String(body.idempotency_key)).toMatch(/^[A-Za-z0-9-]{8,128}$/)

    // An unresolved result keeps the intent: the replay reuses the very same
    // key, the very same revision binding and the very same connection snapshot
    // even though the record, the page and the saved generation all moved on.
    writes.finishSubmit(submitResult({ outcome: 'UNKNOWN' }))
    expect(writes.sessions.value.submit!.keepsIntent).toBe(true)
    const replayed = writes.beginSubmit({ item: item({ revision: 9 }), action: action() }, {
      mode: 'CONTINUE_TRACKING', confirmed: true,
      connection: { connection_ref: '22222222-2222-4222-8222-222222222222', configuration_revision: 4 },
      storageDir: 'other',
    })
    expect(replayed.accepted).toBe(true)
    expect(bodyOf(replayed)).toEqual({ ...body, storage_dir: 'other' })
    expect(bodyOf(replayed).idempotency_key).toBe(body.idempotency_key)
    expect(bodyOf(replayed).connection_ref).toBe(CONNECTION.connection_ref)
    expect(started.request?.endpoint).toBe(replayed.request?.endpoint)
  })

  it('releases the key on every decided result so the next confirmation is explicit', () => {
    const { writes, body } = inFlightSubmit()
    writes.finishSubmit(submitResult({ outcome: 'SUBMIT_FAILED' }))
    const requested = action()
    const next = writes.beginSubmit(
      { item: item({ revision: 8, available_actions: [requested] }), action: requested },
      {
        mode: 'CONTINUE_TRACKING', confirmed: true, connection: CONNECTION,
      },
    )
    expect(bodyOf(next).idempotency_key).not.toBe(body.idempotency_key)
    expect(bodyOf(next).expected_revision).toBe(8)
  })

  it('refuses a different action while one locked intent owns the key', () => {
    const { writes } = inFlightSubmit()
    writes.finishSubmit(submitResult({ outcome: 'UNKNOWN' }))
    const wrong = writes.beginSubmit(
      { item: item(), action: action({ code: 'RETRY', label: '重试提交', style: 'SECONDARY' }) },
      { mode: 'CONTINUE_TRACKING', confirmed: true, connection: CONNECTION },
    )
    expect(wrong.accepted).toBe(false)
    expect(wrong.refusal).toEqual({ trackingId: 'tracking-1', reason: 'INTENT' })
    expect(writes.noticeFor('tracking-1')).toContain('上一次外部操作的结果仍未确认')
  })

  it('opens the submission-mode choice before anything can be confirmed or sent', () => {
    const writes = session()
    const requested = action()
    const target = { item: item({ available_actions: [requested] }), action: requested }
    const started = writes.beginSubmit(target, { connection: CONNECTION })
    expect(started.ask).toBe('SUBMISSION_MODE')
    expect(started.accepted).toBe(false)
    expect(started.request).toBeNull()
    expect(writes.sessions.value.submit).toBeNull()
    // Choosing the mode is the submit family's impact confirmation.
    const chosen = writes.beginSubmit(target, {
      mode: 'DOWNLOAD_EXISTING', confirmed: true, connection: CONNECTION,
    })
    expect(chosen.accepted).toBe(true)
    expect(bodyOf(chosen).submission_mode).toBe('DOWNLOAD_EXISTING')
  })

  it('never sends without a saved connection, and never quietly rebinds a cleared one', () => {
    const { writes } = inFlightSubmit()
    writes.finishSubmit(submitResult({ outcome: 'UNKNOWN' }))
    writes.preserveAfterClear()
    // The unresolved result survives as a tombstone, but its key can never be
    // rebound to a freshly connected account.
    expect(writes.sessions.value.submit!.state).toBe('UNKNOWN')
    expect(writes.sessions.value.submit!.message).toBe(SUBMIT_MESSAGES.UNKNOWN)
    const replayed = writes.beginSubmit({ item: item(), action: action() }, {
      mode: 'CONTINUE_TRACKING', confirmed: true, connection: CONNECTION,
    })
    expect(replayed.refusal).toEqual({ trackingId: 'tracking-1', reason: 'REPLAY' })
    expect(writes.noticeFor('tracking-1')).toContain('绑定的连接已被清除或更换')

    const fresh = session()
    expect(fresh.beginSubmit({ item: item(), action: action() }, {
      mode: 'CONTINUE_TRACKING', confirmed: true, connection: null,
    }).accepted).toBe(false)
  })

  it('refuses an action object that no longer matches the server projection', () => {
    const projected = action()
    const writes = session()
    const stale = { ...projected, label: '旧的标签' }
    const mismatched = writes.beginSubmit(
      { item: item({ available_actions: [projected] }), action: stale },
      { mode: 'CONTINUE_TRACKING', confirmed: true, connection: CONNECTION },
    )
    expect(mismatched.accepted).toBe(false)
    expect(mismatched.request).toBeNull()
    // The identical projected object is still accepted.
    expect(writes.beginSubmit(
      { item: item({ available_actions: [projected] }), action: projected },
      { mode: 'CONTINUE_TRACKING', confirmed: true, connection: CONNECTION },
    ).accepted).toBe(true)
  })

  it('rejects an action the server no longer projects or a revision it cannot have issued', () => {
    // SUBMIT is projected with scopes: not executable, so no request.
    const scoped = beginSubmitWrite({ action: { target_scopes: ['SUBSCRIPTION'] } })
    expect(scoped.started.accepted).toBe(false)
    const unknown = beginSubmitWrite({ action: { code: 'NOT_KNOWN' as never } })
    expect(unknown.started.accepted).toBe(false)
    expect(beginSubmitWrite({ item: { revision: 0 } }).started.accepted).toBe(false)
  })
})

// ---------------------------------------------------------------------------
// Failure diagnostics (issue #101).
// ---------------------------------------------------------------------------

describe('submission failure diagnostics (issue #101)', () => {
  it('gives a one-time failure the plain retryable sentence only', () => {
    const { writes } = inFlightSubmit({ mode: 'DOWNLOAD_EXISTING' })
    writes.finishSubmit(submitResult({ outcome: 'SUBMIT_FAILED' }))
    const settled = writes.sessions.value.submit!
    expect(settled.message).toBe('提交失败，可重新提交。')
    for (const forbidden of ['尚未创建', '可能部分成功', '可安全重试', '外部订阅']) {
      expect(settled.message).not.toContain(forbidden)
    }
  })

  it('keeps the actionable class copy and its blocking channel for 持续追番', () => {
    const { writes } = inFlightSubmit({ mode: 'CONTINUE_TRACKING' })
    const effects = writes.finishSubmit(submitResult({
      outcome: 'SUBMIT_FAILED', failure_category: 'AUTHENTICATION',
    }))
    const settled = writes.sessions.value.submit!
    expect(settled.failureCategory).toBe('AUTHENTICATION')
    expect(settled.message).toContain('前往设置')
    expect(effects).toEqual([
      { kind: 'recheck', trackingId: 'tracking-1', refreshList: false },
      {
        kind: 'notify',
        feedback: {
          channel: 'dialog', title: 'Auto Bangumi 认证失败',
          message: '保存的连接凭据被 Auto Bangumi 拒绝。请前往设置更新账号或密码后重试；本次未创建外部订阅。',
        },
      },
    ])
  })

  it('routes only a blocking connection class to the dialog channel', () => {
    for (const [category, channel] of [
      ['CONNECTION', 'dialog'], ['AUTHENTICATION', 'dialog'], ['VERSION', 'dialog'],
      ['DUPLICATE_SUBSCRIPTION', 'item'], ['VALIDATION', 'item'], ['REJECTED', 'item'],
      ['OUTCOME_UNKNOWN', 'recovery'],
    ] as ReadonlyArray<[string, string]>) {
      const { writes } = inFlightSubmit()
      const effects = writes.finishSubmit(submitResult({ outcome: 'SUBMIT_FAILED', failure_category: category }))
      const feedback = effects.find((effect) => effect.kind === 'notify')
      expect(Boolean(feedback)).toBe(channel === 'dialog')
      expect(writes.sessions.value.submit!.message).not.toContain(category)
    }
    // A success is a lightweight notice, never a dialog.
    const { writes } = inFlightSubmit()
    const effects = writes.finishSubmit(submitResult({ outcome: 'ACTIVE' }))
    expect(effects).toContainEqual({
      kind: 'notify',
      feedback: { channel: 'success', title: '提交成功', message: '已在 Auto Bangumi 创建外部订阅。' },
    })
  })

  it('projects bounded diagnostics and fails closed on anything else', () => {
    const { writes } = inFlightSubmit()
    writes.finishSubmit(submitResult({
      outcome: 'SUBMIT_FAILED',
      diagnostics: { http_status: 503, message_zh: '上游繁忙', message_en: 'busy' },
    }))
    expect(writes.sessions.value.submit!.diagnostics).toEqual({
      httpStatus: 503, messageZh: '上游繁忙', messageEn: 'busy',
    })
    for (const value of [null, undefined, {}, { http_status: 'x' }, 'nope', { message_zh: '  ' }]) {
      const { writes } = inFlightSubmit()
      writes.finishSubmit(submitResult({ outcome: 'SUBMIT_FAILED', diagnostics: value }))
      expect(writes.sessions.value.submit!.diagnostics).toEqual({
        httpStatus: null, messageZh: null, messageEn: null,
      })
    }
  })
})

// ---------------------------------------------------------------------------
// Recovery family (US-312).
// ---------------------------------------------------------------------------

const recoverAutoAction: ItemAction = {
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
    available_actions: [recoverAutoAction, markSucceededAction, markFailedAction],
    ...overrides,
  })
}

function beginRecoveryWrite(
  actionCode: 'RECOVER_AUTO' | 'MARK_SUCCEEDED' | 'MARK_FAILED' | 'VERIFY_EXTERNAL',
  options: {
    item?: Partial<TrackingItem>
    capabilities?: CapabilityResult | null
    connection?: typeof CONNECTION | null
    confirmed?: boolean
    storageDir?: string
    writes?: ReturnType<typeof useTrackingWriteSession>
  } = {},
) {
  const writes = options.writes ?? session()
  const started = writes.beginRecovery(
    { action: actionCode, item: recoverableItem(options.item) },
    {
      capabilities: options.capabilities === undefined ? capabilities() : options.capabilities,
      connection: options.connection === undefined ? CONNECTION : options.connection,
      confirmed: options.confirmed ?? true,
      storageDir: options.storageDir,
    },
  )
  return { writes, started }
}

describe('tracking recovery write session (US-312)', () => {
  it('binds every recovery action to its own request body value and copy', () => {
    const auto = beginRecoveryWrite('RECOVER_AUTO')
    expect(auto.started.ask).toBeNull()
    expect(auto.started.request?.endpoint).toBe('/api/v1/tracking/items/{tracking_id}/recover')
    expect(bodyOf(auto.started)).toEqual({ expected_revision: 3, action: 'AUTO' })

    for (const [actionCode, bodyAction] of [
      ['MARK_SUCCEEDED', 'MARK_SUCCEEDED'], ['MARK_FAILED', 'MARK_FAILED'], ['VERIFY_EXTERNAL', 'VERIFY_EXTERNAL'],
    ] as const) {
      const unconfirmed = beginRecoveryWrite(actionCode, { confirmed: false })
      expect(unconfirmed.started.ask).toBe('IMPACT')
      const confirmation = unconfirmed.started.confirmation!
      expect(confirmation.message).toContain('Auto Bangumi')
      const confirmed = beginRecoveryWrite(actionCode)
      expect(bodyOf(confirmed.started)).toEqual(actionCode === 'VERIFY_EXTERNAL'
        ? {
            expected_revision: 3, action: bodyAction,
            connection_ref: CONNECTION.connection_ref, configuration_revision: 3,
          }
        : { expected_revision: 3, action: bodyAction, confirm: true })
      // A manual conclusion is a user assertion: it must be confirmed again and
      // styled as a danger only for the failure verdict.
      expect(confirmation.danger).toBe(actionCode === 'MARK_FAILED' ? true : undefined)
      if (actionCode !== 'VERIFY_EXTERNAL') {
        expect(confirmation.message).toContain('独立核对')
      }
    }
  })

  it('builds a local AUTO body and a confirm-only manual body', () => {
    expect(bodyOf(beginRecoveryWrite('RECOVER_AUTO', { storageDir: STORAGE }).started)).toEqual({
      expected_revision: 3, action: 'AUTO', storage_dir: STORAGE,
    })
    // The body shape itself cannot express an external id/URL/raw result/note.
    const serialized = JSON.stringify(beginRecoveryWrite('MARK_SUCCEEDED').started.request?.body)
    for (const leaked of ['external_id', 'external_url', 'raw', 'note', 'saved_connection']) {
      expect(serialized).not.toContain(leaked)
    }
  })

  it('binds VERIFY_EXTERNAL only to the saved generation', () => {
    const verify = beginRecoveryWrite('VERIFY_EXTERNAL')
    expect(bodyOf(verify.started)).toEqual({
      expected_revision: 3, action: 'VERIFY_EXTERNAL',
      connection_ref: CONNECTION.connection_ref, configuration_revision: 3,
    })
    // Without the live saved generation the read-only external check is not sent.
    expect(beginRecoveryWrite('VERIFY_EXTERNAL', { connection: null }).started.accepted).toBe(false)
  })

  it('accepts only a recovery action the server actually offers for the record', () => {
    expect(beginRecoveryWrite('RECOVER_AUTO').started.accepted).toBe(true)
    expect(beginRecoveryWrite('MARK_FAILED').started.accepted).toBe(true)
    // A stale/hand-made action, a non-recoverable record and a bad revision.
    expect(beginRecoveryWrite('RECOVER_AUTO', {
      item: { available_actions: [markFailedAction] },
    }).started.accepted).toBe(false)
    expect(beginRecoveryWrite('MARK_SUCCEEDED', {
      item: { status: 'ACTIVE', available_actions: [] },
    }).started.accepted).toBe(false)
    expect(beginRecoveryWrite('RECOVER_AUTO', { item: { revision: 0 } }).started.accepted).toBe(false)
    // The read-only external verification still needs both a recoverable record
    // and the capability the live page session proved.
    expect(beginRecoveryWrite('VERIFY_EXTERNAL', {
      capabilities: capabilities({ external_verify: 'UNKNOWN' }),
    }).started.accepted).toBe(false)
    expect(beginRecoveryWrite('VERIFY_EXTERNAL', { capabilities: null }).started.accepted).toBe(false)
    expect(beginRecoveryWrite('VERIFY_EXTERNAL', {
      item: { status: 'ACTIVE', available_actions: [] }, capabilities: capabilities(),
    }).started.accepted).toBe(false)
  })

  it('keeps the recovery state whenever the outcome is not a decided verdict', () => {
    const auto = beginRecoveryWrite('RECOVER_AUTO')
    auto.writes.finishRecovery(recoverResult())
    expect(auto.writes.sessions.value.recovery).toMatchObject({ state: 'ACTIVE', needsManual: false })

    const failed = beginRecoveryWrite('MARK_FAILED')
    failed.writes.finishRecovery(recoverResult({ action: 'MARK_FAILED', outcome: 'SUBMIT_FAILED' }))
    expect(failed.writes.sessions.value.recovery).toMatchObject({
      state: 'SUBMIT_FAILED', needsManual: false, message: RECOVERY_MESSAGES.SUBMIT_FAILED,
    })

    const manual = beginRecoveryWrite('RECOVER_AUTO')
    manual.writes.finishRecovery(recoverResult({ outcome: 'RECOVERY_REQUIRED', needs_manual: true }))
    expect(manual.writes.sessions.value.recovery).toMatchObject({
      state: 'RECOVERY_REQUIRED', needsManual: true, manualNotice: RECOVERY_MANUAL_NOTICE,
    })
    expect(manual.writes.sessions.value.recovery!.message).not.toContain('RECOVERY_REQUIRED')
    expect(RECOVERY_MANUAL_NOTICE).toContain('独立核对')

    // needs_manual is the server's own verdict even without the outcome value.
    const flag = beginRecoveryWrite('VERIFY_EXTERNAL')
    flag.writes.finishRecovery(recoverResult({ action: 'VERIFY_EXTERNAL', outcome: 'ACTIVE', needs_manual: true }))
    expect(flag.writes.sessions.value.recovery).toMatchObject({ state: 'RECOVERY_REQUIRED', needsManual: true })

    // An outcome outside the documented enum is never read as a success.
    for (const outcome of ['DISABLED', 'EXTERNAL_DELETED', 'SOMETHING_NEW']) {
      const unknown = beginRecoveryWrite('VERIFY_EXTERNAL')
      unknown.writes.finishRecovery(recoverResult({ outcome }))
      expect(unknown.writes.sessions.value.recovery).toMatchObject({ state: 'UNKNOWN', needsManual: false })
      expect(unknown.writes.sessions.value.recovery!.message).toBe(RECOVERY_MESSAGES.UNKNOWN)
      expect(unknown.writes.sessions.value.recovery!.keepsIntent).toBe(true)
    }
  })

  it('releases the recovery lock for every decided verdict and keeps it otherwise', () => {
    for (const [state, locked] of [
      ['UNKNOWN', true], ['RECOVERY_REQUIRED', true],
      ['ACTIVE', false], ['SUBMIT_FAILED', false], ['CONFLICT', false], ['REJECTED', false],
    ] as ReadonlyArray<[string, boolean]>) {
      const writes = beginRecoveryWrite('RECOVER_AUTO').writes
      if (state === 'UNKNOWN') writes.finishRecovery(recoverResult({ outcome: 'SOMETHING_NEW' }))
      else if (state === 'CONFLICT') writes.failRecovery({ status: 409, httpError: true })
      else if (state === 'REJECTED') writes.failRecovery({ status: 400, httpError: true })
      else writes.finishRecovery(recoverResult({ outcome: state, needs_manual: state === 'RECOVERY_REQUIRED' }))
      const current = writes.sessions.value.recovery!
      expect(current.state).toBe(state)
      expect(current.keepsIntent).toBe(locked)
      expect(current.message).not.toContain(state === 'UNKNOWN' ? 'SOMETHING_NEW' : state)
    }
  })

  it('releases the record\'s unresolved write intent only when a recovery concludes', () => {
    const { writes } = inFlightSubmit()
    writes.finishSubmit(submitResult({ outcome: 'UNKNOWN' }))
    expect(writes.sessions.value.submit!.keepsIntent).toBe(true)
    const pending = beginRecoveryWrite('RECOVER_AUTO', { writes })
    expect(pending.started.accepted).toBe(true)
    writes.finishRecovery(recoverResult({ outcome: 'SOMETHING_NEW' }))
    expect(writes.sessions.value.submit).not.toBeNull()
    // A still-unresolved recovery keeps the write intent; the next attempt
    // concludes it and releases the record.
    expect(beginRecoveryWrite('RECOVER_AUTO', { writes }).started.accepted).toBe(true)
    writes.finishRecovery(recoverResult({ outcome: 'ACTIVE' }))
    expect(writes.sessions.value.submit).toBeNull()
  })

  it('treats a 409 as a released recovery and an unreadable answer as unresolved', () => {
    const conflict = beginRecoveryWrite('RECOVER_AUTO')
    expect(conflict.writes.failRecovery({ status: 409, httpError: true })).toEqual([
      { kind: 'recheck', trackingId: 'tracking-1', refreshList: true },
    ])
    expect(conflict.writes.sessions.value.recovery).toMatchObject({
      state: 'CONFLICT', message: RECOVERY_MESSAGES.CONFLICT, keepsIntent: false,
    })

    const unknown = beginRecoveryWrite('RECOVER_AUTO')
    unknown.writes.failRecovery({ status: 503, httpError: true })
    expect(unknown.writes.sessions.value.recovery).toMatchObject({ state: 'UNKNOWN', keepsIntent: true })
    // A cancellation that never crossed the boundary is not a result.
    const cancelled = beginRecoveryWrite('RECOVER_AUTO')
    expect(cancelled.writes.failRecovery({ status: 0, httpError: false, cancelled: true })).toEqual([])
    expect(cancelled.writes.sessions.value.recovery!.state).toBe('IN_FLIGHT')
  })
})

// ---------------------------------------------------------------------------
// Management family (US-313, US-314, US-315).
// ---------------------------------------------------------------------------

const modifyAction: ItemAction = {
  code: 'MODIFY', label: '修改外部方案', style: 'SECONDARY', requires_confirmation: true,
  target_scopes: ['SUBSCRIPTION', 'ASSOCIATED_RSS'],
}
const ENABLE_ACTION: ItemAction = {
  code: 'SET_ENABLED', label: '启用追番', style: 'PRIMARY',
  requires_confirmation: true, target_scopes: ['SUBSCRIPTION', 'ASSOCIATED_RSS'],
}
const DISABLE_ACTION: ItemAction = { ...ENABLE_ACTION, label: '停用追番', style: 'SECONDARY' }
const REFRESH_ACTION: ItemAction = {
  code: 'REFRESH_RSS', label: '立即刷新资源', style: 'SECONDARY',
  requires_confirmation: true, target_scopes: ['ASSOCIATED_RSS'],
}
const DELETE_ACTION: ItemAction = {
  code: 'DELETE_EXTERNAL', label: '删除外部订阅', style: 'DANGER',
  requires_confirmation: true, target_scopes: ['SUBSCRIPTION', 'ASSOCIATED_RSS'],
}

function managementItem(overrides: Partial<TrackingItem> = {}): TrackingItem {
  return item({ available_actions: [modifyAction], ...overrides })
}

function beginManagementWrite(
  payload: {
    action?: ItemAction
    item?: TrackingItem
    targetScope?: 'SUBSCRIPTION' | 'ASSOCIATED_RSS'
    patch?: unknown
    localPlan?: unknown
  } = {},
  options: {
    confirmed?: boolean
    connection?: typeof CONNECTION | null
    storageDir?: string
    writes?: ReturnType<typeof useTrackingWriteSession>
  } = {},
) {
  const writes = options.writes ?? session()
  const action0 = payload.action ?? modifyAction
  const started = writes.beginManagement({
    action: action0,
    item: payload.item ?? managementItem(),
    targetScope: payload.targetScope ?? 'SUBSCRIPTION',
    patch: payload.patch === undefined ? { title: '新标题' } : payload.patch,
    localPlan: payload.localPlan,
  }, {
    confirmed: options.confirmed ?? true,
    connection: options.connection === undefined ? CONNECTION : options.connection,
    storageDir: options.storageDir,
  })
  return { writes, started }
}

describe('tracking management write session (US-313, US-314, US-315)', () => {
  it('requests only a scope the server actually offered', () => {
    const scoped = managementItem({
      available_actions: [{ ...modifyAction, target_scopes: ['SUBSCRIPTION', 'ASSOCIATED_RSS'] }],
    })
    expect(projectTrackingActionScopes(scoped, 'MODIFY', 'SUBSCRIPTION')).toEqual(['SUBSCRIPTION'])
    expect(projectTrackingActionScopes(scoped, 'MODIFY', 'ASSOCIATED_RSS')).toEqual(['ASSOCIATED_RSS'])
    const subscriptionOnly = managementItem({
      available_actions: [{ ...modifyAction, target_scopes: ['SUBSCRIPTION'] }],
    })
    expect(projectTrackingActionScopes(subscriptionOnly, 'MODIFY', 'ASSOCIATED_RSS')).toEqual([])
    expect(projectTrackingActionScopes(subscriptionOnly, 'MODIFY', 'SUBSCRIPTION')).toEqual(['SUBSCRIPTION'])
  })

  it('never derives a requestable scope from an unknown action, style or scope', () => {
    const cases: TrackingItem[] = [
      managementItem({ available_actions: [{ ...modifyAction, code: 'REBOOT_EXTERNAL' as never }] }),
      managementItem({ available_actions: [{ ...modifyAction, style: 'GLOWING' as never }] }),
      managementItem({ available_actions: [{ ...modifyAction, target_scopes: ['WHOLE_LIBRARY' as never] }] }),
      managementItem({ available_actions: [{ ...modifyAction, target_scopes: [] }] }),
    ]
    for (const record of cases) {
      expect(projectTrackingActionScopes(record, 'MODIFY', 'SUBSCRIPTION')).toEqual([])
    }
    expect(projectTrackingActionScopes(managementItem({
      available_actions: [modifyAction],
    }), 'MODIFY', 'SUBSCRIPTION')).toEqual(['SUBSCRIPTION'])
  })

  it('sends only the four management actions this page can build a request for', () => {
    expect(isSendableManagementAction('MODIFY')).toBe(true)
    expect(isSendableManagementAction('SET_ENABLED')).toBe(true)
    expect(isSendableManagementAction('REFRESH_RSS')).toBe(true)
    expect(isSendableManagementAction('DELETE_EXTERNAL')).toBe(true)
    for (const code of ['SUBMIT', 'RETRY', 'RECOVER_AUTO', 'REVALIDATE', 'NOT_KNOWN']) {
      expect(isSendableManagementAction(code)).toBe(false)
    }
    // The two-scope request vocabulary fails closed for everything else.
    expect(isTrackingManagementScope('SUBSCRIPTION')).toBe(true)
    expect(isTrackingManagementScope('ASSOCIATED_RSS')).toBe(true)
    expect(isTrackingManagementScope('EVERYTHING')).toBe(false)
  })

  it('accepts only an action and scope the live session still projects', () => {
    const ok = beginManagementWrite()
    expect(ok.started.accepted).toBe(true)
    expect(bodyOf(ok.started)).toMatchObject({
      target_scope: 'SUBSCRIPTION', patch: { title: '新标题' }, expected_revision: 3, confirm: true,
    })
    expect(String(bodyOf(ok.started).idempotency_key).length).toBeGreaterThanOrEqual(8)

    // A scope the server did not offer for this record is refused.
    expect(beginManagementWrite({
      item: managementItem({ available_actions: [{ ...modifyAction, target_scopes: ['SUBSCRIPTION'] }] }),
      targetScope: 'ASSOCIATED_RSS', patch: { name: 'x' },
    }).started.accepted).toBe(false)
    // An empty or cross-scope patch never becomes an intent.
    expect(beginManagementWrite({ patch: {} }).started.accepted).toBe(false)
    expect(beginManagementWrite({ patch: { name: 'x' } }).started.accepted).toBe(false)
    // A revision the server could not have issued is refused.
    expect(beginManagementWrite({ item: managementItem({ revision: 0 }) }).started.accepted).toBe(false)
    // An action or scope this page cannot send is refused.
    expect(beginManagementWrite({ action: action({ code: 'REVALIDATE' }), patch: null }).started.accepted).toBe(false)
    expect(beginManagementWrite({ targetScope: 'EVERYTHING' as never }).started.accepted).toBe(false)
  })

  it('binds every management action to its own generated endpoint', () => {
    const disabled = managementItem({ status: 'DISABLED', available_actions: [ENABLE_ACTION] })
    const deleteItem = managementItem({ available_actions: [DELETE_ACTION] })
    const routes: ReadonlyArray<[ReturnType<typeof beginManagementWrite>['started'], string]> = [
      [beginManagementWrite().started, '/api/v1/tracking/items/{tracking_id}/modify'],
      [beginManagementWrite({ action: ENABLE_ACTION, item: disabled, patch: null }).started,
        '/api/v1/tracking/items/{tracking_id}/set-enabled'],
      [beginManagementWrite({
        action: REFRESH_ACTION, item: managementItem({ available_actions: [REFRESH_ACTION] }),
        targetScope: 'ASSOCIATED_RSS', patch: null,
      }).started, '/api/v1/tracking/items/{tracking_id}/refresh'],
      [beginManagementWrite({
        action: DELETE_ACTION, item: deleteItem, patch: null,
      }).started, '/api/v1/tracking/items/{tracking_id}/delete-external'],
    ]
    for (const [started, endpoint] of routes) {
      expect(started.accepted).toBe(true)
      expect(started.request?.endpoint).toBe(endpoint)
    }
  })

  it('builds the scope-discriminated body once, with one credential and one key', () => {
    const subscription = beginManagementWrite({}, { storageDir: STORAGE })
    const subscriptionBody = bodyOf(subscription.started)
    expect(subscriptionBody).toEqual({
      target_scope: 'SUBSCRIPTION',
      patch: { title: '新标题' },
      expected_revision: 3,
      idempotency_key: subscriptionBody.idempotency_key,
      confirm: true,
      connection_ref: CONNECTION.connection_ref, configuration_revision: CONNECTION.configuration_revision,
      storage_dir: STORAGE,
    })

    const rss = beginManagementWrite({ targetScope: 'ASSOCIATED_RSS', patch: { name: 'x' } })
    const rssBody = bodyOf(rss.started)
    expect(rssBody).toEqual({
      target_scope: 'ASSOCIATED_RSS',
      patch: { name: 'x' },
      expected_revision: 3,
      idempotency_key: rssBody.idempotency_key,
      confirm: true,
      connection_ref: CONNECTION.connection_ref, configuration_revision: CONNECTION.configuration_revision,
    })
    // The body shape cannot express an external id, URL or raw response.
    expect(Object.keys(rssBody).sort()).toEqual(
      ['target_scope', 'patch', 'expected_revision', 'idempotency_key', 'confirm', 'connection_ref', 'configuration_revision'].sort(),
    )
    expect(Object.keys(rssBody.patch as Body)).toEqual(['name'])

    // A session without a saved generation is never turned into a request.
    expect(beginManagementWrite({}, { connection: null }).started.accepted).toBe(false)
  })

  it('carries the confirmed local plan only for a subscription modify (issue #91)', () => {
    const { started } = beginManagementWrite({
      localPlan: { filter_rule: { must_contain: '1080p' } },
    })
    expect(bodyOf(started).local_plan).toEqual({ filter_rule: { must_contain: '1080p' } })
    // An empty local plan is not sent at all.
    const empty = beginManagementWrite({ localPlan: {} })
    expect(Object.keys(bodyOf(empty.started))).not.toContain('local_plan')
  })

  it('derives the enable direction from the record status, never from the caller', () => {
    const disabled = managementItem({
      status: 'DISABLED', status_label: '已停用', available_actions: [ENABLE_ACTION],
    })
    expect(bodyOf(beginManagementWrite({ action: ENABLE_ACTION, item: disabled }).started))
      .toMatchObject({ target_scope: 'SUBSCRIPTION', enabled: true, expected_revision: 3, confirm: true })

    for (const status of ['ACTIVE', 'EXTERNAL_ONLY'] as const) {
      const body = bodyOf(beginManagementWrite({
        action: DISABLE_ACTION, item: managementItem({ status, available_actions: [DISABLE_ACTION] }),
      }).started)
      expect(body.enabled).toBe(false)
      expect(Object.keys(body)).not.toContain('patch')
    }
    // A status that names no direction never becomes a request even when the
    // action object claims to offer one.
    for (const status of ['PENDING_SUBMIT', 'SUBMITTING', 'UNKNOWN'] as const) {
      expect(beginManagementWrite({
        action: ENABLE_ACTION, item: managementItem({ status, available_actions: [ENABLE_ACTION] }),
      }).started.accepted).toBe(false)
    }
    // The scope must still be one the server actually projected.
    expect(beginManagementWrite({
      action: DISABLE_ACTION,
      item: managementItem({
        status: 'ACTIVE', available_actions: [{ ...DISABLE_ACTION, target_scopes: ['ASSOCIATED_RSS'] }],
      }),
      targetScope: 'SUBSCRIPTION',
    }).started.accepted).toBe(false)
  })

  it('only ever targets the current record own associated RSS for a refresh', () => {
    const refresh = beginManagementWrite({
      action: REFRESH_ACTION, item: managementItem({ available_actions: [REFRESH_ACTION] }),
      targetScope: 'ASSOCIATED_RSS', patch: null,
    })
    expect(bodyOf(refresh.started)).toEqual({
      target_scope: 'ASSOCIATED_RSS',
      expected_revision: 3,
      idempotency_key: bodyOf(refresh.started).idempotency_key,
      confirm: true,
      connection_ref: CONNECTION.connection_ref, configuration_revision: CONNECTION.configuration_revision,
    })
    // A subscription-scoped refresh never travels through the RSS route.
    expect(beginManagementWrite({
      action: REFRESH_ACTION,
      item: managementItem({ available_actions: [{ ...REFRESH_ACTION, target_scopes: ['SUBSCRIPTION'] }] }),
      targetScope: 'ASSOCIATED_RSS', patch: null,
    }).started.accepted).toBe(false)
    expect(beginManagementWrite({
      action: REFRESH_ACTION, item: managementItem(), targetScope: 'ASSOCIATED_RSS', patch: null,
    }).started.accepted).toBe(false)
  })

  it('deletes exactly one explicitly chosen external object of this record', () => {
    const deleteItem = managementItem({ available_actions: [DELETE_ACTION] })
    const deleted = beginManagementWrite({
      action: DELETE_ACTION, item: deleteItem, targetScope: 'SUBSCRIPTION', patch: null,
    })
    const body = bodyOf(deleted.started)
    expect(body).toEqual({
      target_scope: 'SUBSCRIPTION',
      expected_revision: 3,
      idempotency_key: body.idempotency_key,
      confirm: true,
      connection_ref: CONNECTION.connection_ref,
      configuration_revision: CONNECTION.configuration_revision,
    })
    // The generated delete body has no ``file`` field at all.
    expect(Object.keys(body).sort()).toEqual(
      ['target_scope', 'expected_revision', 'idempotency_key', 'confirm', 'connection_ref', 'configuration_revision'].sort(),
    )
    expect(JSON.stringify(body)).not.toContain('file')
    // The server does not offer the delete for this record at all.
    expect(beginManagementWrite({
      action: DELETE_ACTION, item: managementItem(), targetScope: 'SUBSCRIPTION', patch: null,
    }).started.accepted).toBe(false)
    // The server offers only the subscription scope; the RSS choice is dropped.
    expect(beginManagementWrite({
      action: DELETE_ACTION,
      item: managementItem({ available_actions: [{ ...DELETE_ACTION, target_scopes: ['SUBSCRIPTION'] }] }),
      targetScope: 'ASSOCIATED_RSS', patch: null,
    }).started.accepted).toBe(false)
  })

  it('names the action, the scope and the direction in each confirmation', () => {
    const disabled = managementItem({
      status: 'DISABLED', status_label: '已停用', available_actions: [ENABLE_ACTION],
    })
    const enable = beginManagementWrite({ action: ENABLE_ACTION, item: disabled }, { confirmed: false })
    expect(enable.started.ask).toBe('IMPACT')
    expect(enable.started.confirmation).toEqual({
      title: '启用 Auto Bangumi 番剧订阅',
      message: expect.stringContaining('不修改 MiGuOrca 本地方案'),
      confirmLabel: '确认启用订阅',
    })

    const disable = beginManagementWrite({
      action: DISABLE_ACTION,
      item: managementItem({ status: 'ACTIVE', available_actions: [DISABLE_ACTION] }),
      targetScope: 'ASSOCIATED_RSS', patch: null,
    }, { confirmed: false })
    expect(disable.started.confirmation!.title).toContain('停用')
    expect(disable.started.confirmation!.message).toContain('关联 RSS')
    expect(disable.started.confirmation!.confirmLabel).toBe('确认停用 RSS')

    const refresh = beginManagementWrite({
      action: REFRESH_ACTION, item: managementItem({ available_actions: [REFRESH_ACTION] }),
      targetScope: 'ASSOCIATED_RSS', patch: null,
    }, { confirmed: false })
    expect(refresh.started.confirmation!.message).toContain('不会刷新全局 RSS')
    expect(refresh.started.confirmation!.confirmLabel).toBe('确认立即刷新资源')

    const modify = beginManagementWrite({}, { confirmed: false })
    expect(modify.started.confirmation).toEqual({
      title: '修改 Auto Bangumi 番剧订阅',
      message: expect.stringContaining('不修改 MiGuOrca 本地方案'),
      confirmLabel: '确认修改订阅',
    })
    const rssModify = beginManagementWrite({ targetScope: 'ASSOCIATED_RSS', patch: { name: 'x' } }, { confirmed: false })
    expect(rssModify.started.confirmation!.message).toContain('关联 RSS')
    expect(rssModify.started.confirmation!.title).not.toContain('ASSOCIATED_RSS')
    expect(rssModify.started.confirmation!.confirmLabel).toBe('确认修改 RSS')
  })

  it('confirms the delete as a danger that keeps every local record', () => {
    const deleted = beginManagementWrite({
      action: DELETE_ACTION,
      item: managementItem({ available_actions: [DELETE_ACTION] }),
      patch: null,
    }, { confirmed: false })
    const copy = deleted.started.confirmation!
    expect(copy.danger).toBe(true)
    expect(copy.confirmLabel).toBe('确认删除外部对象')
    expect(copy.message).toContain('不会删除任何媒体文件')
    for (const kept of ['本地订阅方案', '追番记录', '审计记录', '下载任务', '已下载媒体文件']) {
      expect(copy.message).toContain(kept)
    }
    // The other management dialogs stay non-dangerous.
    const refresh = beginManagementWrite({
      action: REFRESH_ACTION, item: managementItem({ available_actions: [REFRESH_ACTION] }),
      targetScope: 'ASSOCIATED_RSS', patch: null,
    }, { confirmed: false })
    expect(refresh.started.confirmation!.danger).toBeUndefined()
  })

  it('reports the server management status as fixed Chinese copy only', () => {
    const succeeded = beginManagementWrite()
    expect(succeeded.writes.finishManagement(modifyResult())).toEqual([
      { kind: 'recheck', trackingId: 'tracking-1', refreshList: false },
    ])
    const ok = succeeded.writes.sessions.value.management!
    expect(ok).toMatchObject({ state: 'SUCCEEDED', targetScope: 'SUBSCRIPTION', needsManual: false })
    expect(ok.message).toContain('已应用本次修改')
    expect(ok.message).not.toContain('SUCCEEDED')
    expect(ok.message).not.toContain('管理操作已完成')

    const failed = beginManagementWrite({ targetScope: 'ASSOCIATED_RSS', patch: { name: 'x' } })
    failed.writes.finishManagement(modifyResult({
      management_status: 'FAILED', safe_message: 'Auto Bangumi 未应用管理操作',
    }))
    const bad = failed.writes.sessions.value.management!
    expect(bad).toMatchObject({ state: 'FAILED', targetScope: 'ASSOCIATED_RSS' })
    expect(bad.message).toContain('未应用本次修改')
    expect(bad.message).not.toContain('FAILED')
  })

  // The server's own ``needs_manual`` flag is only consulted for a decided
  // verdict (where it can never turn a verdict back into a manual one); an
  // unresolved status always requires a human conclusion, which is why the
  // snapshot pins ``needsManual``/``manualNotice`` rather than the raw flag.
  it('treats every other management status as an unresolved result', () => {
    for (const status of ['PREPARED', 'IN_PROGRESS', 'OUTCOME_UNKNOWN', 'RECOVERY_REQUIRED']) {
      const { writes } = beginManagementWrite()
      writes.finishManagement(modifyResult({ management_status: status }))
      const settled = writes.sessions.value.management!
      expect(settled.state).toBe('UNKNOWN')
      expect(settled.needsManual).toBe(true)
      expect(settled.manualNotice).toBe(MANAGEMENT_MANUAL_NOTICE)
      expect(MANAGEMENT_MANUAL_NOTICE).toContain('独立核对')
      expect(settled.message).toContain('只读回查')
      expect(settled.message).not.toContain('已应用')
      expect(settled.message).not.toContain(status)
    }
    // A management_status outside the documented enum is never a success.
    const unknown = beginManagementWrite()
    unknown.writes.finishManagement(modifyResult({ management_status: 'SOMETHING_NEW' }))
    expect(unknown.writes.sessions.value.management!.state).toBe('UNKNOWN')
    expect(unknown.writes.sessions.value.management!.message).not.toContain('SOMETHING_NEW')
  })

  it('reports success and definite failure in the wording of the action that was sent', () => {
    const enabled = beginManagementWrite({
      action: ENABLE_ACTION,
      item: managementItem({ status: 'DISABLED', available_actions: [ENABLE_ACTION] }),
      patch: null,
    })
    enabled.writes.finishManagement(modifyResult({ action: 'SET_ENABLED', management_status: 'SUCCEEDED' }))
    expect(enabled.writes.sessions.value.management).toMatchObject({
      operation: 'SET_ENABLED', state: 'SUCCEEDED', needsManual: false,
    })
    expect(enabled.writes.sessions.value.management!.message).toContain('已应用本次启用或停用')
    expect(enabled.writes.sessions.value.management!.message).not.toContain('修改')

    const refreshed = beginManagementWrite({
      action: REFRESH_ACTION, item: managementItem({ available_actions: [REFRESH_ACTION] }),
      targetScope: 'ASSOCIATED_RSS', patch: null,
    })
    refreshed.writes.finishManagement(modifyResult({
      action: 'REFRESH_RSS', management_status: 'FAILED', safe_message: 'Auto Bangumi 未应用管理操作',
    }))
    expect(refreshed.writes.sessions.value.management).toMatchObject({
      operation: 'REFRESH_RSS', state: 'FAILED',
    })
    expect(refreshed.writes.sessions.value.management!.message).toContain('未接受本次刷新')
    expect(refreshed.writes.sessions.value.management!.message).not.toContain('FAILED')

    const deleted = beginManagementWrite({
      action: DELETE_ACTION,
      item: managementItem({ available_actions: [DELETE_ACTION] }),
      patch: null,
    })
    deleted.writes.finishManagement(modifyResult({ action: 'DELETE_EXTERNAL', management_status: 'SUCCEEDED' }))
    const deleteSession = deleted.writes.sessions.value.management!
    expect(deleteSession).toMatchObject({ operation: 'DELETE_EXTERNAL', state: 'SUCCEEDED', needsManual: false })
    expect(deleteSession.message).toBe(MANAGEMENT_MESSAGES.DELETE_EXTERNAL!.SUCCEEDED)
    expect(deleteSession.message).toContain('均保留')
    expect(deleteSession.message).not.toContain('修改')

    const deleteFailed = beginManagementWrite({
      action: DELETE_ACTION, item: managementItem({ available_actions: [DELETE_ACTION] }), patch: null,
    })
    deleteFailed.writes.finishManagement(modifyResult({
      action: 'DELETE_EXTERNAL', management_status: 'FAILED',
    }))
    expect(deleteFailed.writes.sessions.value.management!.message).toBe(
      MANAGEMENT_MESSAGES.DELETE_EXTERNAL!.FAILED,
    )
    expect(deleteFailed.writes.sessions.value.management!.message).toContain('未删除该外部对象')
    expect(deleteFailed.writes.sessions.value.management!.message).not.toContain('修改')

    // A partial or undocumented delete result stays unresolved and keeps the
    // page's single intent instead of being read as a successful delete.
    for (const status of ['PREPARED', 'IN_PROGRESS', 'OUTCOME_UNKNOWN', 'RECOVERY_REQUIRED']) {
      const partial = beginManagementWrite({
        action: DELETE_ACTION, item: managementItem({ available_actions: [DELETE_ACTION] }), patch: null,
      })
      partial.writes.finishManagement(modifyResult({
        action: 'DELETE_EXTERNAL', management_status: status,
      }))
      const settled = partial.writes.sessions.value.management!
      expect(settled.state).toBe('UNKNOWN')
      expect(settled.keepsIntent).toBe(true)
      expect(settled.message).not.toContain('已删除')
      expect(settled.message).not.toContain(status)
    }

    // The one delete conflict whose generic wording would misdescribe it.
    const missing = beginManagementWrite({
      action: DELETE_ACTION, item: managementItem({ available_actions: [DELETE_ACTION] }), patch: null,
    })
    missing.writes.failManagement({ status: 409, httpError: true, type: 'tracking_target_missing' })
    expect(missing.writes.sessions.value.management!.state).toBe('CONFLICT')
    expect(missing.writes.sessions.value.management!.message).toContain('本次未删除任何外部对象')
    expect(missing.writes.sessions.value.management!.keepsIntent).toBe(false)
  })

  it('treats a partial, in-flight or undocumented result as unknown for every action', () => {
    const cases: ReadonlyArray<[ItemAction, TrackingItem, 'SUBSCRIPTION' | 'ASSOCIATED_RSS', unknown]> = [
      [modifyAction, managementItem(), 'SUBSCRIPTION', { title: 'x' }],
      [ENABLE_ACTION, managementItem({ status: 'DISABLED', available_actions: [ENABLE_ACTION] }), 'SUBSCRIPTION', null],
      [REFRESH_ACTION, managementItem({ available_actions: [REFRESH_ACTION] }), 'ASSOCIATED_RSS', null],
    ]
    for (const [action0, record, scope, patch] of cases) {
      for (const status of ['PREPARED', 'IN_PROGRESS', 'OUTCOME_UNKNOWN', 'RECOVERY_REQUIRED']) {
        const { writes } = beginManagementWrite({
          action: action0, item: record, targetScope: scope, patch,
        })
        writes.finishManagement(modifyResult({ management_status: status }))
        const settled = writes.sessions.value.management!
        expect(settled.state).toBe('UNKNOWN')
        expect(settled.needsManual).toBe(true)
        expect(settled.keepsIntent).toBe(true)
        expect(settled.message).toContain('只读回查')
        expect(settled.message).not.toContain('已应用')
        expect(settled.message).not.toContain(status)
      }
    }
  })

  it('gives every documented management conflict its own fixed next step', () => {
    for (const [type, message] of Object.entries(MANAGEMENT_CONFLICT_MESSAGES)) {
      const { writes } = beginManagementWrite()
      writes.failManagement({ status: 409, httpError: true, type })
      const settled = writes.sessions.value.management!
      expect(settled.state).toBe('CONFLICT')
      expect(settled.message).toBe(message)
      expect(message).toContain('未提交到 Auto Bangumi')
      expect(message).not.toContain(type)
      expect(settled.keepsIntent).toBe(false)
    }
    // An unnamed 409 falls back to the generic next step, never to blank copy.
    for (const unknown of ['brand_new_conflict', null, undefined, 42]) {
      const unnamed = beginManagementWrite()
      unnamed.writes.failManagement({ status: 409, httpError: true, type: unknown })
      const settled = unnamed.writes.sessions.value.management!
      expect(settled.message).toBe(MANAGEMENT_CONFLICT_FALLBACK)
      expect(settled.message).not.toContain('brand_new_conflict')
    }
  })

  it('names the request itself only where the generic wording would misdescribe it', () => {
    const cases: ReadonlyArray<[ItemAction, TrackingItem, 'SUBSCRIPTION' | 'ASSOCIATED_RSS', unknown, string]> = [
      [ENABLE_ACTION, managementItem({ status: 'DISABLED', available_actions: [ENABLE_ACTION] }), 'SUBSCRIPTION', null,
        '本次启停请求未通过服务端校验，未提交到 Auto Bangumi；正在刷新最新详情，请重新确认。'],
      [REFRESH_ACTION, managementItem({ available_actions: [REFRESH_ACTION] }), 'ASSOCIATED_RSS', null,
        '本次刷新请求未通过服务端校验，未提交到 Auto Bangumi；正在刷新最新详情，请重新确认。'],
      [DELETE_ACTION, managementItem({ available_actions: [DELETE_ACTION] }), 'SUBSCRIPTION', null,
        '该记录当前没有对应的外部对象，本次未删除任何外部对象；正在刷新最新详情。'],
    ]
    for (const [action0, record, scope, patch, message] of cases) {
      const type = action0.code === 'DELETE_EXTERNAL' ? 'tracking_target_missing' : 'tracking_management_patch_invalid'
      const { writes } = beginManagementWrite({ action: action0, item: record, targetScope: scope, patch })
      writes.failManagement({ status: 409, httpError: true, type })
      expect(writes.sessions.value.management!.message).toBe(message)
      expect(writes.sessions.value.management!.message).not.toContain(type)
    }
  })

  it('keeps the raw conflict type and the action wording out of the copy', () => {
    for (const [action0, record, scope, patch, expected] of [
      [modifyAction, managementItem(), 'SUBSCRIPTION', { title: 'x' }, '外部对象已变化'],
      [REFRESH_ACTION, managementItem({ available_actions: [REFRESH_ACTION] }), 'ASSOCIATED_RSS', null, '本次刷新请求未通过服务端校验'],
      [ENABLE_ACTION, managementItem({ status: 'DISABLED', available_actions: [ENABLE_ACTION] }), 'SUBSCRIPTION', null, '外部对象已变化'],
    ] as ReadonlyArray<[ItemAction, TrackingItem, 'SUBSCRIPTION' | 'ASSOCIATED_RSS', unknown, string]>) {
      const type = expected === '外部对象已变化' ? 'tracking_target_drift' : 'tracking_management_patch_invalid'
      const { writes } = beginManagementWrite({ action: action0, item: record, targetScope: scope, patch })
      writes.failManagement({ status: 409, httpError: true, type })
      const settled = writes.sessions.value.management!
      expect(settled.state).toBe('CONFLICT')
      expect(settled.message).toContain(expected)
      expect(settled.message).not.toContain(type)
      expect(settled.keepsIntent).toBe(false)
    }

    const unknownConflict = beginManagementWrite()
    unknownConflict.writes.failManagement({ status: 409, httpError: true, type: 'brand_new_conflict' })
    expect(unknownConflict.writes.sessions.value.management!.message).toContain('未提交到 Auto Bangumi')
    expect(unknownConflict.writes.sessions.value.management!.message).not.toContain('brand_new_conflict')

    const rejected = beginManagementWrite()
    rejected.writes.failManagement({ status: 404, httpError: true })
    expect(rejected.writes.sessions.value.management).toMatchObject({ state: 'REJECTED' })
    expect(rejected.writes.sessions.value.management!.message).toContain('未修改 Auto Bangumi 外部订阅')

    const enableRejected = beginManagementWrite({
      action: ENABLE_ACTION,
      item: managementItem({ status: 'DISABLED', available_actions: [ENABLE_ACTION] }),
      patch: null,
    })
    enableRejected.writes.failManagement({ status: 404, httpError: true })
    expect(enableRejected.writes.sessions.value.management!.message).toContain('未改变 Auto Bangumi 的启用状态')
    expect(enableRejected.writes.sessions.value.management!.message).not.toContain('修改')

    const deleteRejected = beginManagementWrite({
      action: DELETE_ACTION, item: managementItem({ available_actions: [DELETE_ACTION] }), patch: null,
    })
    deleteRejected.writes.failManagement({ status: 404, httpError: true })
    expect(deleteRejected.writes.sessions.value.management!.message).toContain('未删除 Auto Bangumi 外部对象')
  })

  it('converges an unbuildable request on a definite failure instead of in-flight', () => {
    // A session without any generation is refused before a request exists.
    const missing = beginManagementWrite({}, { connection: null })
    expect(missing.started.accepted).toBe(false)
    expect(missing.writes.sessions.value.management).toBeNull()

    // A generation the page cannot turn into a safe body (no server address) is
    // a definite page-side refusal: zero requests, and the panel converges.
    const { writes, started } = beginManagementWrite({}, {
      connection: { connection_ref: '', configuration_revision: 3 },
    })
    expect(started.accepted).toBe(false)
    expect(started.request).toBeNull()
    expect(started.effects).toEqual([{ kind: 'recheck', trackingId: 'tracking-1', refreshList: true }])
    const settled = writes.sessions.value.management!
    expect(settled.state).toBe('REJECTED')
    expect(settled.state).not.toBe('IN_FLIGHT')
    expect(settled.keepsIntent).toBe(false)
    expect(settled.message).toBe(MANAGEMENT_UNBUILDABLE_MESSAGE)
    expect(settled.message).toContain('未向 Auto Bangumi 发送任何请求')
    expect(settled.message).not.toContain('IN_FLIGHT')
    expect(settled.message).not.toContain('base_url')
  })

  it('replays a locked intent only for the identical request, revision aside', () => {
    const disabled = () => managementItem({
      status: 'DISABLED', status_label: '已停用', available_actions: [ENABLE_ACTION],
    })
    const first = beginManagementWrite({ action: ENABLE_ACTION, item: disabled(), patch: null })
    const firstBody = bodyOf(first.started)
    first.writes.finishManagement(modifyResult({ management_status: 'OUTCOME_UNKNOWN' }))
    expect(first.writes.sessions.value.management!.keepsIntent).toBe(true)

    // The record moved on while the first request was in flight, so a fresh
    // intent would carry another revision and another key. The request itself is
    // unchanged, which is exactly what a locked replay must recognise.
    const replay = first.writes.beginManagement({
      action: ENABLE_ACTION, item: { ...disabled(), revision: 9 },
      targetScope: 'SUBSCRIPTION', patch: null,
    }, { confirmed: true, connection: CONNECTION })
    expect(replay.accepted).toBe(true)
    expect(bodyOf(replay).idempotency_key).toBe(firstBody.idempotency_key)
    expect(bodyOf(replay).expected_revision).toBe(3)
    first.writes.finishManagement(modifyResult({ management_status: 'OUTCOME_UNKNOWN' }))

    // A different scope or a different enable direction is not the same request.
    const otherScope = first.writes.beginManagement({
      action: ENABLE_ACTION, item: disabled(), targetScope: 'ASSOCIATED_RSS', patch: null,
    }, { confirmed: true, connection: CONNECTION })
    expect(otherScope.accepted).toBe(false)
    expect(otherScope.refusal).toEqual({ trackingId: 'tracking-1', reason: 'INTENT' })
    const otherDirection = first.writes.beginManagement({
      action: DISABLE_ACTION,
      item: managementItem({ status: 'ACTIVE', available_actions: [DISABLE_ACTION] }),
      targetScope: 'SUBSCRIPTION', patch: null,
    }, { confirmed: true, connection: CONNECTION })
    expect(otherDirection.accepted).toBe(false)
    expect(otherDirection.refusal).toEqual({ trackingId: 'tracking-1', reason: 'INTENT' })

    // The same patch at another revision is the same request; a different patch
    // never is.
    const lockedModify = beginManagementWrite({ patch: { title: 'x' } })
    const lockedBody = bodyOf(lockedModify.started)
    lockedModify.writes.finishManagement(modifyResult({ management_status: 'OUTCOME_UNKNOWN' }))
    const samePatch = lockedModify.writes.beginManagement({
      action: modifyAction, item: managementItem({ revision: 9 }),
      targetScope: 'SUBSCRIPTION', patch: { title: 'x' },
    }, { confirmed: true, connection: CONNECTION })
    expect(samePatch.accepted).toBe(true)
    expect(bodyOf(samePatch).idempotency_key).toBe(lockedBody.idempotency_key)
    expect(bodyOf(samePatch).expected_revision).toBe(3)
    lockedModify.writes.finishManagement(modifyResult({ management_status: 'OUTCOME_UNKNOWN' }))
    const otherPatch = lockedModify.writes.beginManagement({
      action: modifyAction, item: managementItem(),
      targetScope: 'SUBSCRIPTION', patch: { title: 'y' },
    }, { confirmed: true, connection: CONNECTION })
    expect(otherPatch.accepted).toBe(false)
    expect(otherPatch.refusal).toEqual({ trackingId: 'tracking-1', reason: 'INTENT' })
  })
})

// ---------------------------------------------------------------------------
// Unified plan delete (issue #92).
// ---------------------------------------------------------------------------

function planDeleteResult(overrides: Record<string, unknown> = {}) {
  return { tracking_id: 'tracking-1', outcome: 'DELETED', external_deleted: true, ...overrides } as never
}

describe('tracking plan delete session (issue #92)', () => {
  it('needs no connection for a purely local delete and one for the external option', () => {
    const local = session()
    const localStart = local.beginPlanDelete({ item: item(), deleteExternal: false }, { connection: null })
    expect(localStart.accepted).toBe(true)
    expect(localStart.request?.endpoint).toBe('/api/v1/tracking/items/{tracking_id}/delete-plan')
    expect(localStart.request?.path).toEqual({ tracking_id: 'tracking-1' })
    expect(bodyOf(localStart)).toMatchObject({ confirm: true, delete_external: false })
    expect(Object.keys(bodyOf(localStart))).not.toContain('connection_ref')
    expect(local.planDelete.value!.state).toBe('IN_FLIGHT')

    const external = session()
    expect(external.beginPlanDelete(
      { item: item(), deleteExternal: true }, { connection: null },
    ).accepted).toBe(false)
    const withConnection = external.beginPlanDelete(
      { item: item(), deleteExternal: true }, { connection: CONNECTION, storageDir: STORAGE },
    )
    expect(bodyOf(withConnection)).toMatchObject({
      delete_external: true, connection_ref: CONNECTION.connection_ref,
      configuration_revision: 3, storage_dir: STORAGE,
    })
  })

  it('reports the local deletion and re-reads the list', () => {
    const local = session()
    local.beginPlanDelete({ item: item(), deleteExternal: true }, { connection: CONNECTION })
    expect(local.finishPlanDelete(planDeleteResult())).toEqual([
      {
        kind: 'notify',
        feedback: {
          channel: 'success', title: '追番方案已删除',
          message: '已同时删除受控外部订阅；已下载媒体保留。',
        },
      },
      { kind: 'recheck', trackingId: null, refreshList: true },
    ])
    expect(local.planDelete.value).toEqual({
      trackingId: 'tracking-1', state: 'DELETED', message: '追番方案已删除。',
    })

    const keepExternal = session()
    keepExternal.beginPlanDelete({ item: item(), deleteExternal: false }, { connection: null })
    const effects = keepExternal.finishPlanDelete(planDeleteResult({ outcome: 'SOMETHING_NEW' }))
    expect(keepExternal.planDelete.value!.state).toBe('EXTERNAL_UNKNOWN')
    expect(keepExternal.planDelete.value!.message).toContain('外部删除结果未知')
    expect(effects).toEqual([{ kind: 'recheck', trackingId: 'tracking-1', refreshList: true }])
  })

  it('keeps the local plan on a definite external failure and on an unreadable one', () => {
    const failed = session()
    failed.beginPlanDelete({ item: item(), deleteExternal: true }, { connection: CONNECTION })
    failed.finishPlanDelete(planDeleteResult({ outcome: 'EXTERNAL_FAILED' }))
    expect(failed.planDelete.value!.state).toBe('EXTERNAL_FAILED')
    expect(failed.planDelete.value!.message).toContain('本地方案与追番记录均已保留')

    const conflict = session()
    conflict.beginPlanDelete({ item: item(), deleteExternal: true }, { connection: CONNECTION })
    conflict.failPlanDelete({ status: 409, httpError: true })
    expect(conflict.planDelete.value!.state).toBe('EXTERNAL_FAILED')

    const unknown = session()
    unknown.beginPlanDelete({ item: item(), deleteExternal: true }, { connection: CONNECTION })
    unknown.failPlanDelete({ status: 503, httpError: true })
    expect(unknown.planDelete.value!.state).toBe('EXTERNAL_UNKNOWN')
    unknown.resetPlanDelete()
    expect(unknown.planDelete.value).toBeNull()
  })
})

// ---------------------------------------------------------------------------
// The page's single page-level intent.
// ---------------------------------------------------------------------------

describe('single page-level intent (D38-09.4)', () => {
  it('refuses a different record while one unresolved result owns the page', () => {
    const { writes } = inFlightSubmit()
    writes.finishSubmit(submitResult({ outcome: 'UNKNOWN' }))
    expect(writes.hasUnresolvedLock.value).toBe(true)
    expect(writes.unresolvedOwner('tracking-2')).toBe('tracking-1')
    expect(writes.unresolvedOwner('tracking-1')).toBe('')
    expect(writes.busyFor('tracking-2')).toBe(true)
    expect(writes.busyFor('tracking-1')).toBe(false)

    const other = writes.beginSubmit(
      { item: item({ tracking_id: 'tracking-2' }), action: action() },
      { mode: 'CONTINUE_TRACKING', confirmed: true, connection: CONNECTION },
    )
    expect(other.refusal).toEqual({ trackingId: 'tracking-2', reason: 'INTENT' })
    expect(writes.noticeFor('tracking-2')).toContain('上一次外部操作的结果仍未确认')
    expect(writes.noticeFor('tracking-3')).toContain('上一次外部操作的结果仍未确认')

    // The record's own next step is legitimate and clears the refusal notice.
    const own = writes.beginSubmit({ item: item(), action: action() }, {
      mode: 'CONTINUE_TRACKING', confirmed: true, connection: CONNECTION,
    })
    expect(own.accepted).toBe(true)
    expect(writes.noticeFor('tracking-1')).toBe('')
  })

  it('blocks a write while this record still has an unresolved recovery', () => {
    const pending = beginRecoveryWrite('RECOVER_AUTO')
    pending.writes.finishRecovery(recoverResult({ outcome: 'SOMETHING_NEW' }))
    const blocked = pending.writes.beginSubmit({ item: recoverableItem(), action: action() }, {
      mode: 'CONTINUE_TRACKING', confirmed: true, connection: CONNECTION,
    })
    expect(blocked.refusal).toEqual({ trackingId: 'tracking-1', reason: 'INTENT' })
    // A recovery is still allowed for that very record.
    expect(beginRecoveryWrite('RECOVER_AUTO', { writes: pending.writes }).started.accepted).toBe(true)
  })

  it('forgets a decided session and its notice on a hard reset', () => {
    const { writes } = inFlightSubmit()
    writes.finishSubmit(submitResult({ outcome: 'ACTIVE' }))
    expect(writes.hasUnresolvedLock.value).toBe(false)
    writes.reset()
    expect(writes.sessions.value).toEqual({ submit: null, recovery: null, management: null })
    expect(writes.planDelete.value).toBeNull()
    expect(writes.noticeFor('tracking-1')).toBe('')
    expect(writes.hasUnresolvedLock.value).toBe(false)
  })
})

// ---------------------------------------------------------------------------
// Explicit batch submit (issue #87, #100).
// ---------------------------------------------------------------------------

function batchItem(overrides: Partial<TrackingItem> = {}): TrackingItem {
  return item({
    available_actions: [action()],
    ...overrides,
  })
}

describe('batch selection rules (issue #87)', () => {
  it('offers only server-projected submit-family rows and fails closed otherwise', () => {
    const writes = session()
    expect(writes.batchSkipReason(batchItem())).toBeNull()
    expect(writes.batchSkipReason(batchItem({
      available_actions: [action({ code: 'RETRY', label: '重试', style: 'SECONDARY' })],
    }))).toBeNull()
    // A transient per-row state never enters a batch.
    expect(writes.batchSkipReason(batchItem({ status_group: 'PROCESSING' }))).toContain('正在处理中')
    // An unknown or unsupported action does not become a submit.
    expect(writes.batchSkipReason(batchItem({ available_actions: [modifyAction] }))).toContain('不可提交')
    expect(writes.batchSkipReason(batchItem({ available_actions: [] }))).toContain('不可提交')
  })

  it('toggles one row without disturbing the rest of the selection', () => {
    const writes = session()
    writes.toggleBatchRow('a')
    writes.toggleBatchRow('b')
    expect(writes.batchSelection.value.selected).toEqual(['a', 'b'])
    expect(writes.isBatchSelected('a')).toBe(true)
    writes.toggleBatchRow('a')
    expect(writes.batchSelection.value.selected).toEqual(['b'])
    expect(writes.isBatchSelected('a')).toBe(false)
  })

  it('selects only the submittable rows of the current result and states the rest', () => {
    const writes = session()
    writes.selectAllBatch([
      batchItem({ tracking_id: 'a' }),
      batchItem({ tracking_id: 'b', status_group: 'PROCESSING' }),
      batchItem({ tracking_id: 'c', available_actions: [] }),
      batchItem({
        tracking_id: 'd',
        available_actions: [action({ code: 'RETRY', label: '重试', style: 'SECONDARY' })],
      }),
    ])
    const selection = writes.batchSelection.value
    expect(selection.selected).toEqual(['a', 'd'])
    expect(Object.keys(selection.skipped).sort()).toEqual(['b', 'c'])
    expect(selection.skipped.b).toContain('正在处理中')
    expect(selection.skipped.c).toContain('不可提交')
    expect(writes.batchSkippedNotice.value).toContain('已跳过 2 条不可提交记录')
  })

  it('keeps hidden selections visible in the count when a filter hides them', () => {
    const writes = session()
    writes.toggleBatchRow('a')
    writes.toggleBatchRow('hidden')
    expect(writes.batchSummary([batchItem({ tracking_id: 'a' })])).toEqual({ selected: 2, hidden: 1 })
  })

  it('builds a strict body with one revision-bound opaque key per entry', () => {
    const writes = session()
    writes.toggleBatchRow('a')
    writes.toggleBatchRow('b')
    writes.toggleBatchRow('gone')
    const items = [
      batchItem({ tracking_id: 'a', revision: 3 }),
      batchItem({ tracking_id: 'b', revision: 7 }),
    ]
    const started = writes.beginBatchSubmit({ items, mode: 'CONTINUE_TRACKING' }, {
      connection: CONNECTION, storageDir: STORAGE,
    })
    expect(started.accepted).toBe(true)
    expect(started.skipped).toEqual([
      { trackingId: 'gone', title: '未命名番剧', reason: '不在当前列表中，请刷新后重试' },
    ])
    expect(started.skippedTitle).toBe('部分方案未提交')
    // A batch endpoint has no path parameters at all.
    expect(started.request?.path).toEqual({})
    const body = bodyOf(started)
    expect(body).toMatchObject({
      confirm: true, storage_dir: STORAGE, submission_mode: 'CONTINUE_TRACKING',
      connection_ref: CONNECTION.connection_ref, configuration_revision: 3,
    })
    const entries = body.items as Array<Record<string, unknown>>
    expect(entries.map((entry) => [entry.tracking_id, entry.expected_revision])).toEqual([['a', 3], ['b', 7]])
    for (const entry of entries) {
      expect(String(entry.idempotency_key)).toMatch(/^[A-Za-z0-9-]{8,128}$/)
    }
    expect(entries[0]!.idempotency_key).not.toBe(entries[1]!.idempotency_key)

    // Nothing selectable means zero requests.
    const empty = session()
    const none = empty.beginBatchSubmit({ items, mode: null }, { connection: CONNECTION })
    expect(none.accepted).toBe(false)
    expect(none.request).toBeNull()
    expect(empty.batchNotice.value).toBe('没有可提交的方案')
    expect(none.skippedTitle).toBe('没有可提交的方案')
  })

  it('projects per-entry results and never treats an unknown outcome as success', () => {
    const writes = session()
    writes.toggleBatchRow('ok')
    writes.toggleBatchRow('auth')
    writes.beginBatchSubmit({ items: [], mode: null }, { connection: CONNECTION })
    const effects = writes.finishBatchSubmit({
      items: [
        { tracking_id: 'ok', ok: true, error_type: null, result: { outcome: 'ACTIVE', failure_category: null } },
        { tracking_id: 'auth', ok: false, error_type: null, result: { outcome: 'SUBMIT_FAILED', failure_category: 'AUTHENTICATION' } },
        { tracking_id: 'unknown', ok: false, error_type: null, result: { outcome: 'VERIFYING_EXTERNAL', failure_category: 'OUTCOME_UNKNOWN' } },
        { tracking_id: 'blocked', ok: false, error_type: 'tracking_revision_conflict', result: null },
      ],
    } as never)
    const outcome = writes.batchOutcome.value!
    expect(outcome.succeeded).toBe(1)
    expect(outcome.failed).toBe(3)
    expect([...outcome.unresolved].sort()).toEqual(['blocked', 'unknown'])
    const byId = Object.fromEntries(outcome.entries.map((entry) => [entry.trackingId, entry]))
    expect(byId.auth!.failureCategory).toBe('AUTHENTICATION')
    expect(byId.blocked!.errorType).toBe('tracking_revision_conflict')
    // Only the succeeded entries leave the selection.
    expect(writes.batchSelection.value.selected).toEqual(['auth'])
    expect(writes.batchNotice.value).toContain('成功 1 条，失败 3 条')
    expect(effects).toContainEqual({
      kind: 'notify',
      feedback: { channel: 'success', title: '批量提交完成', message: '已在 Auto Bangumi 创建 1 条外部订阅。' },
    })
    expect(effects).toContainEqual({ kind: 'recheck', trackingId: null, refreshList: true })
    expect(writes.batchLoading.value).toBe(false)
  })

  it('lists only the selected plans the local pre-check refuses', () => {
    const writes = session()
    const submittable = batchItem({ tracking_id: 'tracking-a' })
    const processing = batchItem({
      tracking_id: 'tracking-b', title: '处理中番剧', status_group: 'PROCESSING', available_actions: [],
    })
    writes.toggleBatchRow('tracking-a')
    writes.toggleBatchRow('tracking-b')
    const started = writes.beginBatchSubmit(
      { items: [submittable, processing], mode: null }, { connection: CONNECTION },
    )
    expect(started.skipped).toEqual([
      { trackingId: 'tracking-b', title: '处理中番剧', reason: '正在处理中，请等待当前操作完成' },
    ])
    // The submittable entry still travels, and a fully skipped batch sends
    // nothing at all.
    expect((bodyOf(started).items as unknown[]).length).toBe(1)

    const allSkipped = session()
    allSkipped.toggleBatchRow('tracking-b')
    const nothing = allSkipped.beginBatchSubmit(
      { items: [processing], mode: null }, { connection: CONNECTION },
    )
    expect(nothing.accepted).toBe(false)
    expect(nothing.skipped).toEqual([
      { trackingId: 'tracking-b', title: '处理中番剧', reason: '正在处理中，请等待当前操作完成' },
    ])
  })

  it('keeps the selection and states the fixed reason when the batch never landed', () => {
    const writes = session()
    writes.toggleBatchRow('a')
    writes.beginBatchSubmit({ items: [batchItem({ tracking_id: 'a' })], mode: null }, { connection: CONNECTION })
    writes.failBatchSubmit({ status: 503, httpError: true })
    expect(writes.batchLoading.value).toBe(false)
    expect(writes.batchNotice.value).toBe('批量提交请求未能确认送达，已保留当前选择；请核对连接后重新确认。')
    expect(writes.batchSelection.value.selected).toEqual(['a'])

    const cancelled = session()
    cancelled.toggleBatchRow('a')
    cancelled.beginBatchSubmit({ items: [batchItem({ tracking_id: 'a' })], mode: null }, { connection: CONNECTION })
    expect(cancelled.failBatchSubmit({ status: 0, httpError: false, cancelled: true })).toBeUndefined()
    expect(cancelled.batchNotice.value).toBe('')
    expect(cancelled.batchSelection.value.selected).toEqual(['a'])
  })

  it('clears the whole batch session when the page leaves batch mode', () => {
    const writes = session()
    writes.toggleBatchRow('a')
    writes.finishBatchSubmit({ items: [] } as never)
    writes.resetBatch()
    expect(writes.batchSelection.value).toEqual({ selected: [], skipped: {} })
    expect(writes.batchOutcome.value).toBeNull()
    expect(writes.batchNotice.value).toBe('')
    expect(writes.batchSkippedNotice.value).toBe('')
  })
})

// ---------------------------------------------------------------------------
// The unified session model (issue #168 acceptance).
// ---------------------------------------------------------------------------

describe('one session model for every write family', () => {
  it('builds every family snapshot from the same fields and one release rule', () => {
    const submit = inFlightSubmit().writes
    submit.finishSubmit(submitResult({ outcome: 'UNKNOWN' }))
    const pending = beginRecoveryWrite('RECOVER_AUTO')
    pending.writes.finishRecovery(recoverResult({ outcome: 'SOMETHING_NEW' }))
    const managed = beginManagementWrite()
    managed.writes.finishManagement(modifyResult({ management_status: 'PREPARED' }))

    const snapshotFields = [
      'diagnostics', 'failureCategory', 'family', 'issues', 'keepsIntent', 'manualNotice',
      'message', 'needsManual', 'operation', 'state', 'targetScope', 'trackingId',
    ]
    for (const [snapshot, family, operation] of [
      [submit.sessions.value.submit!, 'SUBMIT', 'SUBMIT'],
      [pending.writes.sessions.value.recovery!, 'RECOVERY', 'RECOVER_AUTO'],
      [managed.writes.sessions.value.management!, 'MANAGEMENT', 'MODIFY'],
    ] as ReadonlyArray<[TrackingWriteSession, string, string]>) {
      // One snapshot type: the same fields, the family derived from the action.
      expect(Object.keys(snapshot).sort()).toEqual(snapshotFields)
      expect(snapshot.family).toBe(family)
      expect(snapshot.operation).toBe(operation)
      // One release rule: an unreadable result keeps the intent in every family.
      expect(snapshot.state).toBe('UNKNOWN')
      expect(snapshot.keepsIntent).toBe(true)
    }
  })

  it('keeps the three families in their own slots so all three panels can render', () => {
    const { writes } = inFlightSubmit()
    writes.finishSubmit(submitResult({ outcome: 'UNKNOWN' }))
    const pending = beginRecoveryWrite('RECOVER_AUTO', { writes })
    expect(pending.started.accepted).toBe(true)
    writes.finishRecovery(recoverResult({ outcome: 'SOMETHING_NEW' }))
    expect(writes.sessions.value.submit!.state).toBe('UNKNOWN')
    expect(writes.sessions.value.recovery!.state).toBe('UNKNOWN')
    expect(writes.sessions.value.management).toBeNull()
    // Both unresolved families still count as one page-level lock.
    expect(writes.hasUnresolvedLock.value).toBe(true)
    expect(writes.busyFor('tracking-2')).toBe(true)
  })
})
