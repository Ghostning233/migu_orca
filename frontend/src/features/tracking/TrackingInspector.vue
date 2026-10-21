<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, ref, watch } from 'vue'

import { api, toApiError } from '@/api/client'
import type { operations } from '@/api/generated/api'
import BaseButton from '@/components/forms/BaseButton.vue'
import ErrorState from '@/components/feedback/ErrorState.vue'
import LoadingState from '@/components/feedback/LoadingState.vue'
import { storageQuery } from '@/features/requests/requestStorage'
import {
  canVerifyExternally,
  executableTrackingActions,
  formatTrackingAuditAction,
  formatTrackingCreatedAt,
  formatTrackingOperation,
  formatTrackingOperationState,
  isRecoverableStatus,
  isPendingSubmission,
  MANAGEMENT_ACTIONS_HELP,
  resubmitOfferState,
  type CapabilityResult,
  type TrackingCheckSession,
  type TrackingResubmitSession,
  type TrackingAction,
  type TrackingItem,
} from './trackingProjection'
import {
  isSendableManagementAction,
  isTrackingManagementScope,
  projectTrackingActionScopes,
  type TrackingManagementActionCode,
  type TrackingManagementScope,
  type TrackingPlanDeleteSession,
  type TrackingRecoveryActionCode,
  type TrackingWriteSession,
  type TrackingWriteSessionSet,
} from './useTrackingWriteSession'
import AnimeDraftEditor from '@/features/workbench/AnimeDraftEditor.vue'
import { EPISODE_PLACEHOLDER, hasTrustedEpisodeCount } from '@/features/workbench/episodeCount'
import {
  useSavedPlanEditor,
  type SavedPlanFetch,
} from '@/features/requests/useSavedPlanEditor'
import type { RequestDetailResult } from '@/features/requests/requestDetail'
import type { PreviewPatch } from '@/features/workbench/candidateSearch'
import CheckboxRow from '@/components/forms/CheckboxRow.vue'
import { buildReuseHandoff, publishReuseHandoff } from '@/features/requests/reuseHandoff'
import TrackingManagementActions from './TrackingManagementActions.vue'
import TrackingModifyForm from './TrackingModifyForm.vue'
import TrackingPoster from './TrackingPoster.vue'

type TrackingDetail = NonNullable<
  operations['getTrackingItemDetail']['responses']['200']['content']['application/json']['result']
>


const props = defineProps<{
  trackingId: string
  /** Diagnostic-only capability summary; never an authorization gate (#86). */
  capabilities?: CapabilityResult | null
  /**
   * True while a usable Auto Bangumi connection is *saved*. Issue #86: this no
   * longer requires a settings-page probe — every external write re-validates
   * the connection, credentials, exact version and capability server-side.
   */
  connectionReady?: boolean
  /**
   * The page's single write-session entry (issue #168): the latest session of
   * each write family.  The page owns the request; this component only renders
   * the result of the family whose panel it is.
   */
  sessions?: TrackingWriteSessionSet | null
  /**
   * Page-level bounded read-only check state for one item (issue #183).  It is
   * its own slot: a read-only check never holds the page-level write intent.
   */
  checkSession?: TrackingCheckSession | null
  /**
   * Issue #184: the page-level read-only phase of one risk-confirmed
   * resubmission. It is its own slot like the check's: the component only offers
   * the step and renders the page-owned result, never the write itself.
   */
  resubmitSession?: TrackingResubmitSession | null
  /** True while the page's risk confirmation dialog is open for this item. */
  resubmitPending?: boolean
  /**
   * Issue #183: true while the page still owes this item one automatic
   * read-only check (reopening/refreshing a 结果待确认 submission). The page
   * disarms it after the first automatic check so a check that changes the
   * revision can never loop forever.
   */
  autoCheckArmed?: boolean
  /** The single page intent is spent elsewhere (another item's write/recovery). */
  writeBusy?: boolean
  /** Page-owned plan-delete result for this item (issue #92). */
  planDeleteSession?: TrackingPlanDeleteSession | null
  /**
   * Fixed page-level reason a locked intent refused a different request. It is
   * shown on the selected record only and never replaces a result panel.
   */
  intentNotice?: string | null
}>()
const emit = defineEmits<{
  (e: 'tracking-updated', tracking: TrackingItem): void
  (e: 'write-requested', payload: { action: TrackingAction; item: TrackingItem }): void
  // The recovery action travels as its server-agreed code, not as a projected
  // action object: VERIFY_EXTERNAL is never part of the server's action list.
  (e: 'recovery-requested', payload: { action: TrackingRecoveryActionCode; item: TrackingItem }): void
  // Issue #183: the only action a pending submission offers. It reads only.
  (e: 'check-requested', payload: { item: TrackingItem; automatic: boolean }): void
  // Issue #184: one single manual resubmission. The page runs the read-only
  // phase first and only writes after an explicit risk confirmation.
  (e: 'resubmit-requested', payload: { item: TrackingItem }): void
  // A management request carries the scope the user chose and the strict patch
  // its own form built; the page re-validates both before anything is sent.
  /** Issue #92: delete this plan, optionally with its controlled external object.
   *  Issue #230: an unresolved record uses the same request as a local-only
   *  abandon bound to the record revision and current operation. */
  (e: 'plan-delete-requested', payload: {
    item: TrackingItem
    deleteExternal: boolean
    abandon?: boolean
    expectedRevision?: number | null
    expectedOperationId?: string | null
  }): void
  /** Issue #93: reuse this plan's safe suggestion in the add journey. */
  (e: 'reuse-requested'): void
  (e: 'management-requested', payload: {
    action: TrackingAction
    item: TrackingItem
    targetScope: TrackingManagementScope
    patch: unknown
    /** Issue #91: local plan values raised only after a confirmed write. */
    localPlan?: unknown
  }): void
}>()
const detail = ref<TrackingDetail | null>(null)
const loading = ref(false)
const failed = ref(false)
const inspectorHeading = ref<HTMLElement | null>(null)
let requestSequence = 0
let controller: AbortController | null = null

// -- explicit external submission and retry (US-310, US-311) -----------------
// The page owns the credential and the request; this component only offers the
// server-computed write action when the page session proves the capability, and
// renders the fixed page-level write result.  No key, credential or request
// state ever lives here.  SUBMIT and RETRY are mutually exclusive on the server
// (different source statuses), so at most one of them is ever projected.
/** The one session of each family, filtered to the record this panel shows. */
function sessionFor(session: TrackingWriteSession | null | undefined): TrackingWriteSession | null {
  return session && session.trackingId === props.trackingId ? session : null
}
const thisWrite = computed(() => sessionFor(props.sessions?.submit))
const writeInFlight = computed(() => (
  thisWrite.value?.state === 'IN_FLIGHT'
))
/** The server-computed write actions, intersected only with known values. */
const writeActions = computed(() => (
  detail.value ? executableTrackingActions(detail.value) : []
))
const submitAction = computed(() => writeActions.value.find((action) => action.code === 'SUBMIT') ?? null)
const retryAction = computed(() => writeActions.value.find((action) => action.code === 'RETRY') ?? null)
const writeHint = computed(() => {
  const offered = (detail.value?.available_actions ?? []).some(
    (action) => action.code === 'SUBMIT' || action.code === 'RETRY',
  )
  return offered ? '当前动作不在受支持的提交范围内，已降级为只读。' : '当前状态不可提交或重试外部订阅。'
})

// -- saved local plan editing (issue #90) ------------------------------------
// The pending/needs-reconfirm/failed plan is edited with the same shared editor
// core the add journeys use. Saving is revision-authoritative on the server: the
// browser sends only the patch and re-reads the snapshot; an unconfirmed write
// locks the editor until the user explicitly re-checks it.
const EDITABLE_PLAN_STATUSES = new Set(['PENDING_SUBMIT', 'NEEDS_RECONFIRM', 'SUBMIT_FAILED'])
const planSnapshot = ref<RequestDetailResult | null>(null)
const planLoading = ref(false)
const planLoadFailed = ref(false)

