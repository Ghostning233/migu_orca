/**
 * Management-write projection and request builders (US-313, US-314).
 *
 * Scope here is the three management actions this page sends: ``MODIFY`` (the
 * strict, scope-discriminated patch the generated ``modifyTrackingItem``
 * operation accepts), ``SET_ENABLED`` (the record's own status decides the
 * direction) and ``REFRESH_RSS`` (this record's associated RSS only).  The
 * module is API-free — it consumes generated operation types, builds the one
 * request body per intent and turns the server's management result into fixed
 * Chinese copy.  Everything generic to the management write family (action
 * codes, scope projection, per-action messages, confirmations, sessions) lives
 * in ``trackingProjection``.
 */
import type { operations, paths } from '@/api/generated/api'

import {
  createManagementSession,
  isManagementActionCode,
  managementConflictMessage,
  managementEnableDirection,
  managementSessionNeedsManual,
  projectTrackingActionScopes,
  type CapabilityResult,
  type TrackingActionCode,
  type TrackingItem,
  type TrackingManagementActionCode,
  type TrackingManagementScope,
  type TrackingManagementSession,
} from './trackingProjection'

type ApiPath = Extract<keyof paths, string>

export type TrackingModifyBody = NonNullable<
  operations['modifyTrackingItem']['requestBody']['content']['application/json']
>
type SubscriptionModifyBody = Extract<TrackingModifyBody, { target_scope: 'SUBSCRIPTION' }>
type RssModifyBody = Extract<TrackingModifyBody, { target_scope: 'ASSOCIATED_RSS' }>
export type TrackingSubscriptionPatch = SubscriptionModifyBody['patch']
export type TrackingRssPatch = RssModifyBody['patch']

/** The enable/disable request body; ``enabled`` is the only extra field. */
export type TrackingSetEnabledBody = NonNullable<
  operations['setTrackingItemEnabled']['requestBody']['content']['application/json']
>
/** The refresh request body; the generated scope is fixed to the associated RSS. */
export type TrackingRefreshRssBody = NonNullable<
  operations['refreshTrackingRss']['requestBody']['content']['application/json']
>

/**
 * Every management route answers with the same ``TrackingManagementResultDTO``,
 * so one generated result type describes all three requests this page sends.
 */
export type TrackingManagementResult = NonNullable<
  operations['modifyTrackingItem']['responses']['200']['content']['application/json']['result']
>

/** Kept as the name US-313 introduced for the modify result. */
export type TrackingModifyResult = TrackingManagementResult

/**
 * The management endpoints this page can send, total over the management action
 * codes so no action can ever be routed by guessing a path.
 */
export const MANAGEMENT_ACTION_ENDPOINTS = {
  MODIFY: '/api/v1/tracking/items/{tracking_id}/modify',
  SET_ENABLED: '/api/v1/tracking/items/{tracking_id}/set-enabled',
  REFRESH_RSS: '/api/v1/tracking/items/{tracking_id}/refresh',
  DELETE_EXTERNAL: '/api/v1/tracking/items/{tracking_id}/delete-external',
} as const satisfies Record<TrackingManagementActionCode, ApiPath>

/** Only ``MODIFY`` carries a patch; every other management action does not. */
export type TrackingModifyActionCode = keyof typeof MANAGEMENT_ACTION_ENDPOINTS

export function isModifyActionCode(value: TrackingManagementActionCode): value is TrackingModifyActionCode {
  return value === 'MODIFY'
}

/**
 * The management actions this page actually sends (US-314).
 *
 * ``DELETE_EXTERNAL`` is deliberately absent: the per-record external delete is
 * its own story and must keep sending zero requests until then, so the set (not
 * the server) is what decides whether an action can leave the page.
 */
export const SENDABLE_MANAGEMENT_ACTION_CODES = ['MODIFY', 'SET_ENABLED', 'REFRESH_RSS'] as const

export type SendableManagementActionCode = (typeof SENDABLE_MANAGEMENT_ACTION_CODES)[number]

