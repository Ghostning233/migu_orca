<script setup lang="ts">
/** Formal tracking overview (US-305). The first management screen is read-only. */
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import { api, toApiError } from '@/api/client'
import type { operations } from '@/api/generated/api'
import EmptyState from '@/components/feedback/EmptyState.vue'
import ErrorState from '@/components/feedback/ErrorState.vue'
import LoadingState from '@/components/feedback/LoadingState.vue'
import ConfirmDialog from '@/components/feedback/ConfirmDialog.vue'
import BaseButton from '@/components/forms/BaseButton.vue'
import BaseInput from '@/components/forms/BaseInput.vue'
import BaseSelect from '@/components/forms/BaseSelect.vue'
import PanelSection from '@/components/layout/PanelSection.vue'
import { routeLocation } from '@/app/router/catalog'
import { useNotificationStore } from '@/app/stores/notification'
import { refreshConnectionStatus } from '@/app/stores/connectionStatus'
import { storageQuery } from '@/features/requests/requestStorage'
import {
  capabilityStateLabel,
  capabilityVersionLabel,
  createManagementSession,
  createCheckSession,
  createRecoveryConflictSession,
  createResubmitConfirmationBody,
  createResubmitSession,
  createRecoverySession,
  createTrackingActionIntent,
  createTrackingRecoverBody,
  createTrackingRecoveryIntent,
  createWriteConflictSession,
  createWriteSession,
  filterTrackingItems,
  formatSubmissionMode,
  formatTrackingUpdatedAt,
  isDefiniteWriteRejection,
  isRecoveryActionCode,
  isTrackingManagementScope,
  isWriteActionCode,
  createPlanDeleteSession,
  makeOpaqueKey,
  managementSessionKeepsIntent,
  probeStatusLabel,
  projectCapabilitySummary,
  projectRecoveryOutcome,
  projectTrackingOverview,
  projectWriteOutcome,
  recoveryConfirmation,
  recoverySessionKeepsLock,
  sortTrackingItems,
  TRACKING_OVERVIEW_GROUPS,
  type TrackingOverviewGroup,
  projectCheckResult,
  projectResubmitOffer,
  resubmitBindingFrom,
  resubmitConflictMessage,
  resubmitRiskMessage,
  TRACKING_CHECK_ENDPOINT,
  TRACKING_RECOVER_ENDPOINT,
  TRACKING_RESUBMIT_ENDPOINT,
  TRACKING_STATUS_GROUPS,
  WRITE_ACTION_CONFIRMATIONS,
  WRITE_FAILURE_PRESENTATIONS,
  WRITE_ACTION_ENDPOINTS,
  writeSessionKeepsIntent,
  type TrackingAction,
  type TrackingActionIntent,
  type TrackingItem,
  type TrackingListSummary,
  type TrackingManagementScope,
  type TrackingManagementSession,
  type TrackingPlanDeleteSession,
  type TrackingCheckBody,
  type TrackingCheckResult,
  type TrackingCheckReason,
  type TrackingCheckSession,
  type TrackingRecoverResult,
  type TrackingRecoveryActionCode,
  type TrackingResubmitBody,
  type TrackingResubmitResult,
  type TrackingResubmitSession,
  type TrackingRecoverySession,
  type TrackingStatusGroup,
  type TrackingWriteActionCode,
  type TrackingWriteBody,
  type TrackingWriteResult,
  type TrackingWriteSession,
} from './trackingProjection'
import {
  createManagementConflictSession,
  createManagementInFlightSession,
  createManagementRejectedSession,
  createManagementUnbuildableSession,
  createTrackingManagementActionIntent,
  createTrackingManagementBody,
  isSendableManagementActionCode,
  MANAGEMENT_ACTION_ENDPOINTS,
  managementConfirmation,
  projectManagementOutcome,
  sameManagementRequest,
  type TrackingManagementIntent,
  type TrackingManagementResult,
} from './trackingManagement'
import TrackingInspector from './TrackingInspector.vue'
import TrackingSubmissionModeDialog, { type SubmissionMode } from './TrackingSubmissionModeDialog.vue'
import TrackingPoster from './TrackingPoster.vue'
import {
  EMPTY_BATCH_SELECTION,
  batchSelectionSummary,
  batchSkipReason,
  buildBatchSubmitBody,
  skippedBatchEntries,
  type SkippedBatchEntry,
  clearBatchSelection,
  isBatchSelected,
  projectBatchOutcome,
  selectAllBatch,
  selectionAfterBatch,
  toggleBatchSelection,
  type TrackingBatchOutcome,
  type TrackingBatchSelection,
} from './batchSelection'

type ListResult = NonNullable<
  operations['listTrackingItems']['responses']['200']['content']['application/json']['result']
>
type CapabilityResult = NonNullable<
  operations['probeSavedAutoBangumiCapabilities']['responses']['200']['content']['application/json']['result']
>
type SavedConnection = NonNullable<operations['getAutoBangumiConnection']['responses']['200']['content']['application/json']['result']>
type PlanDeleteResult = NonNullable<
  operations['deleteTrackingPlan']['responses']['200']['content']['application/json']['result']
>
type BatchResult = NonNullable<
  operations['submitTrackingBatch']['responses']['200']['content']['application/json']['result']
>
type SyncBody = NonNullable<
  operations['syncTrackingItems']['requestBody']['content']['application/json']
>
type SyncResult = NonNullable<
  operations['syncTrackingItems']['responses']['200']['content']['application/json']['result']
>

const route = useRoute()
const router = useRouter()
const notification = useNotificationStore()
const items = ref<TrackingItem[]>([])
const loading = ref(false)
const failed = ref(false)
const searchTerm = ref('')
const statusFilter = ref<TrackingStatusGroup | ''>('')
const selectedTrackingId = ref('')
const listContainer = ref<HTMLElement | null>(null)
type SavedConnectionState = Pick<SavedConnection, 'connection_ref' | 'configuration_revision'> & { capabilities: CapabilityResult }
const savedConnection = ref<SavedConnection | null>(null)
const savedState = ref<SavedConnectionState | null>(null)
/**
 * Issue #86: a saved Auto Bangumi connection is all a business action needs.
 * The settings-page probe remains a diagnostic summary and never becomes a
 * display condition or authorization state for tracking actions.
 */
const savedRef = computed<SavedConnection | null>(() => {
  const summary = savedConnection.value
  return summary?.connection_ref && summary.credential_present ? summary : null
})
const syncLoading = ref(false)
const syncPending = ref(false)
const syncMessage = ref('')
const syncSummary = ref<SyncResult['summary'] | null>(null)
const confirmDialog = ref<InstanceType<typeof ConfirmDialog> | null>(null)
const detailRevision = ref(0)
const inspector = ref<InstanceType<typeof TrackingInspector> | null>(null)
// Explicit external submission (US-310).  The credential itself never leaves
// this component: it is read here and placed only into the single POST body.
const writeSession = ref<TrackingWriteSession | null>(null)
const writeLoading = ref(false)
const writePending = ref(false)
let writeIntent: TrackingActionIntent | null = null
let writeSequence = 0
let writeController: AbortController | null = null
// Explicitly clearing credentials destroys the config.  An unresolved intent
// remains a tombstone, but can never be replayed with a newly connected account.
const writeReplayBlocked = ref(false)
let writeConfigSnapshot: Pick<SavedConnection, 'connection_ref' | 'configuration_revision'> | null = null
// Unknown-result recovery (US-312).  Like the write family, the page owns the
// request (only VERIFY_EXTERNAL needs the page credential) and the single
// page-level intent; no recovery key or credential is ever stored here beyond
// the live session config.
const recoverySession = ref<TrackingRecoverySession | null>(null)
const recoveryLoading = ref(false)
const recoveryPending = ref(false)
let recoverySequence = 0
let recoveryController: AbortController | null = null
// Issue #183: bounded read-only confirmation of a 结果待确认 persistent submit.
// The page owns one check at a time and holds no connection for it — the server
// resolves the original submit operation's saved instance — and a check never
// holds the external-write intent because it writes nothing.
const checkSession = ref<TrackingCheckSession | null>(null)
const checkLoading = ref(false)
let checkSequence = 0
let checkController: AbortController | null = null
// Issue #184: the risk-confirmed resubmission. The page runs the read-only
// phase, then asks for the explicit risk confirmation, and only then sends the
// single write. `resubmitIntent` holds the exact confirmation body while its
// result is unresolved, so a retry replays the identical binding (the server
// derives the same operation key and can never create a second operation).
const resubmitSession = ref<TrackingResubmitSession | null>(null)
const resubmitLoading = ref(false)
const resubmitPending = ref(false)
let resubmitSequence = 0
let resubmitController: AbortController | null = null
let resubmitIntent: { trackingId: string; body: TrackingResubmitBody } | null = null
// One automatic check per opened/armed record: the inspector emits it, the page
// consumes the flag, so a check that persists a new revision cannot loop.
const autoCheckArmed = ref(false)
// External management writes (US-313, US-314).  MODIFY, SET_ENABLED and
// REFRESH_RSS share the page credential, the impact confirmation, the latest
// revision and the single page-level intent with the submit family; only the
// endpoint, the request body and the server verdict differ (management_status
// instead of outcome).  The patch, the enable direction and the refresh scope
// live only in the locked in-memory intent and the single POST body.
const managementSession = ref<TrackingManagementSession | null>(null)
const managementLoading = ref(false)
const managementPending = ref(false)
let managementIntent: TrackingManagementIntent | null = null
let managementSequence = 0
let managementController: AbortController | null = null
const managementReplayBlocked = ref(false)
let managementConfigSnapshot: Pick<SavedConnection, 'connection_ref' | 'configuration_revision'> | null = null
// List reads and server-confirmed tracking writes have independent lifecycles:
// `listSequence` only invalidates stale list responses, while `writeGeneration`
// marks the revision a sync (or a local revalidate) already applied.  A list
// response started before a write must never overwrite it, and a list refresh
// must never discard a write result.
let listSequence = 0
let writeGeneration = 0
let syncSequence = 0
let syncController: AbortController | null = null
// Retired queue deep links (US-316): the one-time compat read is tracked by its
// own sequence so a route change can never let a stale location win.

async function loadSavedConnection(): Promise<void> {
  try {
    const summary = await api.get<SavedConnection>('/api/v1/settings/autobangumi')
    const changed = savedState.value && (savedState.value.connection_ref !== summary.connection_ref
      || savedState.value.configuration_revision !== summary.configuration_revision)
    savedConnection.value = summary
    if (changed) savedState.value = null
  } catch {
    savedConnection.value = null
    savedState.value = null
  }
}