const canEditPlan = computed(() => Boolean(
  detail.value?.request_id && EDITABLE_PLAN_STATUSES.has(detail.value.status),
))

async function fetchPlanSnapshot(): Promise<SavedPlanFetch> {
  const requestId = detail.value?.request_id
  if (!requestId) return { result: null, error: { type: 'invalid_tracking_id' } as never }
  try {
    const result = await api.get<RequestDetailResult>('/api/v1/requests/{request_id}', {
      path: { request_id: requestId },
      query: storageQuery(),
    })
    planSnapshot.value = result
    planLoadFailed.value = false
    return { result, error: null }
  } catch (error) {
    planLoadFailed.value = true
    return { result: null, error: toApiError(error) }
  }
}

const planEditor = useSavedPlanEditor({
  requestId: () => detail.value?.request_id ?? '',
  fetchSnapshot: fetchPlanSnapshot,
  commitSnapshot: (snapshot) => { planSnapshot.value = snapshot },
  storageQuery,
  onApplied: () => { void loadDetail() },
})

async function togglePlanEditor(): Promise<void> {
  if (!planEditor.formOpen.value && !planSnapshot.value) {
    planLoading.value = true
    try {
      await fetchPlanSnapshot()
    } finally {
      planLoading.value = false
    }
  }
  planEditor.toggle()
}

function requestWrite(action: TrackingAction | null): void {
  if (!action || !detail.value || actionBusy.value) return
  // The page confirms, builds the intent (fresh revision + opaque key) and sends.
  emit('write-requested', { action, item: detail.value })
}

// -- bounded read-only check of a pending submission (issue #183) -------------
// A persistent submit whose outcome could not be proven shows 结果待确认. The
// page never guesses: the server publishes the proven reason class and the check
// endpoint, bound to the original operation's saved connection, reads only.
const thisCheck = computed(() => (
  props.checkSession && props.checkSession.trackingId === props.trackingId ? props.checkSession : null
))
const checkInFlight = computed(() => thisCheck.value?.state === 'IN_FLIGHT')
const pendingSubmission = computed(() => isPendingSubmission(
  detail.value?.status,
  detail.value?.current_operation?.operation,
  detail.value?.submission_mode,
))

function requestCheck(automatic = false): void {
  if (!detail.value || checkBusy.value) return
  emit('check-requested', { item: detail.value, automatic })
}

// -- risk-confirmed single resubmission (issue #184) --------------------------
// 结果待确认 is never a safe retry (ADR-0001/ADR-0002). The page runs the same
// bounded read-only check first; only a still-unresolved, server-offered binding
// can lead to a second, explicit risk confirmation. This component offers the
// entry and states the proven reason when the server has already refused it.
const thisResubmit = computed(() => (
  props.resubmitSession && props.resubmitSession.trackingId === props.trackingId
    ? props.resubmitSession
    : null
))
const resubmitInFlight = computed(() => thisResubmit.value?.state === 'IN_FLIGHT')
const resubmitOffer = computed(() => resubmitOfferState(
  detail.value?.status,
  detail.value?.current_operation?.operation,
  detail.value?.current_operation?.state,
  detail.value?.submission_mode,
))
const resubmitOffered = computed(() => resubmitOffer.value.available)
const resubmitHint = computed(() => resubmitOffer.value.hint)
/** The resubmit needs no client credential: the server resolves the bound one. */
const resubmitBusy = computed(() => (
  checkBusy.value || props.resubmitPending === true || resubmitInFlight.value
))

function requestResubmit(): void {
  if (!detail.value || resubmitBusy.value) return
  emit('resubmit-requested', { item: detail.value })
}

// -- unknown-result recovery (US-312 / issue #228) ---------------------------
// Issue #228 retired 自动恢复/标记为成功/标记为失败 and their server-projected
// actions.  Reading the bound Auto Bangumi connection is the only recovery left:
// it is offered for a record whose exact status is unresolved, only while the
// page session has proven `external_verify`, and it never writes upstream.  The
// page owns the request; this component renders the flow and its result.
// -- main feedback (D8, issue #227) -----------------------------------------
/**
 * The failure / undecidable reason belongs to the first-screen main feedback
 * area, not to a fold or to the bottom of the action section.
 *
 * ``title`` says what happened in plain words («结果待确认» is never a failure),
 * ``verdict`` is the server-projected sentence, ``reasons`` are the documented
 * issue messages, and ``nextStep`` names the safe next move without performing
 * any of it (the action hierarchy belongs to T4b).
 */
interface MainFeedback {
  readonly source: 'write' | 'revalidation'
  readonly tone: 'warning' | 'danger'
  readonly title: string
  readonly verdict: string
  readonly reasons: string[]
  readonly nextStep: string
}

/** Write outcomes that must be surfaced as the page's main feedback. */
const FEEDBACK_STATES = [
  'SUBMIT_FAILED', 'NEEDS_RECONFIRM', 'VERIFYING_EXTERNAL', 'RECOVERY_REQUIRED',
  'CONFLICT', 'REJECTED', 'UNKNOWN',
] as const
type FeedbackState = (typeof FEEDBACK_STATES)[number]

const WRITE_FEEDBACK: Record<FeedbackState, { title: string; tone: 'warning' | 'danger' }> = {
  SUBMIT_FAILED: { title: '提交失败', tone: 'danger' },
  NEEDS_RECONFIRM: { title: '提交前复核未通过', tone: 'warning' },
  // The record-level 「结果待确认」 panel (with its 只读核验 entry) keeps that
  // heading; this card names the *write* it is talking about so the two never
  // read as one duplicated title.
  VERIFYING_EXTERNAL: { title: '本次提交结果待确认', tone: 'warning' },
  RECOVERY_REQUIRED: { title: '本次提交结果待确认', tone: 'warning' },
  CONFLICT: { title: '提交未执行', tone: 'danger' },
  REJECTED: { title: '提交被拒绝', tone: 'danger' },
  UNKNOWN: { title: '本次提交结果待确认', tone: 'warning' },
}

/**
 * The next step per server-published failure class.  A credential, version or
 * capability failure needs the saved connection fixed before another submit, so
 * it must never be answered with a flat «retry» (the session copy already says so).
 */
const FAILURE_NEXT_STEPS: Record<string, string> = {
  CONNECTION: '先前往设置检查地址与网络，再回来提交。',
  AUTHENTICATION: '先前往设置更新账号或密码，再回来提交。',
  VERSION: '先前往设置确认 Auto Bangumi 版本，再回来提交。',
  CAPABILITY: '先前往设置改用已验证的账号密码连接，再回来提交。',
  DUPLICATE_SUBSCRIPTION: '先核对 Auto Bangumi 中的既有订阅，再决定是否继续。',
  VALIDATION: '按提示修改追番方案后重新提交。',
  REJECTED: '检查方案内容后重新确认提交。',
  OUTCOME_UNKNOWN: '先做只读核验；未确认前不要重复提交。',
}

const STATE_NEXT_STEPS: Record<FeedbackState, string> = {
  SUBMIT_FAILED: '先按提示处理失败原因，再决定是否重新提交；重新提交会再次发起一次外部写。',
  NEEDS_RECONFIRM: '修改方案后重新确认提交。',
  VERIFYING_EXTERNAL: '先做只读核验；能定论即定论，未确认前不要重复提交。',
  RECOVERY_REQUIRED: '先做只读核验；无法定论时再在服务端允许的出路中选择主动重发或放弃跟踪。',
  CONFLICT: '刷新详情后重新确认。',
  REJECTED: '刷新详情后按提示修正再提交。',
  UNKNOWN: '先做只读核验；未确认前不要重复提交。',
}

function isFeedbackState(state: string): state is FeedbackState {
  return (FEEDBACK_STATES as readonly string[]).includes(state)
}

/** The current write result when it is a failure or an undecidable outcome. */
const failingWrite = computed(() => {
  const session = thisWrite.value
  if (!session || session.family !== 'SUBMIT') return null
  return isFeedbackState(session.state) ? session : null
})