export function isSendableManagementActionCode(
  value: TrackingActionCode,
): value is SendableManagementActionCode {
  // Sendable is a strict subset of the management family, so an action outside
  // the family is never sendable however this list is later extended.
  return isManagementActionCode(value)
    && (SENDABLE_MANAGEMENT_ACTION_CODES as readonly TrackingManagementActionCode[]).includes(value)
}

/** Every scope the modify form can build a patch for is sent to the same route. */
export const MANAGEMENT_SCOPE_ENDPOINTS = {
  SUBSCRIPTION: MANAGEMENT_ACTION_ENDPOINTS.MODIFY,
  ASSOCIATED_RSS: MANAGEMENT_ACTION_ENDPOINTS.MODIFY,
} as const satisfies Record<TrackingManagementScope, ApiPath>

// -- form model --------------------------------------------------------------
// The page never reads the current external values, so every field is opt-in:
// only the fields the user explicitly switched on are sent.  An enabled field
// with an empty value is an explicit clear (``null``), which is why "off" and
// "on but empty" are different states rather than the same empty string.

export interface TrackingSubscriptionForm {
  enabled: Record<string, boolean>
  title: string
  season: string
  subtitleGroup: string
  offset: string
  expectedFolderName: string
  filter: Record<string, boolean>
  mustContain: string
  mustNotContain: string
  useRegex: boolean
  caseSensitive: boolean
}

export interface TrackingRssForm {
  enabled: Record<string, boolean>
  name: string
  aggregate: boolean
  parser: string
}

export function emptySubscriptionForm(): TrackingSubscriptionForm {
  return {
    enabled: {}, title: '', season: '', subtitleGroup: '', offset: '', expectedFolderName: '',
    filter: {}, mustContain: '', mustNotContain: '', useRegex: false, caseSensitive: false,
  }
}

/** The free-text fields of the subscription form, keyed by their public patch name. */
export type TrackingSubscriptionTextField =
  'title' | 'season' | 'subtitle_group' | 'offset' | 'expected_folder_name'

/** The free-text fields of the RSS form, keyed by their public patch name. */
export type TrackingRssTextField = 'name' | 'parser'

export function subscriptionTextValue(
  form: TrackingSubscriptionForm,
  field: TrackingSubscriptionTextField,
): string {
  if (field === 'title') return form.title
  if (field === 'season') return form.season
  if (field === 'subtitle_group') return form.subtitleGroup
  if (field === 'offset') return form.offset
  return form.expectedFolderName
}

export function setSubscriptionTextValue(
  form: TrackingSubscriptionForm,
  field: TrackingSubscriptionTextField,
  value: string,
): void {
  if (field === 'title') form.title = value
  else if (field === 'season') form.season = value
  else if (field === 'subtitle_group') form.subtitleGroup = value
  else if (field === 'offset') form.offset = value
  else form.expectedFolderName = value
}

export function rssTextValue(form: TrackingRssForm, field: TrackingRssTextField): string {
  return field === 'name' ? form.name : form.parser
}

export function setRssTextValue(form: TrackingRssForm, field: TrackingRssTextField, value: string): void {
  if (field === 'name') form.name = value
  else form.parser = value
}

export function emptyRssForm(): TrackingRssForm {
  return { enabled: {}, name: '', aggregate: false, parser: '' }
}

const SUBSCRIPTION_FIELDS = [
  'title', 'season', 'subtitle_group', 'filter_rule', 'offset', 'expected_folder_name',
] as const satisfies readonly (keyof TrackingSubscriptionPatch)[]
const RSS_FIELDS = ['name', 'aggregate', 'parser'] as const satisfies readonly (keyof TrackingRssPatch)[]

/**
 * Client-side guard mirroring the server's patch-value contract.
 *
 * The server refuses URLs, absolute paths and path traversal in patch text
 * (``unsafe_management_patch``).  Blocking them here keeps a rejected value out
 * of the request without inventing any new rule: every rejected string is one
 * the server would reject anyway.
 */
