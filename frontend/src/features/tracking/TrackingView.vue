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
import { routeLocation } from '@/app/router/catalog'
import { useNotificationStore } from '@/app/stores/notification'
import { refreshConnectionStatus } from '@/app/stores/connectionStatus'
import { storageQuery } from '@/features/requests/requestStorage'
import {
  filterTrackingItems,
  projectCapabilitySummary,
  projectStatusGroups,
  projectTrackingOverview,
  sortTrackingItems,
  resubmitRiskMessage,
  type TrackingAction,
  type TrackingCheckResult,
  type TrackingItem,
  type TrackingListSummary,
  type TrackingResubmitBinding,
  type TrackingResubmitResult,
  type TrackingStatusGroup,
} from './trackingProjection'
import {
  useTrackingWriteSession,
  type TrackingManagementScope,
  type TrackingRecoveryActionCode,
  type TrackingWriteRequest,
  type TrackingSubmissionMode,
  type TrackingWriteEffect,
  type TrackingWriteFeedback,
  type TrackingWriteTarget,
} from './useTrackingWriteSession'
import TrackingInspector from './TrackingInspector.vue'
import TrackingBatchDeleteDialog, { type BatchDeleteSkip } from './TrackingBatchDeleteDialog.vue'
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
type BatchDeleteResult = NonNullable<
  operations['deleteTrackingBatchPlans']['responses']['200']['content']['application/json']['result']
>
type BatchDeleteItemResult = BatchDeleteResult['items'][number]

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
/**
 * T6 (#229): the page owns at most one automatic read-only sync per entry.
 * There is no manual entry and no confirmation step any more: the endpoint is
 * read-only, so entering the page is the only trigger the user needs.
 */
const syncLoading = ref(false)
let autoSyncArmed = false
// B5: only degraded / incomplete / ignored sync results stay on the page (in a
// bounded status region inside the list panel); a clean success is a toast.
const syncStatus = ref('')
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
/** Issue #223: rows the batch selection must exclude (in-flight/undecided). */
const batchLockedReason = writes.batchLockedReason
const resetBatch = writes.resetBatch
const clearBatchSelection = writes.clearBatchSelection
// List reads and server-confirmed tracking writes have independent lifecycles:
// `listSequence` only invalidates stale list responses, while `writeGeneration`
// marks the revision a sync (or a local revalidate) already applied.  A list
// response started before a write must never overwrite it, and a list refresh
// must never discard a write result.
let listSequence = 0
// Counts-only refreshes have their own generation: a settled write must not
// invalidate (and so permanently leave loading) a list read the user started.
let countsSequence = 0
let writeGeneration = 0
let syncSequence = 0
let syncController: AbortController | null = null

/**
 * Read the saved connection summary, which already carries the deployment's last
 * proven capability projection (Stage 39 PRD: loading the page must never probe
 * by itself). B1 retires the manual probe entry, so the page only adopts what
 * the summary publishes — a cold cache simply leaves the read-only external
 * check unavailable until the next explicit sync (T6/#229 owns automatic
 * refresh). No extra network call and no capability write happen here.
 */
async function loadSavedConnection(): Promise<void> {
  try {
    const summary = await api.get<SavedConnection>('/api/v1/settings/autobangumi')
    savedConnection.value = summary
    const capabilities = summary.capabilities
    const usable = Boolean(
      summary.connection_ref && summary.credential_present && capabilities,
    )
    const changed = savedState.value && (savedState.value.connection_ref !== summary.connection_ref
      || savedState.value.configuration_revision !== summary.configuration_revision)
    if (!usable) {
      savedState.value = null
    } else if (!savedState.value || changed) {
      savedState.value = {
        connection_ref: summary.connection_ref!,
        configuration_revision: summary.configuration_revision,
        capabilities: capabilities as CapabilityResult,
      }
    }
  } catch {
    savedConnection.value = null
    savedState.value = null
  }
}

/**
 * Issue #224 A2/A5: the overview is exactly the four server-published cards.
 * Clicking one is a whole-library category entry, so it also clears the search
 * box (the user's decision): the card number and the filtered row count then
 * describe the same category, and a later search narrows the rows only.
 */
function selectOverviewGroup(group: TrackingStatusGroup): void {
  searchTerm.value = ''
  statusFilter.value = statusFilter.value === group ? '' : group
}

// Issue #85/#224: the overview is the server's authoritative projection, not a
// recount of whichever rows this page happens to hold or filter.  Both the
// total and the group labels/counts/card membership come from the server, so
// the page owns no label table (A7).
const listSummary = ref<TrackingListSummary | null>(null)
const listStatusGroups = ref<ListResult['status_groups'] | null>(null)
const overview = computed(() => projectTrackingOverview(listSummary.value))
const statusGroups = computed(() => projectStatusGroups(listStatusGroups.value))
const overviewCards = computed(() => statusGroups.value.filter((group) => group.isCard))
const filteredItems = computed(() => sortTrackingItems(filterTrackingItems(items.value, {
  query: searchTerm.value, statusGroup: statusFilter.value,
})))
/** True only while a real search term is narrowing the list (trimmed). */
const hasSearch = computed(() => searchTerm.value.trim() !== '')
/**
 * The authoritative count of the selected category, or of 全部 without one.
 *
 * `null` means the server did not publish the selected group (an older or
 * malformed projection), so the page states the filtered number alone instead
 * of relabelling the whole-library total as the category count.
 */
