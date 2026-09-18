<script setup lang="ts">
// 批量工作台 (US-205).
//
// Migrated from the legacy `/index` 批量搜索 tab onto the shared primitives
// and the generated OpenAPI client. The batch workbench is a separate panel
// below the single-search workbench (the old tab layout is replaced by a
// dedicated 批量工作台 section on /app/add):
//
//   - batch input (textarea, one title per line) → POST /api/v1/batches/parse
//     returns independent FOUND / EMPTY / FAILED cards plus a batch_id;
//   - each FOUND card selects the current detail item; the right-hand
//     CandidateCollectionList chooses a candidate and generates a server-authoritative
//     server-authoritative draft into the card;
//   - DRAFT cards open the shared AnimeDraftEditor (preview-modify) plus a
//     batch-specific 加入批量确认 / 删除当前批量卡片 action row;
//     action row;
//   - the accept toolbar offers select-all, a live selected count, 批量接受
//     (selected) and 全接受 (all reviewable cards), through generated atomic
//     POST /api/v1/batches/{batch_id}/save-confirm;
//   - batch_id is pushed into the URL so a refresh restores the queue (the
//     queue panel itself lands in US-206).
//
// Security boundary: batch items/candidates are the public whitelist only;
// candidate_context / draft_id live only in component memory (never URL/
// storage/logs). Accept payloads carry only item_id/request_id/title (public
// fields) + storage_dir (relative profile). Destructive/irreversible actions
// go through the shared ConfirmDialog and failures surface fixed Chinese copy
// only.
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import { api, toApiError } from '@/api/client'
import { useLeaveGuard } from '@/app/composables/useLeaveGuard'
import { useDraftSession, type DraftSession } from '@/app/composables/useDraftSession'
import { toSafeBatchError, useBatchReviewJourney } from '@/app/composables/useBatchReviewJourney'
import { useNotificationStore } from '@/app/stores/notification'
import ConfirmDialog from '@/components/feedback/ConfirmDialog.vue'
import EmptyState from '@/components/feedback/EmptyState.vue'
import ErrorState from '@/components/feedback/ErrorState.vue'
import LoadingState from '@/components/feedback/LoadingState.vue'
import BaseButton from '@/components/forms/BaseButton.vue'
import CheckboxRow from '@/components/forms/CheckboxRow.vue'
import PanelSection from '@/components/layout/PanelSection.vue'
import AnimeTitleInput from '@/features/workbench/AnimeTitleInput.vue'
import AnimeDraftEditor from '@/features/workbench/AnimeDraftEditor.vue'
import CandidateCollectionList from '@/features/workbench/CandidateCollectionList.vue'
import { useDraftEditScheduler, type DraftEditScheduler } from '@/features/workbench/draftEditScheduler'

import {
  batchAcceptAllScopeText,
  batchSaveConfirmErrorLabel,
  batchSaveConfirmRecoveryAllowed,
  batchSaveConfirmSucceeded,
  findBatchTrackingItem,
  batchCardNeedsReview,
  batchCardPreferenceSummary,
  batchCardRequest,
  batchCardSeedSummary,
  batchCardTitle,
  batchItemMatchesReviewFilters,
  batchEpisodeProgressText,
  batchItemCount,
  batchStatusLabel,
  buildBatchSaveConfirmPayload,
  buildBatchCandidateCreatePayload,
  buildBatchParsePayload,
  canChooseBatchCandidate,
  canExpandBatchCard,
  orderBatchItemsForReview,
  nextBatchException,
  validateBatchRawInput,
  type BatchSaveConfirmDescriptor,
  type BatchSaveConfirmResult,
  type BatchCandidate,
  type BatchItem,
  type BatchParseResult,
} from '@/features/workbench/batchWorkbench'
import { displayValue, type RequestSnapshot } from '@/features/requests/requestDetail'
import type { PreviewEditState } from '@/features/workbench/candidateSearch'
import { currentStorageDir, storageQuery } from '@/features/requests/requestStorage'
import { isPublicRouteIdentifier, routeLocation } from '@/app/router/catalog'
import {
  batchItemFailureMessage,
  batchParseTimeoutMs,
  MIKAN_DRAFT_GENERATION_TIMEOUT_MS,
  mikanFailureMessage,
} from './mikanFeedback'

type CreateRequestResult = NonNullable<
  import('@/api/generated/api').operations['createRequest']['responses']['200']['content']['application/json']['result']
>

const route = useRoute()
const router = useRouter()
const notification = useNotificationStore()
const confirmDialog = ref<InstanceType<typeof ConfirmDialog> | null>(null)
// The journey owns route-local review order, current item and selection. The
// API result below is only the public source snapshot used to render cards;
// lifecycle decisions are dispatched through this reactive state machine.
const journey = useBatchReviewJourney()

const props = withDefaults(defineProps<{ rawInput?: string; hideInput?: boolean }>(), { rawInput: '', hideInput: false })
const emit = defineEmits<{ (event: 'update:rawInput', value: string): void }>()

// Batch parse state.
const rawInput = ref(props.rawInput)

watch(() => props.rawInput, (value) => {
  if (value !== rawInput.value) rawInput.value = value
})

watch(rawInput, (value) => emit('update:rawInput', value))
const parseLoading = ref(false)
const parseBlocked = computed(() => parseLoading.value || Boolean(saveOperation.value) || saveInFlight.value || savingItemIds.value.size > 0 || draftCreateItemIds.value.size > 0)
const parseError = ref('')
const parseResult = ref<BatchParseResult | null>(null)
const items = ref<BatchItem[]>([])
const batchId = ref('')
const loadingMessage = ref('')
const parseCount = ref(0)
const currentItemId = computed<string | null>({
  get: () => journey.state.currentItemId,
  set: (value) => {
    if (value && journey.state.items[value]) journey.dispatch({ type: 'set_current', itemId: value })
  },
})
const inputItemOrder = ref<Map<string, number>>(new Map())

// Selection / accept state.
const selectedItemIds = computed<Set<string>>({
  get: () => new Set(Object.values(journey.state.items).filter((item) => item.selected).map((item) => item.itemId)),
  set: (next) => {
    for (const item of Object.values(journey.state.items)) {
      const selected = next.has(item.itemId)
      if (selected !== item.selected) journey.dispatch({ type: 'set_selected', itemId: item.itemId, selected })
    }
  },
})
const draftCreateItemIds = ref<Set<string>>(new Set())
// US-343: the candidate each item is currently generating a draft from, and the
// sanitized failure that stays beside that candidate. Both are keyed by item so
// one item's generation can never mark another item as loading or failing.
const draftCreateCandidateIds = ref<Record<string, string>>({})
const draftCreateErrors = ref<Record<string, Record<string, string>>>({})
const saveInFlight = ref(false)
const acceptFeedback = ref<Record<string, string>>({})
const savingItemIds = ref<Set<string>>(new Set())
const saveSummary = ref<Record<string, number>>({})
type FrozenBatchSaveOperation = {
  itemIds: string[]
  body: ReturnType<typeof buildBatchSaveConfirmPayload>
  phase: 'sending' | 'response_unknown'
}
const saveOperation = ref<FrozenBatchSaveOperation | null>(null)
const recoveryLoadingItemIds = ref<Set<string>>(new Set())
const recoveryFeedback = ref<Record<string, string>>({})

function batchItemRequestId(item: BatchItem): string {
  const value = (item as Record<string, unknown>).request_id
  return typeof value === 'string' ? value : ''
}

function batchItemTrackingId(item: BatchItem): string {
  const value = (item as Record<string, unknown>).tracking_id
  return typeof value === 'string' ? value : ''
}

// Candidate confirmation state (component memory only).
const seasonConfirmations = ref<Record<string, number | null>>({})

// Draft detail state.
const detailItemId = ref<string | null>(null)
// One route-local session per draft item. The card shortcut and the detail
// editor both use this map, so snapshots, revisions, dirty state and errors
// cannot diverge between the two surfaces.
const draftSessions = new Map<string, DraftSession>()
const draftApplyErrors = ref<Record<string, string>>({})
// US-344: one edit scheduler per item, paired with the session it was built
// for. Both surfaces (card shortcut and right-hand detail) drive the same
// scheduler, so a revision can never be used by two requests at once.
const editSchedulers = new Map<string, { session: DraftSession; scheduler: DraftEditScheduler }>()
const detailEditor = ref<InstanceType<typeof AnimeDraftEditor> | null>(null)

function ensureDraftSession(item: BatchItem): DraftSession | null {
  const itemId = item.item_id
  const request = batchCardRequest(item)
  if (!itemId || !request || !item.draft_id) return null
  const existing = draftSessions.get(itemId)
  if (existing && existing.draftId.value === item.draft_id) return existing
  const session = useDraftSession({
    request,
    draftId: item.draft_id,
    draftRevision: item.draft_revision ?? 1,
  })
  draftSessions.set(itemId, session)
  return session
}

/** The item's edit scheduler, recreated whenever its session is replaced. */
function ensureScheduler(item: BatchItem): DraftEditScheduler | null {
  const itemId = item.item_id
  const session = ensureDraftSession(item)
  if (!itemId || !session) return null
  const existing = editSchedulers.get(itemId)
  if (existing && existing.session === session) return existing.scheduler
  existing?.scheduler.dispose()
  const scheduler = useDraftEditScheduler({
    session,
    storageDir: () => storageQuery().storage_dir ?? null,
    onSending: () => {
      // Keep the review journal in step with the transport: a send may follow
      // a previous failure, so both transitions are attempted.
      journey.dispatch({ type: 'retry_apply', itemId })
      journey.dispatch({ type: 'begin_apply', itemId })
    },
    onApplied: () => {
      onDraftChanged(itemId, {
        request: (session.request.value ?? batchCardRequest(item)) as RequestSnapshot,
        draftId: session.draftId.value ?? '',
        draftRevision: session.draftRevision.value ?? 1,
      })
    },
    onInvalid: () => onDraftExpired(itemId),
    onFailed: () => {
      draftApplyErrors.value = { ...draftApplyErrors.value, [itemId]: '订阅草案修改失败，请稍后重试。' }
      journey.dispatch({ type: 'apply_failed', itemId, error: session.error.value })
    },
  })
  editSchedulers.set(itemId, { session, scheduler })
  return scheduler
}