const UNSAFE_VALUE_PATTERN = /(?:https?|ftp|file):[/\\]|(?:^|\s)www\.|^(?:\/|[A-Za-z]:[\\/]|\\\\)/

export function isUnsafePatchValue(value: string): boolean {
  return UNSAFE_VALUE_PATTERN.test(value)
}

function textPatchValue(value: string): string | null {
  const trimmed = value.trim()
  return trimmed ? trimmed : null
}

function nullableNumber(value: string): number | null {
  const trimmed = value.trim()
  if (!trimmed) return null
  return Number(trimmed)
}

function filterFieldEnabled(form: TrackingSubscriptionForm, field: string): boolean {
  return form.filter[field] === true
}



/**
 * Build the strict subscription patch for the fields the user switched on.
 *
 * Returns ``null`` when nothing is selected, when a selected value is malformed
 * (or unsafe), or when the filter rule is switched on without any of its own
 * fields: an empty rule is not a valid Auto Bangumi filter and an empty patch is
 * refused by the server, so both fail closed here instead of being sent.
 */
export function buildSubscriptionPatch(form: TrackingSubscriptionForm): TrackingSubscriptionPatch | null {
  const patch: Record<string, unknown> = {}
  for (const field of SUBSCRIPTION_FIELDS) {
    if (form.enabled[field] !== true) continue
    if (field === 'filter_rule') {
      // The two switches are always carried: Auto Bangumi's filter is one
      // exclusion expression, so a rule that omits them is not expressible.
      // The text terms are only sent when the user switched that term on, and
      // an empty text term is an explicit clear (``null``).
      const rule: Record<string, unknown> = {
        use_regex: form.useRegex === true,
        case_sensitive: form.caseSensitive === true,
      }
      if (filterFieldEnabled(form, 'must_contain')) rule.must_contain = textPatchValue(form.mustContain)
      if (filterFieldEnabled(form, 'must_not_contain')) rule.must_not_contain = textPatchValue(form.mustNotContain)
      patch.filter_rule = rule
      continue
    }
    if (field === 'season') {
      const season = nullableNumber(form.season)
      if (season !== null && (!Number.isInteger(season) || season < 0 || season > 100)) return null
      patch.season = season
      continue
    }
    if (field === 'offset') {
      const offset = nullableNumber(form.offset)
      if (offset !== null && (!Number.isInteger(offset) || offset < 0)) return null
      patch.offset = offset
      continue
    }
    const value = textPatchValue(subscriptionTextValue(form, field))
    if (value !== null && isUnsafePatchValue(value)) return null
    patch[field] = value
  }
  return Object.keys(patch).length ? (patch as TrackingSubscriptionPatch) : null
}

/** Build the strict RSS patch; ``null`` when nothing is selected or malformed. */
export function buildRssPatch(form: TrackingRssForm): TrackingRssPatch | null {
  const patch: Record<string, unknown> = {}
  for (const field of RSS_FIELDS) {
    if (form.enabled[field] !== true) continue
    if (field === 'aggregate') {
      patch.aggregate = form.aggregate === true
      continue
    }
    const value = textPatchValue(rssTextValue(form, field))
    if (value !== null && isUnsafePatchValue(value)) return null
    patch[field] = value
  }
  return Object.keys(patch).length ? (patch as TrackingRssPatch) : null
}

/** True only for a patch that carries at least one field for its own scope. */
export function managementPatchPresent(
  scope: TrackingManagementScope,
  patch: unknown,
): boolean {
  if (!patch || typeof patch !== 'object') return false
  const keys = Object.keys(patch as Record<string, unknown>)
  if (!keys.length) return false
  const allowed: readonly string[] = scope === 'SUBSCRIPTION' ? SUBSCRIPTION_FIELDS : RSS_FIELDS
  return keys.every((key) => allowed.includes(key))
}

// -- intent and request body -------------------------------------------------

interface TrackingManagementIntentBase {
  readonly expectedRevision: number
  readonly confirm: true
  readonly idempotencyKey: string
}