/**
 * Record-level feedback for a reloaded page that has no live write session.
 *
 * The read DTO does not persist a failure reason, so these entries only state
 * what the status itself proves and point at the safe next move.  They keep AC5
 * (reason/next step on the first screen) true after a refresh; the reason list
 * still comes from a live result or from ``revalidation_issues`` when present.
 */
const RECORD_FEEDBACK: Record<string, { title: string; tone: 'warning' | 'danger'; verdict: string; nextStep: string }> = {
  SUBMIT_FAILED: {
    title: '提交失败',
    tone: 'danger',
    // CONTEXT: 提交失败 allows another submit, but never proves there were no
    // partial side effects.
    verdict: '上次提交没有收到 Auto Bangumi 的成功结果；不证明没有产生部分副作用。',
    nextStep: '确认原因后可重新提交；重试会再次发起一次外部写。',
  },
  NEEDS_RECONFIRM: {
    title: '提交前复核未通过',
    tone: 'warning',
    verdict: '本次尚未创建 Auto Bangumi 外部订阅。',
    nextStep: '修改方案后重新确认提交。',
  },
}

const mainFeedback = computed<MainFeedback | null>(() => {
  const session = failingWrite.value
  if (session) {
    const state = session.state as FeedbackState
    const category = session.failureCategory
    return {
      source: 'write',
      tone: WRITE_FEEDBACK[state].tone,
      title: WRITE_FEEDBACK[state].title,
      verdict: session.message,
      reasons: session.issues.map((issue) => issue.message),
      nextStep: (category ? FAILURE_NEXT_STEPS[category] : undefined) ?? STATE_NEXT_STEPS[state],
    }
  }
  const record = detail.value ? RECORD_FEEDBACK[detail.value.status] : undefined
  if (!record) return null
  return {
    source: 'revalidation',
    tone: record.tone,
    title: record.title,
    verdict: record.verdict,
    reasons: (detail.value?.revalidation_issues ?? []).map((issue) => issue.message),
    nextStep: record.nextStep,
  }
})

const feedbackCard = ref<HTMLElement | null>(null)

// The detail pane scrolls on its own: when a failure lands while the user is
// down at the action buttons, bring the card into view without stealing focus.
// A repeated failure of the same kind carries the same title, so key the watch
// on the session object (a new object per result) and fall back to the record
// title for a reloaded record.
watch(
  () => failingWrite.value ?? mainFeedback.value?.title ?? null,
  async (next) => {
    if (!next) return
    await nextTick()
    feedbackCard.value?.scrollIntoView?.({ block: 'nearest' })
  },
)

/** True while the record's exact status is one only the server can settle. */
const recoveryRecord = computed(() => (
  !!detail.value && isRecoverableStatus(detail.value.status)
))

const verifyExternalOffered = computed(() => (
  recoveryRecord.value
  && props.connectionReady === true
  && canVerifyExternally(props.capabilities)
))
const recoveryInFlight = computed(() => (
  thisRecovery.value?.state === 'IN_FLIGHT'
))
const thisRecovery = computed(() => sessionFor(props.sessions?.recovery))
const managementInFlight = computed(() => (
  thisManagement.value?.state === 'IN_FLIGHT'
))
const thisManagement = computed(() => sessionFor(props.sessions?.management))
/** The modify result is rendered next to the modify form; the rest next to the actions. */
const thisModify = computed(() => (thisManagement.value?.operation === 'MODIFY' ? thisManagement.value : null))
const thisManagementAction = computed(() => (
  thisManagement.value && thisManagement.value.operation !== 'MODIFY'
    ? thisManagement.value
    : null
))

/** This item's own conflicting action is in flight: all of them bump its revision. */
/**
 * Issue #101: the failure diagnostics of this item's last write, when there was
 * one. An empty diagnostic object still renders, so the page can honestly say
 * 未提供具体原因 instead of inventing a cause.
 */

const writeDiagnostics = computed(() => (
  failingWrite.value ? thisWrite.value!.diagnostics : null
))

/**
 * D7 (issue #227): 技术诊断 renders only when it actually has something to show.
 * The name stays as it is (arbitration); an empty fold would be a dead control.
 */
const hasTechnicalDiagnostics = computed(() => Boolean(
  writeDiagnostics.value
  || detail.value?.external_mapping
  || detail.value?.safe_info?.resources?.valid_file_names?.length
))

/**
 * Summary values for D2 (issue #227).  The 2026-10-20 revision fixed the field
 * list to 季度/字幕组/有效资源数/总集数/已更新集数/创建时间: 提交方式 is an
 * operation semantic rather than a record attribute, and 「最近更新」 became
 * 创建时间 (created_at) because updated_at moves on every write.
 */
const seasonLabel = computed(() => (
  detail.value?.season ? `第 ${detail.value.season} 季` : '未设置'
))
const createdAtLabel = computed(() => formatTrackingCreatedAt(detail.value?.created_at))

/**
 * Semantic tone of the summary's status pill.
 *
 * Mirrors TrackingView's list-row pill tones so one status never gets two
 * colours.  TrackingView is owned by the T6 ticket, so the mapping is duplicated
 * here instead of exported from it; T6 can unify both into one helper.
 */
const STATUS_PILL_TONES: Record<string, 'info' | 'unknown' | 'warning' | 'danger'> = {
  ACTIVE: 'info',
  PENDING_SUBMIT: 'unknown',
  ADDED_TO_DOWNLOAD: 'unknown',
  DISABLED: 'unknown',
  NEEDS_RECONFIRM: 'warning',
  RECOVERY_REQUIRED: 'warning',
  EXTERNAL_DELETED: 'warning',
  SUBMIT_FAILED: 'danger',
}

function statusPillTone(status: string): string {
  return `is-${STATUS_PILL_TONES[status] ?? 'unknown'}`
}

const itemActionInFlight = computed(() => (
  writeInFlight.value || recoveryInFlight.value || managementInFlight.value || checkInFlight.value
))
/**
 * One page-level intent at a time: a recovery in flight, or an unresolved write
 * of another item, disables every action that would race it (D38-09.4).
 * Management actions are server-computed, so a record in a recovery status
 * never offers any — this lock covers the actions the page can actually send.
 */
const itemIntentUnresolved = computed(() => Boolean(
  (thisWrite.value?.keepsIntent ?? false)
  || (thisRecovery.value?.keepsIntent ?? false)
  || (thisManagement.value?.keepsIntent ?? false),
))
/**
 * In-flight *or* unresolved: an external result whose outcome is not yet
 * confirmed keeps every conflicting action blocked until an explicit recovery
 * converges it (issue #91 AC 6), instead of racing the pending write.
 */
const actionBusy = computed(() => (
  props.writeBusy === true || itemActionInFlight.value || itemIntentUnresolved.value
))

/**
 * The check's own single-flight gate (issue #183). It deliberately excludes
 * *this* record's unresolved submission intent: a read-only check is exactly how
 * that intent gets settled, so the pending state must not disable it. Another
 * record's intent, an in-flight write on this one and a running check still do.
 */
const checkBusy = computed(() => (
  props.writeBusy === true || checkInFlight.value
  || writeInFlight.value || recoveryInFlight.value || managementInFlight.value
))
// One automatic check per armed detail load. The armed attempt is retried when
// it stops being blocked (a submit that is still settling, another record's
// intent) until the page actually starts it; the page only disarms on a started
// check, so a check that persists a new revision never re-triggers itself.
watch([pendingSubmission, () => props.autoCheckArmed, () => detail.value?.revision, checkBusy], () => {
  if (!pendingSubmission.value || props.autoCheckArmed !== true || checkBusy.value) return
  requestCheck(true)
})

/**
 * Issue 116：外部写（提交、重试提交、外部管理）只有在存在已保存的 Auto
 * Bangumi 连接时才可用。它只看「是否已有已保存配置与所需凭据」，不看最近一次
 * 探测结果；服务端仍会在请求内复核连接、认证、版本与能力。
 */
const externalWritesAvailable = computed(() => props.connectionReady === true)
const connectionRequiredHint = '先在设置中连接 Auto Bangumi；缺少已保存连接时不会发起任何外部写。'