function disposeScheduler(itemId: string): void {
  editSchedulers.get(itemId)?.scheduler.dispose()
  editSchedulers.delete(itemId)
}

/** Displayed subtitle group for a card: unconfirmed intent first. */
function cardSubtitleGroupValue(item: BatchItem): string {
  const pending = editSchedulers.get(item.item_id ?? '')?.scheduler.pendingGroup.value
  if (pending) return pending
  return batchCardRequest(item)?.confirmable_config?.selected_subtitle_group ?? ''
}

interface BatchItemConfirmability {
  confirmable: boolean
  blockers: string[]
  session: DraftSession | null
}

/** The single qualification gate shared by cards, detail and save actions. */
function itemConfirmability(itemId: string): BatchItemConfirmability {
  const item = items.value.find((candidate) => candidate.item_id === itemId)
  const journeyItem = journey.state.items[itemId]
  const blockers: string[] = []
  if (!item || !canExpandBatchCard(item) || !batchCardRequest(item)) blockers.push('需先生成可审核草案')
  const session = item ? ensureDraftSession(item) : null
  const draftId = session?.draftId.value ?? item?.draft_id
  const revision = session?.draftRevision.value ?? item?.draft_revision
  if (!draftId || !draftId.trim()) blockers.push('草案能力无效')
  if (!Number.isInteger(revision) || (revision ?? 0) <= 0) blockers.push('草案版本无效')
  if (!session || session.invalid.value) blockers.push('订阅草案已失效')
  const scheduler = item ? ensureScheduler(item) : null
  // A local edit is never confirmed implicitly: it must reach the server first.
  if (scheduler?.waiting.value) blockers.push('有尚未应用的编辑，正在等待过滤规则自动更新')
  else if (scheduler?.folderPending.value) blockers.push('有尚未应用的编辑，等待提交目录名')
  else if (session?.dirty.value || scheduler?.groupPending.value) blockers.push('有尚未应用的编辑')
  if (session?.applying.value) blockers.push('正在重新计算资源')
  if (session?.error.value || session?.canRetry.value) blockers.push('修改失败，请重试或恢复最后一致值')
  if (savingItemIds.value.has(itemId) || item?.status === 'RESPONSE_UNKNOWN' || journeyItem?.phase === 'saving' || journeyItem?.phase === 'response_unknown') blockers.push('保存结果待核验')
  const request = item ? batchCardRequest(item) : null
  const selectedGroup = request?.confirmable_config?.selected_subtitle_group
  if (!selectedGroup || !String(selectedGroup).trim()) blockers.push('请选择有效字幕组')
  const seeds = request?.confirmable_config?.effective_seed_names ?? []
  if (!seeds.some((seed) => typeof seed === 'string' && seed.trim())) blockers.push('没有有效资源')
  return { confirmable: blockers.length === 0, blockers, session }
}

function hasUnsafeBatchWork(): boolean {
  return Boolean(
    parseLoading.value ||
    draftCreateItemIds.value.size > 0 ||
    saveInFlight.value ||
    savingItemIds.value.size > 0 ||
    recoveryLoadingItemIds.value.size > 0 ||
    selectedItemIds.value.size > 0 ||
    items.value.some((item) => {
      if (['CONFIRMED', 'SAVED_PENDING_CONFIRM'].includes(String(item.status ?? ''))) return false
      const session = draftSessions.get(item.item_id ?? '')
      return Boolean(canChooseBatchCandidate(item) || session?.draftId.value || session?.dirty.value || session?.applying.value)
    }),
  )
}

function clearBatchRouteLocalState(): void {
  for (const { scheduler } of editSchedulers.values()) scheduler.dispose()
  editSchedulers.clear()
  for (const session of draftSessions.values()) session.invalidate()
  draftSessions.clear()
  saveOperation.value = null
  draftCreateItemIds.value = new Set()
  draftCreateCandidateIds.value = {}
  draftCreateErrors.value = {}
  selectedItemIds.value = new Set()
  journey.dispatch({ type: 'clear_route' })
}

// Review filters affect visibility only. The parsed order remains frozen until
// the user explicitly asks for exception-first sorting.
const reviewQuery = ref('')
const reviewStatus = ref('')
const exceptionsOnly = ref(false)
const exceptionSorted = ref(false)
const reviewList = ref<HTMLElement | null>(null)
const reviewScrollPositions = new Map<string, number>()
const cardElements = new Map<string, HTMLElement>()
const temporarilyShownItemId = ref<string | null>(null)
const focusAnnouncement = ref('')
const reviewFilterKey = computed(() => `${reviewQuery.value}\u0000${reviewStatus.value}\u0000${exceptionsOnly.value}`)

const selectable = computed(() => visibleItems.value.filter((item) => itemConfirmability(item.item_id ?? '').confirmable))
const selectedCount = computed(
  () => visibleItems.value.filter((item) => selectedItemIds.value.has(item.item_id ?? '') && itemConfirmability(item.item_id ?? '').confirmable).length,
)
const processingCount = computed(() => items.value.filter((item) => draftSessions.get(item.item_id ?? '')?.applying.value).length)
const confirmableCount = computed(() => visibleItems.value.filter((item) => itemConfirmability(item.item_id ?? '').confirmable).length)
const needsProcessingCount = computed(() => visibleItems.value.filter((item) => !itemConfirmability(item.item_id ?? '').confirmable).length)
const allSelected = computed(
  () => selectable.value.length > 0 && selectable.value.every((item) => selectedItemIds.value.has(item.item_id ?? '')),
)

const detailItem = computed(() =>
  (detailItemId.value || currentItemId.value)
    ? items.value.find((item) => item.item_id === (detailItemId.value || currentItemId.value)) ?? null
    : null,
)
const visibleItems = computed(() => items.value.filter((item) =>
  item.item_id === temporarilyShownItemId.value || batchItemMatchesReviewFilters(item, {
    query: reviewQuery.value,
    status: reviewStatus.value,
    exceptionsOnly: exceptionsOnly.value,
  }),
))
// US-347: 保存并确认全部 的范围是完整批次，不是当前可见子集。筛选和
// 「全选当前可见可确认项」只改变浏览，因此 all 的资格集合、按钮可用性、M 计数、
// 弹窗数量和描述符都必须来自下面同一个完整批次集合。
const batchConfirmable = computed(() => items.value.filter((item) => itemConfirmability(item.item_id ?? '').confirmable))
const batchConfirmableCount = computed(() => batchConfirmable.value.length)
const batchHiddenConfirmableCount = computed(() => {
  const visibleIds = new Set(visibleItems.value.map((item) => item.item_id))
  return batchConfirmable.value.filter((item) => !visibleIds.has(item.item_id)).length
})
const batchAcceptAllScope = computed(() => batchAcceptAllScopeText({
  total: items.value.length,
  confirmable: batchConfirmableCount.value,
  hidden: batchHiddenConfirmableCount.value,
}))

function saveReviewScrollPosition(): void {
  if (reviewList.value) reviewScrollPositions.set(reviewFilterKey.value, reviewList.value.scrollTop)
}

async function restoreReviewScrollPosition(): Promise<void> {
  await nextTick()
  if (reviewList.value) reviewList.value.scrollTop = reviewScrollPositions.get(reviewFilterKey.value) ?? 0
}

watch([reviewQuery, reviewStatus, exceptionsOnly], (_values, oldValues) => {
  if (reviewList.value) {
    const [query, status, exceptions] = oldValues
    reviewScrollPositions.set(`${query}\u0000${status}\u0000${exceptions}`, reviewList.value.scrollTop)
  }
  void restoreReviewScrollPosition()
})

function clearReviewFilters(): void {
  reviewQuery.value = ''
  reviewStatus.value = ''
  exceptionsOnly.value = false
  temporarilyShownItemId.value = null
}

function sortExceptionsFirst(): void {
  saveReviewScrollPosition()
  items.value = orderBatchItemsForReview(items.value)
  exceptionSorted.value = true
  void restoreReviewScrollPosition()
}

function selectCurrentItem(item: BatchItem): void {
  const previousId = detailItemId.value ?? currentItemId.value
  const nextId = item.item_id ?? null
  if (previousId && previousId !== nextId) {
    // US-344: leaving an item cancels its debounce window and drops intent the
    // user can no longer see; a late response for it can never touch the new
    // item because every session and scheduler is keyed by item_id.
    const leaving = editSchedulers.get(previousId)
    leaving?.scheduler.cancelTimer()
    leaving?.scheduler.dropPending()
  }
  currentItemId.value = nextId
  detailItemId.value = nextId
}

function setCardElement(itemId: string | null | undefined, element: unknown): void {
  if (!itemId) return
  if (element instanceof HTMLElement) cardElements.set(itemId, element)
  else cardElements.delete(itemId)
}

function focusCard(itemId: string): void {
  void nextTick(() => {
    const card = cardElements.get(itemId)
    if (!card) return
    card.focus({ preventScroll: true })
    const reducedMotion = typeof window.matchMedia === 'function' && window.matchMedia('(prefers-reduced-motion: reduce)').matches
    if (typeof card.scrollIntoView === 'function') {
      card.scrollIntoView({ block: 'nearest', behavior: reducedMotion ? 'auto' : 'smooth' })
    }
  })
}

function activateCard(item: BatchItem): void {
  selectCurrentItem(item)
  if (canExpandBatchCard(item)) openDraftDetail(item)
}

function moveCardFocus(item: BatchItem, direction: 1 | -1): void {
  const visible = visibleItems.value
  if (!visible.length) return
  const currentIndex = visible.findIndex((candidate) => candidate.item_id === item.item_id)
  const nextIndex = currentIndex < 0
    ? (direction > 0 ? 0 : visible.length - 1)
    : (currentIndex + direction + visible.length) % visible.length
  const next = visible[nextIndex]
  if (!next) return
  selectCurrentItem(next)
  focusCard(next.item_id ?? '')
}