async function probeSavedConnection(): Promise<void> {
  const summary = savedConnection.value
  if (!summary?.connection_ref) return
  try {
    const capabilities = await api.post<CapabilityResult>('/api/v1/settings/autobangumi/probe', {
      body: { connection_ref: summary.connection_ref, configuration_revision: summary.configuration_revision },
    })
    if (savedConnection.value?.connection_ref === summary.connection_ref
      && savedConnection.value.configuration_revision === summary.configuration_revision) {
      savedState.value = { connection_ref: summary.connection_ref, configuration_revision: summary.configuration_revision, capabilities }
    }
  } catch {
    savedState.value = null
  }
}

const statusLabels: Record<TrackingStatusGroup, string> = {
  PENDING: '待提交', PROCESSING: '处理中', ACTIVE: '追番中',
  ATTENTION: '需处理', INACTIVE: '已停用',
}
/**
 * Clicking an overview card filters the list by that server status group.
 * 已加入下载 has no group of its own, so its card only reports the count.
 */
function selectOverviewGroup(group: TrackingOverviewGroup): void {
  if (group === 'ADDED_TO_DOWNLOAD') return
  statusFilter.value = statusFilter.value === group ? '' : group
}

/** Issue #99: the five fixed overview categories, including 已加入下载. */
const overviewLabels: Record<TrackingOverviewGroup, string> = {
  ...statusLabels,
  ADDED_TO_DOWNLOAD: '已加入下载',
}
// Issue #85: the overview is the server's authoritative count projection, not a
// recount of whichever rows this page happens to hold or filter.
const listSummary = ref<TrackingListSummary | null>(null)
const overview = computed(() => projectTrackingOverview(listSummary.value))
const capabilitySummary = computed(() => (
  savedState.value ? projectCapabilitySummary(savedState.value.capabilities) : []
))
const filteredItems = computed(() => sortTrackingItems(filterTrackingItems(items.value, {
  query: searchTerm.value, statusGroup: statusFilter.value,
})))
const selectedItem = computed(() => items.value.find(
  (item) => item.tracking_id === selectedTrackingId.value,
) ?? null)
const selectedHidden = computed(() => Boolean(
  selectedItem.value && !filteredItems.value.some((item) => item.tracking_id === selectedTrackingId.value),
))
/**
 * Feedback for a locked (unresolved) external intent (Stage 38 review fix).
 *
 * One page-level intent at a time is a safety invariant: while an external
 * result is still unconfirmed, minting a new key for a *different* request
 * could duplicate or double-apply the external change, so the page refuses it
 * and sends zero requests.  A refusal the user cannot see is a dead end, so the
 * fixed next step below is stated instead of returning silently.  It is
 * deliberately separate from the write/recovery/management result panels (it
 * never replaces their copy or state) and scoped to the record the user acted
 * on, so it can never leak onto another item.
 */
const INTENT_BLOCKED_MESSAGE =
  '上一次外部操作的结果仍未确认，在确认或恢复之前不能发起不同的外部操作；请先使用只读回查或恢复得出结论。'
const REPLAY_BLOCKED_MESSAGE =
  '该外部操作绑定的连接已被清除或更换，结果确认前不能使用新连接重试写入；请继续使用只读回查或恢复。'

const blockedIntentNotice = ref<{ trackingId: string; message: string } | null>(null)

/** The record whose still-unresolved intent refuses this request, or ''. */
function otherItemIntentOwner(trackingId: string): string {
  if (resubmitIntent && resubmitIntent.trackingId !== trackingId) return resubmitIntent.trackingId
  const write = writeSession.value
  if (write && write.trackingId !== trackingId && writeSessionKeepsIntent(write.state)) return write.trackingId
  const recovery = recoverySession.value
  if (recovery && recovery.trackingId !== trackingId && recoverySessionKeepsLock(recovery.state)) {
    return recovery.trackingId
  }
  const management = managementSession.value
  if (management && management.trackingId !== trackingId && managementSessionKeepsIntent(management)) {
    return management.trackingId
  }
  return ''
}

/** True while any record still owns the page's single unresolved intent. */
function hasPendingIntentLock(): boolean {
  if (resubmitIntent) return true
  const write = writeSession.value
  if (write && writeSessionKeepsIntent(write.state)) return true
  const recovery = recoverySession.value
  if (recovery && recoverySessionKeepsLock(recovery.state)) return true
  const management = managementSession.value
  return Boolean(management && managementSessionKeepsIntent(management))
}

/** State the fixed reason a locked intent refused a different request. */
function blockIntent(trackingId: string): void {
  blockedIntentNotice.value = { trackingId, message: INTENT_BLOCKED_MESSAGE }
}

function blockReplay(trackingId: string): void {
  blockedIntentNotice.value = { trackingId, message: REPLAY_BLOCKED_MESSAGE }
}

/** The notice shown on the selected record; empty while nothing is blocked. */
const selectedIntentNotice = computed(() => {
  const notice = blockedIntentNotice.value
  if (notice && notice.trackingId === selectedTrackingId.value) return notice.message
  return otherItemIntentOwner(selectedTrackingId.value) ? INTENT_BLOCKED_MESSAGE : ''
})

/**
 * External writes and recoveries are single-flight (Stage 38 invariant).  The
 * lock covers the external action only: selecting, searching, refreshing and
 * the pure local revalidate of *other* items stay available while one action is
 * running.  An unresolved result keeps locking other items because it still
 * holds the one page-level intent (D38-09.4 keeps that lock for an unresolved
 * recovery too), but never blocks the item's own next step.
 */
const inspectorIntentBusy = computed(() => {
  if (writeLoading.value || recoveryLoading.value || managementLoading.value
    || resubmitLoading.value || resubmitPending.value) return true
  if (resubmitIntent && resubmitIntent.trackingId !== selectedTrackingId.value) return true
  const write = writeSession.value
  if (write && writeSessionKeepsIntent(write.state) && write.trackingId !== selectedTrackingId.value) {
    return true
  }
  const recovery = recoverySession.value
  if (recovery && recoverySessionKeepsLock(recovery.state) && recovery.trackingId !== selectedTrackingId.value) {
    return true
  }
  const management = managementSession.value
  return Boolean(
    management && managementSessionKeepsIntent(management) && management.trackingId !== selectedTrackingId.value,
  )
})

function queryTrackingId(): string | null {
  const value = route.query.tracking_id
  return typeof value === 'string' ? value.trim() || null : null
}

async function focusSelection(): Promise<void> {
  await nextTick()
  const selected = listContainer.value?.querySelector<HTMLElement>('[aria-current="true"]')
  ;(selected ?? listContainer.value)?.focus({ preventScroll: true })
}

function syncSelection(forceAbsentCheck = false): void {
  const queryId = queryTrackingId()
  const next = queryId && items.value.some(
    (item) => item.tracking_id === queryId && item.status !== 'EXTERNAL_DELETED',
  ) ? queryId : ''
  selectedTrackingId.value = next
  if (queryId && !next && (!loading.value || forceAbsentCheck)) {
    void router.replace(routeLocation('tracking'))
    void focusSelection()
  }
}

async function loadList(silent = false): Promise<void> {
  const sequence = ++listSequence
  const generation = writeGeneration
  if (!silent) loading.value = true
  failed.value = false
  try {
    const result = await api.get<ListResult>('/api/v1/tracking/items', {
      query: { ...storageQuery(), sort: 'updated_at' },
    })
    if (sequence !== listSequence || generation !== writeGeneration) return
    const previous = selectedTrackingId.value
    items.value = result?.items ?? []
    listSummary.value = result?.summary ?? null
    syncSelection(true)
    if (selectedTrackingId.value && selectedTrackingId.value !== previous) await focusSelection()
  } catch (error) {
    if (sequence !== listSequence || generation !== writeGeneration) return
    // A silent re-check never replaces a healthy list with an error state.
    if (!silent) failed.value = true
    void error
  } finally {
    if (sequence === listSequence && !silent) {
      loading.value = false
    }
  }
}

async function refreshTracking(): Promise<void> {
  await loadSavedConnection()
  await loadList()
}

/**
 * Converge one list item with the server-returned tracking summary (US-309).
 *
 * The write bumps `writeGeneration` so a list response that started before it
 * can never restore the superseded revision.
 */
function applyReturnedTracking(tracking: TrackingItem): void {
  if (!tracking || typeof tracking.tracking_id !== 'string') return
  const index = items.value.findIndex((item) => item.tracking_id === tracking.tracking_id)
  if (index === -1) return
  writeGeneration += 1
  const next = items.value.slice()
  next[index] = tracking
  items.value = next
  refreshConnectionStatus()
}

function selectItem(trackingId: string): void {
  selectedTrackingId.value = trackingId
  void router.push(routeLocation('tracking', { tracking_id: trackingId }))
}

function clearFilters(): void {
  searchTerm.value = ''
  statusFilter.value = ''
}

/**
 * Clearing the page session destroys credentials while preserving unresolved
 * intents as non-replayable tombstones. The server record remains authoritative
 * and can only be settled through read-only verification or recovery.
 */
function clearConnection(): void {
  savedState.value = null
  cancelSync()
  preserveWriteLockAfterClear()
  preserveRecoveryLockAfterClear()
  preserveManagementLockAfterClear()
  syncMessage.value = ''
  syncSummary.value = null
}

function preserveWriteLockAfterClear(): void {
  const session = writeSession.value
  const unresolved = Boolean(
    writeLoading.value || (session && (session.state === 'IN_FLIGHT' || writeSessionKeepsIntent(session.state))),
  )
  // Issue #184: the resubmit confirmation is the same kind of locked intent, so
  // a cleared connection keeps it unresolved instead of silently releasing it.
  if (!unresolved || !(writeIntent ?? resubmitIntent) || !session) {
    resetWrite()
    return
  }
  writeSequence += 1
  writeController?.abort()
  writeController = null
  writePending.value = false
  writeLoading.value = false
  writeReplayBlocked.value = true
  writeConfigSnapshot = null
  writeSession.value = createWriteSession(session.trackingId, session.action, 'UNKNOWN')
}

function preserveRecoveryLockAfterClear(): void {
  const session = recoverySession.value
  if (!session || (!recoveryLoading.value && !recoverySessionKeepsLock(session.state))) {
    resetRecovery()
    return
  }
  recoverySequence += 1
  recoveryController?.abort()
  recoveryController = null
  recoveryPending.value = false
  recoveryLoading.value = false
  recoverySession.value = createRecoverySession(session.trackingId, session.action, 'UNKNOWN')
  resetCheck()
}

function preserveManagementLockAfterClear(): void {
  const session = managementSession.value
  const unresolved = Boolean(
    managementLoading.value || (session && (session.state === 'IN_FLIGHT' || managementSessionKeepsIntent(session))),
  )
  if (!unresolved || !managementIntent || !session) {
    resetManagement()
    return
  }
  managementSequence += 1
  managementController?.abort()
  managementController = null
  managementPending.value = false
  managementLoading.value = false
  managementReplayBlocked.value = true
  managementConfigSnapshot = null
  managementSession.value = createManagementSession(
    session.trackingId, session.action, session.targetScope, 'UNKNOWN', true,
  )
}