function requestRecovery(action: TrackingRecoveryActionCode): void {
  if (!detail.value || actionBusy.value) return
  emit('recovery-requested', { action, item: detail.value })
}

// -- external management writes (US-313, US-314, US-315) ---------------------
// Every management action the page sends (MODIFY, SET_ENABLED, REFRESH_RSS) is
// server-computed with explicit target scopes, so each one is
// projected the same way: it needs the page credential session and the matching
// capability for the scope the user wants to act on.  The forms own the user's
// explicit choice (the fields to change, the enable/disable target, the refresh,
// the object to delete), emit it with the latest revision, and the page owns the
// request, confirmation and idempotency.  An action this page does not send is
// never offered at all.

/** One management action together with the scopes this page may request for it. */
interface ManagementOfferView {
  code: TrackingManagementActionCode
  action: TrackingAction
  scopes: TrackingManagementScope[]
}

// Issue #89: management actions come from the server projection alone. The
// server re-validates the saved connection, credentials, exact version and write
// capability inside the same request and fails closed, so a settings-page probe
// never gates them.
const managementOffers = computed<ManagementOfferView[]>(() => {
  if (!detail.value) return []
  const offers: ManagementOfferView[] = []
  for (const action of executableTrackingActions(detail.value)) {
    if (!isSendableManagementAction(action.code)) continue
    const code = action.code
    const scopes = (action.target_scopes ?? [])
      .filter(isTrackingManagementScope)
      .filter((scope) => projectTrackingActionScopes(detail.value!, code, scope).length > 0)
    if (scopes.length) offers.push({ code, action, scopes })
  }
  return offers
})

function offerFor(code: TrackingManagementActionCode): ManagementOfferView | null {
  return managementOffers.value.find((offer) => offer.code === code) ?? null
}

const modifyOffer = computed(() => offerFor('MODIFY'))
const setEnabledOffer = computed(() => offerFor('SET_ENABLED'))
const refreshOffer = computed(() => offerFor('REFRESH_RSS'))

/** Fixed read-only copy when the server does not offer the action at all. */
function managementHint(verb: string): string {
  return `当前状态不可${verb}。`
}

const modifyHint = computed(() => managementHint('修改外部方案'))
const setEnabledHint = computed(() => managementHint('启停外部订阅或关联 RSS'))
const refreshHint = computed(() => managementHint('立即刷新资源'))

// -- apply an edited plan to the controlled external subscription (issue #91) --
// The already-active plan is edited with the same shared core, but saving is a
// real external write: the page confirms it, sends the patch plus the local plan
// values, and only a confirmed read-back raises both sides.
const APPLY_PLAN_STATUSES = new Set(['ACTIVE', 'DISABLED'])
const applyPlanOpen = ref(false)

const canApplyPlan = computed(() => Boolean(
  detail.value?.request_id
  && detail.value.external_mapping
  && APPLY_PLAN_STATUSES.has(detail.value.status)
))

async function toggleApplyPlan(): Promise<void> {
  if (!applyPlanOpen.value && !planSnapshot.value) {
    planLoading.value = true
    try {
      await fetchPlanSnapshot()
    } finally {
      planLoading.value = false
    }
  }
  applyPlanOpen.value = !applyPlanOpen.value
}

/** Only the editable plan fields travel; identity fields are never sent. */
function applyPatchFromEditor(patch: PreviewPatch): Record<string, unknown> {
  const candidate: Record<string, unknown> = {}
  if (patch.filter_rule) candidate.filter_rule = patch.filter_rule
  if (patch.expected_folder_name) candidate.expected_folder_name = patch.expected_folder_name
  return candidate
}

function applyPlanToExternal(patch: PreviewPatch): void {
  const offer = modifyOffer.value
  if (!offer || !detail.value || actionBusy.value) return
  const externalPatch = applyPatchFromEditor(patch)
  if (!Object.keys(externalPatch).length) return
  emit('management-requested', {
    action: offer.action,
    item: detail.value,
    targetScope: 'SUBSCRIPTION',
    patch: externalPatch,
    // The same values raise the local snapshot once the write is confirmed.
    localPlan: externalPatch,
  })
}

// -- unified plan delete (issue #92) -----------------------------------------
// One business action removes the local plan and its tracking record; the
// controlled external subscription is removed first only when the user ticked
// the option, and its default is always off.
const UNDELETABLE_PLAN_STATUSES = new Set([
  'SUBMITTING', 'REVALIDATING', 'VERIFYING_EXTERNAL', 'RECOVERY_REQUIRED',
])
const deletePlanOpen = ref(false)
const deleteExternalChecked = ref(false)

// Issue #96: a settled operation is history, not a delete lock. Issue #230
// (ADR-0006) mirrors the server's operation-state matrix: a write that may still
// run (`PREPARED`/`IN_PROGRESS`, or an unrecognized state) blocks every delete,
// while an exited-but-undecidable write (`OUTCOME_UNKNOWN`/`RECOVERY_REQUIRED`)
// unlocks the risk-confirmed abandon.
const SETTLED_OPERATION_STATES = new Set(['SUCCEEDED', 'FAILED'])
const ABANDONABLE_OPERATION_STATES = new Set(['OUTCOME_UNKNOWN', 'RECOVERY_REQUIRED'])
const currentOperationState = computed<string | null>(() => {
  const raw = detail.value?.current_operation?.state
  return typeof raw === 'string' ? raw : null
})
/** A write that may still run (or a state this page cannot interpret). */
const operationInFlight = computed(() => {
  const state = currentOperationState.value
  if (state === null) return false
  return !SETTLED_OPERATION_STATES.has(state) && !ABANDONABLE_OPERATION_STATES.has(state)
})
/** An exited external write whose result the server cannot decide. */
const abandonableOperation = computed(() => {
  const state = currentOperationState.value
  return state !== null && ABANDONABLE_OPERATION_STATES.has(state)
})
const canDeletePlan = computed(() => Boolean(
  detail.value
  && !operationInFlight.value
  && !abandonableOperation.value
  && !UNDELETABLE_PLAN_STATUSES.has(detail.value.status)
))
/** Only a controlled mapping makes the external option applicable at all. */
const deletePlanHasExternal = computed(() => Boolean(detail.value?.external_mapping))
const thisPlanDelete = computed(() => (
  props.planDeleteSession && props.planDeleteSession.trackingId === props.trackingId
    ? props.planDeleteSession
    : null
))

const deletePlanConsequence = computed(() => (
  abandonableOperation.value
    ? '放弃只删除本地方案与追番记录，不会向 Auto Bangumi 发送任何请求；Auto Bangumi 中可能已经存在并在继续下载的订阅不再由 MiGuOrca 管理。已下载媒体始终保留。'
    : deleteExternalChecked.value
      ? '将先删除 Auto Bangumi 中的受控外部订阅，明确成功后再删除本地方案与追番记录；该外部对象不会被保留，也不会删除已下载媒体。'
      : '本地方案与追番记录将被删除；Auto Bangumi 中的订阅会继续运行，MiGuOrca 不再管理它们。已下载媒体始终保留。'
))

function openDeletePlan(): void {
  deletePlanOpen.value = true
  deleteExternalChecked.value = false
}

function cancelDeletePlan(): void {
  // Cancelling asks for nothing: no request leaves the page.
  deletePlanOpen.value = false
  deleteExternalChecked.value = false
}

function confirmDeletePlan(): void {
  if (!detail.value) return
  if (abandonableOperation.value) {
    // The risk confirmation binds the record revision and the operation the
    // user saw; the server re-reads both before deleting (ADR-0006).  The
    // abandon never carries the external scope.
    emit('plan-delete-requested', {
      item: detail.value,
      deleteExternal: false,
      abandon: true,
      expectedRevision: detail.value.revision,
      expectedOperationId: detail.value.current_operation?.operation_id ?? null,
    })
    return
  }
  if (!canDeletePlan.value) return
  emit('plan-delete-requested', {
    item: detail.value,
    deleteExternal: deletePlanHasExternal.value && deleteExternalChecked.value,
    abandon: false,
    expectedRevision: null,
    expectedOperationId: null,
  })
}