/**
 * One validated management request.
 *
 * The union is discriminated by the action code, so the compiler — not a
 * runtime check — guarantees that only a ``MODIFY`` intent carries a patch, that
 * only a ``SET_ENABLED`` intent carries a direction, and that a ``REFRESH_RSS``
 * intent can only ever target the current record's associated RSS.
 */
export type TrackingManagementIntent =
  | (TrackingManagementIntentBase & {
      readonly action: 'MODIFY'
      readonly targetScope: TrackingManagementScope
      readonly patch: TrackingSubscriptionPatch | TrackingRssPatch
      readonly enabled: null
    })
  | (TrackingManagementIntentBase & {
      readonly action: 'SET_ENABLED'
      readonly targetScope: TrackingManagementScope
      readonly patch: null
      readonly enabled: boolean
    })
  | (TrackingManagementIntentBase & {
      readonly action: 'REFRESH_RSS'
      readonly targetScope: 'ASSOCIATED_RSS'
      readonly patch: null
      readonly enabled: null
    })

function makeOpaqueKey(): string {
  const candidate = globalThis.crypto?.randomUUID?.()
  return candidate && /^[A-Za-z0-9-]{8,128}$/.test(candidate)
    ? candidate
    : `intent-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 14)}`
}

function validRevision(item: TrackingItem): boolean {
  return Number.isInteger(item.revision) && item.revision >= 1
}

/**
 * Validate one modify action against the current server-observed record.
 *
 * The action and the scope must both be projected by ``available_actions`` for
 * the record's current status and the live session's capability, and the patch
 * must be a well-formed, non-empty patch for that very scope.  A stale or
 * hand-made combination therefore never becomes a request.
 */
export function createTrackingManagementIntent(
  item: TrackingItem,
  action: TrackingManagementActionCode,
  targetScope: TrackingManagementScope,
  patch: unknown,
  capabilities?: CapabilityResult | null,
): TrackingManagementIntent | null {
  if (!isModifyActionCode(action)) return null
  if (!validRevision(item) || !managementPatchPresent(targetScope, patch)) return null
  // The page re-checks the server projection itself instead of trusting the
  // emit: the action must still be offered for this record's current revision
  // and the live session must still prove the capability for this very scope.
  if (!projectTrackingActionScopes(item, action, targetScope, capabilities).length) return null
  return {
    action: 'MODIFY',
    targetScope,
    patch: patch as TrackingSubscriptionPatch | TrackingRssPatch,
    enabled: null,
    expectedRevision: item.revision,
    confirm: true,
    idempotencyKey: makeOpaqueKey(),
  }
}

/**
 * Validate one enable/disable against the record's own server status.
 *
 * The direction is never taken from the emit: it is derived from the status the
 * server just returned, and only the three statuses that name a direction yield
 * one.  An unknown status therefore fails closed instead of guessing whether the
 * user meant "启用" or "停用".
 */
export function createTrackingSetEnabledIntent(
  item: TrackingItem,
  targetScope: TrackingManagementScope,
  capabilities?: CapabilityResult | null,
): TrackingManagementIntent | null {
  if (!validRevision(item)) return null
  const enabled = managementEnableDirection(item.status)
  if (enabled === null) return null
  if (!projectTrackingActionScopes(item, 'SET_ENABLED', targetScope, capabilities).length) return null
  return {
    action: 'SET_ENABLED',
    targetScope,
    patch: null,
    enabled,
    expectedRevision: item.revision,
    confirm: true,
    idempotencyKey: makeOpaqueKey(),
  }
}

/**
 * Validate one associated-RSS refresh.
 *
 * The scope is not a parameter: a refresh can only ever address the current
 * tracking record's own associated RSS (the server refuses any other scope, and
 * there is no global refresh route to fall back to).
 */
export function createTrackingRefreshRssIntent(
  item: TrackingItem,
  capabilities?: CapabilityResult | null,
): TrackingManagementIntent | null {
  if (!validRevision(item)) return null
  if (!projectTrackingActionScopes(item, 'REFRESH_RSS', 'ASSOCIATED_RSS', capabilities).length) return null
  return {
    action: 'REFRESH_RSS',
    targetScope: 'ASSOCIATED_RSS',
    patch: null,
    enabled: null,
    expectedRevision: item.revision,
    confirm: true,
    idempotencyKey: makeOpaqueKey(),
  }
}