/** A clear/reconnect never releases an old write; only a confirmed recovery does. */
function releaseSourceIntentLocks(trackingId: string): void {
  const write = writeSession.value
  if (write?.trackingId === trackingId && writeSessionKeepsIntent(write.state)) resetWrite()
  const management = managementSession.value
  if (management?.trackingId === trackingId && managementSessionKeepsIntent(management)) resetManagement()
}

function cancelSync(): void {
  syncSequence += 1
  syncController?.abort()
  syncController = null
  syncPending.value = false
  syncLoading.value = false
}

function hasUnknownCapability(capabilities: CapabilityResult): boolean {
  return capabilities.probe_status !== 'VERIFIED'
    || projectCapabilitySummary(capabilities).some((entry) => entry.state === 'UNKNOWN')
}

async function syncTracking(): Promise<void> {
  // One sync intent at a time: the guard is taken before the confirmation
  // dialog opens so a second click cannot supersede a pending intent.
  if (syncPending.value || syncLoading.value) return
  // Issue #86: the saved connection is enough; the server validates it.
  if (!savedRef.value) return
  syncPending.value = true
  let confirmed = false
  try {
    confirmed = (await confirmDialog.value?.confirm({
      title: '同步 Auto Bangumi',
      message: '将使用已保存的 Auto Bangumi 连接读取外部追番并更新本地安全摘要，是否继续？',
      confirmLabel: '确认同步',
      cancelLabel: '取消',
    })) ?? false
  } finally {
    syncPending.value = false
  }
  if (!confirmed || !savedRef.value) return
  const config = savedRef.value
  const sequence = ++syncSequence
  const controller = new AbortController()
  syncController?.abort()
  syncController = controller
  loading.value = false
  syncLoading.value = true
  syncMessage.value = ''
  try {
    const body: SyncBody = { connection_ref: config.connection_ref!, configuration_revision: config.configuration_revision, confirm: true }
    const result = await api.post<SyncResult>('/api/v1/tracking/sync', { body, signal: controller.signal })
    // Only a newer sync intent or an explicit connection reset can discard this
    // result; list refreshes use their own sequence and revision guard.
    if (sequence !== syncSequence) return
    const incomplete = result.sync_status !== 'COMPLETE'
    const degraded = incomplete || hasUnknownCapability(result.capabilities)
    syncSummary.value = result.summary
    refreshConnectionStatus()
    if (!degraded && result.items) {
      // Writing the synced revision invalidates list responses already in flight.
      writeGeneration += 1
      items.value = result.items
      detailRevision.value += 1
      syncSelection(true)
      // Issue #88: strangers in Auto Bangumi are counted, never imported.
      syncMessage.value = result.summary.ignored
        ? `同步完成：检查 ${result.summary.checked} 条，新增 ${result.summary.created} 条，更新 ${result.summary.updated} 条；忽略 ${result.summary.ignored} 条不属于 MiGuOrca 管理的外部订阅。`
        : `同步完成：检查 ${result.summary.checked} 条，新增 ${result.summary.created} 条，更新 ${result.summary.updated} 条。`
    } else if (incomplete) {
      syncMessage.value = result.sync_status === 'PARTIAL'
        ? '同步部分完成，已保留原有本地列表；可重连或再次同步。'
        : '同步未完成，已保留原有本地列表；可重连、重探测或再次同步。'
    } else {
      syncMessage.value = '同步已完成，但当前连接能力未知，已降级为只读并保留原有本地列表；可重新探测或再次同步。'
    }
    savedState.value = { ...config, capabilities: result.capabilities }
  } catch (error) {
    if (sequence !== syncSequence) return
    syncMessage.value = '同步 Auto Bangumi 失败，已保留原有本地列表；可重连或再次同步。'
    void error
  } finally {
    if (sequence === syncSequence) {
      syncLoading.value = false
      if (syncController === controller) syncController = null
    }
  }
}

function resetWrite(): void {
  writeSequence += 1
  writeController?.abort()
  writeController = null
  writeIntent = null
  writePending.value = false
  writeLoading.value = false
  writeSession.value = null
  writeReplayBlocked.value = false
  writeConfigSnapshot = null
  // Issue #184: a spent write intent also spends the resubmit confirmation.
  resetResubmit(true)
  blockedIntentNotice.value = null
}

function resetRecovery(): void {
  recoverySequence += 1
  recoveryController?.abort()
  recoveryController = null
  recoveryPending.value = false
  recoveryLoading.value = false
  recoverySession.value = null
  blockedIntentNotice.value = null
}

function resetManagement(): void {
  managementSequence += 1
  managementController?.abort()
  managementController = null
  managementIntent = null
  managementPending.value = false
  managementLoading.value = false
  managementSession.value = null
  managementReplayBlocked.value = false
  managementConfigSnapshot = null
  blockedIntentNotice.value = null
}

/**
 * Read-back after an external write or a recovery (US-310, US-312).
 *
 * The list already converged from the returned tracking; only the inspector
 * detail is re-read, so an action never blanks the list.  When the round trip
 * told us nothing authoritative (409 conflict, unreadable result) the list is
 * re-read too, because the returned summary cannot be trusted in those paths.
 */
async function recheckAfterAction(trackingId: string, refreshList = false): Promise<void> {
  if (refreshList) await loadList(true)
  if (selectedTrackingId.value !== trackingId) return
  await inspector.value?.reload()
}

/**
 * Run one bounded read-only confirmation of a pending submission (issue #183).
 *
 * The request carries only the revision the user is looking at; the server
 * resolves the original operation's saved connection, so nothing here can
 * rebind it.  A stale revision is a 409 before any read, and every read-only
 * business outcome converges the list and re-reads the detail.
 */
async function runTrackingCheck(payload: { item: TrackingItem; automatic: boolean }): Promise<void> {
  const trackingId = payload.item.tracking_id
  const revision = payload.item.revision
  if (typeof revision !== 'number') return
  if (payload.automatic && !autoCheckArmed.value) return
  if (checkLoading.value) return
  if (otherItemIntentOwner(trackingId)) {
    if (!payload.automatic) blockIntent(trackingId)
    return
  }
  if (payload.automatic) {
    // The owed automatic check is consumed only when one is actually started,
    // so a refused/blocked attempt is retried rather than silently dropped, and
    // a check that persists a new revision never re-triggers itself.
    autoCheckArmed.value = false
  }
  blockedIntentNotice.value = null
  const sequence = ++checkSequence
  const controller = new AbortController()
  checkController?.abort()
  checkController = controller
  checkLoading.value = true
  checkSession.value = createCheckSession(trackingId, 'IN_FLIGHT', null, revision)
  try {
    const storageDir = storageQuery().storage_dir
    const body: TrackingCheckBody = {
      expected_revision: revision,
      ...(storageDir ? { storage_dir: storageDir } : {}),
    }
    const result = await api.post<TrackingCheckResult>(TRACKING_CHECK_ENDPOINT, {
      path: { tracking_id: trackingId }, body, signal: controller.signal,
    })
    if (sequence !== checkSequence) return
    applyReturnedTracking(result.tracking)
    const session = projectCheckResult(trackingId, result, revision)
    checkSession.value = session
    // Issue #183 review: once the exact object is proven, the pending submit is
    // no longer ambiguous, so its page-level intent lock is released here —
    // otherwise the stale intent would keep blocking every other record.
    if (session.state === 'CONFIRMED') releaseSettledSubmissionIntent(trackingId)
    await recheckAfterAction(trackingId, true)
  } catch (error) {
    if (sequence !== checkSequence) return
    const apiError = toApiError(error)
    if (apiError.cancelled && !apiError.httpError) return
    checkSession.value = apiError.status === 409
      ? createCheckSession(trackingId, 'CONFLICT', null, revision)
      : createCheckSession(trackingId, 'UNKNOWN', null, revision)
    await recheckAfterAction(trackingId, true)
  } finally {
    if (sequence === checkSequence) {
      checkLoading.value = false
      if (checkController === controller) checkController = null
    }
  }
}

/**
 * Run one risk-confirmed single manual resubmission (issue #184).
 *
 * Two steps, exactly as the server defines them:
 *
 * 1. ``confirm=false`` — the same bounded read-only check as 重新检查, through the
 *    Auto Bangumi instance the pending operation was bound to. A proven
 *    subscription converges the record with zero external writes; a proven
 *    refusal (write may still be running, unusable connection/version, plan not
 *    submittable) is displayed with its own reason and never opens a dialog.
 * 2. only a still-unresolved outcome that the server explicitly offered may open
 *    the fixed risk confirmation. Cancelling sends nothing at all; confirming
 *    sends the exact published binding once (the server derives the operation
 *    key from it) and reports through the ordinary submit result panel.
 */
async function runTrackingResubmit(payload: { item: TrackingItem }): Promise<void> {
  const trackingId = payload.item.tracking_id
  if (resubmitLoading.value || resubmitPending.value || writeLoading.value) return
  if (checkLoading.value) return
  if (otherItemIntentOwner(trackingId)) {
    blockIntent(trackingId)
    return
  }
  // A confirmation that was already sent and is still unresolved is replayed
  // with the identical body: re-checking or re-minting could create a second
  // subscription (the confirmation binding is the idempotency identity).
  const locked = resubmitIntent && resubmitIntent.trackingId === trackingId ? resubmitIntent : null
  if (locked) {
    if (writeReplayBlocked.value) {
      blockReplay(trackingId)
      return
    }
    await sendResubmitConfirmation(trackingId, locked.body, null, null)
    return
  }
  const revision = payload.item.revision
  if (typeof revision !== 'number') return
  blockedIntentNotice.value = null
  const sequence = ++resubmitSequence
  const controller = new AbortController()
  resubmitController?.abort()
  resubmitController = controller
  resubmitLoading.value = true
  resubmitSession.value = createResubmitSession(trackingId, 'IN_FLIGHT', null, revision)
  try {
    const storageDir = storageQuery().storage_dir
    const body: TrackingResubmitBody = {
      expected_revision: revision,
      confirm: false,
      ...(storageDir ? { storage_dir: storageDir } : {}),
    }
    const result = await api.post<TrackingResubmitResult>(TRACKING_RESUBMIT_ENDPOINT, {
      path: { tracking_id: trackingId }, body, signal: controller.signal,
    })
    if (sequence !== resubmitSequence) return
    applyReturnedTracking(result.tracking)
    const session = projectResubmitOffer(trackingId, result, revision)
    resubmitSession.value = session
    if (session.state === 'CONFIRMED') {
      // The read-only phase proved the object: the pending submission is settled
      // and releaseSettledSubmissionIntent also drops the resubmit confirmation.
      releaseSettledSubmissionIntent(trackingId)
      await recheckAfterAction(trackingId, true)
      return
    }
    if (session.state === 'BLOCKED') {
      await recheckAfterAction(trackingId, true)
      return
    }
    const binding = resubmitBindingFrom(result)
    if (!binding) {
      // An unresolved check without a published binding is never an
      // authorization: no dialog, no write, just the honest result.
      await recheckAfterAction(trackingId, true)
      return
    }
    // The risk confirmation is the *only* gate before the one new submission.
    resubmitLoading.value = false
    resubmitPending.value = true
    let confirmed = false
    try {
      confirmed = (await confirmDialog.value?.confirm({
        title: '重新提交到 Auto Bangumi？',
        message: resubmitRiskMessage(session.reason),
        itemsLabel: '风险说明',
        items: [
          '原提交结果尚未确认：Auto Bangumi 可能已经创建了该订阅并开始处理资源。',
          '重新提交会以新操作再次创建订阅；MiGuOrca 无法去重，也不会改写或删除原提交记录。',
        ],
        confirmLabel: '确认重新提交',
        cancelLabel: '取消',
      })) ?? false
    } finally {
      resubmitPending.value = false
    }
    if (!confirmed) {
      // Cancelling sends zero requests: no new operation, no external write.
      resubmitSession.value = createResubmitSession(trackingId, 'CANCELLED', session.reason, revision)
      return
    }
    await sendResubmitConfirmation(
      trackingId,
      createResubmitConfirmationBody(binding, storageDir),
      session.reason,
      revision,
    )
  } catch (error) {
    if (sequence !== resubmitSequence) return
    const apiError = toApiError(error)
    if (apiError.cancelled && !apiError.httpError) return
    // Every documented 409 is raised before the external boundary, so nothing
    // was resubmitted; the proven reason is stated and the page re-reads the
    // server truth instead of guessing a generic cause.
    resubmitSession.value = apiError.status === 409
      ? createResubmitSession(
          trackingId, 'CONFLICT', null, revision, resubmitConflictMessage(apiError.type),
        )
      : createResubmitSession(trackingId, 'UNKNOWN', null, revision)
    await recheckAfterAction(trackingId, true)
  } finally {
    if (sequence === resubmitSequence) {
      resubmitLoading.value = false
      if (resubmitController === controller) resubmitController = null
    }
  }
}