// -- reuse this plan in the add journey (issue #93) --------------------------
// "复制并重新添加" carries only the public, user-editable suggestion and never
// the external mapping, history or any technical field. The add journey still
// requires choosing a real MiKan collection again.
const canReusePlan = computed(() => Boolean(
  detail.value?.safe_info && buildReuseHandoff(detail.value.safe_info),
))

function reusePlan(): void {
  const safeInfo = detail.value?.safe_info
  if (!safeInfo) return
  const handoff = buildReuseHandoff(safeInfo)
  if (!handoff) return
  // The handoff travels in memory only; the page owns the navigation.
  publishReuseHandoff(handoff)
  emit('reuse-requested')
}

function requestManagement(payload: {
  action: TrackingAction
  item: TrackingItem
  targetScope: TrackingManagementScope
  patch: unknown
}): void {
  if (actionBusy.value || !detail.value) return
  // The emitted action object must still be one of the server-projected offers
  // and the scope must still be requestable for this very revision: a stale
  // form emit after a revision change is dropped instead of being sent.
  const offer = managementOffers.value.find((candidate) => candidate.action === payload.action)
    ?? managementOffers.value.find((candidate) => candidate.code === payload.action.code)
  if (!offer) return
  if (!offer.scopes.includes(payload.targetScope)) return
  if (payload.item.tracking_id !== props.trackingId || payload.item.revision !== detail.value.revision) return
  emit('management-requested', {
    action: offer.action, item: detail.value, targetScope: payload.targetScope, patch: payload.patch,
  })
}



/**
 * ``preserve`` keeps the current detail visible while re-reading (US-310 write
 * read-back): blanking or re-focusing the panel after a write would both hide
 * the write result and steal focus from it.
 */
async function fetchDetail(preserve: boolean): Promise<void> {
  const sequence = ++requestSequence
  controller?.abort()
  const requestController = new AbortController()
  controller = requestController
  if (!preserve) {
    loading.value = true
    failed.value = false
    detail.value = null
  }
  try {
    const nextDetail = await api.get<TrackingDetail>('/api/v1/tracking/items/{tracking_id}', {
      path: { tracking_id: props.trackingId },
      query: storageQuery(),
      signal: requestController.signal,
    })
    if (sequence !== requestSequence || requestController.signal.aborted) return
    detail.value = nextDetail
    if (preserve) return
    // The summary only exists once the loading branch is gone, so clear it
    // before the focus step — otherwise ``inspectorHeading`` is still null and
    // the AC6 focus transfer silently does nothing.
    loading.value = false
    await nextTick()
    if (sequence === requestSequence) inspectorHeading.value?.focus({ preventScroll: true })
  } catch (error) {
    if (sequence !== requestSequence || requestController.signal.aborted) return
    if (!preserve) failed.value = true
    void error
  } finally {
    if (sequence === requestSequence && !preserve) loading.value = false
  }
}

function loadDetail(): Promise<void> {
  return fetchDetail(false)
}

// Selecting another record re-reads its detail; the immediate run loads the
// detail the page selected on mount.
watch(() => props.trackingId, () => {
  void loadDetail()
}, { immediate: true })

onBeforeUnmount(() => {
  controller?.abort()
  requestSequence += 1
})
defineExpose({ reload: () => fetchDetail(true) })
</script>