function onCardKeydown(event: KeyboardEvent, item: BatchItem): void {
  if (event.key === 'ArrowDown' || event.key === 'ArrowRight') {
    event.preventDefault()
    moveCardFocus(item, 1)
  } else if (event.key === 'ArrowUp' || event.key === 'ArrowLeft') {
    event.preventDefault()
    moveCardFocus(item, -1)
  } else if (event.key === 'Enter') {
    event.preventDefault()
    activateCard(item)
  }
}

function goToNextException(): void {
  const next = nextBatchException(items.value, currentItemId.value)
  if (!next?.item_id) return
  const hidden = !batchItemMatchesReviewFilters(next, {
    query: reviewQuery.value,
    status: reviewStatus.value,
    exceptionsOnly: exceptionsOnly.value,
  })
  temporarilyShownItemId.value = hidden ? next.item_id : null
  selectCurrentItem(next)
  focusAnnouncement.value = hidden ? `已临时显示异常条目：${batchCardTitle(next)}` : `已定位到异常条目：${batchCardTitle(next)}`
  focusCard(next.item_id)
}

function syncBatchIdToUrl(batchIdValue: string): void {
  if (batchIdValue) {
    void router.replace(routeLocation('add', { batch_id: batchIdValue }))
  } else {
    void router.replace(routeLocation('add'))
  }
}

async function parseBatch(): Promise<void> {
  if (parseLoading.value) return
  if (saveOperation.value || savingItemIds.value.size > 0 || saveInFlight.value || draftCreateItemIds.value.size > 0) {
    notification.error('批量审核处理中', '批量保存结果待核验，请先完成当前操作。')
    return
  }
  const validationError = validateBatchRawInput(rawInput.value)
  if (validationError) {
    parseError.value = validationError
    parseResult.value = null
    items.value = []
    batchId.value = ''
    notification.error('校验失败', validationError)
    return
  }
  parseError.value = ''
  clearBatchRouteLocalState()
    parseLoading.value = true
  journey.dispatch({ type: 'parse_started' })
  const count = batchItemCount(rawInput.value)
  parseCount.value = count
  loadingMessage.value = `正在逐项搜索 ${count} 个批量条目的 MiKan 候选；系统会逐项处理，较大的批量可能需要数分钟，请耐心等待。`
  try {
    const payload = buildBatchParsePayload(rawInput.value, currentStorageDir())
    const result = await api.post<BatchParseResult>('/api/v1/batches/parse', {
      body: payload,
      timeoutMs: batchParseTimeoutMs(count),
    })
    parseResult.value = result
    journey.dispatch({ type: 'parse_succeeded', result })
    const parsedItems = result.items ?? []
    inputItemOrder.value = new Map(
      parsedItems.map((item, index) => [item.item_id ?? '', index]),
    )
    items.value = orderBatchItemsForReview(parsedItems)
    for (const item of items.value) ensureDraftSession(item)
    batchId.value = result.batch_id ?? ''
    syncBatchIdToUrl(batchId.value)
    selectedItemIds.value = new Set()
    detailItemId.value = null
    currentItemId.value = items.value[0]?.item_id ?? null
    detailItemId.value = currentItemId.value
    acceptFeedback.value = {}
    saveSummary.value = {}
    savingItemIds.value = new Set()
    seasonConfirmations.value = {}
    notification.success('批量搜索完成', `已返回 ${items.value.length} 个条目的候选搜索状态。`)
  } catch (error) {
    void error
    journey.dispatch({ type: 'parse_failed', error })
    parseResult.value = null
    items.value = []
    batchId.value = ''
    parseError.value = mikanFailureMessage(error, '批量候选解析')
    notification.error('批量草案获取失败', parseError.value)
  } finally {
    parseLoading.value = false
  }
}

function toggleItemSelection(itemId: string, selected: boolean): void {
  if (selected && !itemConfirmability(itemId).confirmable) return
  const next = new Set(selectedItemIds.value)
  if (selected) {
    next.add(itemId)
  } else {
    next.delete(itemId)
  }
  selectedItemIds.value = next
}

function setAllSelected(selected: boolean): void {
  const next = new Set(selectedItemIds.value)
  if (selected) {
    for (const item of selectable.value) {
      if (item.item_id) next.add(item.item_id)
    }
  } else {
    for (const item of selectable.value) {
      if (item.item_id) next.delete(item.item_id)
    }
  }
  selectedItemIds.value = next
}

/** The candidate an item is currently generating a draft from, if any. */
function generatingCandidateIdFor(itemId: string): string | null {
  return draftCreateCandidateIds.value[itemId] ?? null
}

/** The sanitized generation failures of one item's candidates. */
function candidateErrorsFor(itemId: string): Record<string, string> {
  return draftCreateErrors.value[itemId] ?? {}
}

function setItemCandidateError(itemId: string, bangumiId: string, message: string | null): void {
  const itemErrors = { ...(draftCreateErrors.value[itemId] ?? {}) }
  if (message) itemErrors[bangumiId] = message
  else delete itemErrors[bangumiId]
  if (Object.keys(itemErrors).length) {
    draftCreateErrors.value = { ...draftCreateErrors.value, [itemId]: itemErrors }
    return
  }
  const next = { ...draftCreateErrors.value }
  delete next[itemId]
  draftCreateErrors.value = next
}

async function generateDraftFromCandidate(candidate: BatchCandidate): Promise<void> {
  const item = detailItem.value
  const itemId = item?.item_id ?? ''
  if (!item || !itemId || operationLocks(itemId) || draftCreateItemIds.value.has(itemId)) return
  const bangumiId = candidate.bangumi_id
  draftCreateItemIds.value = new Set(draftCreateItemIds.value).add(itemId)
  // Only this item's clicked candidate is marked as loading; a retry clears the
  // previous failure instead of stacking it.
  draftCreateCandidateIds.value = { ...draftCreateCandidateIds.value, [itemId]: bangumiId }
  setItemCandidateError(itemId, bangumiId, null)
  try {
    const payload = buildBatchCandidateCreatePayload(candidate, {
      storageDir: currentStorageDir(),
      confirmedSeason: seasonConfirmations.value[candidate.bangumi_id] ?? null,
    })
    const result = await api.post<CreateRequestResult>('/api/v1/requests', {
      body: { ...payload, storage_dir: storageQuery().storage_dir ?? null },
      timeoutMs: MIKAN_DRAFT_GENERATION_TIMEOUT_MS,
    })
    const request = result?.request as RequestSnapshot | undefined
    if (!request) {
      throw new Error('candidate preview returned no request')
    }
    const draftId = result?.draft_id ?? ''
    const draftRevision =
      typeof result?.draft_revision === 'number' ? result.draft_revision : 1
    journey.dispatch({ type: 'set_draft', itemId: item.item_id ?? '', draftId, revision: draftRevision })
    items.value = items.value.map((current) =>
      current.item_id === item.item_id
        ? { ...current, status: 'DRAFT', preview_request: request, draft_id: draftId, draft_revision: draftRevision }
        : current,
    )
    ensureDraftSession({ ...item, preview_request: request, draft_id: draftId, draft_revision: draftRevision })
    // The item left the candidate step atomically; its candidate feedback goes
    // with it.
    const nextErrors = { ...draftCreateErrors.value }
    delete nextErrors[itemId]
    draftCreateErrors.value = nextErrors
    notification.success('订阅草案已生成', '已根据所选 MiKan 合集生成当前批量条目的订阅草案。')
  } catch (error) {
    void error
    const message = mikanFailureMessage(error, '从 MiKan 合集生成订阅草案')
    notification.error('生成订阅草案失败', message)
    setItemCandidateError(itemId, bangumiId, message)
  } finally {
    const next = new Set(draftCreateItemIds.value)
    next.delete(itemId)
    draftCreateItemIds.value = next
    const nextCandidates = { ...draftCreateCandidateIds.value }
    delete nextCandidates[itemId]
    draftCreateCandidateIds.value = nextCandidates
  }
}

function subtitleGroupOptions(item: BatchItem): Array<{ value: string; label: string }> {
  return ((batchCardRequest(item)?.source_info?.rss_sources ?? []) as Array<{ subtitle_group?: string | null }>)
    .map((source) => ({ value: source.subtitle_group ?? '', label: source.subtitle_group ?? '未知字幕组' }))
    .filter((option) => option.value)
}

/**
 * US-344: a subtitle-group change is authoritative immediately, from either
 * surface. The scheduler owns the CAS so the card and the detail pane can
 * never issue two requests with the same revision.
 */
function applyCardSubtitleGroup(item: BatchItem, value: string): void {
  if (!value) return
  const scheduler = ensureScheduler(item)
  if (!scheduler) return
  draftApplyErrors.value = { ...draftApplyErrors.value, [item.item_id ?? '']: '' }
  scheduler.setSubtitleGroup(value)
}

async function retryCardModify(item: BatchItem): Promise<void> {
  const scheduler = ensureScheduler(item)
  if (!scheduler) return
  draftApplyErrors.value = { ...draftApplyErrors.value, [item.item_id ?? '']: '' }
  await scheduler.retry()
}

function openDraftDetail(item: BatchItem): void {
  selectCurrentItem(item)
}

function deleteBatchCard(itemId: string): void {
  disposeScheduler(itemId)
  draftSessions.get(itemId)?.invalidate()
  draftSessions.delete(itemId)
  journey.dispatch({ type: 'remove_item', itemId })
  const next = new Set(selectedItemIds.value)
  next.delete(itemId)
  selectedItemIds.value = next
  if (detailItemId.value === itemId) {
    detailItemId.value = null
  }
  const feedback = { ...acceptFeedback.value }
  delete feedback[itemId]
  acceptFeedback.value = feedback
  items.value = items.value.filter((item) => item.item_id !== itemId)
}