/**
 * Send the one confirmation of a risk-confirmed resubmission (issue #184).
 *
 * ``body`` is the exact binding the server published (or the identical body of an
 * unresolved earlier attempt). The outcome is projected through the shared submit
 * session so the page shows one submit contract, arms the ordinary automatic
 * read-only check, and keeps the confirmation body only while the external result
 * is still unproven.
 */
async function sendResubmitConfirmation(
  trackingId: string,
  body: TrackingResubmitBody,
  reason: TrackingCheckReason | null,
  sourceRevision: number | null,
): Promise<void> {
  if (writeLoading.value || writePending.value) return
  resubmitIntent = { trackingId, body }
  resubmitLoading.value = true
  // The write panel owns the outcome; the pre-write panel is spent.
  resubmitSession.value = null
  const sequence = ++writeSequence
  const controller = new AbortController()
  writeController?.abort()
  writeController = controller
  writeLoading.value = true
  writeSession.value = createWriteSession(trackingId, 'SUBMIT', 'IN_FLIGHT')
  try {
    const result = await api.post<TrackingResubmitResult>(TRACKING_RESUBMIT_ENDPOINT, {
      path: { tracking_id: trackingId }, body, signal: controller.signal,
    })
    if (sequence !== writeSequence) return
    applyReturnedTracking(result.tracking)
    const session = projectWriteOutcome(trackingId, 'SUBMIT', result, null)
    writeSession.value = session
    if (!writeSessionKeepsIntent(session.state)) resubmitIntent = null
    else autoCheckArmed.value = true
    await recheckAfterAction(trackingId)
    await presentWriteFeedback(session)
  } catch (error) {
    if (sequence !== writeSequence) return
    const apiError = toApiError(error)
    if (apiError.cancelled && !apiError.httpError) return
    if (apiError.status === 409) {
      resubmitIntent = null
      writeIntent = null
      writeSession.value = createWriteConflictSession(trackingId, 'SUBMIT', apiError.type)
      resubmitSession.value = createResubmitSession(trackingId, 'CONFLICT', reason, sourceRevision)
      await recheckAfterAction(trackingId, true)
      return
    }
    if (isDefiniteWriteRejection(apiError)) {
      resubmitIntent = null
      writeSession.value = createWriteSession(trackingId, 'SUBMIT', 'REJECTED')
      await recheckAfterAction(trackingId, true)
      return
    }
    // Network/timeout/unreadable: the external result is unknown, so the exact
    // confirmation keeps its body and is only ever replayed identically.
    writeSession.value = createWriteSession(trackingId, 'SUBMIT', 'UNKNOWN')
    await recheckAfterAction(trackingId, true)
  } finally {
    if (sequence === writeSequence) {
      writeLoading.value = false
      if (writeController === controller) writeController = null
    }
    resubmitLoading.value = false
  }
}

/**
 * Release a pending *submission* intent that a read-only check has just proven
 * settled (issue #183 review). Only the submit-family session is released: a
 * recovery or management lock that is still unresolved stays locked, and the
 * operation/audit history on the server is untouched.
 */
function releaseSettledSubmissionIntent(trackingId: string): void {
  if (writeSession.value?.trackingId !== trackingId) return
  if (writeSession.value.state !== 'VERIFYING_EXTERNAL'
    && writeSession.value.state !== 'RECOVERY_REQUIRED'
    && writeSession.value.state !== 'UNKNOWN') return
  writeIntent = null
  writeSession.value = null
  resubmitIntent = null
}

function resetCheck(): void {
  checkSequence += 1
  checkController?.abort()
  checkController = null
  checkLoading.value = false
  checkSession.value = null
  autoCheckArmed.value = false
}

/**
 * Drop one resubmission interaction's *display* (issue #184).
 *
 * ``clearIntent`` additionally forgets the exact confirmation body. It is only
 * ever passed for a spent intent: an unresolved confirmation keeps its body so a
 * retry replays the identical binding instead of minting a second operation.
 */
function resetResubmit(clearIntent = false): void {
  resubmitSequence += 1
  resubmitController?.abort()
  resubmitController = null
  resubmitLoading.value = false
  resubmitPending.value = false
  resubmitSession.value = null
  if (clearIntent) resubmitIntent = null
}

// -- explicit batch submit (issue #87) --------------------------------------
// A batch is a user-visible selection of *independent* reliable submissions:
// the page owns the single confirmation and the request, every entry keeps its
// own revision and opaque key, and filtering never clears the selection.
const TRACKING_BATCH_SUBMIT_ENDPOINT = '/api/v1/tracking/batch-submit'
// Unified plan delete (issue #92): the page owns the single request and result.
// Issue #98: the entry button opens a mode choice; only the choice writes.
const submitModeOpen = ref(false)
const submitModePending = ref<{ action: TrackingAction; item: TrackingItem } | null>(null)
const submissionMode = ref<SubmissionMode | null>(null)

const SUBMISSION_CHOICE_ACTIONS = new Set(['SUBMIT', 'RETRY'])

function isSubmissionChoiceAction(code: string): boolean {
  return SUBMISSION_CHOICE_ACTIONS.has(code)
}

function chooseSubmissionMode(mode: SubmissionMode): void {
  const pending = submitModePending.value
  // One choice, one request: a second click can neither pick another mode nor
  // start a concurrent submission, because the dialog is gone immediately.
  if (!pending || submissionMode.value) return
  submissionMode.value = mode
  submitModeOpen.value = false
  void runTrackingWrite(pending)
}

function closeSubmissionModeChoice(): void {
  submitModeOpen.value = false
  submitModePending.value = null
  submissionMode.value = null
}

function cancelSubmissionMode(): void {
  // Cancelling sends nothing at all.
  closeSubmissionModeChoice()
}

// The dialog stays open (all actions disabled, the chosen one loading) until the
// page-level write settles, then closes on every path.
watch(writeLoading, (loading) => {
  if (loading) return
  closeSubmissionModeChoice()
})

const planDeleteSession = ref<TrackingPlanDeleteSession | null>(null)
let planDeleteSequence = 0

async function openReuseJourney(): Promise<void> {
  // The safe suggestion is already published in memory by the inspector; the
  // add journey consumes it and still demands a real MiKan collection.
  await router.push(routeLocation('add'))
}

async function runPlanDelete(payload: {
  item: TrackingItem
  deleteExternal: boolean
}): Promise<void> {
  const config = savedRef.value
  // Issue #96: a purely local delete needs no Auto Bangumi connection at all;
  // only the optional external delete requires the saved connection.
  if (payload.deleteExternal && !config?.connection_ref) return
  const trackingId = payload.item.tracking_id
  const sequence = ++planDeleteSequence
  planDeleteSession.value = createPlanDeleteSession(trackingId, 'IN_FLIGHT')
  try {
    const storageDir = storageQuery().storage_dir
    const result = await api.post<PlanDeleteResult>(
      '/api/v1/tracking/items/{tracking_id}/delete-plan',
      {
        path: { tracking_id: trackingId },
        body: {
          confirm: true,
          delete_external: payload.deleteExternal,
          idempotency_key: makeOpaqueKey(),
          ...(payload.deleteExternal && config
            ? {
                connection_ref: config.connection_ref,
                configuration_revision: config.configuration_revision,
              }
            : {}),
          ...(storageDir ? { storage_dir: storageDir } : {}),
        },
      },
    )
    if (sequence !== planDeleteSequence) return
    const state = result?.outcome === 'DELETED'
      ? 'DELETED'
      : result?.outcome === 'EXTERNAL_FAILED' ? 'EXTERNAL_FAILED' : 'EXTERNAL_UNKNOWN'
    planDeleteSession.value = createPlanDeleteSession(trackingId, state)
    if (state === 'DELETED') {
      notification.show(
        'success',
        '追番方案已删除',
        payload.deleteExternal
          ? '已同时删除受控外部订阅；已下载媒体保留。'
          : 'Auto Bangumi 中的订阅继续运行，MiGuOrca 不再管理它。',
      )
      if (selectedTrackingId.value === trackingId) selectedTrackingId.value = ''
      await loadList(true)
      return
    }
    await recheckAfterAction(trackingId, true)
  } catch (error) {
    if (sequence !== planDeleteSequence) return
    const apiError = toApiError(error)
    if (apiError.cancelled && !apiError.httpError) return
    planDeleteSession.value = createPlanDeleteSession(
      trackingId,
      apiError.status === 409 ? 'EXTERNAL_FAILED' : 'EXTERNAL_UNKNOWN',
    )
    await recheckAfterAction(trackingId, true)
  }
}

const batchMode = ref(false)
const batchSubmissionMode = ref<SubmissionMode | null>(null)
const batchSelection = ref<TrackingBatchSelection>(EMPTY_BATCH_SELECTION)
const batchPending = ref(false)
const batchLoading = ref(false)
const batchOutcome = ref<TrackingBatchOutcome | null>(null)
const batchNotice = ref('')
let batchSequence = 0