/**
 * Build one intent for whichever management action the user requested.
 *
 * This is the page's single entry point: an action the page does not send —
 * including ``DELETE_EXTERNAL`` — yields ``null`` rather than a request.
 */
export function createTrackingManagementActionIntent(
  item: TrackingItem,
  action: TrackingManagementActionCode,
  targetScope: TrackingManagementScope,
  patch: unknown,
  capabilities?: CapabilityResult | null,
): TrackingManagementIntent | null {
  if (action === 'MODIFY') {
    return createTrackingManagementIntent(item, action, targetScope, patch, capabilities)
  }
  if (action === 'SET_ENABLED') return createTrackingSetEnabledIntent(item, targetScope, capabilities)
  if (action === 'REFRESH_RSS') return createTrackingRefreshRssIntent(item, capabilities)
  return null
}

/**
 * True when two intents describe the very same management request.
 *
 * ``expectedRevision`` and the opaque key are deliberately **not** compared: a
 * locked intent keeps its own revision binding, so an explicit transport retry
 * must replay the whole locked intent (the server judges a replay by
 * key + revision and rejects a same-key/different-binding request).
 */
export function sameManagementRequest(
  left: TrackingManagementIntent,
  right: TrackingManagementIntent,
): boolean {
  return left.action === right.action
    && left.targetScope === right.targetScope
    && left.enabled === right.enabled
    && JSON.stringify(left.patch) === JSON.stringify(right.patch)
}

/**
 * Build the one request body for a validated management intent.
 *
 * The body is assembled in exactly one place and the action decides the shape,
 * so a subscription patch can never be sent to the enable route, a scope can
 * never be sent to the refresh route, and the body shape itself cannot express
 * an external id, URL, raw response or free-text note.
 */
export function createTrackingManagementBody(
  intent: TrackingManagementIntent,
  abConfig: TrackingModifyBody['ab_config'],
  storageDir?: string,
): TrackingModifyBody | TrackingSetEnabledBody | TrackingRefreshRssBody | null {
  const baseUrl = typeof abConfig?.base_url === 'string' ? abConfig.base_url.trim() : ''
  if (!abConfig || !baseUrl) return null
  const common = {
    expected_revision: intent.expectedRevision,
    idempotency_key: intent.idempotencyKey,
    confirm: true as const,
    ab_config: { ...abConfig, base_url: baseUrl },
    ...(storageDir ? { storage_dir: storageDir } : {}),
  }
  if (intent.action === 'SET_ENABLED') {
    return { ...common, target_scope: intent.targetScope, enabled: intent.enabled }
  }
  if (intent.action === 'REFRESH_RSS') {
    return { ...common, target_scope: 'ASSOCIATED_RSS' }
  }
  if (intent.targetScope === 'SUBSCRIPTION') {
    if (!managementPatchPresent('SUBSCRIPTION', intent.patch)) return null
    return { ...common, target_scope: 'SUBSCRIPTION', patch: intent.patch as TrackingSubscriptionPatch }
  }
  if (!managementPatchPresent('ASSOCIATED_RSS', intent.patch)) return null
  return { ...common, target_scope: 'ASSOCIATED_RSS', patch: intent.patch as TrackingRssPatch }
}

// -- result projection -------------------------------------------------------

export const MANAGEMENT_STATUSES = [
  'PREPARED', 'IN_PROGRESS', 'SUCCEEDED', 'FAILED', 'OUTCOME_UNKNOWN', 'RECOVERY_REQUIRED',
] as const satisfies readonly TrackingModifyResult['management_status'][]

export type TrackingManagementStatus = (typeof MANAGEMENT_STATUSES)[number]

const KNOWN_MANAGEMENT_STATUSES = new Set<string>(MANAGEMENT_STATUSES)