function operationLocks(itemId: string): boolean {
  return Boolean(saveOperation.value?.itemIds.includes(itemId) && saveOperation.value.phase === 'response_unknown') || savingItemIds.value.has(itemId)
}

function validateBatchSaveResult(
  result: BatchSaveConfirmResult,
  participantIds: readonly string[],
): BatchSaveConfirmResult['results'] | null {
  const raw = (result as unknown as { results?: unknown }).results
  if (!Array.isArray(raw) || raw.length !== participantIds.length) return null
  const expected = new Set(participantIds)
  const seen = new Set<string>()
  const rows: BatchSaveConfirmResult['results'] = []
  for (const candidate of raw) {
    if (!candidate || typeof candidate !== 'object') return null
    const row = candidate as Record<string, unknown>
    const itemId = row.item_id
    const outcome = row.outcome
    const required = ['item_id', 'outcome', 'request_id', 'status', 'error_type', 'error_message', 'tracking_id', 'tracking_ready']
    if (required.some((field) => !Object.prototype.hasOwnProperty.call(row, field))) return null
    if (typeof itemId !== 'string' || !itemId || !expected.has(itemId) || seen.has(itemId)) return null
    if (typeof outcome !== 'string' || !outcome.trim()) return null
    const normalizedOutcome = outcome.toUpperCase()
    if (normalizedOutcome !== 'CONFIRMED' && normalizedOutcome !== 'FAILED') return null
    if (row.request_id !== null && typeof row.request_id !== 'string') return null
    if (row.status !== null && typeof row.status !== 'string') return null
    if (row.tracking_id !== null && typeof row.tracking_id !== 'string') return null
    if (row.error_type !== null && typeof row.error_type !== 'string') return null
    if (row.error_message !== null && typeof row.error_message !== 'string') return null
    if (row.tracking_ready !== null && typeof row.tracking_ready !== 'boolean') return null
    if (normalizedOutcome === 'CONFIRMED' && (
      !batchSaveConfirmSucceeded(row as BatchSaveConfirmResult['results'][number]) ||
      row.error_type !== null || row.error_message !== null
    )) return null
    if (normalizedOutcome === 'FAILED') {
      if (typeof row.error_type !== 'string' || !row.error_type.trim() || row.error_type.length > 128) return null
      if (row.status !== null || row.tracking_id !== null || row.tracking_ready !== null) return null
      if (row.error_type === 'save_confirm_failed') {
        if (!isPublicRouteIdentifier(row.request_id)) return null
      } else if (row.request_id !== null) {
        return null
      }
    }
    seen.add(itemId)
    rows.push(row as BatchSaveConfirmResult['results'][number])
  }
  return seen.size === expected.size ? rows : null
}

function applySaveConfirmResult(result: BatchSaveConfirmResult): void {
  const feedback: Record<string, string> = {}
  const rawResultItems = result && Array.isArray((result as unknown as { results?: unknown }).results)
    ? (result as unknown as { results: unknown[] }).results
    : result && Array.isArray((result as unknown as { items?: unknown }).items)
      ? (result as unknown as { items: unknown[] }).items
      : []
  const seenResultIds = new Set<string>()
  const resultItems = rawResultItems.filter((candidate): candidate is BatchSaveConfirmResult['results'][number] => {
    if (!candidate || typeof candidate !== 'object') return false
    const itemId = (candidate as { item_id?: unknown }).item_id
    if (typeof itemId !== 'string' || !itemId || seenResultIds.has(itemId)) return false
    seenResultIds.add(itemId)
    return true
  })
  const nextItems = items.value.map((row) => {
    let updated = row
    for (const item of resultItems) {
      if (item.item_id !== row.item_id) continue
      if (batchSaveConfirmSucceeded(item)) {
        updated = {
          ...row,
          status: 'CONFIRMED',
          draft_id: null,
          draft_revision: null,
          request_id: item.request_id,
          tracking_id: item.tracking_id,
        }
        draftSessions.get(row.item_id ?? '')?.invalidate()
        draftSessions.delete(row.item_id ?? '')
        const selected = new Set(selectedItemIds.value)
        selected.delete(row.item_id ?? '')
        selectedItemIds.value = selected
      } else {
        feedback[row.item_id ?? ''] = batchSaveConfirmErrorLabel(item)
        if (batchSaveConfirmRecoveryAllowed(item)) {
          updated = { ...row, status: 'SAVED_PENDING_CONFIRM', draft_id: null, draft_revision: null, request_id: item.request_id }
          draftSessions.get(row.item_id ?? '')?.invalidate()
          draftSessions.delete(row.item_id ?? '')
        } else if (['draft_expired', 'draft_evicted', 'draft_replayed', 'draft_revision_conflict'].includes(String(item.error_type ?? ''))) {
          draftSessions.get(row.item_id ?? '')?.invalidate()
          draftSessions.delete(row.item_id ?? '')
          updated = {
            ...row,
            status: (row.candidates?.length ?? 0) > 0 ? 'FOUND' : 'EMPTY',
            preview_request: null,
            draft_id: null,
            draft_revision: null,
          }
          const selected = new Set(selectedItemIds.value)
          selected.delete(row.item_id ?? '')
          selectedItemIds.value = selected
        } else {
          updated = { ...row, status: 'DRAFT' }
        }
      }
    }
    return updated
  })
  items.value = nextItems
  acceptFeedback.value = { ...acceptFeedback.value, ...feedback }
  const firstFailed = resultItems.find((item) => !batchSaveConfirmSucceeded(item))?.item_id
  const firstFailedRow = nextItems.find((item) => item.item_id === firstFailed)
  if (firstFailed && firstFailedRow) {
    const hidden = !visibleItems.value.some((item) => item.item_id === firstFailed)
    temporarilyShownItemId.value = hidden ? firstFailed : null
    selectCurrentItem(firstFailedRow)
    focusAnnouncement.value = `已定位到首个失败条目：${batchCardTitle(firstFailedRow)}`
    focusCard(firstFailed)
  }

}

function setRecoveryLoading(itemId: string, loading: boolean): void {
  const next = new Set(recoveryLoadingItemIds.value)
  if (loading) next.add(itemId)
  else next.delete(itemId)
  recoveryLoadingItemIds.value = next
}

function setRecoveryFeedback(itemId: string, message: string): void {
  recoveryFeedback.value = { ...recoveryFeedback.value, [itemId]: message }
}

async function locateBatchTracking(item: BatchItem): Promise<'found' | 'not_found' | 'failed'> {
  const requestId = batchItemRequestId(item)
  if (!isPublicRouteIdentifier(requestId)) return 'not_found'
  try {
    const result = await api.get<import('@/app/composables/useBatchReviewJourney').TrackingItemsResult>('/api/v1/tracking/items', { query: storageQuery() })
    const match = findBatchTrackingItem(result, requestId)
    if (!match || !isPublicRouteIdentifier(match.tracking_id)) return 'not_found'
    items.value = items.value.map((row) => row.item_id === item.item_id
      ? { ...row, status: 'CONFIRMED', tracking_id: match.tracking_id }
      : row)
    journey.dispatch({ type: 'tracking_located', itemId: item.item_id ?? '', requestId, trackingId: match.tracking_id ?? '' })
    setRecoveryFeedback(item.item_id ?? '', '已定位到真实追番记录。')
    if (router.hasRoute('tracking')) await router.replace(routeLocation('tracking', { tracking_id: match.tracking_id }))
    return 'found'
  } catch {
    return 'failed'
  }
}

async function retrySavedConfirmation(item: BatchItem): Promise<void> {
  const itemId = item.item_id ?? ''
  const requestId = batchItemRequestId(item)
  if (!itemId || !isPublicRouteIdentifier(requestId) || recoveryLoadingItemIds.value.has(itemId)) return
  setRecoveryLoading(itemId, true)
  setRecoveryFeedback(itemId, '')
  try {
    await api.post<import('@/app/composables/useBatchReviewJourney').AcceptRequestResult>('/api/v1/requests/{request_id}/accept', {
      path: { request_id: requestId },
      body: { storage_dir: storageQuery().storage_dir ?? null },
    })
    // Accept was explicitly successful. From this point on only location may
    // be retried; the accept action is never reopened.
    items.value = items.value.map((row) => row.item_id === itemId
      ? { ...row, status: 'CONFIRMED', request_id: requestId, tracking_id: null }
      : row)
    journey.dispatch({ type: 'accept_succeeded', itemId, requestId })
    const located = await locateBatchTracking({ ...item, request_id: requestId })
    if (located === 'not_found') setRecoveryFeedback(itemId, '方案已确认，但暂未定位到追番记录；可稍后重试定位。')
    if (located === 'failed') setRecoveryFeedback(itemId, '确认已完成，但定位暂不可用；请稍后重试定位。')
  } catch (cause) {
    const safeError = toApiError(cause)
    const uncertain = safeError.network || safeError.nonJson || safeError.status >= 500 || ['network_error', 'request_timeout', 'upstream_timeout', 'cancelled'].includes(safeError.type)
    const verificationRequired = uncertain || safeError.type === 'invalid_request_status'
    if (!verificationRequired) {
      setRecoveryFeedback(itemId, '确认未完成，请根据安全错误提示处理后再试。')
      return
    }
    const located = await locateBatchTracking(item)
    if (located === 'found') return
    items.value = items.value.map((row) => row.item_id === itemId
      ? { ...row, status: located === 'failed' ? 'RESPONSE_UNKNOWN' : 'SAVED_PENDING_CONFIRM' }
      : row)
    journey.dispatch(located === 'failed'
      ? { type: 'tracking_verification_failed', itemId }
      : { type: 'tracking_not_found', itemId })
    setRecoveryFeedback(itemId, verificationRequired
      ? located === 'failed' ? '确认结果暂无法核验，请重试定位；不会重复确认。' : '确认结果已核验，但暂未找到追番记录；请明确重试确认。'
      : '确认未完成，请根据安全错误提示处理后再试。')
  } finally {
    setRecoveryLoading(itemId, false)
  }
}