const batchSummary = computed(() => (
  batchSelectionSummary(batchSelection.value, filteredItems.value)
))
const batchSkippedNotice = computed(() => {
  const reasons = Object.values(batchSelection.value.skipped)
  if (!reasons.length) return ''
  const counts = new Map<string, number>()
  for (const reason of reasons) counts.set(reason, (counts.get(reason) ?? 0) + 1)
  const detail = [...counts].map(([reason, count]) => `${reason}（${count} 条）`).join('；')
  return `已跳过 ${reasons.length} 条不可提交记录：${detail}。`
})

function toggleBatchMode(): void {
  batchMode.value = !batchMode.value
  batchSelection.value = clearBatchSelection()
  batchOutcome.value = null
  batchNotice.value = ''
}

function toggleRow(trackingId: string): void {
  batchSelection.value = toggleBatchSelection(batchSelection.value, trackingId)
}

function selectAllCurrent(): void {
  batchSelection.value = selectAllBatch(filteredItems.value)
}

function clearSelection(): void {
  batchSelection.value = clearBatchSelection()
}

function titleFor(trackingId: string): string {
  return items.value.find((item) => item.tracking_id === trackingId)?.title || '未命名番剧'
}

/**
 * Run one explicitly confirmed batch.
 *
 * Each entry is sent once with its own revision and opaque key. A transport
 * failure keeps the selection untouched and resends nothing; a persisted
 * per-entry result converges the success list and leaves every failed or
 * unresolved row selected for the user's next explicit action.
 */
const batchModeOpen = ref(false)

/**
 * AC 9: the local pre-check result lives in its own dialog; external success,
 * failure and unknown results stay in the batch result area.
 */
async function showSkippedPlans(title: string, skipped: readonly SkippedBatchEntry[]): Promise<void> {
  if (!skipped.length) return
  await confirmDialog.value?.confirm({
    title,
    message: '以下所选方案未通过本地预检，本次不会提交到 Auto Bangumi：',
    items: skipped.map((entry) => `${entry.title}：${entry.reason}`),
    itemsLabel: '未提交的方案',
    confirmLabel: '知道了',
    cancelLabel: '关闭',
  })
}


/** Issue #100 AC 1: the entry opens one mode choice for the whole batch. */
function runBatchSubmit(): void {
  if (batchPending.value || batchLoading.value) return
  if (!savedRef.value?.connection_ref) return
  if (!batchSummary.value.selected) return
  batchModeOpen.value = true
}

function chooseBatchSubmissionMode(mode: SubmissionMode): void {
  const config = savedRef.value
  if (!config?.connection_ref || batchSubmissionMode.value) return
  batchSubmissionMode.value = mode
  batchModeOpen.value = false
  void performBatchSubmit()
}

function cancelBatchSubmissionMode(): void {
  batchModeOpen.value = false
}

async function performBatchSubmit(): Promise<void> {
  if (batchPending.value || batchLoading.value) return
  const config = savedRef.value
  if (!config?.connection_ref) return
  if (!batchSummary.value.selected) return

  // One choice, one batch: the mode is spent here so a later batch cannot
  // silently reuse it.
  const submissionMode = batchSubmissionMode.value ?? undefined
  batchSubmissionMode.value = null
  // AC 5/6/9: the local pre-check result is stated before (and separately from)
  // any external result, and a fully skipped batch sends nothing at all.
  const skipped = skippedBatchEntries(batchSelection.value, items.value)
  const body = buildBatchSubmitBody(
    batchSelection.value,
    items.value,
    {
      connection_ref: config.connection_ref,
      configuration_revision: config.configuration_revision,
    },
    storageQuery().storage_dir,
    submissionMode,
  )
  if (!body) {
    // AC 6: a fully skipped batch proves zero Auto Bangumi requests.
    batchOutcome.value = null
    batchNotice.value = '没有可提交的方案'
    void showSkippedPlans('没有可提交的方案', skipped)
    return
  }
  if (skipped.length) {
    // AC 4: the information dialog never gates the run — the submittable plans
    // start immediately, with no second confirmation.
    batchNotice.value = '部分方案未提交'
    void showSkippedPlans('部分方案未提交', skipped)
  }

  const sequence = ++batchSequence
  batchLoading.value = true
  batchNotice.value = ''
  batchOutcome.value = null
  try {
    const result = await api.post<BatchResult>(TRACKING_BATCH_SUBMIT_ENDPOINT, { body })
    if (sequence !== batchSequence) return
    const outcome = projectBatchOutcome(result)
    batchOutcome.value = outcome
    batchSelection.value = selectionAfterBatch(batchSelection.value, outcome)
    const unknown = outcome.unresolved.length
    batchNotice.value = `本次批量提交：成功 ${outcome.succeeded} 条，失败 ${outcome.failed} 条${unknown ? `，其中 ${unknown} 条结果未知需先恢复` : ''}。`
    if (outcome.succeeded) {
      notification.show('success', '批量提交完成', `已在 Auto Bangumi 创建 ${outcome.succeeded} 条外部订阅。`)
    }
    await loadList(true)
  } catch (error) {
    if (sequence !== batchSequence) return
    const apiError = toApiError(error)
    if (apiError.cancelled && !apiError.httpError) return
    // Nothing was resolved: keep the selection and never resend on our own.
    batchNotice.value = '批量提交请求未能确认送达，已保留当前选择；请核对连接后重新确认。'
  } finally {
    if (sequence === batchSequence) batchLoading.value = false
  }
}

/**
 * Route one submit result to its fixed channel (issue #86).
 *
 * A blocking connection/credential/version problem takes over the page as an
 * actionable dialog with a settings deep link; success is a lightweight global
 * notice; every other failure keeps its copy on the affected record, where the
 * recovery controls already live. The server sends only a category code — all
 * user-facing sentences are fixed here.
 */
async function presentWriteFeedback(session: TrackingWriteSession): Promise<void> {
  if (session.state === 'ACTIVE') {
    notification.show('success', '提交成功', '已在 Auto Bangumi 创建外部订阅。')
    return
  }
  const category = session.failureCategory
  if (!category || WRITE_FAILURE_PRESENTATIONS[category].channel !== 'dialog') return
  const presentation = WRITE_FAILURE_PRESENTATIONS[category]
  const openSettings = (await confirmDialog.value?.confirm({
    title: presentation.title,
    message: presentation.message,
    confirmLabel: '前往设置',
    cancelLabel: '关闭',
  })) ?? false
  if (openSettings) await router.push(routeLocation('settings'))
}

/**
 * Run one explicit submit-family external write (US-310, US-311).
 *
 * ``SUBMIT`` and ``RETRY`` share this single path: the endpoint, the impact
 * confirmation and the result projection are all bound to the server-computed
 * action code, so a retry can never be sent with submit copy (or the reverse).
 */
async function runTrackingWrite(payload: { action: TrackingAction; item: TrackingItem }): Promise<void> {
  const trackingId = payload.item.tracking_id
  // A confirmation is already open, or an external write/recovery is already
  // running: one page-level intent at a time, and no second dialog can displace
  // the first (D38-09.4: an active recovery blocks submit/retry).
  if (writePending.value || writeLoading.value || recoveryPending.value || recoveryLoading.value
    || managementPending.value || managementLoading.value
    || resubmitPending.value || resubmitLoading.value) return
  if (writeReplayBlocked.value) {
    blockReplay(trackingId)
    return
  }
  // Issue #86: a saved Auto Bangumi connection is all an external write needs.
  // The server re-validates the connection, credentials, exact version and write
  // capability inside the same request and fails closed, so a settings-page
  // probe is never a precondition for submitting.
  if (!savedRef.value) return
  const sameItemRecovery = recoverySession.value?.trackingId === trackingId
    && recoverySessionKeepsLock(recoverySession.value.state)
  const sameItemManagement = managementSession.value?.trackingId === trackingId
    && managementSessionKeepsIntent(managementSession.value)
  if (sameItemRecovery || sameItemManagement) {
    blockIntent(trackingId)
    return
  }
  // Any *other* record still holding the page's single unresolved intent refuses
  // this request — with a stated next step instead of a silent no-op.
  if (otherItemIntentOwner(trackingId)) {
    blockIntent(trackingId)
    return
  }
  const requested = payload.action.code
  // Only the submit-family actions this page can actually send are accepted;
  // every other server action waits for its own story.
  if (!isWriteActionCode(requested)) return
  // A locked intent still owns the single opaque key for this item. Replaying it
  // under a different action would send something the user did not ask for, and
  // minting a new key while the external result is unresolved could create a
  // second subscription — so a mismatching action does nothing but explain why.
  const locked = writeIntent && writeSession.value?.trackingId === trackingId ? writeIntent : null
  if (locked && locked.action !== requested) {
    blockIntent(trackingId)
    return
  }
  // Issue #98 AC 2: the entry only opens the mode choice.
  if (isSubmissionChoiceAction(requested) && submissionMode.value === null) {
    submitModePending.value = payload
    submitModeOpen.value = true
    return
  }
  const action: TrackingWriteActionCode = requested

  // The user is now replaying the one locked request (or starting a fresh one
  // once nothing is pending): the refusal notice has served its purpose.
  blockedIntentNotice.value = null
  writePending.value = true
  // Choosing the submission mode is the impact confirmation for SUBMIT/RETRY;
  // every other write action keeps the shared confirm dialog.
  let confirmed = submissionMode.value !== null
  try {
    if (!confirmed) {
      confirmed = (await confirmDialog.value?.confirm({
        ...WRITE_ACTION_CONFIRMATIONS[action], cancelLabel: '取消',
      })) ?? false
    }
  } finally {
    writePending.value = false
  }
  // Cancelling the impact confirmation sends zero requests.
  if (!confirmed || !savedRef.value) return

  // One opaque key per confirmation.  Only an indeterminate earlier result keeps
  // its locked intent, so a transport retry reuses the very same key (and the
  // very same revision binding) instead of risking a second external
  // subscription; a definite failure always mints a fresh one.  Issue #86: the
  // saved connection is enough to submit — the server performs the authoritative
  // connection/authentication/version/capability check in the same request.
  const intent = locked ?? createTrackingActionIntent(payload.item, payload.action)
  if (!intent) return
  const requestConfig = locked ? writeConfigSnapshot : savedRef.value
  if (!requestConfig) {
    blockReplay(trackingId)
    return
  }
  writeIntent = intent
  // Captured before the request: the settle watch clears the ref, and the
  // result copy still needs to know which mode this attempt used (issue #101).
  const requestedMode = submissionMode.value
  if (!locked) writeConfigSnapshot = { ...requestConfig }
  const sequence = ++writeSequence
  const controller = new AbortController()
  writeController?.abort()
  writeController = controller
  writeLoading.value = true
  writeSession.value = createWriteSession(trackingId, action, 'IN_FLIGHT')
  try {
    const storageDir = storageQuery().storage_dir
    const body: TrackingWriteBody = {
      expected_revision: intent.expectedRevision,
      idempotency_key: intent.idempotencyKey,
      confirm: true,
      ...(submissionMode.value ? { submission_mode: submissionMode.value } : {}),
      connection_ref: requestConfig.connection_ref!,
      configuration_revision: requestConfig.configuration_revision,
      ...(storageDir ? { storage_dir: storageDir } : {}),
    }
    const result = await api.post<TrackingWriteResult>(WRITE_ACTION_ENDPOINTS[action], {
      path: { tracking_id: trackingId }, body, signal: controller.signal,
    })
    if (sequence !== writeSequence) return
    // The returned tracking converges the list row without a second list read.
    closeSubmissionModeChoice()
    applyReturnedTracking(result.tracking)
    const session = projectWriteOutcome(trackingId, action, result, requestedMode)
    writeSession.value = session
    if (!writeSessionKeepsIntent(session.state)) writeIntent = null
    // Issue #183: a submit whose result is still unproven owes one automatic
    // bounded read-only check, which is exactly what the submit area then shows.
    else autoCheckArmed.value = true
    await recheckAfterAction(trackingId)
    await presentWriteFeedback(session)
  } catch (error) {
    if (sequence !== writeSequence) return
    const apiError = toApiError(error)
    if (apiError.cancelled && !apiError.httpError) return
    if (apiError.status === 409) {
      // Every documented 409 (revision / idempotency / state / in-flight) is
      // raised before the external boundary, so nothing was submitted. The
      // locked intent is spent, the error body carries no authoritative
      // tracking, so re-read both and require a new explicit confirmation —
      // nothing is ever resent on the user's behalf.
      writeIntent = null
      writeSession.value = createWriteConflictSession(trackingId, action, apiError.type)
      await recheckAfterAction(trackingId, true)
      return
    }
    if (isDefiniteWriteRejection(apiError)) {
      // D38-08.5: a documented JSON 400/404 is a definite refusal raised before
      // the external boundary — Auto Bangumi was never written. This is *not*
      // "结果未知": the intent is released (so the page-level write lock no
      // longer blocks other items, and the next confirmation mints a fresh key)
      // and the page only reads the latest state back. Nothing is ever resent.
      writeIntent = null
      writeSession.value = createWriteSession(trackingId, action, 'REJECTED')
      await recheckAfterAction(trackingId, true)
      return
    }
    // Network, timeout, non-JSON, 5xx — anything we cannot read as a definite
    // outcome: the external result is unknown. Keeping the locked intent can
    // never duplicate a subscription, so this path fails closed and only reads
    // back; it never mints a new key and never resends by itself.
    writeSession.value = createWriteSession(trackingId, action, 'UNKNOWN')
    await recheckAfterAction(trackingId, true)
  } finally {
    if (sequence === writeSequence) {
      writeLoading.value = false
      if (writeController === controller) writeController = null
    }
  }
}

