/**
 * Management-write projection and form helpers (US-313).
 *
 * Scope here is exactly ``MODIFY``: the strict, scope-discriminated patch the
 * generated ``modifyTrackingItem`` operation accepts.  The module is API-free —
 * it only consumes generated operation types, builds the request body and turns
 * the server's management result into fixed Chinese copy.  Everything generic to
 * the management write family (action codes, scope projection, confirmations,
 * sessions) lives in ``trackingProjection``.
 */
import type { operations, paths } from '@/api/generated/api'

import {
  createManagementSession,
  managementConflictMessage,
  managementSessionNeedsManual,
  projectTrackingActionScopes,
  type CapabilityResult,
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
export type TrackingModifyResult = NonNullable<
  operations['modifyTrackingItem']['responses']['200']['content']['application/json']['result']
>

/**
 * The management endpoints this page can send. ``MODIFY`` is the action this
 * story wires; the map stays total over the management action codes so a future
 * story can add its own action without the page guessing a path.
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

export interface TrackingManagementIntent {
  readonly action: TrackingManagementActionCode
  readonly targetScope: TrackingManagementScope
  readonly patch: TrackingSubscriptionPatch | TrackingRssPatch
  readonly expectedRevision: number
  readonly confirm: true
  readonly idempotencyKey: string
}

function makeOpaqueKey(): string {
  const candidate = globalThis.crypto?.randomUUID?.()
  return candidate && /^[A-Za-z0-9-]{8,128}$/.test(candidate)
    ? candidate
    : `intent-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 14)}`
}

/**
 * Validate one management action against the current server-observed record.
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
  if (action === 'MODIFY' && !managementPatchPresent(targetScope, patch)) return null
  if (!Number.isInteger(item.revision) || item.revision < 1) return null
  // The page re-checks the server projection itself instead of trusting the
  // emit: the action must still be offered for this record's current revision
  // and the live session must still prove the capability for this very scope.
  if (!projectTrackingActionScopes(item, action, targetScope, capabilities).length) return null
  return {
    action,
    targetScope,
    patch: patch as TrackingManagementIntent['patch'],
    expectedRevision: item.revision,
    confirm: true,
    idempotencyKey: makeOpaqueKey(),
  }
}

/**
 * Build the one request body for a validated management intent.
 *
 * The body is assembled in exactly one place and the scope decides the patch
 * shape, so a subscription form can never send RSS fields (or the reverse).
 * The body shape itself cannot express an external id, URL, raw response or
 * free-text note.
 */
export function createTrackingManagementBody(
  intent: TrackingManagementIntent,
  abConfig: TrackingModifyBody['ab_config'],
  storageDir?: string,
): TrackingModifyBody | null {
  const baseUrl = typeof abConfig?.base_url === 'string' ? abConfig.base_url.trim() : ''
  if (!abConfig || !baseUrl) return null
  const common = {
    expected_revision: intent.expectedRevision,
    idempotency_key: intent.idempotencyKey,
    confirm: true as const,
    ab_config: { ...abConfig, base_url: baseUrl },
    ...(storageDir ? { storage_dir: storageDir } : {}),
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

const FIXED_IN_FLIGHT_MESSAGE = '正在提交外部修改，请稍候…'

/**
 * Project one HTTP 200 management result.
 *
 * ``management_status`` is the server's own verdict and the only thing that may
 * be reported as success: ``SUCCEEDED``.  ``FAILED`` is a definite failure and
 * everything else (including an undocumented status) stays indeterminate, so the
 * page reads back and never claims the external change was applied.
 */
export function projectModifyOutcome(
  trackingId: string,
  targetScope: TrackingManagementScope,
  result: TrackingModifyResult,
): TrackingManagementSession {
  const status: unknown = result.management_status
  if (!isManagementStatus(status)) {
    return createManagementSession(trackingId, 'MODIFY', targetScope, 'UNKNOWN')
  }
  if (status === 'SUCCEEDED' || status === 'FAILED') {
    return createManagementSession(
      trackingId, 'MODIFY', targetScope, status, managementSessionNeedsManual(status, result.needs_manual),
    )
  }
  return createManagementSession(trackingId, 'MODIFY', targetScope, 'UNKNOWN', true)
}

export function createModifyConflictSession(
  trackingId: string,
  targetScope: TrackingManagementScope,
  errorType: unknown,
): TrackingManagementSession {
  return createManagementSession(
    trackingId, 'MODIFY', targetScope, 'CONFLICT', false, managementConflictMessage(errorType),
  )
}

export function createModifyRejectedSession(
  trackingId: string,
  targetScope: TrackingManagementScope,
): TrackingManagementSession {
  return createManagementSession(trackingId, 'MODIFY', targetScope, 'REJECTED')
}

export function createModifyInFlightSession(
  trackingId: string,
  targetScope: TrackingManagementScope,
): TrackingManagementSession {
  return createManagementSession(
    trackingId, 'MODIFY', targetScope, 'IN_FLIGHT', false, FIXED_IN_FLIGHT_MESSAGE,
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

/** Fixed copy explaining why the form is a write-only field set. */
export const MODIFY_FORM_HELP =
  '本表单不读取 Auto Bangumi 的当前值，只提交你明确勾选并填写的字段；未勾选的字段保持 Auto Bangumi 现有值。清空已勾选的文本字段会将该字段设为空。'