function isManagementStatus(value: unknown): value is TrackingManagementStatus {
  return typeof value === 'string' && KNOWN_MANAGEMENT_STATUSES.has(value)
}

/**
 * Project one HTTP 200 management result.
 *
 * ``management_status`` is the server's own verdict and the only thing that may
 * be reported as success: ``SUCCEEDED``.  ``FAILED`` is a definite failure and
 * everything else — an in-flight status, a partial batch, an explicit
 * recovery-required verdict or an undocumented value — stays indeterminate, so
 * the page reads back and never claims the external change was applied.
 */
export function projectManagementOutcome(
  trackingId: string,
  action: SendableManagementActionCode,
  targetScope: TrackingManagementScope,
  result: TrackingManagementResult,
): TrackingManagementSession {
  const status: unknown = result.management_status
  if (isManagementStatus(status) && (status === 'SUCCEEDED' || status === 'FAILED')) {
    return createManagementSession(
      trackingId, action, targetScope, status, managementSessionNeedsManual(status, result.needs_manual),
    )
  }
  return createManagementSession(trackingId, action, targetScope, 'UNKNOWN', true)
}

export function createManagementConflictSession(
  trackingId: string,
  action: SendableManagementActionCode,
  targetScope: TrackingManagementScope,
  errorType: unknown,
): TrackingManagementSession {
  return createManagementSession(
    trackingId, action, targetScope, 'CONFLICT', false, managementConflictMessage(errorType, action),
  )
}

export function createManagementRejectedSession(
  trackingId: string,
  action: SendableManagementActionCode,
  targetScope: TrackingManagementScope,
): TrackingManagementSession {
  return createManagementSession(trackingId, action, targetScope, 'REJECTED')
}

export function createManagementInFlightSession(
  trackingId: string,
  action: SendableManagementActionCode,
  targetScope: TrackingManagementScope,
): TrackingManagementSession {
  return createManagementSession(trackingId, action, targetScope, 'IN_FLIGHT')
}

/**
 * Fixed copy for a management request the page itself refuses to build.
 *
 * ``createTrackingManagementBody`` returns ``null`` when an intent cannot be
 * turned into a safe request.  That is a definite page-side refusal — nothing
 * was sent — so it must converge on a decided state instead of leaving the
 * panel on ``IN_FLIGHT`` ("正在提交外部修改，请稍候…") forever.
 */
export const MANAGEMENT_UNBUILDABLE_MESSAGE =
  '本次管理请求缺少可安全发送的必要信息，未向 Auto Bangumi 发送任何请求；已重新读取最新详情，请重新确认后再试。'

/**
 * A management intent the page could not turn into a request: no external call
 * was made, so it releases the page-level intent exactly like ``REJECTED``.
 */
export function createManagementUnbuildableSession(
  trackingId: string,
  action: SendableManagementActionCode,
  targetScope: TrackingManagementScope,
): TrackingManagementSession {
  return createManagementSession(
    trackingId, action, targetScope, 'REJECTED', false, MANAGEMENT_UNBUILDABLE_MESSAGE,
  )
}

// -- confirmation copy -------------------------------------------------------

export interface TrackingManagementConfirmation {
  title: string
  message: string
  confirmLabel: string
}

/**
 * Impact confirmation for one scope.  Both say the change happens only in Auto
 * Bangumi; the subscription form additionally says it may change which episodes
 * get downloaded, because Auto Bangumi acts on the updated subscription.
 */
export const MODIFY_SCOPE_CONFIRMATIONS = {
  SUBSCRIPTION: {
    title: '修改 Auto Bangumi 番剧订阅',
    message: '将在 Auto Bangumi 中修改该追番的外部番剧订阅，并可能改变后续下载；只影响 Auto Bangumi 外部订阅，不修改 MiGuOrca 本地方案。是否继续？',
    confirmLabel: '确认修改订阅',
  },
  ASSOCIATED_RSS: {
    title: '修改 Auto Bangumi 关联 RSS',
    message: '将在 Auto Bangumi 中修改该追番的关联 RSS，只影响 Auto Bangumi 外部 RSS，不修改 MiGuOrca 本地方案。是否继续？',
    confirmLabel: '确认修改 RSS',
  },
} as const satisfies Record<TrackingManagementScope, TrackingManagementConfirmation>

