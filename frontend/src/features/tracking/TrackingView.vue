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
import { refreshConnectionStatus } from '@/app/stores/connectionStatus'
import { storageQuery } from '@/features/requests/requestStorage'
import {
  capabilityStateLabel,
  capabilityVersionLabel,
  createManagementSession,
  createRecoveryConflictSession,
  createRecoverySession,
  createTrackingActionIntent,
  createTrackingRecoverBody,
  createTrackingRecoveryIntent,
  createWriteConflictSession,
  createWriteSession,
  filterTrackingItems,
  isDefiniteWriteRejection,
  isRecoveryActionCode,
  isTrackingManagementScope,
  isWriteActionCode,
  managementSessionKeepsIntent,
  probeStatusLabel,
  projectCapabilitySummary,
  projectRecoveryOutcome,
  projectTrackingOverview,
  projectWriteOutcome,
  recoveryConfirmation,
  recoverySessionKeepsLock,
  sortTrackingItems,
  TRACKING_RECOVER_ENDPOINT,
  TRACKING_STATUS_GROUPS,
  WRITE_ACTION_CONFIRMATIONS,
  WRITE_ACTION_ENDPOINTS,
  writeSessionKeepsIntent,
  type TrackingAction,
  type TrackingActionIntent,
  type TrackingItem,
  type TrackingManagementScope,
  type TrackingManagementSession,
  type TrackingRecoverResult,
  type TrackingRecoveryActionCode,
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

type ListResult = NonNullable<
  operations['listTrackingItems']['responses']['200']['content']['application/json']['result']
>
type CapabilityResult = NonNullable<
  operations['probeSavedAutoBangumiCapabilities']['responses']['200']['content']['application/json']['result']
>
type SavedConnection = NonNullable<operations['getAutoBangumiConnection']['responses']['200']['content']['application/json']['result']>
type SyncBody = NonNullable<
  operations['syncTrackingItems']['requestBody']['content']['application/json']
>
type SyncResult = NonNullable<
  operations['syncTrackingItems']['responses']['200']['content']['application/json']['result']
>

const route = useRoute()
const router = useRouter()
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
  PENDING: '待处理', PROCESSING: '处理中', ACTIVE: '追番中',
  ATTENTION: '需处理', INACTIVE: '已停用/已删除',
}
const overview = computed(() => projectTrackingOverview(items.value))
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
  if (writeLoading.value || recoveryLoading.value || managementLoading.value) return true
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
  if (!unresolved || !writeIntent || !session) {
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
  if (!savedState.value) return
  syncPending.value = true
  let confirmed = false
  try {
    confirmed = (await confirmDialog.value?.confirm({
      title: '同步 Auto Bangumi',
      message: '将使用本页面已探测的连接读取外部追番并更新本地安全摘要，是否继续？',
      confirmLabel: '确认同步',
      cancelLabel: '取消',
    })) ?? false
  } finally {
    syncPending.value = false
  }
  if (!confirmed || !savedState.value) return
  const config = savedState.value
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
      syncMessage.value = `同步完成：检查 ${result.summary.checked} 条，新增 ${result.summary.created} 条，更新 ${result.summary.updated} 条。`
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
    || managementPending.value || managementLoading.value) return
  if (writeReplayBlocked.value) {
    blockReplay(trackingId)
    return
  }
  const config = savedState.value
  const capabilities = savedState.value?.capabilities
  // No page credential session means no external write at all.
  if (!config || !capabilities) return
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
  const action: TrackingWriteActionCode = requested

  // The user is now replaying the one locked request (or starting a fresh one
  // once nothing is pending): the refusal notice has served its purpose.
  blockedIntentNotice.value = null
  writePending.value = true
  let confirmed = false
  try {
    confirmed = (await confirmDialog.value?.confirm({
      ...WRITE_ACTION_CONFIRMATIONS[action], cancelLabel: '取消',
    })) ?? false
  } finally {
    writePending.value = false
  }
  // Cancelling the impact confirmation sends zero requests.
  if (!confirmed || !savedState.value) return

  // One opaque key per confirmation.  Only an indeterminate earlier result keeps
  // its locked intent, so a transport retry reuses the very same key (and the
  // very same revision binding) instead of risking a second external
  // subscription; a definite failure always mints a fresh one.
  const intent = locked ?? createTrackingActionIntent(payload.item, payload.action, undefined, savedState.value.capabilities)
  if (!intent) return
  const requestConfig = locked ? writeConfigSnapshot : savedState.value
  if (!requestConfig) {
    blockReplay(trackingId)
    return
  }
  writeIntent = intent
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
      connection_ref: requestConfig.connection_ref!,
      configuration_revision: requestConfig.configuration_revision,
      ...(storageDir ? { storage_dir: storageDir } : {}),
    }
    const result = await api.post<TrackingWriteResult>(WRITE_ACTION_ENDPOINTS[action], {
      path: { tracking_id: trackingId }, body, signal: controller.signal,
    })
    if (sequence !== writeSequence) return
    // The returned tracking converges the list row without a second list read.
    applyReturnedTracking(result.tracking)
    const session = projectWriteOutcome(trackingId, action, result)
    writeSession.value = session
    if (!writeSessionKeepsIntent(session.state)) writeIntent = null
    await recheckAfterAction(trackingId)
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
}): Promise<void> {
  const trackingId = payload.item.tracking_id
  if (managementPending.value || managementLoading.value || writePending.value || writeLoading.value
    || recoveryPending.value || recoveryLoading.value) return
  if (managementReplayBlocked.value) {
    blockReplay(trackingId)
    return
  }
  const config = savedState.value
  const capabilities = savedState.value?.capabilities
  // No page credential session means no external management write at all.
  if (!config || !capabilities) return
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
  // the live session must still prove the capability, the patch must belong to
  // the chosen scope and the enable direction must still be the one the
  // record's own status implies.
  const projectedIntent = createTrackingManagementActionIntent(
    payload.item, action, targetScope, payload.patch, capabilities,
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
  if (!confirmed || !savedState.value) return

  const requestConfig = locked ? managementConfigSnapshot : savedState.value
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
  resetManagement()
  savedState.value = null
})
</script>