async function retryBatchTrackingLocation(item: BatchItem): Promise<void> {
  const itemId = item.item_id ?? ''
  if (!itemId || recoveryLoadingItemIds.value.has(itemId)) return
  setRecoveryLoading(itemId, true)
  setRecoveryFeedback(itemId, '')
  const located = await locateBatchTracking(item)
  if (located === 'not_found') {
    const current = items.value.find((row) => row.item_id === itemId)
    if (current?.status === 'RESPONSE_UNKNOWN') {
      items.value = items.value.map((row) => row.item_id === itemId ? { ...row, status: 'SAVED_PENDING_CONFIRM' } : row)
      journey.dispatch({ type: 'tracking_not_found', itemId })
      setRecoveryFeedback(itemId, '确认结果已核验，但暂未找到追番记录；可明确重试确认。')
    } else setRecoveryFeedback(itemId, '暂未定位到追番记录，请稍后重试定位。')
  }
  if (located === 'failed') setRecoveryFeedback(itemId, '定位暂不可用，请稍后重试。')
  setRecoveryLoading(itemId, false)
}

async function submitBatchSaveConfirm(rows: BatchItem[], itemIds: string[] | null): Promise<void> {
  if (!batchId.value) {
    notification.error('保存确认失败', '缺少批次标识，请重新获取批量草案。')
    return
  }
  const frozen = saveOperation.value?.phase === 'response_unknown' ? saveOperation.value : null
  if (frozen) {
    rows = frozen.itemIds.map((itemId) => items.value.find((row) => row.item_id === itemId)).filter((row): row is BatchItem => Boolean(row))
    itemIds = frozen.body.item_ids ?? null
  } else {
    const eligibleRows = rows.filter((row) => itemConfirmability(row.item_id ?? '').confirmable)
    const participantIds = eligibleRows.map((row) => row.item_id ?? '')
    if (eligibleRows.length !== rows.length || eligibleRows.length === 0 || new Set(participantIds).size !== participantIds.length) {
      notification.error('保存确认失败', '存在尚未准备好的条目，请先完成修改或恢复。')
      return
    }
    rows = eligibleRows
    const accepted = journey.dispatch({ type: 'begin_save', itemIds: rows.map((row) => row.item_id ?? '') })
    if (!accepted) {
      notification.error('保存确认失败', '当前条目状态已变化，请重新检查后再试。')
      return
    }
  }
  saveInFlight.value = true
  savingItemIds.value = new Set(rows.map((row) => row.item_id ?? '').filter(Boolean))
  try {
    let body: ReturnType<typeof buildBatchSaveConfirmPayload>
    if (frozen) {
      body = frozen.body
    } else {
      const descriptors: BatchSaveConfirmDescriptor[] = rows.map((row) => {
        const itemId = row.item_id ?? ''
        const key = journey.state.items[itemId]?.idempotencyKey
        return { item_id: itemId, draft_id: row.draft_id ?? '', base_revision: row.draft_revision ?? 1, idempotency_key: key ?? '' }
      })
      if (!descriptors.length || descriptors.some((item) => !item.draft_id)) {
        notification.error('保存确认失败', '没有可确认的批量草案。')
        return
      }
      body = buildBatchSaveConfirmPayload(descriptors, itemIds, currentStorageDir())
      saveOperation.value = { itemIds: rows.map((row) => row.item_id ?? ''), body, phase: 'sending' }
    }
    const result = await api.post<BatchSaveConfirmResult>(`/api/v1/batches/{batch_id}/save-confirm`, {
      path: { batch_id: batchId.value },
      body,
    })
    saveSummary.value = result.summary ?? {}
    const resultItems = validateBatchSaveResult(result, rows.map((row) => row.item_id ?? ''))
    if (!resultItems) {
      if (saveOperation.value) saveOperation.value = { ...saveOperation.value, phase: 'response_unknown' }
      journey.dispatch({ type: 'save_response_unknown', itemIds: rows.map((row) => row.item_id ?? '') })
      items.value = items.value.map((item) => savingItemIds.value.has(item.item_id ?? '') ? { ...item, status: 'RESPONSE_UNKNOWN' } : item)
      notification.error('保存确认结果待核验', '响应未知，请使用相同操作重试。')
      return
    }
    applySaveConfirmResult({ ...result, results: resultItems })
    const resultById = new Map(resultItems.map((resultItem) => [resultItem.item_id, resultItem]))
    for (const row of rows) {
      const itemId = row.item_id ?? ''
      const resultItem = resultById.get(itemId)
      if (resultItem && batchSaveConfirmSucceeded(resultItem)) journey.dispatch({ type: 'save_succeeded', itemId, result: resultItem })
      else if (resultItem) journey.dispatch({ type: 'save_failed', itemId, error: resultItem })
    }
    saveOperation.value = null
    const confirmed = result.summary?.confirmed ?? 0
    const failed = result.summary?.failed ?? 0
    notification.show(failed && !confirmed ? 'error' : 'success', '批量保存确认完成', `已确认 ${confirmed} 项${failed ? `；${failed} 项需处理` : ''}。`)
  } catch (error) {
    const safeError = toApiError(error)
    const nested = safeError.details?.details
    const details = nested && typeof nested === 'object' ? nested as Record<string, unknown> : null
    const requestId = details && typeof details.request_id === 'string' ? details.request_id : ''
    const validSavedFailure = safeError.type === 'save_confirm_failed' &&
      details?.outcome === 'SAVED_CONFIRM_FAILED' &&
      details?.retry_action === 'ACCEPT_SAVED_REQUEST' &&
      isPublicRouteIdentifier(requestId)
    if (validSavedFailure && rows.length === 1) {
      const row = rows[0]
      draftSessions.get(row?.item_id ?? '')?.invalidate()
      draftSessions.delete(row?.item_id ?? '')
      items.value = items.value.map((item) => item.item_id === row?.item_id
        ? { ...item, status: 'SAVED_PENDING_CONFIRM', draft_id: null, draft_revision: null, request_id: requestId }
        : item)
      journey.dispatch({ type: 'save_failed', itemId: row?.item_id ?? '', error })
      setRecoveryFeedback(row?.item_id ?? '', '订阅方案已保存但确认未完成；不会重复保存，可直接重试确认。')
    }
    const source = error && typeof error === 'object' ? error as { network?: unknown; nonJson?: unknown; status?: unknown; type?: unknown } : {}
    const status = typeof source.status === 'number' ? source.status : 0
    const responseUnknown = source.network === true || source.nonJson === true || status >= 500 ||
      ['network_error', 'request_timeout', 'upstream_timeout', 'cancelled'].includes(String(source.type))
    if (!responseUnknown) {
      if (!validSavedFailure) rows.forEach((row) => journey.dispatch({ type: 'save_failed', itemId: row.item_id ?? '', error }))
      if (!validSavedFailure) {
        const safeType = toSafeBatchError(error).type
        items.value = items.value.map((item) => rows.some((row) => row.item_id === item.item_id)
          ? ['draft_expired', 'draft_evicted', 'draft_replayed', 'draft_revision_conflict'].includes(safeType)
            ? { ...item, status: (item.candidates?.length ?? 0) > 0 ? 'FOUND' : 'EMPTY', preview_request: null, draft_id: null, draft_revision: null }
            : { ...item, status: 'DRAFT' }
          : item)
      }
      saveOperation.value = null
      notification.error('保存确认失败', '保存确认失败，请根据条目提示处理。')
    } else {
      if (saveOperation.value) saveOperation.value = { ...saveOperation.value, phase: 'response_unknown' }
      journey.dispatch({ type: 'save_response_unknown', itemIds: rows.map((row) => row.item_id ?? ''), error })
      items.value = items.value.map((item) => savingItemIds.value.has(item.item_id ?? '') ? { ...item, status: 'RESPONSE_UNKNOWN' } : item)
      notification.error('保存确认结果待核验', '响应未知，请使用相同操作重试。')
    }
  } finally {
    saveInFlight.value = false
    savingItemIds.value = new Set()
  }
}

async function retryFrozenBatchSaveConfirm(): Promise<void> {
  const operation = saveOperation.value
  if (!operation || operation.phase !== 'response_unknown' || saveInFlight.value) return
  const rows = operation.itemIds
    .map((itemId) => items.value.find((row) => row.item_id === itemId))
    .filter((row): row is BatchItem => Boolean(row))
  if (rows.length !== operation.itemIds.length) return
  await submitBatchSaveConfirm(rows, operation.body.item_ids ?? null)
}

async function confirmBatchAcceptSelected(): Promise<void> {
  const rows = visibleItems.value.filter((item) => selectedItemIds.value.has(item.item_id ?? '') && itemConfirmability(item.item_id ?? '').confirmable)
  if (!rows.length || saveInFlight.value) return
  const ok = await confirmDialog.value?.confirm({
    title: '批量保存确认',
    message: `确认保存并确认选中的 ${rows.length} 个批量草案？`,
    confirmLabel: '保存并确认',
  })
  if (!ok) return
  await submitBatchSaveConfirm(rows, rows.map((row) => row.item_id ?? ''))
}

async function confirmBatchAcceptAll(): Promise<void> {
  // US-347: 全部 covers the complete batch's confirmable set. The filter and the
  // checkboxes only change what is browsed, so neither may shrink this scope;
  // submitBatchSaveConfirm still re-checks every participant before sending.
  const rows = batchConfirmable.value
  if (!rows.length || saveInFlight.value) return
  const hiddenCount = rows.filter(
    (item) => !visibleItems.value.some((visible) => visible.item_id === item.item_id),
  ).length
  const ok = await confirmDialog.value?.confirm({
    title: '批量保存确认',
    message: `确认保存并确认完整批次中的 ${rows.length} 个可确认批量草案？${hiddenCount ? `其中 ${hiddenCount} 个当前被筛选隐藏，仍会一并保存并确认。` : ''}`,
    confirmLabel: '保存并确认',
  })
  if (!ok) return
  await submitBatchSaveConfirm(rows, null)
}