/**
 * Run one explicit unknown-result recovery (US-312).
 *
 * ``RECOVER_AUTO`` is pure local: no credential, no confirmation, no external
 * call.  ``MARK_SUCCEEDED``/``MARK_FAILED`` are the user's manual conclusion and
 * are always confirmed a second time (the dialog defaults to cancel and states
 * that the user must have checked Auto Bangumi first).  ``VERIFY_EXTERNAL`` is
 * the read-only external check: it uses the saved connection generation
 * for one verification of the record's own operation and can never create an
 * external write.  Every path converges on the returned tracking and never
 * resends by itself.
 */
async function runTrackingRecovery(
  payload: { action: TrackingRecoveryActionCode; item: TrackingItem },
): Promise<void> {
  // One page-level intent at a time: a confirmation is open, or a write or
  // recovery is already running, or another item still owns the locked intent.
  if (recoveryPending.value || recoveryLoading.value || writePending.value || writeLoading.value
    || managementPending.value || managementLoading.value) return
  const requested = payload.action
  if (!isRecoveryActionCode(requested)) return
  const trackingId = payload.item.tracking_id
  // Another record's unresolved write or recovery keeps the page's single
  // intent, so this recovery is refused before it can race it (D38-09.4) — and
  // the reason is stated rather than swallowed.
  if (otherItemIntentOwner(trackingId)) {
    blockIntent(trackingId)
    return
  }
  // This record's own next step is legitimate: drop the earlier refusal notice.
  blockedIntentNotice.value = null
  const confirmation = recoveryConfirmation(requested)
  if (confirmation) {
    recoveryPending.value = true
    let confirmed = false
    try {
      confirmed = (await confirmDialog.value?.confirm({ ...confirmation, cancelLabel: '取消' })) ?? false
    } finally {
      recoveryPending.value = false
    }
    // Cancelling the recovery confirmation sends zero requests.
    if (!confirmed) return
  }
  // Read the live session *after* the confirmation: a session cleared while the
  // dialog was open must not be used (and the local actions never need one).
  const intent = createTrackingRecoveryIntent(payload.item, requested, savedState.value?.capabilities ?? null)
  if (!intent) return
  const body = createTrackingRecoverBody(
    intent.action, intent.expectedRevision, savedState.value, storageQuery().storage_dir,
  )
  // A body the page cannot build safely (external verification without the live
  // session) is not sent at all.
  if (!body) return

  const sequence = ++recoverySequence
  const controller = new AbortController()
  recoveryController?.abort()
  recoveryController = controller
  recoveryLoading.value = true
  recoverySession.value = createRecoverySession(trackingId, intent.action, 'IN_FLIGHT')
  try {
    const result = await api.post<TrackingRecoverResult>(TRACKING_RECOVER_ENDPOINT, {
      path: { tracking_id: trackingId }, body, signal: controller.signal,
    })
    if (sequence !== recoverySequence) return
    // The returned tracking converges the list row; the detail is re-read so the
    // inspector shows the recovered status and its next legitimate action.
    applyReturnedTracking(result.tracking)
    recoverySession.value = projectRecoveryOutcome(trackingId, intent.action, result)
    if (recoverySession.value.state === 'ACTIVE' || recoverySession.value.state === 'SUBMIT_FAILED') {
      releaseSourceIntentLocks(trackingId)
    }
    await recheckAfterAction(trackingId)
  } catch (error) {
    if (sequence !== recoverySequence) return
    const apiError = toApiError(error)
    if (apiError.cancelled && !apiError.httpError) return
    if (apiError.status === 409) {
      // Revision/state conflict: the recovery was refused before anything was
      // persisted, so re-read the server state and let the user confirm again.
      recoverySession.value = createRecoveryConflictSession(trackingId, intent.action)
      await recheckAfterAction(trackingId, true)
      return
    }
    if (isDefiniteWriteRejection(apiError)) {
      // A documented JSON 400/404 is decided before any state change.
      recoverySession.value = createRecoverySession(trackingId, intent.action, 'REJECTED')
      await recheckAfterAction(trackingId, true)
      return
    }
    // Anything unreadable stays indeterminate: read back, keep the recovery
    // state and never resend on the user's behalf.
    recoverySession.value = createRecoverySession(trackingId, intent.action, 'UNKNOWN')
    await recheckAfterAction(trackingId, true)
  } finally {
    if (sequence === recoverySequence) {
      recoveryLoading.value = false
      if (recoveryController === controller) recoveryController = null
    }
  }
}

/**
 * Run one explicit external management write (US-313, US-314).
 *
 * ``MODIFY``, ``SET_ENABLED`` and ``REFRESH_RSS`` share this single path.  It
 * reuses everything the submit family already guarantees: the live page
 * credential, the latest revision, an impact confirmation, one opaque key per
 * confirmation, the single page-level intent, the returned-tracking convergence
 * and a read-only read-back — never an automatic resend.  The endpoint, the
 * request body and the confirmation copy are all bound to the validated intent,
 * so an action can never send another action's request or copy.
 */
async function runTrackingManagement(payload: {
  action: TrackingAction
  item: TrackingItem
  targetScope: TrackingManagementScope
  patch: unknown
  /** Issue #91: local plan values raised with a confirmed subscription modify. */
  localPlan?: unknown
}): Promise<void> {
  const trackingId = payload.item.tracking_id
  if (managementPending.value || managementLoading.value || writePending.value || writeLoading.value
    || recoveryPending.value || recoveryLoading.value) return
  if (managementReplayBlocked.value) {
    blockReplay(trackingId)
    return
  }
  // Issue #89: a saved Auto Bangumi connection is all an external management
  // write needs. The server re-validates connection, credentials, exact version
  // and write capability in the same request and fails closed.
  if (!savedRef.value) return
  const requested = payload.action.code
  // Only the management actions this page can actually send are accepted;
  // DELETE_EXTERNAL waits for its own story and still sends zero requests.
  if (!isSendableManagementActionCode(requested)) return
  const action = requested
  const targetScope = payload.targetScope
  if (!isTrackingManagementScope(targetScope)) return
  const sameItemWrite = writeSession.value?.trackingId === trackingId
    && writeSessionKeepsIntent(writeSession.value.state)
  const sameItemRecovery = recoverySession.value?.trackingId === trackingId
    && recoverySessionKeepsLock(recoverySession.value.state)
  if (sameItemWrite || sameItemRecovery) {
    blockIntent(trackingId)
    return
  }
  // Any other record still holding the page's single unresolved intent refuses
  // this management request — with a stated reason, not a silent no-op.
  if (otherItemIntentOwner(trackingId)) {
    blockIntent(trackingId)
    return
  }

  // The page re-validates the emitted request against the current server
  // projection: the action and scope must still be offered for this revision,
  // the patch must belong to the chosen scope and the enable direction must
  // still be the one the record's own status implies. The server validates the
  // connection, credentials, version and write capability itself (issue #89).
  const projectedIntent = createTrackingManagementActionIntent(
    payload.item, action, targetScope, payload.patch, payload.localPlan,
  )
  if (!projectedIntent) return
  // A locked intent still owns the single opaque key *and* the request it was
  // confirmed with. Replaying it for a different scope, patch or direction
  // would send something the user did not ask for, and minting a new key while
  // the external result is unresolved could apply the change twice — so a
  // mismatching request is not sent, and the fixed next step is shown.
  const locked = managementIntent && managementSession.value?.trackingId === trackingId ? managementIntent : null
  if (locked && !sameManagementRequest(locked, projectedIntent)) {
    blockIntent(trackingId)
    return
  }
  const intent = locked ?? projectedIntent

  // The user is replaying the one locked request (or starting a fresh one):
  // the refusal notice has served its purpose.
  blockedIntentNotice.value = null
  managementPending.value = true
  let confirmed = false
  try {
    confirmed = (await confirmDialog.value?.confirm({
      ...managementConfirmation(intent), cancelLabel: '取消',
    })) ?? false
  } finally {
    managementPending.value = false
  }
  // Cancelling the impact confirmation sends zero requests.
  if (!confirmed || !savedRef.value) return

  const requestConfig = locked ? managementConfigSnapshot : savedRef.value
  if (!requestConfig) {
    blockReplay(trackingId)
    return
  }
  managementIntent = intent
  if (!locked) managementConfigSnapshot = { ...requestConfig }
  // A body the page cannot build safely (no server address, missing scope
  // patch, no known enable direction) is refused here, before any in-flight
  // session exists: it sends zero requests and converges on a definite failure
  // instead of leaving the panel stuck on "正在提交外部修改，请稍候…".
  const body = createTrackingManagementBody(intent, requestConfig, storageQuery().storage_dir)
  if (!body) {
    managementIntent = null
    managementSession.value = createManagementUnbuildableSession(trackingId, action, targetScope)
    await recheckAfterAction(trackingId, true)
    return
  }
  const sequence = ++managementSequence
  const controller = new AbortController()
  managementController?.abort()
  managementController = controller
  managementLoading.value = true
  managementSession.value = createManagementInFlightSession(trackingId, action, targetScope)
  try {
    const result = await api.post<TrackingManagementResult>(MANAGEMENT_ACTION_ENDPOINTS[intent.action], {
      path: { tracking_id: trackingId }, body, signal: controller.signal,
    })
    if (sequence !== managementSequence) return
    // The returned tracking converges the list row without a second list read.
    applyReturnedTracking(result.tracking)
    const session = projectManagementOutcome(trackingId, intent.action, targetScope, result)
    managementSession.value = session
    if (!managementSessionKeepsIntent(session)) managementIntent = null
    await recheckAfterAction(trackingId)
  } catch (error) {
    if (sequence !== managementSequence) return
    const apiError = toApiError(error)
    if (apiError.cancelled && !apiError.httpError) return
    if (apiError.status === 409) {
      // Every documented management 409 is raised while the operation is being
      // prepared, i.e. before the external boundary: nothing was submitted. The
      // locked intent is spent, the error body carries no authoritative
      // tracking, so re-read both and require a new explicit confirmation —
      // nothing is ever resent on the user's behalf.
      managementIntent = null
      managementSession.value = createManagementConflictSession(trackingId, action, targetScope, apiError.type)
      await recheckAfterAction(trackingId, true)
      return
    }
    if (isDefiniteWriteRejection(apiError)) {
      // A structured non-409 4xx is a definite refusal raised before the
      // external boundary, so Auto Bangumi was never touched. The intent is
      // released (other items are no longer blocked and the next confirmation
      // mints a fresh key) and the page only reads the latest state back.
      managementIntent = null
      managementSession.value = createManagementRejectedSession(trackingId, action, targetScope)
      await recheckAfterAction(trackingId, true)
      return
    }
    // Network, timeout, non-JSON, 5xx — anything we cannot read as a definite
    // verdict: the external result is unknown. Keeping the locked intent can
    // never apply the change twice, so this path fails closed and only reads
    // back; it never mints a new key and never resends by itself.
    managementSession.value = createManagementSession(trackingId, action, targetScope, 'UNKNOWN', true)
    await recheckAfterAction(trackingId, true)
  } finally {
    if (sequence === managementSequence) {
      managementLoading.value = false
      if (managementController === controller) managementController = null
    }
  }
}