const categoryTotal = computed<number | null>(() => {
  if (!statusFilter.value) return overview.value.total
  return statusGroups.value.find((group) => group.group === statusFilter.value)?.count ?? null
})
/** Issue #224 A5: 共 N 部; with a search 筛选出 M 部 · 共 N 部. */
const listCountText = computed(() => {
  const total = categoryTotal.value
  if (hasSearch.value) {
    return total === null
      ? `筛选出 ${filteredItems.value.length} 部`
      : `筛选出 ${filteredItems.value.length} 部 · 共 ${total} 部`
  }
  return total === null ? '共 — 部' : `共 ${total} 部`
})
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
  // A full read supersedes a counts-only refresh still in flight.
  countsSequence += 1
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
    listStatusGroups.value = result?.status_groups ?? null
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
  refreshConnectionStatus()
}

function selectItem(trackingId: string): void {
  selectedTrackingId.value = trackingId
  void router.push(routeLocation('tracking', { tracking_id: trackingId }))
}

/**
 * Row body action follows the mode (D0 row spec): browsing opens the detail,
 * multi-select toggles the batch selection and never changes the detail. The
 * arrow is the one control that always opens the detail.
 */
function activateRow(item: TrackingItem): void {
  if (batchMode.value) {
    toggleRow(item.tracking_id)
    return
  }
  selectItem(item.tracking_id)
}

/**
 * Status-pill tone (D0 row spec §状态药丸). Only existing semantic tokens are
 * used; an unmapped exact status falls back to the neutral `unknown` pair
 * instead of inventing a colour.
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

function statusPillClass(status: string): string {
  return `is-${STATUS_PILL_TONES[status] ?? 'unknown'}`
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
  syncLoading.value = false
}

function hasUnknownCapability(capabilities: CapabilityResult): boolean {
  return capabilities.probe_status !== 'VERIFIED'
    || projectCapabilitySummary(capabilities).some((entry) => entry.state === 'UNKNOWN')
}

/**
 * T6 (#229 F1): one read-only sync when the page is entered.
 *
 * The saved summary is read first, because the endpoint binds to that
 * connection, and entering the page is the only trigger: a re-render, a filter
 * change or opening a record never reaches this function at all. The one-shot
 * flag is defensive on top of that — it keeps a future second entry point (or a
 * kept-alive page) from stacking a second read against the same connection
 * (AC4), while `syncSequence` plus the abort controller keep an older response
 * from overwriting newer state.
 */
function syncOnEntry(): void {
  if (autoSyncArmed) return
  autoSyncArmed = true
  // Issue #86: the saved connection is enough; the server validates it.
  if (!savedRef.value) return
  void syncTracking()
}

