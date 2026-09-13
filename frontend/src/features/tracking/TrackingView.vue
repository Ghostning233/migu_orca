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
  isManagementActionCode,
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
  createModifyConflictSession,
  createModifyInFlightSession,
  createModifyRejectedSession,
  createTrackingManagementBody,
  createTrackingManagementIntent,
  MANAGEMENT_ACTION_ENDPOINTS,
  MODIFY_SCOPE_CONFIRMATIONS,
  projectModifyOutcome,
  type TrackingManagementIntent,
  type TrackingModifyResult,
} from './trackingManagement'
import TrackingInspector from './TrackingInspector.vue'
import CredentialSessionDialog from './CredentialSessionDialog.vue'

type ListResult = NonNullable<
  operations['listTrackingItems']['responses']['200']['content']['application/json']['result']
>
type ProbeBody = NonNullable<
  operations['probeAutoBangumiCapabilities']['requestBody']['content']['application/json']
>
type CapabilityResult = NonNullable<
  operations['probeAutoBangumiCapabilities']['responses']['200']['content']['application/json']['result']
>
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
const credentialDialogOpen = ref(false)
const credentialDialog = ref<InstanceType<typeof CredentialSessionDialog> | null>(null)
const sessionConfig = ref<ProbeBody['ab_config'] | null>(null)
const sessionCapabilities = ref<CapabilityResult | null>(null)
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
// Unknown-result recovery (US-312).  Like the write family, the page owns the
// request (only VERIFY_EXTERNAL needs the page credential) and the single
// page-level intent; no recovery key or credential is ever stored here beyond
// the live session config.
const recoverySession = ref<TrackingRecoverySession | null>(null)
const recoveryLoading = ref(false)
const recoveryPending = ref(false)
let recoverySequence = 0
let recoveryController: AbortController | null = null
// External management writes (US-313).  MODIFY shares the page credential, the
// impact confirmation, the latest revision and the single page-level intent
// with the submit family; only the endpoint, the request body and the server
// verdict differ (management_status instead of outcome).  The patch lives only
// in the locked in-memory intent and the single POST body.
const managementSession = ref<TrackingManagementSession | null>(null)
const managementLoading = ref(false)
const managementPending = ref(false)
let managementIntent: TrackingManagementIntent | null = null
let managementSequence = 0
let managementController: AbortController | null = null
// List reads and server-confirmed tracking writes have independent lifecycles:
// `listSequence` only invalidates stale list responses, while `writeGeneration`
// marks the revision a sync (or a local revalidate) already applied.  A list
// response started before a write must never overwrite it, and a list refresh
// must never discard a write result.
let listSequence = 0
let writeGeneration = 0
let syncSequence = 0
let syncController: AbortController | null = null