onMounted(() => {
  void loadSavedConnection()
  void loadList().then(() => {
    // A legacy batch link is located against the freshly read local list, so the
    // compat read never races the tracking list it maps onto.
    if (selectedTrackingId.value) void focusSelection()
  })
})
watch(() => route.query.tracking_id, () => {
  syncSelection()
  void focusSelection()
})
watch(selectedTrackingId, (trackingId) => {
  // Reopening/refreshing an item owes it one automatic bounded check; the
  // inspector decides from the server's status + operation kind whether it is a
  // 结果待确认 submission, and the page consumes the flag here.
  autoCheckArmed.value = Boolean(trackingId)
  if (trackingId) void focusSelection()
}, { flush: 'post' })
// A refusal notice only explains a still-pending intent: once every write,
// recovery and management lock is released (a definite result, a 409, a 4xx
// refusal, a manual recovery verdict or a cleared connection) it must disappear.
watch([writeSession, recoverySession, managementSession], () => {
  if (blockedIntentNotice.value && !hasPendingIntentLock()) blockedIntentNotice.value = null
})
onBeforeUnmount(() => {
  cancelSync()
  resetWrite()
  resetRecovery()
  resetCheck()
  resetResubmit(true)
  resetManagement()
  savedState.value = null
})
</script>

<template>
  <section id="tracking-overview" class="tracking-overview" aria-labelledby="tracking-heading">
    <PanelSection title="我的追番" class="tracking-header">
      <template #actions>
        <BaseButton id="tracking-probe-saved" variant="secondary" :disabled="!savedConnection?.connection_ref" @click="probeSavedConnection">测试已保存连接</BaseButton>
        <BaseButton v-if="savedRef" id="tracking-sync" variant="secondary" :loading="syncLoading" :disabled="syncLoading || syncPending" @click="syncTracking">同步 Auto Bangumi</BaseButton>
        <BaseButton id="tracking-refresh" variant="secondary" :loading="loading" @click="refreshTracking">刷新列表</BaseButton>
        <BaseButton v-if="savedRef" id="tracking-batch-mode" variant="secondary" @click="toggleBatchMode">
          {{ batchMode ? '退出批量提交模式' : '批量提交模式' }}
        </BaseButton>
      </template>
      <p id="tracking-heading" class="tracking-lede">管理待提交任务和正在运行的追番。</p>
    </PanelSection>

    <section class="tracking-status-overview" aria-labelledby="tracking-status-heading">
      <h2 id="tracking-status-heading">状态总览</h2>
      <div class="tracking-status-cards">
        <button
          v-for="group in TRACKING_OVERVIEW_GROUPS"
          :key="group"
          type="button"
          class="tracking-status-card"
          :id="`tracking-overview-${group.toLowerCase()}`"
          :class="{ 'is-selected': statusFilter === group }"
          :aria-pressed="statusFilter === group"
          :disabled="group === 'ADDED_TO_DOWNLOAD'"
          @click="selectOverviewGroup(group)"
        >
          <span>{{ overviewLabels[group] }}</span><strong>{{ overview.byGroup[group] }}</strong>
        </button>
      </div>
      <p class="tracking-status-total" role="status">共 {{ overview.total }} 条追番记录</p>
    </section>

    <section class="tracking-workspace" aria-label="追番记录与追番详情">
      <PanelSection title="追番列表" class="tracking-list-panel">
        <template #actions><span class="tracking-count" aria-live="polite">显示 {{ filteredItems.length }} / {{ items.length }}</span></template>
        <div class="tracking-filters">
          <label for="tracking-search">搜索标题或字幕组</label>
          <BaseInput id="tracking-search" v-model="searchTerm" type="search" placeholder="输入公开标题或字幕组" />
          <label for="tracking-status-filter">状态筛选</label>
          <BaseSelect id="tracking-status-filter" v-model="statusFilter" label="状态筛选"
            :options="[{ value: '', label: '全部状态' }, ...TRACKING_STATUS_GROUPS.map((group) => ({ value: group, label: statusLabels[group] }))]" />
          <BaseButton v-if="searchTerm || statusFilter" variant="secondary" @click="clearFilters">清除筛选</BaseButton>
        </div>
        <div v-if="loading" class="tracking-list-state"><LoadingState message="正在读取追番列表…" /></div>
        <ErrorState v-else-if="failed" title="追番列表读取失败" message="暂时无法读取本地追番列表，请稍后重试。" retry-label="重试读取" @retry="loadList()" />
        <EmptyState v-else-if="!items.length" message="还没有本地追番记录。" />
        <EmptyState v-else-if="!filteredItems.length" message="没有符合当前搜索或状态筛选的记录。" />
        <div v-if="batchMode" class="tracking-batch-toolbar" aria-label="批量提交">
          <span id="tracking-batch-count" class="tracking-batch-count" role="status">
            已选 {{ batchSummary.selected }} 条<template v-if="batchSummary.hidden">（其中 {{ batchSummary.hidden }} 条不在当前筛选内）</template>
          </span>
          <BaseButton id="tracking-batch-select-all" variant="secondary" @click="selectAllCurrent">全选当前结果</BaseButton>
          <BaseButton id="tracking-batch-clear" variant="secondary" :disabled="!batchSummary.selected" @click="clearSelection">清除选择</BaseButton>
          <BaseButton id="tracking-batch-submit" :loading="batchLoading" :disabled="batchLoading || batchPending || !batchSummary.selected || !savedRef" @click="runBatchSubmit">
            提交选中方案
          </BaseButton>
          <!-- Issue 116：缺少已保存连接时批量提交可见但禁用，并就地说明下一步。 -->
          <p v-if="!savedRef" id="tracking-batch-connection-required" class="field-help" role="status">
            先在设置中连接 Auto Bangumi；缺少已保存连接时不会发起任何外部提交。
          </p>
        </div>
        <p v-if="batchMode && batchSkippedNotice" id="tracking-batch-skipped" class="tracking-batch-skipped" role="status">{{ batchSkippedNotice }}</p>
        <div v-else id="tracking-list-container" ref="listContainer" class="tracking-list" tabindex="-1" aria-label="追番记录列表">
          <button v-for="item in filteredItems" :key="item.tracking_id" type="button" class="tracking-list-item"
            :class="{ 'is-selected': selectedTrackingId === item.tracking_id, 'is-batch': batchMode }" :data-tracking-id="item.tracking_id"
            :aria-current="selectedTrackingId === item.tracking_id ? 'true' : undefined" @click="selectItem(item.tracking_id)">
            <input
              v-if="batchMode"
              type="checkbox"
              class="base-checkbox tracking-list-checkbox"
              :checked="isBatchSelected(batchSelection, item.tracking_id)"
              :disabled="Boolean(batchSkipReason(item))"
              :aria-label="`选择提交 ${item.title || '未命名番剧'}`"
              @click.stop
              @change="toggleRow(item.tracking_id)"
            >
            <span class="tracking-list-indicator" aria-hidden="true" />
            <TrackingPoster :poster-path="item.poster_path" variant="list" />
            <span class="tracking-list-copy">
              <strong>{{ item.title || '未命名番剧' }}</strong>
              <span>{{ item.season ? `第 ${item.season} 季` : '季度未设置' }}</span>
            </span>
            <span class="tracking-list-meta">
              <span>{{ item.status_label }}</span>
              <span
                v-if="formatSubmissionMode(item.submission_mode)"
                class="tracking-list-mode"
              >{{ formatSubmissionMode(item.submission_mode) }}</span>
              <small>{{ formatTrackingUpdatedAt(item.updated_at) }}</small>
            </span>
          </button>
        </div>
        <p v-if="selectedHidden" class="tracking-selection-note" role="status">当前选择被筛选条件隐藏，未自动切换记录。</p>
      </PanelSection>

      <aside class="tracking-inspector" aria-labelledby="tracking-inspector-heading">
        <TrackingInspector
          v-if="selectedItem"
          ref="inspector"
          :key="`${selectedItem.tracking_id}:${detailRevision}`"
          :tracking-id="selectedItem.tracking_id"
          :capabilities="savedState?.capabilities ?? null"
          :connection-ready="Boolean(savedRef)"
          :write-session="writeSession"
          :recovery-session="recoverySession"
          :check-session="checkSession"
          :resubmit-session="resubmitSession"
          :resubmit-pending="resubmitPending"
          :auto-check-armed="autoCheckArmed"
          :management-session="managementSession"
          :write-busy="inspectorIntentBusy"
          :intent-notice="selectedIntentNotice"
          :plan-delete-session="planDeleteSession"
          @reuse-requested="openReuseJourney"
          @plan-delete-requested="runPlanDelete"
          @tracking-updated="applyReturnedTracking"
          @write-requested="runTrackingWrite"
          @recovery-requested="runTrackingRecovery"
          @check-requested="runTrackingCheck"
          @resubmit-requested="runTrackingResubmit"
          @management-requested="runTrackingManagement"
        />
        <template v-else>
          <h2 id="tracking-inspector-heading">检查器</h2>
          <EmptyState message="选择一条追番记录查看安全检查器。" />
        </template>
      </aside>
    </section>
    <section
      v-if="batchMode && (batchOutcome || batchNotice)"
      id="tracking-batch-result"
      class="tracking-batch-result"
      aria-labelledby="tracking-batch-result-heading"
      role="status"
    >
      <h2 id="tracking-batch-result-heading">批量提交结果</h2>
      <p v-if="batchNotice" id="tracking-batch-notice" class="tracking-batch-verdict">{{ batchNotice }}</p>
      <ul v-if="batchOutcome" class="tracking-batch-entries">
        <li v-for="entry in batchOutcome.entries" :key="entry.trackingId" :class="entry.ok ? 'is-ok' : 'is-failed'">
          <strong>{{ titleFor(entry.trackingId) }}</strong>：{{ entry.message }}
        </li>
      </ul>
    </section>

    <section v-if="savedState" class="tracking-connection-status" aria-labelledby="tracking-connection-heading">
      <h2 id="tracking-connection-heading">Auto Bangumi 页面连接</h2>
      <p role="status">
        当前页面已连接 Auto Bangumi（{{ probeStatusLabel(savedState.capabilities.probe_status) }}），仅在用户明确操作时使用。
        <button type="button" class="tracking-clear-connection" @click="clearConnection">清除连接</button>
      </p>
      <dl id="tracking-capability-summary" class="tracking-capability-summary">
        <div><dt>版本</dt><dd>{{ capabilityVersionLabel(savedState.capabilities) }}</dd></div>
        <div><dt>探测状态</dt><dd>{{ probeStatusLabel(savedState.capabilities.probe_status) }}</dd></div>
        <div v-for="entry in capabilitySummary" :key="entry.key">
          <dt>{{ entry.label }}</dt><dd>{{ capabilityStateLabel(entry.state) }}</dd>
        </div>
      </dl>
      <p class="field-help">以上仅为本次探测到的安全能力摘要，管理写能力仍需服务端按当前认证与版本逐项确认。</p>
    </section>
    <p v-if="syncMessage" id="tracking-sync-status" class="tracking-sync-status" role="status">{{ syncMessage }}</p>
    <p v-if="syncSummary" class="tracking-sync-summary" role="status">本次安全同步摘要：检查 {{ syncSummary.checked }}，新增 {{ syncSummary.created }}，更新 {{ syncSummary.updated }}，未变化 {{ syncSummary.unchanged }}。</p>
    <ConfirmDialog ref="confirmDialog" />
    <TrackingSubmissionModeDialog
      :open="batchModeOpen"
      :batch-count="batchSummary.selected"
      :busy="batchLoading || batchPending"
      @choose="chooseBatchSubmissionMode"
      @cancel="cancelBatchSubmissionMode"
    />
    <TrackingSubmissionModeDialog
      :open="submitModeOpen"
      :pending-mode="submissionMode"
      :busy="writeLoading || writePending || recoveryLoading || managementLoading"
      @choose="chooseSubmissionMode"
      @cancel="cancelSubmissionMode"
    />
  </section>