function selectForBatch(itemId: string): void {
  toggleItemSelection(itemId, true)
}

function onDraftChanged(
  itemId: string,
  state: { request: RequestSnapshot; draftId: string; draftRevision: number },
): void {
  journey.dispatch({ type: 'apply_succeeded', itemId, draftId: state.draftId, revision: state.draftRevision })
  items.value = items.value.map((current) =>
    current.item_id === itemId
      ? {
          ...current,
          preview_request: state.request,
          draft_id: state.draftId,
          draft_revision: state.draftRevision,
        }
      : current,
  )
  draftApplyErrors.value = { ...draftApplyErrors.value, [itemId]: '' }
}

function onDetailDirty(dirty: boolean): void {
  const item = detailItem.value
  if (!item) return
  journey.dispatch({ type: 'set_dirty', itemId: item.item_id ?? '', dirty })
  draftSessions.get(item.item_id ?? '')?.setDirty(dirty)
}

function onDraftDeleted(itemId: string): void {
  deleteBatchCard(itemId)
  notification.info('已删除批量卡片', '当前批量卡片已从本批结果中移除。')
}

function onDraftExpired(itemId: string): void {
  disposeScheduler(itemId)
  draftSessions.get(itemId)?.invalidate()
  journey.dispatch({ type: 'invalidate_draft', itemId })
  const nextSelected = new Set(selectedItemIds.value)
  nextSelected.delete(itemId)
  selectedItemIds.value = nextSelected
  const nextFeedback = { ...acceptFeedback.value }
  delete nextFeedback[itemId]
  acceptFeedback.value = nextFeedback
  items.value = items.value.map((current) => {
    if (current.item_id !== itemId) return current
    const hasCandidates = (current.candidates?.length ?? 0) > 0
    return {
      ...current,
      status: hasCandidates ? 'FOUND' : 'EMPTY',
      preview_request: null,
      draft_id: null,
      draft_revision: null,
    }
  })
  draftSessions.delete(itemId)
  draftApplyErrors.value = { ...draftApplyErrors.value, [itemId]: '订阅草案已失效，请重新生成。' }
  detailItemId.value = null
}

/** 保存修改: flush the not-yet-due filter input and the folder name now. */
async function flushDetailModify(): Promise<void> {
  const item = detailItem.value
  if (!item) return
  const scheduler = ensureScheduler(item)
  if (!scheduler) return
  draftApplyErrors.value = { ...draftApplyErrors.value, [item.item_id ?? '']: '' }
  await scheduler.flush()
}

function onSubtitleGroupChange(value: string): void {
  const item = detailItem.value
  if (!item) return
  applyCardSubtitleGroup(item, value)
}

function onFilterChange(state: PreviewEditState): void {
  const item = detailItem.value
  const scheduler = item ? ensureScheduler(item) : null
  if (!scheduler) return
  scheduler.setFilter(state)
}

function onFolderNameChange(value: string): void {
  const item = detailItem.value
  const scheduler = item ? ensureScheduler(item) : null
  if (!scheduler) return
  scheduler.setFolderName(value)
}

async function retryDetailModify(): Promise<void> {
  const item = detailItem.value
  const scheduler = item ? ensureScheduler(item) : null
  if (!scheduler) return
  await scheduler.retry()
}

function resetDetailModify(): void {
  const item = detailItem.value
  const scheduler = item ? ensureScheduler(item) : null
  if (!scheduler) return
  detailEditor.value?.reset()
  scheduler.restore()
  journey.dispatch({ type: 'set_dirty', itemId: item?.item_id ?? '', dirty: false })
  draftApplyErrors.value = { ...draftApplyErrors.value, [item?.item_id ?? '']: '' }
}

useLeaveGuard({
  shouldGuard: hasUnsafeBatchWork,
  confirm: async () => {
    const confirmed = await confirmDialog.value?.confirm({
      title: '离开批量审核',
      message: '离开批量审核将清理当前批量现场和未保存编辑，是否继续？',
      confirmLabel: '确认离开',
      cancelLabel: '留在此页',
      danger: true,
    })
    return confirmed === true
  },
  cleanup: clearBatchRouteLocalState,
})

onMounted(() => {
  const fromQuery = typeof route.query.batch_id === 'string' ? route.query.batch_id : ''
  if (fromQuery) {
    batchId.value = fromQuery
    // The queue panel (US-206) will restore the queue on refresh; the batch
    // card grid itself is never persisted server-side, so a refresh can only
    // restore the queue context, not the cards.
  }
})

onUnmounted(() => {
  for (const { scheduler } of editSchedulers.values()) scheduler.dispose()
  editSchedulers.clear()
})

defineExpose({ parseBatch, generateDraftFromCandidate, submitBatchSaveConfirm, deleteBatchCard })
</script>

