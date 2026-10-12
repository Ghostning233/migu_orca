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
  filterTrackingItems,
  formatSubmissionMode,
  formatTrackingUpdatedAt,
  probeStatusLabel,
  projectCapabilitySummary,
  projectTrackingOverview,
  sortTrackingItems,
  TRACKING_OVERVIEW_GROUPS,
  TRACKING_STATUS_GROUPS,
  resubmitRiskMessage,
  type TrackingAction,
  type TrackingCheckResult,
  type TrackingItem,
  type TrackingListSummary,
  type TrackingManagementScope,
  type TrackingOverviewGroup,
  type TrackingResubmitBinding,
  type TrackingResubmitResult,
  type TrackingStatusGroup,
} from './trackingProjection'
import {
  useTrackingWriteSession,
  type TrackingRecoveryActionCode,
  type TrackingWriteRequest,
  type TrackingSubmissionMode,
  type TrackingWriteEffect,
  type TrackingWriteFeedback,
  type TrackingWriteTarget,
} from './useTrackingWriteSession'
import TrackingInspector from './TrackingInspector.vue'
import TrackingSubmissionModeDialog, { type SubmissionMode } from './TrackingSubmissionModeDialog.vue'
import TrackingPoster from './TrackingPoster.vue'

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
type TrackingWriteResult = NonNullable<
  operations['submitTrackingItem']['responses']['200']['content']['application/json']['result']
>
type TrackingRecoverResult = NonNullable<
  operations['recoverTrackingItem']['responses']['200']['content']['application/json']['result']
>
type TrackingManagementResult = NonNullable<
  operations['modifyTrackingItem']['responses']['200']['content']['application/json']['result']
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
/**
 * Every external write — submit/retry, recovery, the four management actions,
 * the unified plan delete and the confirmed batch — is one local session owned
 * by this module (issue #168).  The page keeps the transport lifecycle: the
 * abort controller and its sequence guard, the dialogs, the notifications, the
 * routing and the focus.
 */
const writes = useTrackingWriteSession()
/** The inspector consumes the page's single write-session entry. */
const writeSessions = writes.sessions
const writeLoading = writes.loading
const writePending = writes.pending
let writeSequence = 0
let writeController: AbortController | null = null
/**
 * Issue #183: the bounded read-only check of a pending submission.  It is its
 * own session slot rather than a write family — it holds no page-level intent,
 * so the page only owns its transport sequence and abort controller.
 */
const checkSession = writes.check
/**
 * Issue #184: the risk-confirmed resubmission's own read-only slot, plus the
 * page's dialog-open flag (the module refuses a second command while it is set).
 */
const resubmitSession = writes.resubmit
const resubmitPending = writes.pending
const autoCheckArmed = writes.autoCheckArmed
let checkSequence = 0
let checkController: AbortController | null = null
const planDeleteSession = writes.planDelete
const batchOutcome = writes.batchOutcome
const batchLoading = writes.batchLoading
const batchNotice = writes.batchNotice
const batchSkippedNotice = writes.batchSkippedNotice
const isBatchSelected = writes.isBatchSelected
const batchSkipReason = writes.batchSkipReason
const resetBatch = writes.resetBatch
const clearBatchSelection = writes.clearBatchSelection
// List reads and server-confirmed tracking writes have independent lifecycles:
// `listSequence` only invalidates stale list responses, while `writeGeneration`
// marks the revision a sync (or a local revalidate) already applied.  A list
// response started before a write must never overwrite it, and a list refresh
// must never discard a write result.
let listSequence = 0
let writeGeneration = 0
let syncSequence = 0
let syncController: AbortController | null = null

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
 * The fixed page-level reason a locked intent refused a different request, or ''
 * while nothing is blocked.  The session owns the rule; the page only asks for
 * the selected record.
 */
const selectedIntentNotice = computed(() => writes.noticeFor(selectedTrackingId.value))

/**
 * External writes and recoveries are single-flight (Stage 38 invariant).  The
 * lock covers the external action only: selecting, searching, refreshing and
 * the pure local revalidate of *other* items stay available while one action is
 * running.  An unresolved result keeps locking other items because it still
 * holds the one page-level intent (D38-09.4 keeps that lock for an unresolved
 * recovery too), but never blocks the item's own next step.
 */
const inspectorIntentBusy = computed(() => writes.busyFor(selectedTrackingId.value))

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
  writeSequence += 1
  writeController?.abort()
  writeController = null
  writes.preserveAfterClear()
  syncMessage.value = ''
  syncSummary.value = null
}