<template>
  <section id="tracking-overview" class="tracking-overview" aria-labelledby="tracking-heading">
    <PanelSection title="追番管理" class="tracking-header">
      <template #actions>
        <BaseButton id="tracking-probe-saved" variant="secondary" :disabled="!savedConnection?.connection_ref" @click="probeSavedConnection">测试已保存连接</BaseButton>
        <BaseButton v-if="savedState" id="tracking-sync" variant="secondary" :loading="syncLoading" :disabled="syncLoading || syncPending || savedState.capabilities.probe_status !== 'VERIFIED'" @click="syncTracking">同步 Auto Bangumi</BaseButton>
        <BaseButton id="tracking-refresh" variant="secondary" :loading="loading" @click="refreshTracking">刷新列表</BaseButton>
      </template>
      <p id="tracking-heading" class="tracking-lede">查看本地追番状态。选择单条记录后，右侧将显示检查器入口。</p>
    </PanelSection>

    <section class="tracking-status-overview" aria-labelledby="tracking-status-heading">
      <h2 id="tracking-status-heading">状态总览</h2>
      <div class="tracking-status-cards">
        <button v-for="group in TRACKING_STATUS_GROUPS" :key="group" type="button" class="tracking-status-card"
          :class="{ 'is-selected': statusFilter === group }" :aria-pressed="statusFilter === group"
          @click="statusFilter = statusFilter === group ? '' : group">
          <span>{{ statusLabels[group] }}</span><strong>{{ overview.byGroup[group] }}</strong>
        </button>
      </div>
      <p class="tracking-status-total" role="status">共 {{ overview.total }} 条追番记录</p>
    </section>

    <section class="tracking-workspace" aria-label="追番记录与检查器">
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
        <div v-else id="tracking-list-container" ref="listContainer" class="tracking-list" tabindex="-1" aria-label="追番记录列表">
          <button v-for="item in filteredItems" :key="item.tracking_id" type="button" class="tracking-list-item"
            :class="{ 'is-selected': selectedTrackingId === item.tracking_id }" :data-tracking-id="item.tracking_id"
            :aria-current="selectedTrackingId === item.tracking_id ? 'true' : undefined" @click="selectItem(item.tracking_id)">
            <span class="tracking-list-indicator" aria-hidden="true" />
            <span class="tracking-list-copy"><strong>{{ item.title || '未命名番剧' }}</strong><span>{{ item.subtitle_group || '未设置字幕组' }}</span></span>
            <span class="tracking-list-meta"><span>{{ item.status_label }}</span><small>{{ item.updated_episode_status === 'NOT_IMPLEMENTED' ? '更新集数待开发' : '更新信息不可用' }}</small></span>
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
          :credential-ready="Boolean(savedState)"
          :write-session="writeSession"
          :recovery-session="recoverySession"
          :management-session="managementSession"
          :write-busy="inspectorIntentBusy"
          :intent-notice="selectedIntentNotice"
          @tracking-updated="applyReturnedTracking"
          @write-requested="runTrackingWrite"
          @recovery-requested="runTrackingRecovery"
          @management-requested="runTrackingManagement"
        />
        <template v-else>
          <h2 id="tracking-inspector-heading">检查器</h2>
          <EmptyState message="选择一条追番记录查看安全检查器。" />
        </template>
      </aside>
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
.tracking-workspace { display: grid; grid-template-columns: minmax(0, 1.6fr) minmax(17rem, 1fr); gap: var(--space-5); align-items: start; }
.tracking-list-panel { min-width: 0; }
.tracking-filters { display: grid; grid-template-columns: auto minmax(10rem, 1fr) auto minmax(8rem, .7fr) auto; gap: .65rem; align-items: center; margin-bottom: var(--space-4); }
.tracking-filters label { font-size: .85rem; font-weight: 600; }
.tracking-list { display: grid; gap: .55rem; }
.tracking-list-item { display: grid; grid-template-columns: .35rem minmax(0, 1fr) auto; gap: .8rem; align-items: center; width: 100%; padding: .85rem .9rem; border: 1px solid var(--color-border); border-radius: var(--radius-md); background: var(--color-surface); color: var(--color-text); text-align: left; cursor: pointer; }
.tracking-list-item:hover, .tracking-list-item:focus-visible, .tracking-list-item.is-selected { border-color: var(--color-primary); background: var(--color-surface-subtle); }
.tracking-list-item.is-selected .tracking-list-indicator { background: var(--color-primary); }
.tracking-list-indicator { align-self: stretch; min-height: 2rem; border-radius: 99px; background: var(--color-border); }
.tracking-list-copy, .tracking-list-meta { display: grid; gap: .25rem; min-width: 0; }
.tracking-list-copy strong { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.tracking-list-copy span, .tracking-list-meta small { color: var(--color-text-muted); }
.tracking-list-meta { text-align: right; white-space: nowrap; }
.tracking-list-state { min-height: 8rem; }
.tracking-selection-note { margin: var(--space-3) 0 0; color: var(--color-text-muted); }
.tracking-inspector { position: sticky; top: var(--space-4); display: grid; gap: var(--space-3); min-height: 15rem; padding: var(--space-4); border: 1px solid var(--color-border); border-radius: var(--radius-md); background: var(--color-surface); }
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
  .tracking-workspace { grid-template-columns: 1fr; }
  .tracking-inspector { position: static; }
  .tracking-filters { grid-template-columns: 1fr; }
  .tracking-filters label { margin-top: .25rem; }
  .tracking-list-meta { white-space: normal; }
}
</style>
