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
  formatSubmissionMode,
  DELETE_EXTERNAL_HELP,
  MANAGEMENT_ACTIONS_HELP,
  type CapabilityResult,
  type TrackingAction,
  type TrackingItem,
  type TrackingManagementScope,
} from './trackingProjection'
import {
  isSendableManagementAction,
  projectTrackingActionScopes,
  type TrackingManagementActionCode,
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
import TrackingExternalDelete from './TrackingExternalDelete.vue'
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
  // A management request carries the scope the user chose and the strict patch
  // its own form built; the page re-validates both before anything is sent.
  /** Issue #92: delete this plan, optionally with its controlled external object. */
  (e: 'plan-delete-requested', payload: { item: TrackingItem; deleteExternal: boolean }): void
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

// -- unknown-result recovery (US-312) ----------------------------------------
// The three local actions are rendered exactly as the server offers them for a
// recovery status, so no capability or credential is involved; the read-only
// external verification is the page's own recovery-flow choice and therefore
// requires the live page session to have proven `external_verify`.  The page
// owns the request: this component only projects the actions and renders the
// page-level recovery result.
const RECOVERY_BUTTON_IDS = {
  RECOVER_AUTO: 'tracking-recover-auto',
  MARK_SUCCEEDED: 'tracking-recover-succeeded',
  MARK_FAILED: 'tracking-recover-failed',
} as const satisfies Record<Exclude<TrackingRecoveryActionCode, 'VERIFY_EXTERNAL'>, string>

const RECOVERY_VARIANTS = {
  PRIMARY: 'primary', SECONDARY: 'secondary', DANGER: 'danger',
} as const

/** Only the server-computed local recovery actions, in server order. */
const recoveryActions = computed(() => (
  detail.value
    ? executableTrackingActions(detail.value).filter(
        (action): action is TrackingAction & { code: keyof typeof RECOVERY_BUTTON_IDS } =>
          action.code === 'RECOVER_AUTO' || action.code === 'MARK_SUCCEEDED' || action.code === 'MARK_FAILED',
      )
    : []
))
/**
 * The read-only external verification is offered only inside a recovery flow
 * (the server marks every recoverable status with RECOVER_AUTO) and only while
 * the page session proves the capability; it never creates an external write.
 */
const verifyExternalOffered = computed(() => (
  recoveryActions.value.length > 0 && props.connectionReady === true && canVerifyExternally(props.capabilities)
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
/** The delete result belongs to the delete section only (US-315). */
const thisDelete = computed(() => (
  thisManagement.value?.operation === 'DELETE_EXTERNAL' ? thisManagement.value : null
))
const thisManagementAction = computed(() => (
  thisManagement.value && thisManagement.value.operation !== 'MODIFY'
    && thisManagement.value.operation !== 'DELETE_EXTERNAL'
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
  thisWrite.value && thisWrite.value.state !== 'IN_FLIGHT' && thisWrite.value.state !== 'ACTIVE'
    ? thisWrite.value.diagnostics
    : null
))

const submissionModeLabel = computed(() => formatSubmissionMode(detail.value?.submission_mode))

const itemActionInFlight = computed(() => (
  writeInFlight.value || recoveryInFlight.value || managementInFlight.value
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
// Every management action the page sends (MODIFY, SET_ENABLED, REFRESH_RSS,
// DELETE_EXTERNAL) is server-computed with explicit target scopes, so each one is
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
      .filter((scope): scope is TrackingManagementScope =>
        scope === 'SUBSCRIPTION' || scope === 'ASSOCIATED_RSS')
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
const deleteOffer = computed(() => offerFor('DELETE_EXTERNAL'))

/** Fixed read-only copy when the server does not offer the action at all. */
function managementHint(verb: string): string {
  return `当前状态不可${verb}。`
}

const modifyHint = computed(() => managementHint('修改外部方案'))
const setEnabledHint = computed(() => managementHint('启停外部订阅或关联 RSS'))
const refreshHint = computed(() => managementHint('立即刷新资源'))
const deleteHint = computed(() => managementHint('删除外部对象'))

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

// Issue #96: a settled operation is history, not a delete lock. Only an
// in-flight or unresolved current operation (or a status mid-external-action)
// still blocks; an unrecognized state fails closed.
const SETTLED_OPERATION_STATES = new Set(['SUCCEEDED', 'FAILED'])
const hasUnresolvedOperation = computed(() => {
  const operation = detail.value?.current_operation
  if (!operation) return false
  return !SETTLED_OPERATION_STATES.has(String(operation.state))
})

const canDeletePlan = computed(() => Boolean(
  detail.value
  && !UNDELETABLE_PLAN_STATUSES.has(detail.value.status)
  && !hasUnresolvedOperation.value
))
/** Only a controlled mapping makes the external option applicable at all. */
const deletePlanHasExternal = computed(() => Boolean(detail.value?.external_mapping))
const thisPlanDelete = computed(() => (
  props.planDeleteSession && props.planDeleteSession.trackingId === props.trackingId
    ? props.planDeleteSession
    : null
))

const deletePlanConsequence = computed(() => (
  deleteExternalChecked.value
    ? '将先删除 Auto Bangumi 中的受控外部订阅，明确成功后再删除本地方案与追番记录；该外部对象不会被保留，也不会删除已下载媒体。'
    : '本地方案与追番记录将被删除；Auto Bangumi 中的受控外部订阅继续运行，但 MiGuOrca 不再管理它。已下载媒体始终保留。'
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
  if (!detail.value || !canDeletePlan.value) return
  emit('plan-delete-requested', {
    item: detail.value,
    deleteExternal: deletePlanHasExternal.value && deleteExternalChecked.value,
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
        <p class="field-help">安全追番摘要</p>
        <div class="tracking-inspector-identity">
          <TrackingPoster :poster-path="detail.poster_path" variant="detail" />
          <h3 id="tracking-inspector-title">{{ detail.title || '未命名番剧' }}</h3>
        </div>
        <dl>
          <div><dt>季度</dt><dd>{{ detail.season ?? '未设置' }}</dd></div>
          <div><dt>字幕组</dt><dd>{{ detail.subtitle_group || '未设置' }}</dd></div>
          <div><dt>本地状态</dt><dd>{{ detail.status_label }}</dd></div>
          <div v-if="submissionModeLabel"><dt>提交方式</dt><dd>{{ submissionModeLabel }}</dd></div>
          <div><dt>有效资源</dt><dd>{{ detail.valid_resource_count }}</dd></div>
          <div><dt>总集数</dt><dd>{{ hasTrustedEpisodeCount(detail.total_episodes) ? detail.total_episodes : EPISODE_PLACEHOLDER }}</dd></div>
          <div><dt>已更新集数</dt><dd>{{ EPISODE_PLACEHOLDER }}</dd></div>
        </dl>
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
        v-if="canDeletePlan"
        id="tracking-delete-plan-section"
        class="tracking-inspector-section tracking-delete-plan-section"
        aria-labelledby="tracking-delete-plan-heading"
      >
        <h4 id="tracking-delete-plan-heading">删除追番方案</h4>
        <p class="field-help">删除本地方案与追番记录；已下载的媒体始终保留。</p>
        <BaseButton
          v-if="!deletePlanOpen"
          id="tracking-delete-plan"
          variant="danger"
          :disabled="actionBusy"
          @click="openDeletePlan"
        >删除追番方案</BaseButton>
        <template v-else>
          <CheckboxRow
            v-if="deletePlanHasExternal"
            id="tracking-delete-plan-external"
            v-model:checked="deleteExternalChecked"
            label="同时删除 Auto Bangumi 中的受控外部订阅"
          />
          <p class="field-help">{{ deletePlanConsequence }}</p>
          <div class="tracking-delete-plan-actions">
            <BaseButton
              id="tracking-delete-plan-confirm"
              variant="danger"
              :loading="Boolean(thisPlanDelete && thisPlanDelete.state === 'IN_FLIGHT')"
              :disabled="actionBusy"
              @click="confirmDeletePlan"
            >删除追番方案</BaseButton>
            <BaseButton
              id="tracking-delete-plan-cancel"
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
        <template v-if="submitAction">
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
          v-if="thisWrite"
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
        v-if="recoveryActions.length || verifyExternalOffered || thisRecovery"
        class="tracking-inspector-section tracking-recovery"
        aria-labelledby="tracking-recovery-heading"
      >
        <h4 id="tracking-recovery-heading">结果未知恢复</h4>
        <p class="field-help">恢复只用本地证据或只读外部核验，不会重新提交，也不会创建、修改或删除 Auto Bangumi 订阅。</p>
        <div class="tracking-recovery-actions">
          <BaseButton
            v-for="action in recoveryActions"
            :key="action.code"
            :id="RECOVERY_BUTTON_IDS[action.code]"
            :variant="RECOVERY_VARIANTS[action.style]"
            :disabled="actionBusy"
            @click="requestRecovery(action.code)"
          >{{ action.label }}</BaseButton>
          <BaseButton
            v-if="verifyExternalOffered"
            id="tracking-recover-verify"
            variant="secondary"
            :disabled="actionBusy"
            @click="requestRecovery('VERIFY_EXTERNAL')"
          >只读核验外部状态</BaseButton>
        </div>
        <p v-if="!verifyExternalOffered && recoveryActions.length" class="field-help">
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
            <p>{{ detail.current_operation.operation }} · {{ detail.current_operation.state }} · 第 {{ detail.current_operation.attempt }} 次</p>
          </section>

          <section v-if="detail.revalidation_issues?.length" class="tracking-inspector-section" aria-labelledby="tracking-issues-heading">
            <h4 id="tracking-issues-heading">复核问题</h4>
            <ul><li v-for="issue in detail.revalidation_issues" :key="`${issue.code}-${issue.field ?? ''}`">{{ issue.message }}</li></ul>
          </section>

          <section v-if="detail.audit_events?.length" class="tracking-inspector-section" aria-labelledby="tracking-audit-heading">
            <h4 id="tracking-audit-heading">安全审计</h4>
            <ul><li v-for="event in detail.audit_events" :key="`${event.action}-${event.created_at}`">{{ event.safe_message || event.action }} · {{ event.created_at }}</li></ul>
          </section>

          <p v-if="!detail.current_operation && !detail.revalidation_issues?.length && !detail.audit_events?.length" class="field-help">暂无操作记录。</p>
        </div>
      </details>

      <details id="tracking-tech-diagnostics" class="tracking-inspector-disclosure">
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

      <section
        class="tracking-inspector-section tracking-delete-external-section"
        aria-labelledby="tracking-delete-external-section-heading"
      >
        <h4 id="tracking-delete-external-section-heading">删除 Auto Bangumi 外部对象</h4>
        <p class="field-help">{{ DELETE_EXTERNAL_HELP }}</p>
        <TrackingExternalDelete
          :item="detail"
          :action="deleteOffer?.action ?? null"
          :result="thisDelete"
          :hint="deleteHint"
          :busy="actionBusy || !externalWritesAvailable"
          :loading="managementInFlight"
          @submit="requestManagement"
        />
        <p
          v-if="deleteOffer && !externalWritesAvailable"
          id="tracking-delete-connection-required"
          class="field-help"
          role="status"
        >
          {{ connectionRequiredHint }}
        </p>
      </section>

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
.tracking-inspector-summary, .tracking-inspector-section { padding: var(--space-3); border: 1px solid var(--color-border); border-radius: var(--radius-md); }
.tracking-inspector-summary:focus-visible { outline: 2px solid var(--color-primary); outline-offset: 2px; }
.tracking-inspector-identity { display: flex; align-items: center; gap: var(--space-3); }
.tracking-inspector-identity h3 { margin: 0; }
.tracking-inspector-disclosure { padding: var(--space-3); border: 1px solid var(--color-border); border-radius: var(--radius-md); }
.tracking-inspector-disclosure > summary { cursor: pointer; font-weight: 600; }
.tracking-inspector-disclosure > summary:focus-visible { outline: 2px solid var(--color-primary); outline-offset: 2px; }
.tracking-inspector-disclosure-body { display: grid; gap: var(--space-3); margin-top: var(--space-3); }
.tracking-inspector-detail dl { display: grid; gap: .35rem; margin: 0; }
.tracking-inspector-detail dl div { display: flex; justify-content: space-between; gap: 1rem; }
.tracking-inspector-detail dt { color: var(--color-text-muted); }
.tracking-inspector-detail dd { margin: 0; text-align: right; font-weight: 600; }
.tracking-inspector-section ul, .tracking-resource-names { display: grid; gap: .3rem; margin: 0; padding-left: 1.2rem; }
.tracking-plan-link { font-weight: 600; }
.tracking-inspector-loading { min-height: 8rem; }
.tracking-intent-notice { padding: var(--space-3); border: 1px solid var(--color-border-subtle); border-left: 0.3rem solid var(--color-accent-emphasis); border-radius: var(--radius-sm); background: var(--color-surface-raised); font-weight: 600; }
.tracking-submit { gap: .65rem; }
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
.tracking-delete-external-section { gap: .65rem; }
</style>