</template>

<style scoped>
.tracking-overview { display: grid; gap: var(--space-5); }
.tracking-lede { margin: 0; color: var(--color-text-muted); }
.tracking-status-overview { display: grid; gap: var(--space-3); }
.tracking-status-overview h2, .tracking-inspector h2 { margin: 0; font-size: 1.05rem; }
.tracking-status-cards { display: grid; grid-template-columns: repeat(5, minmax(0, 1fr)); gap: var(--space-3); }
.tracking-status-card { display: grid; gap: .35rem; text-align: left; padding: var(--space-3); border: 1px solid var(--color-border); border-radius: var(--radius-md); background: var(--color-surface); color: var(--color-text); cursor: pointer; }
.tracking-status-card:hover, .tracking-status-card:focus-visible, .tracking-status-card.is-selected { border-color: var(--color-primary); box-shadow: 0 0 0 2px color-mix(in srgb, var(--color-primary) 18%, transparent); }
.tracking-status-card strong { font-size: 1.35rem; }
.tracking-status-total, .tracking-count { margin: 0; color: var(--color-text-muted); }
.tracking-compat-notice { margin: var(--space-3) 0 0; padding: var(--space-3); border: 1px solid var(--color-border); border-radius: var(--radius-md); background: var(--color-surface-subtle); color: var(--color-text-muted); }
/* Issue 115：状态总览与导航留在外侧；列表与详情各自在固定可用高度内滚动，
 * 展开记录或操作不会拉长整页，也不会移动另一列。 */
.tracking-workspace {
  --tracking-panel-max-height: clamp(320px, calc(100vh - 420px), 640px);
  display: grid;
  grid-template-columns: minmax(0, 3fr) minmax(18rem, 2fr);
  gap: var(--space-5);
  align-items: start;
}
.tracking-list-panel { display: flex; flex-direction: column; min-height: 0; min-width: 0; }
#tracking-list-container {
  max-height: var(--tracking-panel-max-height);
  overflow-y: auto;
  overscroll-behavior: contain;
  padding-right: var(--space-1);
}
.tracking-filters { display: grid; grid-template-columns: auto minmax(10rem, 1fr) auto minmax(8rem, .7fr) auto; gap: .65rem; align-items: center; margin-bottom: var(--space-4); }
.tracking-filters label { font-size: .85rem; font-weight: 600; }
.tracking-list { display: grid; gap: .55rem; }
.tracking-list-item { display: grid; grid-template-columns: .35rem auto minmax(0, 1fr) auto; gap: .8rem; align-items: center; width: 100%; padding: .85rem .9rem; border: 1px solid var(--color-border); border-radius: var(--radius-md); background: var(--color-surface); color: var(--color-text); text-align: left; cursor: pointer; }
.tracking-list-item:hover, .tracking-list-item:focus-visible, .tracking-list-item.is-selected { border-color: var(--color-primary); background: var(--color-surface-subtle); }
.tracking-list-item.is-selected .tracking-list-indicator { background: var(--color-primary); }
.tracking-list-indicator { align-self: stretch; min-height: 2rem; border-radius: 99px; background: var(--color-border); }
.tracking-list-item.is-batch { grid-template-columns: auto .35rem auto minmax(0, 1fr) auto; }
.tracking-list-checkbox { align-self: center; }
.tracking-batch-toolbar { display: flex; flex-wrap: wrap; align-items: center; gap: var(--space-2); padding: var(--space-3); border: 1px solid var(--color-border); border-radius: var(--radius-md); background: var(--color-surface-subtle); }
.tracking-batch-count { margin-inline-end: auto; font-weight: 600; }
.tracking-batch-skipped { margin: var(--space-2) 0 0; color: var(--color-text-muted); }
.tracking-batch-result { display: grid; gap: var(--space-2); padding: var(--space-3); border: 1px solid var(--color-border); border-radius: var(--radius-md); background: var(--color-surface); }
.tracking-batch-result h2 { margin: 0; font-size: 1.05rem; }
.tracking-batch-verdict { margin: 0; font-weight: 600; }
.tracking-batch-entries { display: grid; gap: .3rem; margin: 0; padding-left: 1.2rem; }
.tracking-batch-entries li.is-failed { color: var(--color-danger); }
.tracking-list-copy, .tracking-list-meta { display: grid; gap: .25rem; min-width: 0; }
.tracking-list-copy strong { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.tracking-list-copy span, .tracking-list-meta small { color: var(--color-text-muted); }
.tracking-list-meta { text-align: right; white-space: nowrap; }
.tracking-list-state { min-height: 8rem; }
.tracking-selection-note { margin: var(--space-3) 0 0; color: var(--color-text-muted); }
.tracking-inspector { position: sticky; top: var(--space-4); display: grid; gap: var(--space-3); min-height: 15rem; max-height: var(--tracking-panel-max-height); overflow-y: auto; overscroll-behavior: contain; padding: var(--space-4); border: 1px solid var(--color-border); border-radius: var(--radius-md); background: var(--color-surface); }
.tracking-inspector-placeholder { display: grid; gap: .5rem; padding: var(--space-4); border: 1px dashed var(--color-border); border-radius: var(--radius-md); }
.tracking-inspector-placeholder h3, .tracking-inspector-placeholder p { margin: 0; }
.tracking-connection-status { display: grid; gap: .5rem; margin: 0; padding: var(--space-3); border: 1px solid var(--color-border); border-radius: var(--radius-md); background: var(--color-surface); color: var(--color-text-muted); }
.tracking-connection-status h2 { margin: 0; font-size: 1.05rem; color: var(--color-text); }
.tracking-connection-status p { margin: 0; }
.tracking-capability-summary { display: grid; grid-template-columns: repeat(auto-fit, minmax(11rem, 1fr)); gap: .35rem var(--space-4); margin: 0; }
.tracking-capability-summary div { display: flex; justify-content: space-between; gap: .5rem; border-bottom: 1px dashed var(--color-border); }
.tracking-capability-summary dt { color: var(--color-text-muted); }
.tracking-capability-summary dd { margin: 0; font-weight: 600; color: var(--color-text); }
.tracking-clear-connection { margin-left: .5rem; color: var(--color-primary); text-decoration: underline; }
.tracking-sync-status, .tracking-sync-summary { margin: 0; color: var(--color-text-muted); }
@media (max-width: 1280px) { .tracking-workspace { grid-template-columns: minmax(0, 1.35fr) minmax(16rem, 1fr); } }
@media (max-width: 800px) {
  .tracking-status-cards { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .tracking-workspace { --tracking-panel-max-height: 320px; grid-template-columns: 1fr; }
  .tracking-inspector { position: static; }
  .tracking-filters { grid-template-columns: 1fr; }
  .tracking-filters label { margin-top: .25rem; }
  .tracking-list-meta { white-space: normal; }
}
</style>