/** Drop every session and invalidate whatever transport is still outstanding. */
function resetSession(): void {
  writeSequence += 1
  writeController?.abort()
  writeController = null
  writes.reset()
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

/**
 * Read-back after an external write or a recovery (US-310, US-312).
 *
 * The list already converged from the returned tracking; only the inspector
 * detail is re-read, so an action never blanks the list.  When the round trip
 * told us nothing authoritative (409 conflict, unreadable result) the list is
 * re-read too, because the returned summary cannot be trusted in those paths.
 */
async function recheckAfterAction(trackingId: string | null, refreshList: boolean): Promise<void> {
  if (refreshList) await loadList(true)
  if (!trackingId || selectedTrackingId.value !== trackingId) return
  await inspector.value?.reload()
}

/** A fixed verdict the session produced, mapped to its one page-level channel. */
async function presentFeedback(feedback: TrackingWriteFeedback): Promise<void> {
  if (feedback.channel === 'success') {
    notification.show('success', feedback.title, feedback.message)
    return
  }
  const openSettings = (await confirmDialog.value?.confirm({
    title: feedback.title,
    message: feedback.message,
    confirmLabel: '前往设置',
    cancelLabel: '关闭',
  })) ?? false
  if (openSettings) await router.push(routeLocation('settings'))
}

/**
 * Run one single-write session transport.
 *
 * The page owns the transport: the abort controller, the sequence guard, the
 * returned-tracking convergence, the converging effects and the end of the
 * attempt all live here exactly once, so the submit, recovery and management
 * paths can only differ in which session command settles them.
 */
async function runSessionTransport<Result extends { tracking: TrackingItem }>(options: {
  readonly request: TrackingWriteRequest
  /** Runs after a success response and before the returned tracking converges. */
  readonly beforeConverge?: () => void
  readonly settle: (result: Result) => readonly TrackingWriteEffect[]
  readonly fail: (error: ReturnType<typeof toApiError>) => readonly TrackingWriteEffect[]
}): Promise<void> {
  const sequence = ++writeSequence
  const controller = new AbortController()
  writeController?.abort()
  writeController = controller
  try {
    const result = await api.post<Result>(options.request.endpoint, {
      path: options.request.path, body: options.request.body, signal: controller.signal,
    })
    if (sequence !== writeSequence) return
    // The returned tracking converges the list row without a second list read.
    options.beforeConverge?.()
    applyReturnedTracking(result.tracking)
    await runWriteEffects(options.settle(result))
  } catch (error) {
    if (sequence !== writeSequence) return
    await runWriteEffects(options.fail(toApiError(error)))
  } finally {
    if (sequence === writeSequence) {
      writes.finishAttempt()
      if (writeController === controller) writeController = null
    }
  }
}

/**
 * Run the converging effects one session command returned.
 *
 * The module decides *what* must happen (re-read the server, state a fixed
 * verdict); the page owns the IO, the dialog and the routing.
 */
async function runWriteEffects(effects: readonly TrackingWriteEffect[]): Promise<void> {
  for (const effect of effects) {
    if (effect.kind === 'recheck') {
      await recheckAfterAction(effect.trackingId, effect.refreshList)
      continue
    }
    if (effect.kind === 'confirmResubmitRisk') {
      await confirmResubmitRisk(effect.trackingId, effect.binding)
      continue
    }
    await presentFeedback(effect.feedback)
  }
}

/**
 * Ask for the one explicit acceptance of a resubmission's duplicate/resource
 * risk (issue #184) and then send the confirmation the server offered.
 *
 * Cancelling sends nothing at all: no new operation, no external write. The
 * dialog copy comes from the module's fixed Chinese risk table, never from an
 * upstream response.
 */
async function confirmResubmitRisk(
  trackingId: string,
  binding: TrackingResubmitBinding,
): Promise<void> {
  const offer = writes.resubmit.value
  if (!offer || offer.trackingId !== trackingId) return
  writes.setPending(true)
  let confirmed = false
  try {
    confirmed = (await confirmDialog.value?.confirm({
      title: '重新提交到 Auto Bangumi？',
      message: resubmitRiskMessage(offer.reason),
      itemsLabel: '风险说明',
      items: [
        '原提交结果尚未确认：Auto Bangumi 可能已经创建了该订阅并开始处理资源。',
        '重新提交会以新操作再次创建订阅；MiGuOrca 无法去重，也不会改写或删除原提交记录。',
      ],
      confirmLabel: '确认重新提交',
      cancelLabel: '取消',
    })) ?? false
  } finally {
    writes.setPending(false)
  }
  if (!confirmed) {
    writes.cancelResubmit(trackingId)
    return
  }
  const started = writes.beginResubmitConfirmation(binding, {
    storageDir: storageQuery().storage_dir,
  })
  if (!started.accepted || !started.request) {
    await runWriteEffects(started.effects)
    return
  }
  await runSessionTransport<TrackingResubmitResult>({
    request: started.request,
    settle: (result) => writes.finishSubmit(result),
    fail: (error) => writes.failSubmit(error),
  })
}

/**
 * Run one risk-confirmed single manual resubmission (issue #184).
 *
 * The module owns the phase decision: the first call is the bounded read-only
 * check (a proven subscription converges with zero external writes), while an
 * unresolved earlier confirmation of the same item replays its exact body — so
 * one confirmation can never create a second operation. The page only owns the
 * transport, the effects and the risk dialog.
 */
async function runTrackingResubmit(payload: { item: TrackingItem }): Promise<void> {
  const started = writes.beginResubmit(payload, { storageDir: storageQuery().storage_dir })
  if (!started.accepted || !started.request) {
    await runWriteEffects(started.effects)
    return
  }
  if (started.resubmitPhase === 'CONFIRMATION') {
    await runSessionTransport<TrackingResubmitResult>({
      request: started.request,
      settle: (result) => writes.finishSubmit(result),
      fail: (error) => writes.failSubmit(error),
    })
    return
  }
  await runSessionTransport<TrackingResubmitResult>({
    request: started.request,
    settle: (result) => writes.finishResubmitOffer(result),
    fail: (error) => writes.failResubmitOffer(error),
  })
}

// -- explicit batch submit (issue #87) --------------------------------------
const batchMode = ref(false)
const batchSubmissionMode = ref<SubmissionMode | null>(null)
const batchModeOpen = ref(false)
/** Issue #100: the mode dialog is answered before the whole batch is sent. */
let batchSequence = 0

const batchSummary = computed(() => writes.batchSummary(filteredItems.value))

function toggleBatchMode(): void {
  batchMode.value = !batchMode.value
  resetBatch()
}

function toggleRow(trackingId: string): void {
  writes.toggleBatchRow(trackingId)
}

function selectAllCurrent(): void {
  writes.selectAllBatch(filteredItems.value)
}

function clearSelection(): void {
  clearBatchSelection()
}

function titleFor(trackingId: string): string {
  return items.value.find((item) => item.tracking_id === trackingId)?.title || '未命名番剧'
}

/**
 * AC 9: the local pre-check result lives in its own dialog; external success,
 * failure and unknown results stay in the batch result area.
 */
async function showSkippedPlans(title: string, skipped: readonly { title: string; reason: string }[]): Promise<void> {
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
  if (batchLoading.value) return
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
  if (batchLoading.value) return
  const config = savedRef.value
  if (!config?.connection_ref) return
  if (!batchSummary.value.selected) return

  // One choice, one batch: the mode is spent here so a later batch cannot
  // silently reuse it.
  const submissionMode = batchSubmissionMode.value ?? null
  batchSubmissionMode.value = null
  const started = writes.beginBatchSubmit(
    { items: items.value, mode: submissionMode },
    { connection: config, storageDir: storageQuery().storage_dir },
  )
  if (started.skipped.length) {
    // AC 4: the information dialog never gates the run — the submittable plans
    // start immediately, with no second confirmation.
    void showSkippedPlans(started.skippedTitle, started.skipped)
  }
  if (!started.accepted || !started.request) return

  const sequence = ++batchSequence
  try {
    const result = await api.post<BatchResult>(started.request.endpoint, {
      path: started.request.path, body: started.request.body,
    })
    if (sequence !== batchSequence) return
    await runWriteEffects(writes.finishBatchSubmit(result))
  } catch (error) {
    if (sequence !== batchSequence) return
    writes.failBatchSubmit(toApiError(error))
  }
}

// -- explicit submit-family external writes (US-310, US-311) ----------------
// The dialog stays open (all actions disabled, the chosen one loading) until the
// page-level write settles, then closes on every path.
const submitModeOpen = ref(false)
const submitModePending = ref<TrackingWriteTarget | null>(null)
const submissionMode = ref<TrackingSubmissionMode | null>(null)

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

watch(writeLoading, (loading) => {
  if (loading) return
  closeSubmissionModeChoice()
})

/**
 * Run one explicit submit-family external write (US-310, US-311).
 *
 * ``SUBMIT`` and ``RETRY`` share this single path: the endpoint, the impact
 * confirmation and the result projection are all bound to the server-computed
 * action code, so a retry can never be sent with submit copy (or the reverse).
 */
async function runTrackingWrite(payload: TrackingWriteTarget): Promise<void> {
  const options = {
    mode: submissionMode.value,
    confirmed: submissionMode.value !== null,
    connection: savedRef.value,
    storageDir: storageQuery().storage_dir,
  }
  let started = writes.beginSubmit(payload, options)
  if (started.ask === 'SUBMISSION_MODE') {
    // Issue #98 AC 2: the entry only opens the mode choice, which is also the
    // submit family's impact confirmation; opening it sends nothing.
    submitModePending.value = payload
    submitModeOpen.value = true
    return
  }
  if (started.ask === 'IMPACT' && started.confirmation) {
    writes.setPending(true)
    let confirmed = false
    try {
      confirmed = (await confirmDialog.value?.confirm({
        ...started.confirmation, cancelLabel: '取消',
      })) ?? false
    } finally {
      writes.setPending(false)
    }
    // Cancelling the impact confirmation sends zero requests, and the live
    // saved generation is read again after the dialog.
    if (!confirmed) return
    started = writes.beginSubmit(payload, {
      ...options, confirmed: true, connection: savedRef.value, storageDir: storageQuery().storage_dir,
    })
  }
  if (!started.accepted || !started.request) {
    await runWriteEffects(started.effects)
    return
  }
  await runSessionTransport<TrackingWriteResult>({
    request: started.request,
    beforeConverge: closeSubmissionModeChoice,
    settle: (result) => writes.finishSubmit(result),
    fail: (error) => writes.failSubmit(error),
  })
}

/**
 * Run one explicit unknown-result recovery (US-312).
 *
 * ``RECOVER_AUTO`` is pure local: no credential, no confirmation, no external
 * call.  ``MARK_SUCCEEDED``/``MARK_FAILED`` are the user's manual conclusion and
 * are always confirmed a second time (the dialog defaults to cancel and states
 * that the user must have checked Auto Bangumi first).  ``VERIFY_EXTERNAL`` is
 * the read-only external check: it uses the saved connection generation for one
 * verification of the record's own operation and can never create an external
 * write.  Every path converges on the returned tracking and never resends.
 */
async function runTrackingRecovery(
  payload: { action: TrackingRecoveryActionCode; item: TrackingItem },
): Promise<void> {
  const recoveryOptions = {
    capabilities: savedState.value?.capabilities ?? null,
    connection: savedState.value,
    storageDir: storageQuery().storage_dir,
  }
  let started = writes.beginRecovery(payload, recoveryOptions)
  if (started.ask === 'IMPACT' && started.confirmation) {
    writes.setPending(true)
    let confirmed = false
    try {
      confirmed = (await confirmDialog.value?.confirm({
        ...started.confirmation, cancelLabel: '取消',
      })) ?? false
    } finally {
      writes.setPending(false)
    }
    // Cancelling the recovery confirmation sends zero requests, and the live
    // page session is read again after the dialog.
    if (!confirmed) return
    started = writes.beginRecovery(payload, {
      ...recoveryOptions,
      capabilities: savedState.value?.capabilities ?? null,
      connection: savedState.value,
      confirmed: true,
    })
  }
  if (!started.accepted || !started.request) {
    await runWriteEffects(started.effects)
    return
  }
  await runSessionTransport<TrackingRecoverResult>({
    request: started.request,
    settle: (result) => writes.finishRecovery(result),
    fail: (error) => writes.failRecovery(error),
  })
}

/**
 * Run one bounded read-only confirmation of a pending submission (issue #183).
 *
 * The session decides whether anything may be sent at all and builds the one
 * request (revision only); the server resolves the original operation's saved
 * connection, so nothing here can rebind it.  A stale revision is a 409 before
 * any read, and every read-only business outcome converges the list and
 * re-reads the detail.
 */
async function runTrackingCheck(payload: { item: TrackingItem; automatic: boolean }): Promise<void> {
  const started = writes.beginCheck(payload, { storageDir: storageQuery().storage_dir })
  if (!started.accepted || !started.request) return
  const request = started.request
  const sequence = ++checkSequence
  const controller = new AbortController()
  checkController?.abort()
  checkController = controller
  try {
    const result = await api.post<TrackingCheckResult>(request.endpoint, {
      path: request.path, body: request.body, signal: controller.signal,
    })
    if (sequence !== checkSequence) return
    // The returned tracking converges the list row; the detail is re-read so the
    // check's own verdict is what the submit area shows.
    applyReturnedTracking(result.tracking)
    await runWriteEffects(writes.finishCheck(result))
  } catch (error) {
    if (sequence !== checkSequence) return
    await runWriteEffects(writes.failCheck(toApiError(error)))
  } finally {
    if (sequence === checkSequence) checkController = null
  }
}

/**
 * Run one explicit external management write (US-313, US-314).
 *
 * ``MODIFY``, ``SET_ENABLED``, ``REFRESH_RSS`` and ``DELETE_EXTERNAL`` share
 * this single path.  The session re-validates the emitted request against the
 * current server projection, binds the endpoint/body/confirmation to the
 * validated intent and projects the management verdict; the page owns the
 * confirmation dialog and the transport.
 */
async function runTrackingManagement(payload: {
  action: TrackingAction
  item: TrackingItem
  targetScope: TrackingManagementScope
  patch: unknown
  /** Issue #91: local plan values raised with a confirmed subscription modify. */
  localPlan?: unknown
}): Promise<void> {
  const options = { connection: savedRef.value, storageDir: storageQuery().storage_dir }
  let started = writes.beginManagement(payload, options)
  if (started.ask === 'IMPACT' && started.confirmation) {
    writes.setPending(true)
    let confirmed = false
    try {
      confirmed = (await confirmDialog.value?.confirm({
        ...started.confirmation, cancelLabel: '取消',
      })) ?? false
    } finally {
      writes.setPending(false)
    }
    // Cancelling the impact confirmation sends zero requests, and the live
    // saved generation is read again after the dialog.
    if (!confirmed) return
    started = writes.beginManagement(payload, {
      ...options, confirmed: true, connection: savedRef.value, storageDir: storageQuery().storage_dir,
    })
  }
  if (!started.accepted || !started.request) {
    await runWriteEffects(started.effects)
    return
  }
  await runSessionTransport<TrackingManagementResult>({
    request: started.request,
    settle: (result) => writes.finishManagement(result),
    fail: (error) => writes.failManagement(error),
  })
}

// -- unified plan delete (issue #92) -----------------------------------------
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
  // Issue #96: a purely local delete needs no Auto Bangumi connection at all;
  // only the optional external delete requires the saved connection (the
  // session enforces exactly that).
  const started = writes.beginPlanDelete(payload, {
    connection: savedRef.value,
    storageDir: storageQuery().storage_dir,
  })
  if (!started.accepted || !started.request) return
  const request = started.request
  const trackingId = payload.item.tracking_id
  const sequence = ++planDeleteSequence
  try {
    const result = await api.post<PlanDeleteResult>(request.endpoint, {
      path: request.path, body: request.body,
    })
    if (sequence !== planDeleteSequence) return
    const effects = writes.finishPlanDelete(result)
    if (planDeleteSession.value?.state === 'DELETED' && selectedTrackingId.value === trackingId) {
      selectedTrackingId.value = ''
    }
    await runWriteEffects(effects)
  } catch (error) {
    if (sequence !== planDeleteSequence) return
    const apiError = toApiError(error)
    if (apiError.cancelled && !apiError.httpError) return
    await runWriteEffects(writes.failPlanDelete(apiError))
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
  writes.setAutoCheck(Boolean(trackingId))
  if (trackingId) void focusSelection()
}, { flush: 'post' })
onBeforeUnmount(() => {
  cancelSync()
  resetSession()
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
          <BaseButton id="tracking-batch-submit" :loading="batchLoading" :disabled="batchLoading || !batchSummary.selected || !savedRef" @click="runBatchSubmit">
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
              :checked="isBatchSelected(item.tracking_id)"
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
          :sessions="writeSessions"
          :check-session="checkSession"
          :resubmit-session="resubmitSession"
          :resubmit-pending="resubmitPending"
          :auto-check-armed="autoCheckArmed"
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
      :busy="batchLoading"
      @choose="chooseBatchSubmissionMode"
      @cancel="cancelBatchSubmissionMode"
    />
    <TrackingSubmissionModeDialog
      :open="submitModeOpen"
      :pending-mode="submissionMode"
      :busy="writeLoading || writePending"
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