type EnableDirection = 'enable' | 'disable'

/**
 * Enable/disable copy, per scope and per direction.
 *
 * The record's own status decides the direction, and each direction names what
 * it does to future downloads, so an "启用" confirmation can never be shown for
 * a request that disables.
 */
const SET_ENABLED_CONFIRMATIONS = {
  SUBSCRIPTION: {
    enable: {
      title: '启用 Auto Bangumi 番剧订阅',
      message: '将在 Auto Bangumi 中启用该追番的外部番剧订阅，之后可能恢复或触发下载；只影响 Auto Bangumi 外部订阅，不修改 MiGuOrca 本地方案。是否继续？',
      confirmLabel: '确认启用订阅',
    },
    disable: {
      title: '停用 Auto Bangumi 番剧订阅',
      message: '将在 Auto Bangumi 中停用该追番的外部番剧订阅，之后不再按该订阅下载；只影响 Auto Bangumi 外部订阅，不修改 MiGuOrca 本地方案。是否继续？',
      confirmLabel: '确认停用订阅',
    },
  },
  ASSOCIATED_RSS: {
    enable: {
      title: '启用 Auto Bangumi 关联 RSS',
      message: '将在 Auto Bangumi 中启用该追番的关联 RSS，之后可能恢复或触发下载；只影响 Auto Bangumi 外部 RSS，不修改 MiGuOrca 本地方案。是否继续？',
      confirmLabel: '确认启用 RSS',
    },
    disable: {
      title: '停用 Auto Bangumi 关联 RSS',
      message: '将在 Auto Bangumi 中停用该追番的关联 RSS，之后不再按该 RSS 下载；只影响 Auto Bangumi 外部 RSS，不修改 MiGuOrca 本地方案。是否继续？',
      confirmLabel: '确认停用 RSS',
    },
  },
} as const satisfies Record<TrackingManagementScope, Record<EnableDirection, TrackingManagementConfirmation>>

/**
 * The refresh confirmation says explicitly that only this record's own RSS is
 * refreshed: there is no global refresh behind this button.
 */
const REFRESH_RSS_CONFIRMATION: TrackingManagementConfirmation = {
  title: '刷新 Auto Bangumi 关联 RSS',
  message: '将让 Auto Bangumi 重新拉取该追番当前关联的 RSS 内容；只刷新当前追番的关联 RSS，不会刷新全局 RSS，也不修改 MiGuOrca 本地方案。是否继续？',
  confirmLabel: '确认刷新关联 RSS',
}

/**
 * Impact confirmation for one validated management intent.
 *
 * It is derived from the intent itself, so the copy always describes the action,
 * the scope and (for enable/disable) the direction that is actually about to be
 * sent — never a direction the user did not choose.
 */
export function managementConfirmation(
  intent: TrackingManagementIntent,
): TrackingManagementConfirmation {
  if (intent.action === 'SET_ENABLED') {
    return SET_ENABLED_CONFIRMATIONS[intent.targetScope][intent.enabled ? 'enable' : 'disable']
  }
  if (intent.action === 'REFRESH_RSS') return REFRESH_RSS_CONFIRMATION
  return MODIFY_SCOPE_CONFIRMATIONS[intent.targetScope]
}

/** Fixed copy explaining why the form is a write-only field set. */
export const MODIFY_FORM_HELP =
  '本表单不读取 Auto Bangumi 的当前值，只提交你明确勾选并填写的字段；未勾选的字段保持 Auto Bangumi 现有值。清空已勾选的文本字段会将该字段设为空。'

/** Fixed copy shown next to the enable/disable and refresh actions (US-314). */
export const MANAGEMENT_ACTIONS_HELP =
  '启停与刷新只作用于 Auto Bangumi 中的外部对象，不修改 MiGuOrca 本地方案；每次操作都需要单独确认。'