<template>
  <section class="tracking-inspector-content" aria-labelledby="tracking-inspector-heading">
    <h2 id="tracking-inspector-heading">追番详情</h2>
    <div v-if="loading" class="tracking-inspector-loading"><LoadingState message="正在读取安全详情…" /></div>
    <ErrorState v-else-if="failed" title="追番详情读取失败" message="暂时无法读取该追番详情，请稍后重试。" retry-label="重试详情" @retry="loadDetail" />
    <div v-else-if="detail" class="tracking-inspector-detail">
      <section ref="inspectorHeading" tabindex="-1" class="tracking-inspector-summary" aria-labelledby="tracking-inspector-title">
        <div class="tracking-inspector-identity">
          <TrackingPoster :poster-path="detail.poster_path" variant="detail" />
          <div class="tracking-inspector-headline">
            <div class="tracking-inspector-title-row">
              <h3 id="tracking-inspector-title">{{ detail.title || '未命名番剧' }}</h3>
              <span
                id="tracking-inspector-status"
                class="tracking-status-pill"
                :class="statusPillTone(detail.status)"
              >{{ detail.status_label }}</span>
            </div>
            <dl class="tracking-inspector-facts">
              <div><dt>季度</dt><dd>{{ seasonLabel }}</dd></div>
              <div><dt>字幕组</dt><dd>{{ detail.subtitle_group || '未设置' }}</dd></div>
              <div><dt>有效资源数</dt><dd>{{ detail.valid_resource_count }}</dd></div>
              <div><dt>总集数</dt><dd>{{ hasTrustedEpisodeCount(detail.total_episodes) ? detail.total_episodes : EPISODE_PLACEHOLDER }}</dd></div>
              <div><dt>已更新集数</dt><dd>{{ EPISODE_PLACEHOLDER }}</dd></div>
              <div><dt>创建时间</dt><dd>{{ createdAtLabel }}</dd></div>
            </dl>
          </div>
        </div>
      </section>

      <section
        v-if="mainFeedback"
        id="tracking-feedback"
        ref="feedbackCard"
        class="tracking-feedback-card"
        :class="`is-${mainFeedback.tone}`"
      >
        <h4 id="tracking-feedback-title">{{ mainFeedback.title }}</h4>
        <!--
          Failure/undecidable write results render here (first screen); decided
          successes keep rendering in the submit section below.  The two
          conditions are mutually exclusive, so ``#tracking-submit-result`` is
          only ever in the DOM once.  A record-level card keeps the same shape
          without borrowing that id or a live status role.
        -->
        <div
          :id="mainFeedback.source === 'write' ? 'tracking-submit-result' : undefined"
          class="tracking-submit-result"
          :role="mainFeedback.source === 'write' ? 'status' : undefined"
        >
          <p class="tracking-submit-verdict">{{ mainFeedback.verdict }}</p>
          <template v-if="mainFeedback.reasons.length">
            <p v-if="mainFeedback.source === 'revalidation'" class="field-help">原因</p>
            <ul class="tracking-submit-issues" aria-label="提交问题">
              <li v-for="reason in mainFeedback.reasons" :key="reason">{{ reason }}</li>
            </ul>
          </template>
        </div>
        <p class="field-help tracking-feedback-next">下一步：{{ mainFeedback.nextStep }}</p>
      </section>

      <p
        v-if="intentNotice"
        id="tracking-intent-blocked-notice"
        class="tracking-intent-notice"
        role="status"
      >{{ intentNotice }}</p>

      <section
        v-if="canApplyPlan"
        class="tracking-inspector-section tracking-plan-apply-section"
        aria-labelledby="tracking-plan-apply-heading"
      >
        <h4 id="tracking-plan-apply-heading">已生效追番方案</h4>
        <p class="field-help">
          过滤规则与存储目录名会同时应用到本地方案与受控外部订阅；字幕组等身份字段为只读，
          更换真实 RSS 来源需要删除该追番后重新添加。
        </p>
        <BaseButton
          id="tracking-apply-plan"
          variant="secondary"
          :aria-expanded="applyPlanOpen"
          :disabled="actionBusy"
          @click="toggleApplyPlan"
        >保存并应用到 Auto Bangumi</BaseButton>
        <AnimeDraftEditor
          v-if="applyPlanOpen && planSnapshot?.request"
          :request="planSnapshot.request"
          mode="saved"
          heading="保存并应用到 Auto Bangumi"
          form-heading="编辑已生效追番方案"
          apply-label="保存并应用到 Auto Bangumi"
          id-prefix="tracking-apply"
          container-id="tracking-apply-editor"
          form-id="tracking-apply-form"
          :applying="managementInFlight"
          :disabled="actionBusy"
          subtitle-group-read-only
          @apply="applyPlanToExternal"
          @empty-apply="applyPlanToExternal({})"
        />
        <p v-if="thisManagementAction" id="tracking-apply-result" class="field-help" role="status">
          {{ thisManagementAction.message }}
        </p>
      </section>

      <section
        v-if="canReusePlan"
        class="tracking-inspector-section tracking-reuse-section"
        aria-labelledby="tracking-reuse-heading"
      >
        <h4 id="tracking-reuse-heading">复制并重新添加</h4>
        <p class="field-help">
          只携带安全标题与编辑建议，回到添加番剧后需要重新选择真实 MiKan 合集；
          不会复制外部映射、历史或状态。
        </p>
        <BaseButton
          id="tracking-reuse-plan"
          variant="secondary"
          @click="reusePlan"
        >复制并重新添加</BaseButton>
      </section>

      <section
        v-if="canEditPlan"
        class="tracking-inspector-section tracking-plan-edit-section"
        aria-labelledby="tracking-plan-edit-heading"
      >
        <h4 id="tracking-plan-edit-heading">追番方案</h4>
        <p class="field-help">
          修改只更新本地追番方案（身份字段保持只读）；保存后请重新确认再提交到 Auto Bangumi。
        </p>
        <BaseButton
          id="tracking-edit-plan"
          variant="secondary"
          :loading="planLoading"
          :aria-expanded="planEditor.formOpen.value"
          :disabled="planEditor.inFlight.value || planEditor.resultUnknown.value"
          @click="togglePlanEditor"
        >修改追番方案</BaseButton>
        <p v-if="planLoadFailed" id="tracking-plan-load-failed" class="field-help" role="status">
          暂时无法读取本地追番方案，请稍后重试。
        </p>
        <AnimeDraftEditor
          v-if="planEditor.formOpen.value && planSnapshot?.request"
          :request="planSnapshot.request"
          mode="saved"
          heading="修改追番方案"
          form-heading="编辑本地追番方案"
          apply-label="保存追番方案"
          id-prefix="tracking-plan"
          container-id="tracking-plan-editor"
          form-id="tracking-plan-form"
          :applying="planEditor.inFlight.value"
          :error="planEditor.error.value"
          :can-retry="Boolean(planEditor.error.value)"
          :retry-label="planEditor.resultUnknown.value ? '重新确认结果' : '重试修改'"
          :disabled="planEditor.resultUnknown.value"
          @apply="planEditor.submit"
          @empty-apply="planEditor.submit({})"
          @retry="planEditor.retry"
          @reset="planEditor.recover"
        />
      </section>

      <section class="tracking-inspector-section tracking-submit" aria-labelledby="tracking-submit-heading">
        <h4 id="tracking-submit-heading">提交到 Auto Bangumi</h4>
        <template v-if="pendingSubmission || thisCheck || thisResubmit">
          <p v-if="pendingSubmission" class="field-help">
            持续追番提交结果尚未确认。重新检查只会使用原提交绑定的已保存连接只读核对
            Auto Bangumi 的当前状态，不会创建、修改、删除或重新提交订阅。
          </p>
          <div class="tracking-submit-actions">
            <BaseButton
              v-if="pendingSubmission"
              id="tracking-check"
              variant="secondary"
              :loading="checkInFlight"
              :disabled="checkBusy"
              @click="requestCheck(false)"
            >重新检查</BaseButton>
            <BaseButton
              v-if="resubmitOffered"
              id="tracking-resubmit"
              variant="secondary"
              :loading="resubmitInFlight"
              :disabled="resubmitBusy"
              @click="requestResubmit"
            >重新提交</BaseButton>
          </div>
          <p v-if="resubmitHint" id="tracking-resubmit-hint" class="field-help" role="status">
            {{ resubmitHint }}
          </p>
          <div
            v-if="thisResubmit"
            id="tracking-resubmit-result"
            class="tracking-submit-result"
            :class="`is-${thisResubmit.state.toLowerCase()}`"
            role="status"
          >
            <p class="tracking-submit-verdict">{{ thisResubmit.message }}</p>
          </div>
          <div
            v-if="thisCheck"
            id="tracking-check-result"
            class="tracking-submit-result"
            :class="`is-${thisCheck.state.toLowerCase()}`"
            role="status"
          >
            <p class="tracking-submit-verdict">{{ thisCheck.message }}</p>
          </div>
        </template>
        <template v-else-if="submitAction">
          <p class="field-help">提交会使用已保存的 Auto Bangumi 连接，在 Auto Bangumi 创建外部订阅并可能触发下载；服务端会在同一次请求中校验连接、认证、版本与写能力，每次提交都需要单独确认。</p>
          <BaseButton
            id="tracking-submit"
            :loading="writeInFlight"
            :disabled="actionBusy || !externalWritesAvailable"
            @click="requestWrite(submitAction)"
          >提交方案</BaseButton>
        </template>
        <template v-else-if="retryAction">
          <p class="field-help">该记录上次提交明确失败。重试会使用已保存的 Auto Bangumi 连接，重新在 Auto Bangumi 创建外部订阅并可能触发下载；每次重试都需要单独确认。</p>
          <BaseButton
            id="tracking-retry"
            :loading="writeInFlight"
            :disabled="actionBusy || !externalWritesAvailable"
            @click="requestWrite(retryAction)"
          >{{ retryAction.label }}</BaseButton>
        </template>
        <p v-else class="field-help">{{ writeHint }}</p>
        <p
          v-if="(submitAction || retryAction) && !externalWritesAvailable"
          id="tracking-submit-connection-required"
          class="field-help"
          role="status"
        >
          {{ connectionRequiredHint }}
        </p>
        <div
          v-if="thisWrite && !failingWrite"
          id="tracking-submit-result"
          class="tracking-submit-result"
          :class="`is-${thisWrite.state.toLowerCase()}`"
          role="status"
        >
          <p class="tracking-submit-verdict">{{ thisWrite.message }}</p>
          <ul v-if="thisWrite.issues.length" class="tracking-submit-issues" aria-label="提交问题">
            <li v-for="issue in thisWrite.issues" :key="issue.code">{{ issue.message }}</li>
          </ul>
        </div>
      </section>

      <section
        v-if="!pendingSubmission && (recoveryRecord || thisRecovery)"
        class="tracking-inspector-section tracking-recovery"
        aria-labelledby="tracking-recovery-heading"
      >
        <h4 id="tracking-recovery-heading">结果待确认</h4>
        <p class="field-help">只读核验会用已保存的 Auto Bangumi 连接比对该追番的当前状态；不会重新提交，也不会创建、修改或删除任何外部订阅。</p>
        <div class="tracking-recovery-actions">
          <BaseButton
            v-if="verifyExternalOffered"
            id="tracking-recover-verify"
            variant="secondary"
            :disabled="actionBusy"
            @click="requestRecovery('VERIFY_EXTERNAL')"
          >只读核验外部状态</BaseButton>
        </div>
        <p v-if="!verifyExternalOffered" class="field-help">
          只读外部核验需要先在页面连接 Auto Bangumi，并确认外部核验能力可用。
        </p>
        <div
          v-if="thisRecovery"
          id="tracking-recovery-result"
          class="tracking-recovery-result"
          :class="`is-${thisRecovery.state.toLowerCase()}`"
          role="status"
        >
          <p class="tracking-recovery-verdict">{{ thisRecovery.message }}</p>
          <p v-if="thisRecovery.manualNotice" id="tracking-recovery-manual-notice" class="tracking-recovery-manual">
            {{ thisRecovery.manualNotice }}
          </p>
        </div>
      </section>

      <section
        v-if="canDeletePlan || abandonableOperation"
        id="tracking-delete-plan-section"
        class="tracking-inspector-section tracking-delete-plan-section"
        aria-labelledby="tracking-delete-plan-heading"
      >
        <h4 id="tracking-delete-plan-heading">{{ abandonableOperation ? '放弃跟踪并删除' : '删除追番方案' }}</h4>
        <p
          v-if="abandonableOperation"
          id="tracking-abandon-risk"
          class="field-help"
        >这次提交的结果无法确认，Auto Bangumi 中可能已经建立了订阅并会继续下载；删除后 MiGuOrca 不再跟踪它，也不会再提醒。放弃只删除本地数据，不会向 Auto Bangumi 发送任何请求。</p>
        <p v-else class="field-help">删除本地方案与追番记录；已下载的媒体始终保留。</p>
        <BaseButton
          v-if="!deletePlanOpen"
          :id="abandonableOperation ? 'tracking-abandon-plan' : 'tracking-delete-plan'"
          variant="danger"
          :disabled="actionBusy"
          @click="openDeletePlan"
        >{{ abandonableOperation ? '放弃跟踪并删除' : '删除追番方案' }}</BaseButton>
        <template v-else>
          <CheckboxRow
            v-if="!abandonableOperation && deletePlanHasExternal"
            id="tracking-delete-plan-external"
            v-model:checked="deleteExternalChecked"
            label="同时删除 Auto Bangumi 中的受控外部订阅"
          />
          <p class="field-help">{{ deletePlanConsequence }}</p>
          <div class="tracking-delete-plan-actions">
            <BaseButton
              :id="abandonableOperation ? 'tracking-abandon-confirm' : 'tracking-delete-plan-confirm'"
              variant="danger"
              :loading="Boolean(thisPlanDelete && thisPlanDelete.state === 'IN_FLIGHT')"
              :disabled="actionBusy"
              @click="confirmDeletePlan"
            >{{ abandonableOperation ? '确认放弃并删除' : '删除追番方案' }}</BaseButton>
            <BaseButton
              :id="abandonableOperation ? 'tracking-abandon-cancel' : 'tracking-delete-plan-cancel'"
              variant="secondary"
              :disabled="actionBusy"
              @click="cancelDeletePlan"
            >取消</BaseButton>
          </div>
        </template>
        <p
          v-if="thisPlanDelete && thisPlanDelete.state !== 'IN_FLIGHT'"
          id="tracking-delete-plan-result"
          class="field-help"
          role="status"
        >{{ thisPlanDelete.message }}</p>
      </section>

      <section class="tracking-inspector-section tracking-modify-section" aria-labelledby="tracking-modify-heading">
        <h4 id="tracking-modify-heading">修改 Auto Bangumi 外部方案</h4>
        <template v-if="modifyOffer">
          <p class="field-help">
            修改只作用于当前受控外部订阅及其关联 RSS，不显示外部对象标识。
          </p>
          <TrackingModifyForm
            :item="detail"
            :action="modifyOffer.action"
            :busy="actionBusy || !externalWritesAvailable"
            :loading="managementInFlight"
            @submit="requestManagement"
          />
        </template>
        <p v-else class="field-help">{{ modifyHint }}</p>
        <p
          v-if="modifyOffer && !externalWritesAvailable"
          id="tracking-modify-connection-required"
          class="field-help"
          role="status"
        >
          {{ connectionRequiredHint }}
        </p>
        <div
          v-if="thisModify"
          id="tracking-modify-result"
          class="tracking-modify-result"
          :class="`is-${thisModify.state.toLowerCase()}`"
          role="status"
        >
          <p class="tracking-modify-verdict">{{ thisModify.message }}</p>
          <p v-if="thisModify.manualNotice" id="tracking-modify-manual-notice" class="tracking-modify-manual">
            {{ thisModify.manualNotice }}
          </p>
        </div>
      </section>

      <section
        class="tracking-inspector-section tracking-management-actions-section"
        aria-labelledby="tracking-management-actions-heading"
      >
        <h4 id="tracking-management-actions-heading">启停与关联 RSS 刷新</h4>
        <p class="field-help">{{ MANAGEMENT_ACTIONS_HELP }}</p>
        <TrackingManagementActions
          :item="detail"
          :set-enabled="setEnabledOffer?.action ?? null"
          :refresh-rss="refreshOffer?.action ?? null"
          :set-enabled-hint="setEnabledHint"
          :refresh-hint="refreshHint"
          :result="thisManagementAction"
          :busy="actionBusy || !externalWritesAvailable"
          :loading="managementInFlight"
          @submit="requestManagement"
        />
        <p
          v-if="(setEnabledOffer || refreshOffer) && !externalWritesAvailable"
          id="tracking-management-connection-required"
          class="field-help"
          role="status"
        >
          {{ connectionRequiredHint }}
        </p>
      </section>

      <details id="tracking-activity-log" class="tracking-inspector-disclosure">
        <summary>操作记录</summary>
        <div class="tracking-inspector-disclosure-body">
          <section v-if="detail.current_operation" class="tracking-inspector-section" aria-labelledby="tracking-operation-heading">
            <h4 id="tracking-operation-heading">最近操作</h4>
            <p>
              {{ formatTrackingOperation(detail.current_operation.operation) }}
              · {{ formatTrackingOperationState(detail.current_operation.state) }}
              · 第 {{ detail.current_operation.attempt }} 次
            </p>
          </section>

          <section v-if="detail.revalidation_issues?.length" class="tracking-inspector-section" aria-labelledby="tracking-issues-heading">
            <h4 id="tracking-issues-heading">复核问题</h4>
            <ul><li v-for="issue in detail.revalidation_issues" :key="`${issue.code}-${issue.field ?? ''}`">{{ issue.message }}</li></ul>
          </section>

          <section v-if="detail.audit_events?.length" class="tracking-inspector-section" aria-labelledby="tracking-audit-heading">
            <h4 id="tracking-audit-heading">安全审计</h4>
            <ul><li v-for="event in detail.audit_events" :key="`${event.action}-${event.created_at}`">{{ event.safe_message || formatTrackingAuditAction(event.action) }} · {{ event.created_at }}</li></ul>
          </section>

          <p v-if="!detail.current_operation && !detail.revalidation_issues?.length && !detail.audit_events?.length" class="field-help">暂无操作记录。</p>
        </div>
      </details>

      <details v-if="hasTechnicalDiagnostics" id="tracking-tech-diagnostics" class="tracking-inspector-disclosure">
        <summary>技术诊断</summary>
        <div class="tracking-inspector-disclosure-body">
          <section
            v-if="writeDiagnostics"
            id="tracking-write-diagnostics"
            class="tracking-inspector-section"
            aria-labelledby="tracking-write-diagnostics-heading"
          >
            <h4 id="tracking-write-diagnostics-heading">提交失败诊断</h4>
            <dl>
              <div><dt>失败类别</dt><dd>{{ thisWrite?.failureCategory || '未提供' }}</dd></div>
              <div><dt>HTTP 类别</dt><dd>{{ writeDiagnostics.httpStatus ?? '未提供' }}</dd></div>
              <div>
                <dt>Auto Bangumi 原因</dt>
                <dd id="tracking-write-diagnostic-reason">
                  {{ writeDiagnostics.messageZh || writeDiagnostics.messageEn || '未提供具体原因' }}
                </dd>
              </div>
              <div v-if="writeDiagnostics.messageZh && writeDiagnostics.messageEn">
                <dt>原因（EN）</dt><dd>{{ writeDiagnostics.messageEn }}</dd>
              </div>
            </dl>
          </section>
          <section v-if="detail.external_mapping" class="tracking-inspector-section" aria-labelledby="tracking-external-heading">
            <h4 id="tracking-external-heading">外部安全摘要</h4>
            <dl>
              <div><dt>关联状态</dt><dd>{{ detail.external_mapping.match_reason || '未提供' }}</dd></div>
              <div><dt>启用状态</dt><dd>{{ detail.external_mapping.enabled ? '已启用' : '未启用' }}</dd></div>
              <div><dt>外部删除</dt><dd>{{ detail.external_mapping.external_deleted ? '是' : '否' }}</dd></div>
            </dl>
          </section>


          <ul v-if="detail.safe_info?.resources?.valid_file_names?.length" class="tracking-resource-names" aria-label="有效资源名称">
            <li v-for="name in detail.safe_info.resources.valid_file_names" :key="name">{{ name }}</li>
          </ul>
        </div>
      </details>

      <p v-if="!detail.request_id" class="field-help" role="status">
        该记录没有关联的本地追番方案。
      </p>
      <p v-if="detail.warnings?.length" class="field-help" role="status">{{ detail.warnings[0] }}</p>
    </div>
    <p v-else class="field-help">选择一条追番记录查看追番详情。</p>
  </section>