async function syncTracking(): Promise<void> {
  // One sync intent at a time, whichever entry asked for it.
  if (syncLoading.value || !savedRef.value) return
  const config = savedRef.value
  const sequence = ++syncSequence
  const controller = new AbortController()
  syncController?.abort()
  syncController = controller
  // The first list read keeps the list's loading state while the entry sync
  // runs; clearing it here would flash the empty state before any rows exist.
  syncLoading.value = true
  syncStatus.value = ''
  try {
    // Like every other read/write on this page, the sync addresses the selected
    // storage profile; without it a non-default profile would sync the root one.
    const body: SyncBody = {
      connection_ref: config.connection_ref!,
      configuration_revision: config.configuration_revision,
      confirm: true,
      ...storageQuery(),
    }
    const result = await api.post<SyncResult>('/api/v1/tracking/sync', { body, signal: controller.signal })
    // Only a newer sync intent or an explicit connection reset can discard this
    // result; list refreshes use their own sequence and revision guard.
    if (sequence !== syncSequence) return
    const incomplete = result.sync_status !== 'COMPLETE'
    const degraded = incomplete || hasUnknownCapability(result.capabilities)
    refreshConnectionStatus()
    if (!degraded && result.items) {
      // Writing the synced revision invalidates list responses already in flight.
      writeGeneration += 1
      items.value = result.items
      detailRevision.value += 1
      syncSelection(true)
      // Issue #224 A5: the sync response carries rows only, so the authoritative
      // total and group metadata are re-read once.  The cards are never
      // recounted from the rows — a sync can add, update or retire records and
      // the four counts must match the list again right after it.
      await loadList(true)
      // A connection reset (or a newer sync intent) during that read owns the
      // page now: never restore the old summary or its success message.
      if (sequence !== syncSequence) return
      // When the entry sync wins the race the first list read is superseded by
      // `writeGeneration` and never reaches its own cleanup, so the sync's
      // re-read is what finally retires the loading state. A first read that
      // finished earlier already cleared it, and the failure/degraded branches
      // leave `loading` to that first read.
      loading.value = false
      // Issue #88: strangers in Auto Bangumi are counted, never imported.
      const message = result.summary.ignored
        ? `同步完成：检查 ${result.summary.checked} 条，新增 ${result.summary.created} 条，更新 ${result.summary.updated} 条；忽略 ${result.summary.ignored} 条不属于 MiGuOrca 管理的外部订阅。`
        : `同步完成：检查 ${result.summary.checked} 条，新增 ${result.summary.created} 条，更新 ${result.summary.updated} 条。`
      if (result.summary.ignored) {
        // B5: a result carrying ignored strangers stays in the bounded list
        // status area instead of disappearing into a toast.
        syncStatus.value = message
      } else {
        notification.show('success', '同步完成', message)
      }
    } else if (incomplete) {
      syncStatus.value = result.sync_status === 'PARTIAL'
        ? '同步部分完成，已保留原有本地列表；重新进入本页会再次只读同步。'
        : '同步未完成，已保留原有本地列表；重新进入本页会再次只读同步。'
    } else if (!result.items) {
      // Defensive: a COMPLETE + verified result without a list snapshot is not
      // the same fact as an unknown capability projection.
      syncStatus.value = '同步已完成，但没有返回列表快照，已保留原有本地列表；重新进入本页会再次只读同步。'
    } else {
      syncStatus.value = '同步已完成，但当前连接能力未知，已降级为只读并保留原有本地列表；重新进入本页会再次只读同步。'
    }
    savedState.value = { ...config, capabilities: result.capabilities }
  } catch (error) {
    if (sequence !== syncSequence) return
    syncStatus.value = '同步 Auto Bangumi 失败，已保留原有本地列表；重新进入本页会再次只读同步。'
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

/**
 * Re-read only the authoritative counts after a settled write (issue #224 A5).
 *
 * The write response carries the row, not the projection, so a status change
 * would otherwise leave the four card numbers on the previous category.  The
 * converged row is deliberately kept: this refresh never replaces the list, it
 * only re-states the server's whole-library summary and group metadata.  A
 * failure is silent — a count refresh must never turn a healthy list into an
 * error state.
 */
async function refreshServerCounts(): Promise<void> {
  const sequence = ++countsSequence
  const generation = writeGeneration
  try {
    const result = await api.get<ListResult>('/api/v1/tracking/items', {
      query: { ...storageQuery(), sort: 'updated_at' },
    })
    if (sequence !== countsSequence || generation !== writeGeneration) return
    listSummary.value = result?.summary ?? null
    listStatusGroups.value = result?.status_groups ?? null
  } catch {
    // Leave the last authoritative projection in place.
  }
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
      // Issue #224 A5: a converged row never moves a category count by itself,
      // so the settled write re-reads the server projection as well.
      if (!effect.refreshList) await refreshServerCounts()
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
  // A different selection is a different batch: retire the locked batch key.
  batchDeleteKey.value = ''
  writes.toggleBatchRow(trackingId)
}

function selectAllCurrent(): void {
  batchDeleteKey.value = ''
  writes.selectAllBatch(filteredItems.value)
}

function clearSelection(): void {
  batchDeleteKey.value = ''
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

// -- explicit batch delete (issue #223) ------------------------------------
const batchDeleteOpen = ref(false)
const batchDeleteBusy = ref(false)
const batchDeleteNotice = ref('')
const batchDeleteOutcome = ref<BatchDeleteResult | null>(null)
/**
 * Issue #223 AC9: the batch idempotency key is locked for one attempt, so a
 * transport retry replays/queries the same batch instead of deleting twice. It
 * is retired once the batch completed or the selection changed.
 */
const batchDeleteKey = ref('')
let batchDeleteSequence = 0

/** One opaque client batch id (same shape the write session uses). */
function makeOpaqueKey(): string {
  const candidate = globalThis.crypto?.randomUUID?.()
  return candidate && /^[A-Za-z0-9-]{8,128}$/.test(candidate)
    ? candidate
    : `batch-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 14)}`
}

/**
 * The local pre-check for a batch delete. It uses only the list evidence the
 * page already holds (status group + exact status); the server re-verifies every
 * entry before it writes. Unknown values are treated as locked (fail closed).
 */
function batchDeleteSkipReason(item: TrackingItem): string | null {
  // The selection lock is the session's single source (ADR-0006 states).
  return writes.batchLockedReason(item)
}

const batchDeletePreview = computed(() => {
  const byId = new Map(items.value.map((item) => [item.tracking_id, item]))
  const deletable: { trackingId: string; revision: number }[] = []
  const skipped: BatchDeleteSkip[] = []
  for (const trackingId of writes.batchSelectedIds()) {
    const item = byId.get(trackingId)
    const title = item?.title || titleFor(trackingId)
    if (!item) {
      skipped.push({ trackingId, title, reason: '不在当前列表中，请刷新后重试' })
      continue
    }
    const reason = batchDeleteSkipReason(item)
    if (reason) {
      skipped.push({ trackingId, title, reason })
      continue
    }
    if (!Number.isInteger(item.revision) || item.revision < 1) {
      skipped.push({ trackingId, title, reason: '缺少可校验的记录版本，请刷新后重试' })
      continue
    }
    deletable.push({ trackingId, revision: item.revision })
  }
  return { deletable, skipped }
})

function openBatchDelete(): void {
  if (batchDeleteBusy.value || batchLoading.value) return
  if (!batchSummary.value.selected) return
  if (!batchDeleteKey.value) batchDeleteKey.value = makeOpaqueKey()
  batchDeleteNotice.value = ''
  batchDeleteOutcome.value = null
  batchDeleteOpen.value = true
}

function cancelBatchDelete(): void {
  batchDeleteOpen.value = false
}

function batchDeleteEntryMessage(entry: BatchDeleteItemResult): string {
  if (entry.outcome === 'DELETED') {
    return entry.external_deleted ? '已删除本地记录，并已删除受控外部订阅' : '已删除本地记录'
  }
  if (entry.outcome === 'EXTERNAL_FAILED') return '外部订阅删除失败：本地方案与记录已保留'
  if (entry.outcome === 'EXTERNAL_UNKNOWN') return '外部删除结果待确认：本地方案与记录已保留，请先核验'
  if (entry.skip_reason === 'UNRESOLVED') return '结果待确认或外部操作进行中：本次跳过，需要逐条处理'
  if (entry.skip_reason === 'REVISION_CHANGED') return '记录已变化：本次跳过，请刷新后重试'
  if (entry.skip_reason === 'NOT_FOUND') return '记录已不存在：本次跳过'
  return '服务端在删除前拒绝了该条目：本次未删除'
}

function applyBatchDeleteResult(result: BatchDeleteResult): void {
  batchDeleteOutcome.value = result
  batchDeleteNotice.value = ''
  const deleted = result.items
    .filter((entry) => entry.outcome === 'DELETED')
    .map((entry) => entry.tracking_id)
  if (deleted.length) writes.removeBatchRows(deleted)
  // The batch completed: a later delete is a new batch with a new key.
  batchDeleteKey.value = ''
  // The server is authoritative: converge the rows, the detail and the counts.
  writeGeneration += 1
  detailRevision.value += 1
  syncSelection(true)
  void loadList(true)
}

/**
 * Run the whole selection through one explicit batch delete.
 *
 * ``deleteExternal`` is the dialog's opt-in; without it the request has no
 * connection fields at all (local-only). Entries the local pre-check excluded
 * are never sent; the server re-verifies the rest and can still skip them.
 */
async function runBatchDelete(deleteExternal: boolean): Promise<void> {
  if (batchDeleteBusy.value || batchLoading.value) return
  const key = batchDeleteKey.value
  if (!key) return
  const preview = batchDeletePreview.value
  if (!preview.deletable.length) {
    batchDeleteOpen.value = false
    batchDeleteNotice.value = '没有可删除的条目：所选记录都需要逐条处理。'
    return
  }
  const config = savedRef.value
  if (deleteExternal && !config?.connection_ref) return
  batchDeleteBusy.value = true
  batchDeleteNotice.value = ''
  batchDeleteOutcome.value = null
  const sequence = ++batchDeleteSequence
  const storageDir = storageQuery().storage_dir
  const items = preview.deletable.map((entry) => ({
    tracking_id: entry.trackingId,
    expected_revision: entry.revision,
  }))
  try {
    const result = deleteExternal
      ? await api.post<BatchDeleteResult>('/api/v1/tracking/batch-delete-plan-external', {
          body: {
            confirm: true,
            idempotency_key: key,
            items,
            connection_ref: String(config?.connection_ref ?? ''),
            configuration_revision: config?.configuration_revision ?? 0,
            ...(storageDir ? { storage_dir: storageDir } : {}),
          },
        })
      : await api.post<BatchDeleteResult>('/api/v1/tracking/batch-delete-plan', {
          body: {
            confirm: true,
            idempotency_key: key,
            items,
            ...(storageDir ? { storage_dir: storageDir } : {}),
          },
        })
    if (sequence !== batchDeleteSequence) return
    applyBatchDeleteResult(result)
  } catch (error) {
    if (sequence !== batchDeleteSequence) return
    const apiError = toApiError(error)
    // The locked batch key stays: the next attempt queries/replays the same
    // batch, so a lost response can never delete something twice.
    batchDeleteNotice.value = apiError.type === 'request_timeout' || apiError.type === 'request_cancelled'
      ? '批量删除未收到结果：批次标识已保留，重新提交会按同一批次查询/重放，不会重复删除。'
      : '批量删除失败，未收到逐条结果；请刷新列表后逐条处理。'
  } finally {
    if (sequence === batchDeleteSequence) {
      batchDeleteBusy.value = false
      batchDeleteOpen.value = false
    }
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
 * Run one explicit unknown-result recovery (US-312 / issue #228).
 *
 * ``VERIFY_EXTERNAL`` is the only recovery left: the read-only external check.
 * It uses the saved connection generation for one verification of the record's
 * own operation and can never create an external write.  It converges on the
 * returned tracking and never resends; the retired local verdicts are rejected
 * by the session before a request exists.
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
 * ``MODIFY``, ``SET_ENABLED`` and ``REFRESH_RSS`` share this single path (the
 * standalone ``DELETE_EXTERNAL`` entry is retired, issue #228).  The session
 * re-validates the emitted request against the current server projection, binds
 * the endpoint/body/confirmation to the validated intent and projects the
 * management verdict; the page owns the confirmation dialog and the transport.
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
  abandon?: boolean
  expectedRevision?: number | null
  expectedOperationId?: string | null
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
  void loadSavedConnection().then(() => {
    // The sync binds to the saved connection, so it can only start after the
    // summary is adopted; `syncOnEntry` keeps it to one run per page entry.
    syncOnEntry()
  })
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
    <!-- B1: the page title/subtitle live in the page header area (like the
         other primary pages), not in a page-level PanelSection card. -->
    <header class="tracking-page-header">
      <div class="tracking-page-heading">
        <h1 id="tracking-heading" class="tracking-page-title">我的追番</h1>
        <p class="tracking-lede">管理待提交任务和正在运行的追番。</p>
      </div>
      <!-- T6 (#229 F1): the manual sync entry is retired; the page syncs once,
           read-only, when it is entered. -->
    </header>

    <section class="tracking-status-overview" aria-labelledby="tracking-status-heading">
      <h2 id="tracking-status-heading" class="tracking-visually-hidden">状态总览</h2>
      <div class="tracking-status-cards">
        <button
          v-for="group in overviewCards"
          :key="group.group"
          type="button"
          class="tracking-status-card"
          :id="`tracking-overview-${group.group.toLowerCase()}`"
          :class="{ 'is-selected': statusFilter === group.group }"
          :aria-pressed="statusFilter === group.group"
          :title="statusFilter === group.group ? '再次点击取消筛选' : undefined"
          @click="selectOverviewGroup(group.group)"
        >
          <span>{{ group.label }}</span><strong>{{ group.count }}</strong>
        </button>
      </div>
    </section>

    <section class="tracking-workspace" aria-label="追番记录与追番详情">
      <section class="panel tracking-list-panel" aria-labelledby="tracking-list-heading">
        <!-- 标题行：左侧标题，右侧「多选/完成」→搜索（搜索靠右）。状态下拉、
             全部、清除筛选、刷新列表都不再出现（C1/C5/2026-10-20 修订）。 -->
        <div class="tracking-list-heading-row">
          <h2 id="tracking-list-heading" class="tracking-list-heading">追番列表</h2>
          <div class="tracking-list-tools">
            <BaseButton id="tracking-batch-mode" variant="secondary" @click="toggleBatchMode">
              {{ batchMode ? '完成' : '多选' }}
            </BaseButton>
            <BaseInput
              id="tracking-search"
              v-model="searchTerm"
              class="tracking-search-input"
              type="search"
              aria-label="搜索标题或字幕组"
              placeholder="搜索番剧名称"
            />
          </div>
        </div>

        <!-- B5: 降级／未完成／含忽略项的同步结果留在列表工具区的有界状态区；
             成功且干净的结果走全局通知。 -->
        <div
          v-if="syncStatus || (batchMode && batchSkippedNotice)"
          class="tracking-toolbar-status"
        >
          <p v-if="syncStatus" id="tracking-sync-status" role="status">{{ syncStatus }}</p>
          <p v-if="batchMode && batchSkippedNotice" id="tracking-batch-skipped" role="status">{{ batchSkippedNotice }}</p>
        </div>

        <!-- 批量工具栏：仅多选态，标题行下方另起一行（#218 补充澄清 + 行规格）。 -->
        <div v-if="batchMode" class="tracking-batch-toolbar" aria-label="批量提交">
          <div class="tracking-batch-selection">
            <span id="tracking-batch-count" class="tracking-batch-count" role="status">
              已选 <strong class="tracking-batch-number">{{ batchSummary.selected }}</strong> 部
            </span>
            <span v-if="batchSummary.hidden" class="tracking-batch-hidden">
              （其中 {{ batchSummary.hidden }} 部不在当前筛选内）
            </span>
            <span class="tracking-batch-dot">·</span>
            <button
              id="tracking-batch-select-all"
              type="button"
              class="tracking-text-button"
              @click="selectAllCurrent"
            >全选当前 {{ filteredItems.length }} 部</button>
            <span class="tracking-batch-dot">·</span>
            <button
              id="tracking-batch-clear"
              type="button"
              class="tracking-text-button"
              :disabled="!batchSummary.selected"
              @click="clearSelection"
            >清除选择</button>
          </div>
          <div class="tracking-batch-actions">
            <!-- Submit stays the rightmost primary action; delete sits before it
                 as the destructive alternative (issue #223). -->
            <BaseButton
              id="tracking-batch-delete"
              variant="danger"
              :loading="batchDeleteBusy"
              :disabled="batchLoading || batchDeleteBusy || !batchSummary.selected"
              @click="openBatchDelete"
            >删除选中</BaseButton>
            <BaseButton
              id="tracking-batch-submit"
              variant="primary"
              :loading="batchLoading"
              :disabled="batchLoading || batchDeleteBusy || !batchSummary.selected || !savedRef"
              @click="runBatchSubmit"
            >提交选中</BaseButton>
          </div>
        </div>
        <!-- Issue 116：缺少已保存连接时批量提交可见但禁用，并就地说明下一步。 -->
        <p v-if="batchMode && !savedRef" id="tracking-batch-connection-required" class="tracking-batch-help" role="status">
          先在设置中连接 Auto Bangumi；缺少已保存连接时不会发起任何外部提交。
        </p>

        <div v-if="loading" class="tracking-list-state"><LoadingState message="正在读取追番列表…" /></div>
        <ErrorState v-else-if="failed" title="追番列表读取失败" message="暂时无法读取本地追番列表，请稍后重试。" retry-label="重试读取" @retry="loadList()" />
        <EmptyState v-else-if="!items.length" message="还没有本地追番记录。" />
        <EmptyState v-else-if="!filteredItems.length" message="没有符合当前搜索或状态筛选的记录。" />

        <!-- C7：提示是独立兄弟节点，绝不因为批量提示而移除列表容器。 -->
        <div
          v-if="!loading && !failed && items.length && filteredItems.length"
          id="tracking-list-container"
          ref="listContainer"
          class="tracking-list"
          tabindex="-1"
          aria-label="追番记录列表"
        >
          <div
            v-for="item in filteredItems"
            :key="item.tracking_id"
            class="tracking-list-row"
            :class="{
              'is-selected': selectedTrackingId === item.tracking_id,
              'is-batch-selected': isBatchSelected(item.tracking_id),
            }"
            :data-tracking-id="item.tracking_id"
          >
            <!-- 共享背景/色条装饰层：detail 选中决定唯一左条，批量选中与悬停只改底色。 -->
            <span class="tracking-row-background" />
            <button
              type="button"
              class="tracking-list-item"
              :data-tracking-id="item.tracking_id"
              :aria-current="selectedTrackingId === item.tracking_id ? 'true' : undefined"
              :disabled="batchMode && Boolean(batchLockedReason(item))"
              @click="activateRow(item)"
            >
              <TrackingPoster :poster-path="item.poster_path" variant="list" />
              <span class="tracking-list-copy">
                <strong class="tracking-list-title">{{ item.title || '未命名番剧' }}</strong>
                <span class="tracking-list-season">{{ item.season ? `第 ${item.season} 季` : '季度未设置' }}</span>
              </span>
              <span class="tracking-status-pill" :class="statusPillClass(item.status)">{{ item.status_label }}</span>
            </button>
            <button
              type="button"
              class="tracking-list-arrow"
              tabindex="-1"
              aria-hidden="true"
              @click="selectItem(item.tracking_id)"
            >
              <span class="tracking-list-chevron" />
            </button>
          </div>
        </div>
        <p v-if="selectedHidden" class="tracking-selection-note" role="status">当前选择被筛选条件隐藏，未自动切换记录。</p>
        <!-- B5：批量结果搬进列表模块内部有界区域，不再作为工作区兄弟节点。 -->
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
        <!-- Issue #223: per-entry batch delete results stay inside the same
             bounded area; failed entries are handled one by one (no retry-all). -->
        <section
          v-if="batchMode && (batchDeleteOutcome || batchDeleteNotice)"
          id="tracking-batch-delete-result"
          class="tracking-batch-result"
          aria-labelledby="tracking-batch-delete-heading"
          role="status"
        >
          <h2 id="tracking-batch-delete-heading">批量删除结果</h2>
          <p v-if="batchDeleteNotice" id="tracking-batch-delete-notice" class="tracking-batch-verdict">{{ batchDeleteNotice }}</p>
          <p v-if="batchDeleteOutcome" id="tracking-batch-delete-summary" class="tracking-batch-verdict">
            已删除 {{ batchDeleteOutcome.summary.deleted }} 条<template v-if="batchDeleteOutcome.summary.external_deleted">（其中 {{ batchDeleteOutcome.summary.external_deleted }} 条同时删除了受控外部订阅）</template>；
            跳过 {{ batchDeleteOutcome.summary.skipped }} 条；外部删除失败 {{ batchDeleteOutcome.summary.failed }} 条、结果待确认 {{ batchDeleteOutcome.summary.unknown }} 条。
            失败项只能逐条处理。
          </p>
          <ul v-if="batchDeleteOutcome" class="tracking-batch-entries">
            <li
              v-for="entry in batchDeleteOutcome.items"
              :key="entry.tracking_id"
              :class="entry.outcome === 'DELETED' ? 'is-ok' : 'is-failed'"
            >
              <strong>{{ titleFor(entry.tracking_id) }}</strong>：{{ batchDeleteEntryMessage(entry) }}
            </li>
          </ul>
        </section>
        <!-- Issue #224 A5: the count lives at the list bottom; N stays the
             server's whole-library category count and never a frontend recount. -->
        <p v-if="!loading && !failed" class="tracking-list-count" role="status">{{ listCountText }}</p>
      </section>

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
    <TrackingBatchDeleteDialog
      :open="batchDeleteOpen"
      :count="batchDeletePreview.deletable.length"
      :skipped="batchDeletePreview.skipped"
      :external-available="Boolean(savedRef?.connection_ref)"
      :busy="batchDeleteBusy"
      @confirm="runBatchDelete"
      @cancel="cancelBatchDelete"
    />
  </section>
</template>

<style scoped>
/* 页面骨架（B1/B3/B4）：标题回到页头，状态总览留在模块外，工作区占满剩余
 * 视口高度；两栏等高、各自内滚。低于 320px 保底时允许整页滚动（降级）。 */
.tracking-overview {
  display: flex;
  flex-direction: column;
  gap: var(--space-5);
  min-height: 0;
}

@media (min-width: 761px) {
  .tracking-overview {
    /* The shell owns the header height and the main padding; 2px is the
       sub-pixel safety slack that keeps a fractional viewport from producing a
       document scrollbar on the acceptance canvas. */
    height: calc(100vh - var(--size-shell-header) - 2 * var(--space-6) - 2px);
  }
}

.tracking-page-header {
  display: flex;
  flex-wrap: wrap;
  align-items: flex-end;
  justify-content: space-between;
  gap: var(--space-4);
}
.tracking-page-heading { display: grid; gap: var(--space-1); }
.tracking-page-title {
  margin: 0;
  font-size: var(--type-display);
  line-height: var(--type-display-line-height);
  font-weight: var(--font-weight-bold);
}
.tracking-lede { margin: 0; color: var(--color-text-muted); }

.tracking-visually-hidden {
  position: absolute;
  inline-size: 1px;
  block-size: 1px;
  overflow: hidden;
  clip-path: inset(50%);
  white-space: nowrap;
}

.tracking-status-overview { display: grid; gap: var(--space-3); }
.tracking-status-overview h2, .tracking-inspector h2 { margin: 0; font-size: 1.05rem; }
.tracking-status-cards { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: var(--space-3); }
.tracking-status-card { display: grid; gap: .35rem; text-align: left; padding: var(--space-3); border: 1px solid var(--color-border); border-radius: var(--radius-md); background: var(--color-surface); color: var(--color-text); cursor: pointer; }
.tracking-status-card:hover, .tracking-status-card:focus-visible, .tracking-status-card.is-selected { border-color: var(--color-primary); box-shadow: 0 0 0 2px color-mix(in srgb, var(--color-primary) 18%, transparent); }
.tracking-status-card strong { font-size: 1.35rem; }

/* 工作区：两栏等高；列表与详情的滚动互不影响。 */
.tracking-workspace {
  flex: 1 1 auto;
  min-height: 320px;
  display: grid;
  grid-template-columns: minmax(0, 3fr) minmax(18rem, 2fr);
  gap: var(--space-5);
  align-items: stretch;
}

.tracking-list-panel {
  display: flex;
  flex-direction: column;
  min-height: 0;
  min-width: 0;
  margin-bottom: 0;
  padding: 0;
  overflow: hidden;
}
.tracking-list-heading-row {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--space-3);
  padding: var(--space-4) var(--space-5) var(--space-2);
}
.tracking-list-heading {
  margin: 0;
  font-size: var(--type-section-title);
  font-weight: var(--font-weight-semibold);
  color: var(--color-text);
}
.tracking-list-tools {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--space-3);
  margin-inline-start: auto;
}
.tracking-list-tools :deep(.base-button:hover:not(:disabled)) { transform: none; }
.tracking-search-input {
  inline-size: var(--tracking-search-width);
  min-inline-size: var(--tracking-search-min-width);
  flex: 0 1 auto;
}

/* B5 有界状态区：降级/未完成/含忽略项的同步结果与批量跳过提示。 */
.tracking-toolbar-status {
  display: grid;
  gap: var(--space-1);
  max-block-size: 5.5rem;
  overflow-y: auto;
  margin: 0 var(--space-5) var(--space-2);
  padding: var(--space-2) var(--space-3);
  border-radius: var(--radius-sm);
  background: var(--color-surface-subtle);
  color: var(--color-text-muted);
  font-size: var(--font-size-sm);
}
.tracking-toolbar-status p { margin: 0; }

/* 批量工具栏：无边框/阴影/卡片底；标题行下方独立一行。 */
.tracking-batch-toolbar {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--space-4);
  padding: var(--space-2) var(--space-5);
}
.tracking-batch-selection {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 0;
  min-inline-size: 0;
}
.tracking-batch-count {
  color: var(--color-text-secondary);
  font-size: var(--font-size-sm);
  font-weight: var(--font-weight-medium);
  white-space: nowrap;
}
.tracking-batch-number { font-weight: var(--font-weight-semibold); }
.tracking-batch-hidden { color: var(--color-text-muted); font-size: var(--font-size-sm); }
.tracking-batch-dot { color: var(--color-text-disabled); margin-inline: var(--space-2); }
.tracking-text-button {
  min-block-size: var(--control-target-min);
  padding: 0 var(--space-2);
  border: 0;
  border-radius: var(--radius-sm);
  background: transparent;
  color: var(--color-primary);
  font-size: var(--font-size-sm);
  font-weight: var(--font-weight-medium);
  cursor: pointer;
}
.tracking-text-button:hover:not(:disabled) { background: var(--color-primary-subtle); }
.tracking-text-button:disabled { color: var(--color-text-disabled); cursor: not-allowed; }
.tracking-batch-actions { margin-inline-start: auto; display: flex; flex-wrap: wrap; gap: var(--space-2); }
.tracking-batch-help {
  margin: 0 var(--space-5) var(--space-2);
  color: var(--color-text-muted);
  font-size: var(--font-size-sm);
}

/* 列表：单列、无卡片间距；行内滚动由容器负责。 */
.tracking-list {
  display: grid;
  gap: 0;
  flex: 1 1 auto;
  min-block-size: 0;
  overflow-y: auto;
  overscroll-behavior: contain;
}
.tracking-list-row {
  position: relative;
  display: grid;
  grid-template-columns: minmax(0, 1fr) var(--control-target-min);
  align-items: stretch;
  gap: var(--space-3);
  padding: var(--space-3) var(--space-4);
  /* 底部 1px 线槽由行自身保留，末行无线也不跳高度。 */
  padding-block-end: calc(var(--space-3) + var(--control-border-width));
  min-block-size: var(--tracking-row-min-height);
}
.tracking-list-row::after {
  content: '';
  position: absolute;
  inset-inline: var(--space-4);
  inset-block-end: 0;
  block-size: var(--control-border-width);
  background: var(--color-border-subtle);
}
.tracking-list-row:last-child::after { background: transparent; }

/* 共享背景/色条装饰层：只过渡 background-color；左条只由 detail 选中决定。 */
.tracking-row-background {
  position: absolute;
  inset: 0 0 var(--control-border-width) 0;
  border-radius: var(--radius-md);
  overflow: hidden;
  pointer-events: none;
  background-color: transparent;
  transition: background-color var(--motion-duration-fast) var(--motion-easing-standard);
}
.tracking-list-row:hover .tracking-row-background,
.tracking-list-row.is-selected .tracking-row-background,
.tracking-list-row.is-batch-selected .tracking-row-background {
  background-color: var(--color-info-surface);
}
.tracking-list-row.is-selected .tracking-row-background::before {
  content: '';
  position: absolute;
  inset-block: 0;
  inset-inline-start: 0;
  inline-size: var(--space-1);
  background: var(--color-primary);
}

/* 行体：原生 button，包含封面/标题/季度/状态药丸；自身无 padding/border/背景。 */
.tracking-list-item {
  position: relative;
  display: grid;
  grid-template-columns: var(--tracking-poster-width) minmax(0, 1fr) auto;
  align-items: center;
  gap: var(--space-3);
  min-inline-size: 0;
  padding: 0;
  border: 0;
  background: transparent;
  color: var(--color-text);
  text-align: start;
  cursor: pointer;
}
.tracking-list-item:disabled { cursor: not-allowed; }
.tracking-list-item:focus-visible,
.tracking-list-arrow:focus-visible {
  outline: var(--focus-ring-width) solid var(--color-focus-ring);
  outline-offset: calc(-1 * var(--focus-ring-width));
  border-radius: var(--radius-sm);
}
.tracking-list-copy { display: grid; gap: var(--space-1); min-inline-size: 0; }
.tracking-list-title {
  font-size: var(--type-card-title);
  line-height: var(--line-height-tight);
  font-weight: var(--font-weight-semibold);
  color: var(--color-text);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.tracking-list-season {
  font-size: var(--type-label);
  font-weight: var(--font-weight-regular);
  color: var(--color-text-muted);
}
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

/* 箭头：固定末列 44px 矩形热区，两种模式都看详情，不进入 Tab 序列。 */
.tracking-list-arrow {
  position: relative;
  display: flex;
  align-items: center;
  justify-content: center;
  inline-size: var(--control-target-min);
  min-block-size: var(--control-target-min);
  padding: 0;
  border: 0;
  background: transparent;
  color: var(--color-text-muted);
  cursor: pointer;
}
.tracking-list-chevron {
  position: relative;
  inline-size: var(--icon-md);
  block-size: var(--icon-md);
}
.tracking-list-chevron::before {
  content: '';
  position: absolute;
  inset-inline-start: 6px;
  inset-block-start: 7px;
  inline-size: 8px;
  block-size: 8px;
  border-block-start: 2px solid var(--color-text-muted);
  border-inline-end: 2px solid var(--color-text-muted);
  transform: rotate(45deg);
}

.tracking-list-state { flex: 1 1 auto; min-block-size: 8rem; }
.tracking-selection-note {
  margin: 0;
  padding: var(--space-1) var(--space-5);
  color: var(--color-text-muted);
  font-size: var(--font-size-sm);
}
.tracking-list-count {
  margin: 0;
  padding: var(--space-3) var(--space-5);
  color: var(--color-text-muted);
}

/* 批量结果：列表模块内部有界区域（不再拉长整页）。 */
.tracking-batch-result {
  display: grid;
  gap: var(--space-2);
  max-block-size: 9rem;
  overflow-y: auto;
  margin: 0 var(--space-5) var(--space-2);
  padding: var(--space-3);
  border-radius: var(--radius-sm);
  background: var(--color-surface-subtle);
}
.tracking-batch-result h2 { margin: 0; font-size: 1.05rem; }
.tracking-batch-verdict { margin: 0; font-weight: var(--font-weight-semibold); }
.tracking-batch-entries { display: grid; gap: .3rem; margin: 0; padding-inline-start: 1.2rem; }
.tracking-batch-entries li.is-failed { color: var(--color-danger); }

/* 详情栏与列表等高，自己内滚；导航/标题/状态总览留在模块外。 */
.tracking-inspector {
  display: block;
  min-height: 0;
  overflow-y: auto;
  overscroll-behavior: contain;
  padding: var(--space-4) var(--space-5);
  border: 1px solid var(--color-border-subtle);
  border-radius: var(--radius-lg);
  background: var(--color-bg);
}

/* 低高度降级（B4）：两栏保底 320px 后，批量工具栏/状态区/结果区可能挤占列表；
 * 此时让整块列表面板滚动（列表本身不再二次内滚），内容始终可达。 */
@media (max-height: 640px) {
  .tracking-list-panel { overflow-y: auto; }
  .tracking-list { flex: 0 0 auto; overflow-y: visible; min-block-size: 0; }
}

/* ≤760px：只用壳层断点纵向重排；标题与多选/完成同一行、搜索独占下一行；批量
 * 左组先排、提交选中独占下一行占满宽度；无横向滚动、允许整页滚动。 */
@media (max-width: 760px) {
  .tracking-overview { height: auto; }
  .tracking-status-cards { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .tracking-workspace {
    grid-template-columns: 1fr;
    min-height: 0;
  }
  .tracking-list-panel, .tracking-inspector { min-block-size: 320px; }
  .tracking-list-heading-row {
    display: grid;
    grid-template-columns: minmax(0, 1fr) auto;
    align-items: center;
  }
  .tracking-list-tools { display: contents; }
  .tracking-list-tools :deep(.base-button) { grid-column: 2; grid-row: 1; }
  .tracking-search-input {
    grid-column: 1 / -1;
    grid-row: 2;
    inline-size: 100%;
    min-inline-size: 0;
  }
  .tracking-batch-toolbar { align-items: flex-start; }
  .tracking-batch-selection { inline-size: 100%; }
  .tracking-batch-actions { inline-size: 100%; margin-inline-start: 0; }
  .tracking-batch-actions :deep(.base-button) { inline-size: 100%; }
}
</style>