const statusLabels: Record<TrackingStatusGroup, string> = {
  PENDING: '待处理', PROCESSING: '处理中', ACTIVE: '追番中',
  ATTENTION: '需处理', INACTIVE: '已停用/已删除',
}
const overview = computed(() => projectTrackingOverview(items.value))
const capabilitySummary = computed(() => (
  sessionCapabilities.value ? projectCapabilitySummary(sessionCapabilities.value) : []
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
}

function selectItem(trackingId: string): void {
  selectedTrackingId.value = trackingId
  void router.push(routeLocation('tracking', { tracking_id: trackingId }))
}

function clearFilters(): void {
  searchTerm.value = ''
  statusFilter.value = ''
}

function onConnected(value: { config: ProbeBody['ab_config']; capabilities: CapabilityResult }): void {
  sessionConfig.value = value.config
  sessionCapabilities.value = value.capabilities
  credentialDialogOpen.value = false
}

/**
 * Clearing the page session drops every page-level intent (the locked write key
 * and the recovery lock).  The server record stays authoritative: the record's
 * own status and actions are re-read from the server on demand, so nothing is
 * lost or assumed.
 */
function clearConnection(): void {
  credentialDialog.value?.clearSession()
  sessionConfig.value = null
  sessionCapabilities.value = null
  cancelSync()
  resetWrite()
  resetRecovery()
  resetManagement()
  syncMessage.value = ''
  syncSummary.value = null
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
  if (!sessionConfig.value || !sessionCapabilities.value) return
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
  if (!confirmed || !sessionConfig.value || !sessionCapabilities.value) return
  const config = sessionConfig.value
  const sequence = ++syncSequence
  const controller = new AbortController()
  syncController?.abort()
  syncController = controller
  loading.value = false
  syncLoading.value = true
  syncMessage.value = ''
  try {
    const body: SyncBody = { ab_config: config, confirm: true }
    const result = await api.post<SyncResult>('/api/v1/tracking/sync', { body, signal: controller.signal })
    // Only a newer sync intent or an explicit connection reset can discard this
    // result; list refreshes use their own sequence and revision guard.
    if (sequence !== syncSequence) return
    const incomplete = result.sync_status !== 'COMPLETE'
    const degraded = incomplete || hasUnknownCapability(result.capabilities)
    syncSummary.value = result.summary
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
    sessionCapabilities.value = result.capabilities
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
}

function resetRecovery(): void {
  recoverySequence += 1
  recoveryController?.abort()
  recoveryController = null
  recoveryPending.value = false
  recoveryLoading.value = false
  recoverySession.value = null
}

function resetManagement(): void {
  managementSequence += 1
  managementController?.abort()
  managementController = null
  managementIntent = null
  managementPending.value = false
  managementLoading.value = false
  managementSession.value = null
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
  // A confirmation is already open, or an external write/recovery is already
  // running: one page-level intent at a time, and no second dialog can displace
  // the first (D38-09.4: an active recovery blocks submit/retry).
  if (writePending.value || writeLoading.value || recoveryPending.value || recoveryLoading.value
    || managementPending.value || managementLoading.value) return
  const config = sessionConfig.value
  const capabilities = sessionCapabilities.value
  // No page credential session means no external write at all.
  if (!config || !capabilities) return
  const trackingId = payload.item.tracking_id
  const unresolved = writeSession.value
  if (unresolved && unresolved.trackingId !== trackingId && writeSessionKeepsIntent(unresolved.state)) return
  const requested = payload.action.code
  // Only the submit-family actions this page can actually send are accepted;
  // every other server action waits for its own story.
  if (!isWriteActionCode(requested)) return
  // A locked intent still owns the single opaque key for this item. Replaying it
  // under a different action would send something the user did not ask for, and
  // minting a new key while the external result is unresolved could create a
  // second subscription — so a mismatching action does nothing at all.
  const locked = writeIntent && writeSession.value?.trackingId === trackingId ? writeIntent : null
  if (locked && locked.action !== requested) return
  const action: TrackingWriteActionCode = requested

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
  if (!confirmed || !sessionConfig.value || !sessionCapabilities.value) return

  // One opaque key per confirmation.  Only an indeterminate earlier result keeps
  // its locked intent, so a transport retry reuses the very same key (and the
  // very same revision binding) instead of risking a second external
  // subscription; a definite failure always mints a fresh one.
  const intent = locked ?? createTrackingActionIntent(payload.item, payload.action, undefined, sessionCapabilities.value)
  if (!intent) return
  writeIntent = intent
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
      ab_config: config,
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
      // D38-08.5: a structured non-409 4xx is a definite refusal raised before
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
 * the read-only external check: it uses the live page session's ``ab_config``
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
  const unresolvedWrite = writeSession.value
  if (unresolvedWrite && unresolvedWrite.trackingId !== trackingId && writeSessionKeepsIntent(unresolvedWrite.state)) return
  const openRecovery = recoverySession.value
  if (openRecovery && openRecovery.trackingId !== trackingId && recoverySessionKeepsLock(openRecovery.state)) return
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
  const intent = createTrackingRecoveryIntent(payload.item, requested, sessionCapabilities.value)
  if (!intent) return
  const body = createTrackingRecoverBody(
    intent.action, intent.expectedRevision, sessionConfig.value, storageQuery().storage_dir,
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
      // A structured non-409 4xx is decided before any state change.
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
 * Run one explicit external management write (US-313).
 *
 * ``MODIFY`` is the management action this story sends.  It reuses everything
 * the submit family already guarantees: the live page credential, the latest
 * revision, an impact confirmation, one opaque key per confirmation, the single
 * page-level intent, the returned-tracking convergence and a read-only read-back
 * — never an automatic resend.  The endpoint and the request body are both bound
 * to the scope the user chose, so a scope can only ever send its own patch.
 */
async function runTrackingManagement(payload: {
  action: TrackingAction
  item: TrackingItem
  targetScope: TrackingManagementScope
  patch: unknown
}): Promise<void> {
  if (managementPending.value || managementLoading.value || writePending.value || writeLoading.value
    || recoveryPending.value || recoveryLoading.value) return
  const config = sessionConfig.value
  const capabilities = sessionCapabilities.value
  // No page credential session means no external management write at all.
  if (!config || !capabilities) return
  const requested = payload.action.code
  // Only the management actions this page can actually send are accepted.
  if (!isManagementActionCode(requested)) return
  const action = requested
  const targetScope = payload.targetScope
  if (!isTrackingManagementScope(targetScope)) return
  const trackingId = payload.item.tracking_id
  const unresolvedWrite = writeSession.value
  if (unresolvedWrite && unresolvedWrite.trackingId !== trackingId && writeSessionKeepsIntent(unresolvedWrite.state)) return
  const openRecovery = recoverySession.value
  if (openRecovery && openRecovery.trackingId !== trackingId && recoverySessionKeepsLock(openRecovery.state)) return
  const openManagement = managementSession.value
  if (openManagement && openManagement.trackingId !== trackingId && managementSessionKeepsIntent(openManagement)) return
  // A locked intent still owns the single opaque key *and* the scope/patch it
  // was confirmed with. Replaying it under a different scope or patch would
  // send something the user did not ask for, and minting a new key while the
  // external result is unresolved could apply the change twice — so a
  // mismatching request does nothing at all.
  const locked = managementIntent && managementSession.value?.trackingId === trackingId ? managementIntent : null
  if (locked && (locked.action !== action || locked.targetScope !== targetScope
    || JSON.stringify(locked.patch) !== JSON.stringify(payload.patch))) return

  // The page re-validates the emitted request against the current server
  // projection: the action and scope must still be offered for this revision
  // and the live session must still prove the capability.
  const intent = locked ?? createTrackingManagementIntent(
    payload.item, action, targetScope, payload.patch, capabilities,
  )
  if (!intent) return

  managementPending.value = true
  let confirmed = false
  try {
    confirmed = (await confirmDialog.value?.confirm({
      ...MODIFY_SCOPE_CONFIRMATIONS[targetScope], cancelLabel: '取消',
    })) ?? false
  } finally {
    managementPending.value = false
  }
  // Cancelling the impact confirmation sends zero requests.
  if (!confirmed || !sessionConfig.value || !sessionCapabilities.value) return

  managementIntent = intent
  const sequence = ++managementSequence
  const controller = new AbortController()
  managementController?.abort()
  managementController = controller
  managementLoading.value = true
  managementSession.value = createModifyInFlightSession(trackingId, targetScope)
  try {
    // A body the page cannot build safely (no server address, missing scope
    // patch) is not sent at all.
    const body = createTrackingManagementBody(intent, sessionConfig.value, storageQuery().storage_dir)
    if (!body) return
    const result = await api.post<TrackingModifyResult>(MANAGEMENT_ACTION_ENDPOINTS[intent.action], {
      path: { tracking_id: trackingId }, body, signal: controller.signal,
    })
    if (sequence !== managementSequence) return
    // The returned tracking converges the list row without a second list read.
    applyReturnedTracking(result.tracking)
    const session = projectModifyOutcome(trackingId, targetScope, result)
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
      managementSession.value = createModifyConflictSession(trackingId, targetScope, apiError.type)
      await recheckAfterAction(trackingId, true)
      return
    }
    if (isDefiniteWriteRejection(apiError)) {
      // A structured non-409 4xx is a definite refusal raised before the
      // external boundary, so Auto Bangumi was never modified. The intent is
      // released (other items are no longer blocked and the next confirmation
      // mints a fresh key) and the page only reads the latest state back.
      managementIntent = null
      managementSession.value = createModifyRejectedSession(trackingId, targetScope)
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
  void loadList().then(() => {
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
onBeforeUnmount(() => {
  cancelSync()
  resetWrite()
  resetRecovery()
  resetManagement()
  credentialDialog.value?.clearSession()
  sessionConfig.value = null
  sessionCapabilities.value = null
})
</script>

<template>
  <section id="tracking-overview" class="tracking-overview" aria-labelledby="tracking-heading">
    <PanelSection title="追番管理" class="tracking-header">
      <template #actions>
        <BaseButton id="tracking-connect" variant="secondary" @click="credentialDialogOpen = true">连接 Auto Bangumi</BaseButton>
        <BaseButton v-if="sessionCapabilities" id="tracking-sync" variant="secondary" :loading="syncLoading" :disabled="syncLoading || syncPending" @click="syncTracking">同步 Auto Bangumi</BaseButton>
        <BaseButton id="tracking-refresh" variant="secondary" :loading="loading" @click="loadList()">刷新列表</BaseButton>
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
          :capabilities="sessionCapabilities"
          :credential-ready="Boolean(sessionConfig)"
          :write-session="writeSession"
          :recovery-session="recoverySession"
          :management-session="managementSession"
          :write-busy="inspectorIntentBusy"
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
    <section v-if="sessionCapabilities" class="tracking-connection-status" aria-labelledby="tracking-connection-heading">
      <h2 id="tracking-connection-heading">Auto Bangumi 页面连接</h2>
      <p role="status">
        当前页面已连接 Auto Bangumi（{{ probeStatusLabel(sessionCapabilities.probe_status) }}），仅在用户明确操作时使用。
        <button type="button" class="tracking-clear-connection" @click="clearConnection">清除连接</button>
      </p>
      <dl id="tracking-capability-summary" class="tracking-capability-summary">
        <div><dt>版本</dt><dd>{{ capabilityVersionLabel(sessionCapabilities) }}</dd></div>
        <div><dt>探测状态</dt><dd>{{ probeStatusLabel(sessionCapabilities.probe_status) }}</dd></div>
        <div v-for="entry in capabilitySummary" :key="entry.key">
          <dt>{{ entry.label }}</dt><dd>{{ capabilityStateLabel(entry.state) }}</dd>
        </div>
      </dl>
      <p class="field-help">以上仅为本次探测到的安全能力摘要，管理写能力仍需服务端按当前认证与版本逐项确认。</p>
    </section>
    <p v-if="syncMessage" id="tracking-sync-status" class="tracking-sync-status" role="status">{{ syncMessage }}</p>
    <p v-if="syncSummary" class="tracking-sync-summary" role="status">本次安全同步摘要：检查 {{ syncSummary.checked }}，新增 {{ syncSummary.created }}，更新 {{ syncSummary.updated }}，未变化 {{ syncSummary.unchanged }}。</p>
    <CredentialSessionDialog ref="credentialDialog" v-model:open="credentialDialogOpen" @connected="onConnected" />
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