</template>

<style scoped>
.tracking-inspector-content { display: grid; gap: var(--space-3); }
.tracking-inspector-content h2, .tracking-inspector-content h3, .tracking-inspector-content h4, .tracking-inspector-content p { margin: 0; }
.tracking-inspector-detail, .tracking-inspector-summary, .tracking-inspector-section { display: grid; gap: .55rem; }
.tracking-inspector-section { padding: var(--space-3); border: 1px solid var(--color-border); border-radius: var(--radius-md); }
/* D1 (issue #227): the summary is not a card — no inner frame, no padding. */
.tracking-inspector-summary { padding: 0; border: 0; border-radius: 0; }
.tracking-inspector-summary:focus-visible { outline: 2px solid var(--color-primary); outline-offset: 2px; }
.tracking-inspector-identity { display: flex; align-items: flex-start; gap: var(--space-4); }
.tracking-inspector-identity h3 { margin: 0; }
.tracking-inspector-headline { display: grid; gap: var(--space-2); min-width: 0; }
.tracking-inspector-title-row { display: flex; align-items: center; flex-wrap: wrap; gap: var(--space-2); }
/* Same pill vocabulary as the list row (D1: reuse the semantic tone). */
.tracking-status-pill {
  align-self: center;
  padding: var(--space-1) var(--space-3);
  border-radius: var(--radius-pill);
  font-size: var(--type-label);
  font-weight: var(--font-weight-medium);
  line-height: var(--line-height-tight);
  white-space: nowrap;
}
.tracking-status-pill.is-info { color: var(--color-info); background: var(--color-info-surface); }
.tracking-status-pill.is-unknown { color: var(--color-unknown); background: var(--color-unknown-surface); }
.tracking-status-pill.is-warning { color: var(--color-warning); background: var(--color-warning-surface); }
.tracking-status-pill.is-danger { color: var(--color-danger); background: var(--color-danger-surface); }
/* D1/D2: two columns, both left aligned (never space-between / right aligned). */
.tracking-inspector-summary .tracking-inspector-facts {
  display: grid;
  grid-template-columns: max-content minmax(0, 1fr);
  gap: .35rem var(--space-4);
  margin: 0;
}
.tracking-inspector-summary .tracking-inspector-facts > div { display: contents; }
.tracking-inspector-summary .tracking-inspector-facts dt { color: var(--color-text-muted); }
.tracking-inspector-summary .tracking-inspector-facts dd { margin: 0; text-align: left; font-weight: 600; }
.tracking-inspector-disclosure { padding: var(--space-3); border: 1px solid var(--color-border); border-radius: var(--radius-md); }
.tracking-inspector-disclosure > summary { cursor: pointer; font-weight: 600; }
.tracking-inspector-disclosure > summary:focus-visible { outline: 2px solid var(--color-primary); outline-offset: 2px; }
.tracking-inspector-disclosure-body { display: grid; gap: var(--space-3); margin-top: var(--space-3); }
.tracking-inspector-section dl { display: grid; gap: .35rem; margin: 0; }
.tracking-inspector-section dl div { display: flex; justify-content: space-between; gap: 1rem; }
.tracking-inspector-section dt { color: var(--color-text-muted); }
.tracking-inspector-section dd { margin: 0; text-align: right; font-weight: 600; }
.tracking-inspector-section ul, .tracking-resource-names { display: grid; gap: .3rem; margin: 0; padding-left: 1.2rem; }
.tracking-plan-link { font-weight: 600; }
.tracking-inspector-loading { min-height: 8rem; }
/* D8 (issue #227): the first-screen reason card, orange like design image 16. */
.tracking-feedback-card {
  display: grid;
  gap: .4rem;
  padding: var(--space-3);
  border: 1px solid var(--color-warning-border);
  border-left: 0.3rem solid var(--color-warning);
  border-radius: var(--radius-sm);
  background: var(--color-warning-surface);
}
.tracking-feedback-card.is-danger {
  border-color: var(--color-danger-border);
  border-left-color: var(--color-danger);
  background: var(--color-danger-surface);
}
.tracking-feedback-card > h4 { color: var(--color-warning); }
.tracking-feedback-card.is-danger > h4 { color: var(--color-danger); }
/* The design's warning badge, drawn in CSS so no DOM/ARIA is added. */
.tracking-feedback-card > h4::before {
  content: "!";
  display: inline-grid;
  place-items: center;
  width: 1.15rem;
  height: 1.15rem;
  margin-right: .4rem;
  border-radius: 50%;
  background: var(--color-warning);
  color: var(--color-surface-raised);
  font-size: .78rem;
  font-weight: 700;
  vertical-align: .05rem;
}
.tracking-feedback-card.is-danger > h4::before { background: var(--color-danger); }
/* The card is one visual unit: the nested write result keeps its semantics but
   drops the extra frame it had when it lived inside the action section. */