<template>
  <PanelSection title="批量工作台" class="batch-workbench-panel">
    <form id="batch-parse-form" class="batch-parse-form" @submit.prevent="parseBatch">
      <label v-if="!props.hideInput" for="batch-raw-input">批量番剧名称</label>
      <AnimeTitleInput
        v-if="!props.hideInput"
        id="batch-raw-input"
        v-model="rawInput"
        mode="batch"
        :disabled="parseBlocked"
      />
      <p v-if="!props.hideInput" class="field-help" id="batch-parse-help">
        每行一个番剧简称或不完整标题；系统会逐项解析并搜索候选合集，结果需人工审核。
      </p>
      <p v-if="parseError" id="batch-parse-error" class="field-error" role="alert">
        {{ parseError }}
      </p>
      <div class="notification-actions">
        <BaseButton id="batch-parse-submit" type="submit" variant="primary" :loading="parseLoading" :disabled="parseBlocked">
          获取批量草案
        </BaseButton>
      </div>
    </form>

    <div id="batch-parse-result" class="batch-parse-result" aria-live="polite" aria-relevant="additions text">
      <LoadingState v-if="parseLoading" :message="loadingMessage" />
      <ErrorState
        v-else-if="parseError && !items.length"
        title="批量草案获取失败"
        message="批量草案获取失败。请稍后重试。"
        retry-label="重试"
        @retry="parseBatch"
      />
      <EmptyState
        v-else-if="!items.length"
        message="粘贴多行番剧名称后获取解析结果。"
      />
      <template v-else>
        <div class="batch-review-layout">
          <div ref="reviewList" class="batch-card-grid-wrapper">
            <div class="batch-review-filters" aria-label="批量结果筛选">
              <label class="batch-review-search">
                标题搜索
                <input id="batch-review-search" v-model="reviewQuery" type="search" placeholder="搜索标题" />
              </label>
              <label>
                状态
                <select id="batch-review-status" v-model="reviewStatus">
                  <option value="">全部状态</option>
                  <option v-for="status in ['FAILED', 'EMPTY', 'FOUND', 'DRAFT', 'SAVED_PENDING_CONFIRM', 'CONFIRMED']" :key="status" :value="status">
                    {{ batchStatusLabel(status) }}
                  </option>
                </select>
              </label>
              <CheckboxRow id="batch-review-exceptions" label="只看异常" :checked="exceptionsOnly" @update:checked="(value: boolean) => (exceptionsOnly = value)" />
              <BaseButton id="batch-review-clear" variant="secondary" :disabled="!reviewQuery && !reviewStatus && !exceptionsOnly" @click="clearReviewFilters">
                清除条件
              </BaseButton>
              <BaseButton id="batch-review-sort-exceptions" variant="secondary" @click="sortExceptionsFirst">
                按异常排序
              </BaseButton>
            </div>
            <p class="batch-review-count" role="status">共 {{ items.length }} 部，当前显示 {{ visibleItems.length }} 部{{ exceptionSorted ? '；已按异常排序' : '' }}</p>
            <div class="batch-review-navigation">
              <BaseButton
                id="batch-next-exception"
                variant="secondary"
                :disabled="!nextBatchException(items, currentItemId)"
                @click="goToNextException"
              >
                下一异常
              </BaseButton>
              <span v-if="focusAnnouncement" role="status" aria-live="polite">{{ focusAnnouncement }}</span>
              <span v-else class="field-help">无异常时不可用</span>
            </div>
            <p v-if="detailItem && !visibleItems.some((item) => item.item_id === detailItem?.item_id)" class="batch-filter-hidden" role="status">
              当前条目已被筛选隐藏，详情仍保持显示。
            </p>
            <div class="batch-card-grid" role="list" aria-label="批量草案卡片">
            <article
              v-for="item in visibleItems"
              :key="item.item_id ?? item.raw_title ?? ''"
              class="batch-draft-card"
              :class="{ 'is-current': currentItemId === item.item_id }"
              :data-item-id="item.item_id ?? ''"
              role="listitem"
              tabindex="0"
              :ref="(element) => setCardElement(item.item_id, element)"
              @click="selectCurrentItem(item)"
              @keydown="onCardKeydown($event, item)"
            >
              <CheckboxRow
                class="batch-card-checkbox-row"
                :class="{ 'is-selected': selectedItemIds.has(item.item_id ?? '') }"
                :label="`选择 ${item.raw_title ?? '批量条目'}`"
                :checked="selectedItemIds.has(item.item_id ?? '')"
                :disabled="!itemConfirmability(item.item_id ?? '').confirmable || operationLocks(item.item_id ?? '')"
                @click.stop
                @update:checked="(value: boolean) => toggleItemSelection(item.item_id ?? '', value)"
              />
              <button
                v-if="!['CONFIRMED', 'SAVED_PENDING_CONFIRM'].includes(String(item.status ?? ''))"
                type="button"
                class="icon-button batch-card-delete"
                :aria-label="`删除 ${item.raw_title ?? '批量条目'}`"
                title="删除"
                :disabled="operationLocks(item.item_id ?? '')"
                @click.stop
                @click="deleteBatchCard(item.item_id ?? '')"
              >
                ×
              </button>

              <div class="batch-card-poster">
                <span v-if="canChooseBatchCandidate(item)" class="batch-card-poster-placeholder" data-poster-state="unselected">
                  待选择合集
                </span>
                <span v-else class="batch-card-poster-placeholder" data-poster-state="unavailable">
                  暂无封面
                </span>
              </div>

              <div class="batch-card-status-row">
                <span class="batch-status batch-card-status">{{ batchStatusLabel(item.status) }}</span>
                <span v-if="batchCardNeedsReview(item)" class="batch-status batch-card-review-status">
                  需人工核对
                </span>
              </div>

              <strong class="batch-card-title">{{ batchCardTitle(item) }}</strong>
              <div class="batch-card-raw-title">输入：{{ displayValue(item.raw_title) }}</div>
              <div class="batch-card-source">候选来源：{{ canChooseBatchCandidate(item) || batchCardRequest(item) ? 'MiKan 候选搜索' : 'MiKan 候选搜索' }}</div>
              <div class="batch-card-preference">{{ batchCardPreferenceSummary(item) }}</div>
              <div v-if="canExpandBatchCard(item) && batchCardRequest(item)" class="batch-card-subtitle-group" @click.stop>
                <label :for="`batch-card-subtitle-${item.item_id}`">字幕组快捷修改</label>
                <select
                  :id="`batch-card-subtitle-${item.item_id}`"
                  :value="cardSubtitleGroupValue(item)"
                  :disabled="operationLocks(item.item_id ?? '') || draftSessions.get(item.item_id ?? '')?.applying.value"
                  @change="applyCardSubtitleGroup(item, ($event.target as HTMLSelectElement).value)"
                >
                  <option value="">保持当前选择</option>
                  <option v-for="option in subtitleGroupOptions(item)" :key="option.value" :value="option.value">{{ option.label }}</option>
                </select>
                <p v-if="draftApplyErrors[item.item_id ?? '']" class="batch-card-reason">{{ draftApplyErrors[item.item_id ?? ''] }}</p>
                <p v-if="draftSessions.get(item.item_id ?? '')?.applying.value" class="field-help" aria-live="polite">正在重新计算资源...</p>
                <BaseButton
                  v-if="draftSessions.get(item.item_id ?? '')?.canRetry.value"
                  variant="secondary"
                  :disabled="savingItemIds.has(item.item_id ?? '') || draftSessions.get(item.item_id ?? '')?.applying.value"
                  @click.stop="retryCardModify(item)"
                >重试修改</BaseButton>
              </div>
              <!-- US-343: the candidate step shows no resource count; the
                   effective seed count appears only once a draft exists. -->
              <div v-if="batchCardRequest(item)" class="batch-card-seeds">有效种子数：{{ batchCardSeedSummary(item) }}</div>
              <div class="batch-card-progress">{{ batchEpisodeProgressText(undefined) }}</div>

              <p
                v-if="generatingCandidateIdFor(item.item_id ?? '')"
                class="batch-card-generating-status"
                role="status"
              >
                正在生成订阅草案…
              </p>

              <p v-if="String(item.status ?? '') === 'EMPTY'" class="batch-candidate-feedback">
                未找到匹配的 MiKan 合集。
              </p>
              <p v-else-if="String(item.status ?? '') === 'FAILED'" class="batch-candidate-feedback">
                {{ batchItemFailureMessage(item) }}
              </p>
              <p
                v-if="!['CONFIRMED', 'SAVED_PENDING_CONFIRM'].includes(String(item.status ?? '')) && !itemConfirmability(item.item_id ?? '').confirmable"
                class="batch-card-selection-help"
              >
                {{ itemConfirmability(item.item_id ?? '').blockers[0] ?? '当前条目暂不可加入批量确认。' }}
              </p>

              <p
                v-if="item.review_hints?.length"
                class="batch-card-preference-note"
              >
                {{ item.review_hints.join('；') }}
              </p>

              <div v-if="acceptFeedback[item.item_id ?? '']" class="batch-card-reason">
                {{ acceptFeedback[item.item_id ?? ''] }}
              </div>

              <div class="batch-card-actions">
                <BaseButton
                  v-if="String(item.status ?? '') === 'SAVED_PENDING_CONFIRM'"
                  :id="`batch-retry-accept-${item.item_id}`"
                  variant="primary"
                  :loading="recoveryLoadingItemIds.has(item.item_id ?? '')"
                  :disabled="recoveryLoadingItemIds.has(item.item_id ?? '') || !batchItemRequestId(item)"
                  @click.stop="retrySavedConfirmation(item)"
                >重试确认</BaseButton>
                <BaseButton
                  v-if="String(item.status ?? '') === 'CONFIRMED' && batchItemTrackingId(item)"
                  :id="`batch-open-tracking-${item.item_id}`"
                  variant="secondary"
                  @click.stop="router.replace(routeLocation('tracking', { tracking_id: batchItemTrackingId(item) }))"
                >打开追番记录</BaseButton>
                <BaseButton
                  v-if="['CONFIRMED', 'RESPONSE_UNKNOWN'].includes(String(item.status ?? '')) && !batchItemTrackingId(item)"
                  :id="`batch-retry-locate-${item.item_id}`"
                  variant="secondary"
                  :loading="recoveryLoadingItemIds.has(item.item_id ?? '')"
                  :disabled="recoveryLoadingItemIds.has(item.item_id ?? '') || !batchItemRequestId(item)"
                  @click.stop="retryBatchTrackingLocation(item)"
                >重试定位</BaseButton>
                <BaseButton
                  v-if="canChooseBatchCandidate(item)"
                  :class="{ 'batch-card-expand': true }"
                  :aria-expanded="detailItemId === item.item_id ? 'true' : 'false'"
                  aria-controls="batch-detail-pane"
                  :aria-label="`查看候选：${item.raw_title ?? '批量条目'}`"
                  :disabled="savingItemIds.has(item.item_id ?? '')"
                  @click.stop
                  @click="selectCurrentItem(item)"
                >
                  查看候选
                </BaseButton>
                <BaseButton
                  v-else-if="canExpandBatchCard(item)"
                  class="batch-card-expand"
                  :aria-expanded="detailItemId === item.item_id ? 'true' : 'false'"
                  aria-controls="request-detail-panel"
                  :aria-label="`查看草案：${item.raw_title ?? '批量条目'}`"
                  :disabled="operationLocks(item.item_id ?? '')"
                  @click.stop
                  @click="openDraftDetail(item)"
                >
                  查看草案
                </BaseButton>
                <BaseButton v-else class="batch-card-expand" disabled title="当前条目没有可选择的候选合集">
                  查看候选
                </BaseButton>
              </div>
              <p v-if="recoveryFeedback[item.item_id ?? '']" class="batch-card-reason" role="status">
                {{ recoveryFeedback[item.item_id ?? ''] }}
              </p>
            </article>
            </div>
          </div>

          <aside id="batch-detail-pane" class="batch-detail-pane" aria-label="当前批量条目详情">
            <template v-if="detailItem && canChooseBatchCandidate(detailItem)">
              <h3 class="batch-detail-title">候选合集：{{ batchCardTitle(detailItem) }}</h3>
              <p class="field-help">请选择一个真实 MiKan 合集后生成订阅草案。</p>
              <CandidateCollectionList
                class="batch-candidate-list"
                :candidates="detailItem.candidates ?? []"
                :query="batchCardTitle(detailItem)"
                  :disabled="operationLocks(detailItem.item_id ?? '')"
                :loading-candidate-id="generatingCandidateIdFor(detailItem.item_id ?? '')"
                :candidate-errors="candidateErrorsFor(detailItem.item_id ?? '')"
                :confirmed-seasons="seasonConfirmations"
                @select="generateDraftFromCandidate"
                @update:confirmed-season="(bangumiId: string, season: number | null) => (seasonConfirmations = { ...seasonConfirmations, [bangumiId]: season })"
              />
            </template>
            <template v-else-if="detailItem && canExpandBatchCard(detailItem) && batchCardRequest(detailItem)">
              <div class="batch-draft-panel">
                <AnimeDraftEditor
                  ref="detailEditor"
                  :key="`detail-${detailItem.item_id ?? detailItem.raw_title ?? ''}`"
                  :request="(ensureDraftSession(detailItem)?.request.value ?? batchCardRequest(detailItem)) as RequestSnapshot"
                  id-prefix="batch-preview"
                  form-id="detail-preview-edit-form"
                  container-id="request-detail-container"
                  apply-variant="secondary"
                  :applying="ensureDraftSession(detailItem)?.applying.value ?? false"
                  :error="draftApplyErrors[detailItem.item_id ?? '']"
                  :can-retry="ensureDraftSession(detailItem)?.canRetry.value ?? false"
                  :disabled="(ensureDraftSession(detailItem)?.applying.value ?? false) || operationLocks(detailItem.item_id ?? '')"
                  @apply="flushDetailModify"
                  @subtitle-group-change="onSubtitleGroupChange"
                  @filter-change="onFilterChange"
                  @folder-change="onFolderNameChange"
                  @dirty-change="onDetailDirty"
                  @retry="retryDetailModify"
                  @reset="resetDetailModify"
                >
                  <template #review-note>
                    <p class="field-help preview-mode-note">订阅草案（未保存）：字幕组会立即重新计算，筛选规则在停止输入 1.5 秒后自动更新，目录名只在「保存修改」时提交；随后在固定操作栏统一保存并确认。</p>
                  </template>
                </AnimeDraftEditor>
                <div class="batch-draft-actions" aria-label="批量卡片操作">
                  <!-- F4: 右栏只负责当前条目的查看与改选，固定操作栏是唯一的
                       批量「保存并确认」主入口，因此这里不使用主按钮样式。 -->
                  <BaseButton
                    id="batch-detail-accept"
                    variant="secondary"
                    :disabled="!itemConfirmability(detailItem.item_id ?? '').confirmable"
                    :title="itemConfirmability(detailItem.item_id ?? '').blockers.join('；')"
                    @click="selectForBatch(detailItem.item_id ?? '')"
                  >加入批量确认</BaseButton>
                  <BaseButton id="batch-detail-delete" variant="danger" :disabled="savingItemIds.has(detailItem.item_id ?? '')" @click="onDraftDeleted(detailItem.item_id ?? '')">删除当前批量卡片</BaseButton>
                </div>
              </div>
            </template>
            <template v-else-if="detailItem">
              <h3 class="batch-detail-title">{{ batchCardTitle(detailItem) }}</h3>
              <p class="batch-detail-empty">
                {{ String(detailItem.status ?? '') === 'FAILED' ? '该条目搜索失败，请重新获取批量草案后重试。' : '该条目暂无可审核的候选合集。' }}
              </p>
            </template>
            <p v-else class="batch-detail-empty">请选择左侧条目查看详情。</p>
          </aside>
        </div>

        <p id="batch-parse-progress" class="batch-parse-progress" role="status">
          解析完成：{{ items.length }} / {{ parseCount }} 部；异常条目已置顶，条目顺序已固定。
        </p>

        <div id="batch-accept-toolbar" class="batch-accept-toolbar">
          <CheckboxRow
            id="batch-select-all-checkbox"
            :label="'全选当前可见可确认项'"
            :checked="allSelected"
            :disabled="selectable.length === 0 || saveInFlight"
            @update:checked="setAllSelected"
          />
          <span id="batch-accept-selected-count" class="batch-selected-count">
            全部 {{ items.length }} 项；当前筛选 {{ visibleItems.length }} 项；已选且可确认 {{ selectedCount }} 项；可确认 {{ confirmableCount }} 项；需处理 {{ needsProcessingCount }} 项；重算中 {{ processingCount }} 项；请求 {{ saveSummary.requested ?? 0 }} 项；已确认 {{ saveSummary.confirmed ?? 0 }} 项；失败 {{ saveSummary.failed ?? 0 }} 项
          </span>
          <p
            id="batch-accept-all-scope"
            class="batch-accept-scope"
            :class="{ 'is-blocked': batchConfirmableCount === 0 }"
          >
            {{ batchAcceptAllScope }}
          </p>
          <BaseButton
            v-if="saveOperation?.phase === 'response_unknown'"
            id="batch-retry-frozen-operation"
            variant="secondary"
            :loading="saveInFlight"
            :disabled="saveInFlight"
            @click="retryFrozenBatchSaveConfirm"
          >使用相同操作重试</BaseButton>
          <div class="notification-actions batch-accept-actions">
            <BaseButton
              id="batch-accept-submit"
              variant="primary"
              :disabled="selectedCount === 0 || saveInFlight"
              :loading="saveInFlight"
              @click="confirmBatchAcceptSelected"
            >
              保存并确认 {{ selectedCount }} 部
            </BaseButton>
            <BaseButton
              id="batch-accept-all"
              variant="secondary"
              :disabled="batchConfirmableCount === 0 || saveInFlight"
              :loading="saveInFlight"
              aria-describedby="batch-accept-all-scope"
              @click="confirmBatchAcceptAll"
            >
              保存并确认全部 {{ batchConfirmableCount }} 部
            </BaseButton>
          </div>
        </div>

      </template>
    </div>

    <ConfirmDialog ref="confirmDialog" />
  </PanelSection>