.tracking-feedback-card #tracking-submit-result {
  padding: 0;
  border: 0;
  background: transparent;
}
.tracking-intent-notice { padding: var(--space-3); border: 1px solid var(--color-border-subtle); border-left: 0.3rem solid var(--color-accent-emphasis); border-radius: var(--radius-sm); background: var(--color-surface-raised); font-weight: 600; }
.tracking-submit { gap: .65rem; }
.tracking-submit-actions { display: flex; flex-wrap: wrap; gap: var(--space-2); }
.tracking-submit-result { display: grid; gap: .4rem; padding: var(--space-3); border: 1px solid var(--color-border-subtle); border-left: 0.3rem solid var(--color-text-muted); border-radius: var(--radius-sm); background: var(--color-surface-raised); }
.tracking-submit-result.is-active { border-left-color: var(--color-feedback-success-border); }
.tracking-submit-result.is-submit_failed, .tracking-submit-result.is-conflict, .tracking-submit-result.is-rejected, .tracking-submit-result.is-unknown { border-left-color: var(--color-feedback-error-border); }
.tracking-submit-result.is-needs_reconfirm, .tracking-submit-result.is-verifying_external, .tracking-submit-result.is-recovery_required { border-left-color: var(--color-accent-emphasis); }
.tracking-submit-verdict { font-weight: 600; }
.tracking-submit-issues { padding-left: 1.2rem; }
.tracking-recovery { gap: .65rem; }
.tracking-recovery-actions { display: flex; flex-wrap: wrap; gap: .5rem; }
.tracking-recovery-result { display: grid; gap: .4rem; padding: var(--space-3); border: 1px solid var(--color-border-subtle); border-left: 0.3rem solid var(--color-text-muted); border-radius: var(--radius-sm); background: var(--color-surface-raised); }
.tracking-recovery-result.is-active { border-left-color: var(--color-feedback-success-border); }
.tracking-recovery-result.is-submit_failed, .tracking-recovery-result.is-conflict, .tracking-recovery-result.is-rejected, .tracking-recovery-result.is-unknown { border-left-color: var(--color-feedback-error-border); }
.tracking-recovery-result.is-recovery_required { border-left-color: var(--color-accent-emphasis); }
.tracking-recovery-verdict, .tracking-recovery-manual { font-weight: 600; }
.tracking-modify-section { gap: .65rem; }
.tracking-modify-scope { margin-left: .4rem; padding: .1rem .45rem; border: 1px solid var(--color-border); border-radius: var(--radius-sm); background: var(--color-surface-subtle); font-weight: 600; }
.tracking-modify-result { display: grid; gap: .4rem; padding: var(--space-3); border: 1px solid var(--color-border-subtle); border-left: 0.3rem solid var(--color-text-muted); border-radius: var(--radius-sm); background: var(--color-surface-raised); }
.tracking-modify-result.is-succeeded { border-left-color: var(--color-feedback-success-border); }
.tracking-modify-result.is-failed, .tracking-modify-result.is-conflict, .tracking-modify-result.is-rejected, .tracking-modify-result.is-unknown { border-left-color: var(--color-feedback-error-border); }
.tracking-modify-verdict, .tracking-modify-manual { font-weight: 600; }
</style>