</template>

<style scoped>
.batch-parse-form {
  display: grid;
  gap: 0.75rem;
}

.batch-parse-form label {
  font-weight: 500;
  font-size: 0.875rem;
}

.batch-parse-result {
  display: grid;
  gap: 0.75rem;
  margin-top: 1rem;
}

.batch-card-grid-wrapper {
  max-height: 640px;
  overflow-y: auto;
  padding-right: 2px;
}

.batch-review-filters {
  align-items: end;
  background: var(--color-bg);
  display: flex;
  flex-wrap: wrap;
  gap: 0.6rem;
  padding: 0 0 0.75rem;
  position: sticky;
  top: 0;
  z-index: 1;
}

.batch-review-filters label {
  color: var(--color-text-muted);
  display: grid;
  font-size: 0.78rem;
  gap: 0.2rem;
}

.batch-review-filters input,
.batch-review-filters select {
  background: var(--color-bg);
  border: 1px solid var(--color-border);
  border-radius: 4px;
  color: var(--color-text);
  min-height: 2rem;
  padding: 0.25rem 0.5rem;
}

.batch-review-filters :deep(.checkbox-row) {
  align-self: end;
  min-height: 2rem;
}

.batch-review-count,
.batch-filter-hidden {
  color: var(--color-text-muted);
  font-size: 0.84rem;
  margin: 0 0 0.75rem;
}

.batch-review-navigation {
  align-items: center;
  display: flex;
  flex-wrap: wrap;
  gap: 0.6rem;
  margin-bottom: 0.75rem;
}

.batch-review-navigation [role='status'] {
  color: var(--color-text-muted);
  font-size: 0.84rem;
}

.batch-filter-hidden {
  color: #8a5a13;
}

.batch-review-layout {
  align-items: start;
  display: grid;
  gap: 1rem;
  grid-template-columns: minmax(260px, 36%) minmax(0, 64%);
}

.batch-detail-pane {
  background: var(--color-bg);
  border: 1px solid var(--color-border);
  border-radius: 6px;
  min-width: 0;
  padding: 1rem;
  position: sticky;
  top: 1rem;
}

.batch-detail-title {
  font-size: 1rem;
  margin: 0 0 0.5rem;
}

.batch-detail-empty {
  color: var(--color-text-muted);
  margin: 0;
}

.batch-detail-pane :deep(.batch-draft-panel) {
  margin: -1rem;
}

.batch-candidate-list {
  display: grid;
  gap: 0.75rem;
  list-style: none;
  margin: 0;
  padding: 0;
}

.batch-parse-progress {
  color: var(--color-text-muted);
  font-size: 0.84rem;
  margin: 0;
}

.batch-card-grid {
  display: grid;
  gap: 12px;
  grid-template-columns: 1fr;
  margin: 0;
  padding: 0;
}

.batch-draft-card {
  background: var(--color-bg);
  border: 1px solid var(--color-border);
  border-radius: 6px;
  display: grid;
  grid-template-columns: 76px minmax(0, 1fr);
  gap: 8px;
  min-width: 0;
  padding: 10px;
  position: relative;
}

.batch-draft-card.is-current {
  border-color: var(--color-primary);
  box-shadow: 0 0 0 2px color-mix(in srgb, var(--color-primary) 18%, transparent);
}

.batch-card-poster {
  align-items: center;
  aspect-ratio: auto;
  background: var(--color-bg-muted);
  border: 1px solid var(--color-border);
  border-radius: 4px;
  color: var(--color-text-muted);
  display: flex;
  font-size: 0.82rem;
  font-weight: 700;
  justify-content: center;
  grid-column: 1;
  grid-row: 1 / span 8;
  height: 82px;
  margin-top: 1.8rem;
  overflow: hidden;
  text-align: center;
}

.batch-card-poster-placeholder {
  padding: 8px;
}

.batch-card-title {
  overflow-wrap: anywhere;
  grid-column: 2;
}

.batch-card-raw-title,
.batch-card-source,
.batch-card-preference,
.batch-card-seeds,
.batch-card-generating-status,
.batch-card-progress {
  color: var(--color-text-muted);
  font-size: 0.84rem;
  overflow-wrap: anywhere;
  grid-column: 2;
}

/* The generating item is marked in place; the candidates it owns carry the
   aria-busy loading state in the detail pane. */
.batch-card-generating-status {
  color: var(--color-action-primary);
}

.batch-card-preference {
  color: #3f6b8f;
}

.batch-card-review-status {
  background: #fdf1dd;
  border: 1px solid #e8c378;
  color: #8a5a13;
}

.batch-card-status-row {
  align-items: center;
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  grid-column: 2;
}

.batch-card-checkbox-row {
  grid-column: 1;
  grid-row: 1;
  position: relative;
  z-index: 1;
}

.batch-card-queue-status {
  background: #e7f4e9;
  border: 1px solid #abd3b6;
  color: #1f5f34;
}

.batch-card-reason,
.batch-card-preference-note,
.batch-card-selection-help {
  color: #8d2f20;
  font-size: 0.82rem;
  overflow-wrap: anywhere;
  margin: 0;
  grid-column: 2;
}

.batch-card-selection-help {
  color: var(--color-text-muted);
  margin: 0;
}

.batch-card-delete {
  min-height: 30px;
  min-width: 30px;
  position: absolute;
  right: 8px;
  top: 8px;
}

.batch-card-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 0.5rem;
  grid-column: 2;
}

.batch-accept-toolbar {
  align-items: center;
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  margin-top: 12px;
  background: var(--color-bg);
  border-top: 1px solid var(--color-border);
  bottom: 0;
  box-shadow: 0 -4px 12px color-mix(in srgb, var(--color-text) 10%, transparent);
  padding: 0.7rem;
  position: sticky;
  z-index: 2;
}

.batch-selected-count {
  color: var(--color-text-muted);
  font-size: 0.84rem;
}

/* US-347: the confirm-all scope is stated in visible copy next to its button
   and is also the button's accessible description. */
.batch-accept-scope {
  color: var(--color-text-muted);
  flex-basis: 100%;
  font-size: 0.84rem;
  margin: 0;
  overflow-wrap: anywhere;
}

.batch-accept-scope.is-blocked {
  color: #8d2f20;
}

.batch-accept-actions {
  margin-left: auto;
}

.batch-queue-summary {
  display: grid;
  gap: 0.25rem;
  margin-top: 0.75rem;
}

@media (max-width: 1080px) {
  .batch-review-layout {
    grid-template-columns: minmax(220px, 38%) minmax(0, 62%);
  }
}

@media (max-width: 720px) {
  .batch-review-layout {
    grid-template-columns: 1fr;
  }

  .batch-detail-pane {
    position: static;
  }
}

@media (prefers-reduced-motion: reduce) {
  .batch-draft-card {
    scroll-behavior: auto;
    transition: none;
  }
}
</style>
