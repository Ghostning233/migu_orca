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
  batchAcceptAllConfirmCopy,
  batchAcceptAllScopeText,
  batchCardAuxiliaryFacts,
  batchCardNextStep,
  batchConfirmDisabledReason,
  batchSaveConfirmErrorLabel,
  batchSaveConfirmNextFocus,
  batchSaveConfirmOutcomeSummary,
  batchSaveConfirmOutcomeSummaryText,
  batchSaveConfirmRecoveryAllowed,
  batchSaveConfirmSucceeded,
  batchSaveConfirmTrackingId,
  batchSelectedConfirmCopy,
  batchSelectedScopeText,
  findBatchTrackingItem,
  batchCardNeedsReview,
  batchCardRequest,
  batchCardSeedSummary,
  batchCardTitle,
  batchItemMatchesReviewFilters,
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
  type BatchConfirmScopeCounts,
  type BatchCardFact,
  type BatchSaveConfirmDescriptor,
  type BatchSaveConfirmOutcomeSummary,
  type BatchSaveConfirmResult,
  type BatchCandidate,
  type BatchItem,
  type BatchParseResult,
} from '@/features/workbench/batchWorkbench'
import { displayValue, type RequestSnapshot } from '@/features/requests/requestDetail'
import { selectedCollectionSummary, type PreviewEditState, type SelectedCollectionSummary } from '@/features/workbench/candidateSearch'
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
const emit = defineEmits<{
  (event: 'update:rawInput', value: string): void
  (event: 'restore-search-focus'): void
}>()

// The selected candidate is a display-only, in-memory projection. It is set
// only from the candidate the user clicked and is never reconstructed from a
// Request snapshot, parser hint, alias, or another candidate.
const selectedCollectionByItem = ref<Record<string, SelectedCollectionSummary>>({})

// Batch parse state.
const rawInput = ref(props.rawInput)
const parseStarted = ref(false)
const previousRawInput = ref(props.rawInput)
const inputControl = ref<InstanceType<typeof AnimeTitleInput> | null>(null)

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
const saveSummary = ref<BatchSaveConfirmOutcomeSummary | null>(null)
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
  selectedCollectionByItem.value = {}
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
const cardGrid = ref<HTMLElement | null>(null)
const reviewScrollPositions = new Map<string, number>()
const cardElements = new Map<string, HTMLElement>()
const temporarilyShownItemId = ref<string | null>(null)
const focusAnnouncement = ref('')
const reviewFilterKey = computed(() => `${reviewQuery.value}\u0000${reviewStatus.value}\u0000${exceptionsOnly.value}`)

const selectable = computed(() => visibleItems.value.filter((item) => itemConfirmability(item.item_id ?? '').confirmable))
const processingCount = computed(() => items.value.filter((item) => draftSessions.get(item.item_id ?? '')?.applying.value).length)
const allSelected = computed(
  () => selectable.value.length > 0 && selectable.value.every((item) => selectedItemIds.value.has(item.item_id ?? '')),
)

// US-356 / D-02: N 部（保存并确认 N 部）的资格集合是「完整批次中手工勾选且当前可确认」
// 的条目。筛选只改变浏览：被隐藏的勾选仍参与，被阻断的勾选保留意图但不进入请求。
const checkedItemCount = computed(() => items.value.filter((item) => selectedItemIds.value.has(item.item_id ?? '')).length)
const selectedEligibleItems = computed(() => items.value.filter(
  (item) => selectedItemIds.value.has(item.item_id ?? '') && itemConfirmability(item.item_id ?? '').confirmable,
))
const selectedEligibleCount = computed(() => selectedEligibleItems.value.length)
const selectedExcludedCount = computed(() => Math.max(0, checkedItemCount.value - selectedEligibleCount.value))
const visibleItemIds = computed(() => new Set(visibleItems.value.map((item) => item.item_id)))
const selectedHiddenCount = computed(
  () => selectedEligibleItems.value.filter((item) => !visibleItemIds.value.has(item.item_id)).length,
)

// US-347: 保存并确认全部 的范围是完整批次，不是当前可见子集。筛选和
// 「全选当前可见可确认项」只改变浏览，因此 all 的资格集合、按钮可用性、M 计数、
// 弹窗数量和描述符都必须来自下面同一个完整批次集合。
const batchConfirmable = computed(() => items.value.filter((item) => itemConfirmability(item.item_id ?? '').confirmable))
const batchConfirmableCount = computed(() => batchConfirmable.value.length)
const batchNeedsProcessingCount = computed(() => Math.max(0, items.value.length - batchConfirmableCount.value))
const batchHiddenConfirmableCount = computed(
  () => batchConfirmable.value.filter((item) => !visibleItemIds.value.has(item.item_id)).length,
)

// US-356: 两个入口的数量、范围文案、弹窗安全清单、描述符与 item_ids 都从这一份计数派生。
const batchConfirmScope = computed<BatchConfirmScopeCounts>(() => ({
  total: items.value.length,
  visible: visibleItems.value.length,
  selected: selectedEligibleCount.value,
  selectedHidden: selectedHiddenCount.value,
  selectedExcluded: selectedExcludedCount.value,
  confirmable: batchConfirmableCount.value,
  hidden: batchHiddenConfirmableCount.value,
  needsProcessing: batchNeedsProcessingCount.value,
}))
const batchSelectedScope = computed(() => batchSelectedScopeText(batchConfirmScope.value))
const batchAcceptAllScope = computed(() => batchAcceptAllScopeText(batchConfirmScope.value))

// US-356: 保存中或上一次结果待核验时两个入口都不可用，并在固定栏常驻同一条可见原因，
// 不依赖按钮的 title。空集合的原因由各自的 scope 文案给出。
const batchSaveOperationalReason = computed(() => batchConfirmDisabledReason({
  saving: saveInFlight.value,
  pendingVerification: saveOperation.value?.phase === 'response_unknown',
}))
const canConfirmSelected = computed(() => selectedEligibleCount.value > 0 && !batchSaveOperationalReason.value)
const canConfirmAll = computed(() => batchConfirmableCount.value > 0 && !batchSaveOperationalReason.value)

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

// US-348: 打开「保存并确认全部」时把完整批次参与集合与绑定版本冻结成内存 intent
// （confirmBatchAcceptAll 的 route-local 闭包值），确认前重新核对，任何资格/版本/batch
// 变化都不发送。draft_id 等能力只存在于该对象，不展示、不持久化、不进入 URL 或存储。
interface BatchAcceptAllIntent {
  batchId: string
  participants: Array<{ itemId: string; draftId: string; baseRevision: number }>
  counts: BatchConfirmScopeCounts
  titles: string[]
}
const acceptAllDialogOpen = ref(false)
const acceptAllRecheckNotice = ref('')
const acceptAllRecheckElement = ref<HTMLElement | null>(null)

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

// US-355: the card's default layer answers 「这是什么 / 现在什么状态 / 卡在哪里 /
// 下一步做什么」. Aliases and preference details move behind 「辅助信息」, while the
// blockers, failures, unknown results and recovery actions stay in this layer.
function itemBlockers(itemId: string): string[] {
  return itemConfirmability(itemId).blockers
}

/** The card's single next step, derived from public state only. */
function cardNextStep(item: BatchItem): string {
  return batchCardNextStep({
    status: item.status,
    hasCandidates: canChooseBatchCandidate(item),
    hasDraft: canExpandBatchCard(item) && Boolean(batchCardRequest(item)),
    blocker: itemConfirmability(item.item_id ?? '').blockers[0] ?? null,
    resultUnknown: String(item.status ?? '') === 'RESPONSE_UNKNOWN',
    savedPendingConfirm: String(item.status ?? '') === 'SAVED_PENDING_CONFIRM',
    trackingLocated: Boolean(batchItemTrackingId(item)),
    generating: Boolean(generatingCandidateIdFor(item.item_id ?? '')),
  })
}

function cardAuxiliaryFacts(item: BatchItem): BatchCardFact[] {
  return batchCardAuxiliaryFacts(item)
}

/**
 * US-355: a manually checked item that is currently blocked keeps its intent —
 * it stays checked and explained — but is excluded from the confirmable set
 * until its blocker clears. Terminal cards never claim a pending intent.
 */
function cardIntentIsExcluded(item: BatchItem): boolean {
  const itemId = item.item_id ?? ''
  if (!selectedItemIds.value.has(itemId)) return false
  if (['CONFIRMED', 'SAVED_PENDING_CONFIRM'].includes(String(item.status ?? ''))) return false
  return !itemConfirmability(itemId).confirmable
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

/**
 * US-355: deleting a temporary card must not drop focus. Focus moves to the
 * next visible card, then to the previous one, and finally to the list heading
 * (the panel title, which keeps focus inside the batch workbench) so the
 * keyboard user always lands on a real, described element.
 */
function focusAfterCardRemoval(candidateItemIds: readonly string[]): void {
  void nextTick(() => {
    const target = candidateItemIds.map((itemId) => cardElements.get(itemId)).find((element) => Boolean(element))
    if (target) {
      target.focus({ preventScroll: true })
      if (typeof target.scrollIntoView === 'function') target.scrollIntoView({ block: 'nearest', behavior: 'auto' })
      return
    }
    const heading = cardGrid.value ?? document.querySelector<HTMLElement>('#panel-section-批量工作台')
    heading?.focus({ preventScroll: true })
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

// US-355: the card shortcut only owns keys pressed on the card itself. Any
// key that belongs to an inner form control (checkbox, 字幕组 select, action
// button) must stay with that control instead of moving or activating the card.
function onCardKeydown(event: KeyboardEvent, item: BatchItem): void {
  if (event.target !== event.currentTarget) return
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
    notification.error('校验失败', validationError)
    return
  }
  if (items.value.length && hasUnsafeBatchWork() && !acceptAllDialogOpen.value && !selectedDialogOpen.value) {
    const confirmed = await confirmDialog.value?.confirm({
      title: '重新搜索批量条目',
      message: '重新搜索将舍弃当前候选、草案和勾选现场，只保留新的批量输入。是否继续？',
      confirmLabel: '舍弃现场并搜索',
      cancelLabel: '取消',
    })
    if (!confirmed) {
      rawInput.value = previousRawInput.value
      await nextTick()
      inputControl.value?.focusInput()
      emit('restore-search-focus')
      return
    }
  }
  parseError.value = ''
  clearBatchRouteLocalState()
  parseStarted.value = true
  parseLoading.value = true
  journey.dispatch({ type: 'parse_started' })
  const count = batchItemCount(rawInput.value)
  parseCount.value = count
  loadingMessage.value = `正在逐项搜索 ${count} 个批量条目的 MiKan 候选；整体结果将在批量完成后统一展示，较大的批量可能需要数分钟，请耐心等待。`
  try {
    const payload = buildBatchParsePayload(rawInput.value, currentStorageDir())
    const result = await api.post<BatchParseResult>('/api/v1/batches/parse', {
      body: payload,
      timeoutMs: batchParseTimeoutMs(count),
    })
    parseResult.value = result
    previousRawInput.value = rawInput.value
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
    saveSummary.value = null
    savingItemIds.value = new Set()
    seasonConfirmations.value = {}
    notification.success('批量搜索完成', `已返回 ${items.value.length} 个条目的候选搜索状态。`)
    await nextTick()
    document.querySelector<HTMLElement>('#panel-section-批量工作台')?.focus()
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
    selectedCollectionByItem.value = {
      ...selectedCollectionByItem.value,
      [itemId]: selectedCollectionSummary(candidate, seasonConfirmations.value[candidate.bangumi_id] ?? null),
    }
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
  // US-355: capture the removal neighbourhood before the card leaves the list,
  // so focus can land on the next card, then the previous one, then the list.
  const visible = visibleItems.value
  const removedIndex = visible.findIndex((item) => item.item_id === itemId)
  const focusTargets = removedIndex < 0
    ? []
    : [visible[removedIndex + 1]?.item_id, visible[removedIndex - 1]?.item_id]
      .filter((candidate): candidate is string => Boolean(candidate))
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
  const selectedCollections = { ...selectedCollectionByItem.value }
  delete selectedCollections[itemId]
  selectedCollectionByItem.value = selectedCollections
  items.value = items.value.filter((item) => item.item_id !== itemId)
  focusAfterCardRemoval(focusTargets)
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

function applySaveConfirmResult(result: BatchSaveConfirmResult): {
  summary: BatchSaveConfirmOutcomeSummary
  nextFocus: ReturnType<typeof batchSaveConfirmNextFocus>
  trackingId: string | null
} {
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
  const summary = batchSaveConfirmOutcomeSummary(resultItems, nextItems)
  const nextFocus = batchSaveConfirmNextFocus(resultItems, nextItems)
  const trackingId = batchSaveConfirmTrackingId(resultItems)
  if (nextFocus) {
    const target = nextItems.find((item) => item.item_id === nextFocus.itemId)
    if (target) {
      const hidden = !visibleItems.value.some((item) => item.item_id === nextFocus.itemId)
      temporarilyShownItemId.value = hidden ? nextFocus.itemId : null
      selectCurrentItem(target)
      focusAnnouncement.value = nextFocus.kind === 'failed'
        ? `已定位到首个失败条目：${batchCardTitle(target)}`
        : `已定位到首个未处理条目：${batchCardTitle(target)}`
      focusCard(nextFocus.itemId)
    }
  }
  return { summary, nextFocus, trackingId }
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
  // A later save attempt owns the next result summary. Never leave the
  // previous batch response looking like the current operation while this
  // request is in flight or awaiting verification.
  saveSummary.value = null
  saveInFlight.value = true
  savingItemIds.value = new Set(rows.map((row) => row.item_id ?? '').filter(Boolean))
  // Undefined means this response still has work (or did not settle). Null is
  // a completed batch whose tracking handoff has no usable public id.
  let completionTrackingId: string | null | undefined
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
    const resultItems = validateBatchSaveResult(result, rows.map((row) => row.item_id ?? ''))
    if (!resultItems) {
      saveSummary.value = null
      if (saveOperation.value) saveOperation.value = { ...saveOperation.value, phase: 'response_unknown' }
      journey.dispatch({ type: 'save_response_unknown', itemIds: rows.map((row) => row.item_id ?? '') })
      items.value = items.value.map((item) => savingItemIds.value.has(item.item_id ?? '') ? { ...item, status: 'RESPONSE_UNKNOWN' } : item)
      notification.error('保存确认结果待核验', '响应未知，请使用相同操作重试。')
      return
    }
    const applied = applySaveConfirmResult({ ...result, results: resultItems })
    saveSummary.value = applied.summary
    const resultById = new Map(resultItems.map((resultItem) => [resultItem.item_id, resultItem]))
    for (const row of rows) {
      const itemId = row.item_id ?? ''
      const resultItem = resultById.get(itemId)
      if (resultItem && batchSaveConfirmSucceeded(resultItem)) journey.dispatch({ type: 'save_succeeded', itemId, result: resultItem })
      else if (resultItem) journey.dispatch({ type: 'save_failed', itemId, error: resultItem })
    }
    notification.show(
      applied.summary.failed > 0 && applied.summary.confirmed === 0 ? 'error' : 'success',
      '批量保存确认完成',
      batchSaveConfirmOutcomeSummaryText(applied.summary),
    )
    saveOperation.value = null
    if (applied.summary.remaining === 0) {
      completionTrackingId = applied.trackingId
    }
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
      saveSummary.value = null
      if (saveOperation.value) saveOperation.value = { ...saveOperation.value, phase: 'response_unknown' }
      journey.dispatch({ type: 'save_response_unknown', itemIds: rows.map((row) => row.item_id ?? ''), error })
      items.value = items.value.map((item) => savingItemIds.value.has(item.item_id ?? '') ? { ...item, status: 'RESPONSE_UNKNOWN' } : item)
      notification.error('保存确认结果待核验', '响应未知，请使用相同操作重试。')
    }
  } finally {
    saveInFlight.value = false
    savingItemIds.value = new Set()
    if (completionTrackingId !== undefined && router.hasRoute('tracking')) {
      // D-04: only use a server-provided public tracking id. If the handoff is
      // not ready, enter the management page without inventing a query id.
      await router.replace(routeLocation('tracking', completionTrackingId ? { tracking_id: completionTrackingId } : {}))
    }
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

// US-356: 打开「保存并确认 N 部」时把 D-02 的完整勾选资格集合、绑定版本与安全标题清单
// 冻结成内存 intent，确认前重新核对；之后任何筛选或可见性变化都不得改写它。
interface BatchSelectedIntent {
  batchId: string
  participants: Array<{ itemId: string; draftId: string; baseRevision: number }>
  itemIds: string[]
  counts: BatchConfirmScopeCounts
  titles: string[]
}
const selectedDialogOpen = ref(false)
const selectedRecheckNotice = ref('')
const selectedRecheckElement = ref<HTMLElement | null>(null)

// US-356: 固定操作栏是 sticky 的，会浮在批量内容之上；它的真实渲染高度（多行范围文案与
// 禁用原因换行后会变高）作为 CSS 变量发布，布局据此预留底部滚动空间，卡片聚焦或滚动
// 定位时也把固定栏让出来，末卡/字段/错误因此不会被遮挡。
const acceptToolbarElement = ref<HTMLElement | null>(null)
const acceptToolbarHeight = ref(0)
let acceptToolbarObserver: ResizeObserver | null = null

function measureAcceptToolbar(): void {
  acceptToolbarHeight.value = Math.ceil(acceptToolbarElement.value?.getBoundingClientRect().height ?? 0)
}

function setAcceptToolbarElement(element: unknown): void {
  acceptToolbarObserver?.disconnect()
  acceptToolbarObserver = null
  acceptToolbarElement.value = element instanceof HTMLElement ? element : null
  if (acceptToolbarElement.value && typeof ResizeObserver !== 'undefined') {
    acceptToolbarObserver = new ResizeObserver(() => measureAcceptToolbar())
    acceptToolbarObserver.observe(acceptToolbarElement.value)
  }
  measureAcceptToolbar()
}

// 两个入口的可访问描述始终包含自己的范围文案，并追加当前的常驻说明/禁用原因。
const selectedEntryDescription = computed(() => [
  'batch-accept-selected-scope',
  ...(selectedRecheckNotice.value ? ['batch-accept-selected-recheck'] : []),
  ...(batchSaveOperationalReason.value ? ['batch-accept-selected-reason'] : []),
].join(' '))
const allEntryDescription = computed(() => [
  'batch-accept-all-scope',
  ...(acceptAllRecheckNotice.value ? ['batch-accept-all-recheck'] : []),
  ...(batchSaveOperationalReason.value ? ['batch-accept-all-reason'] : []),
].join(' '))

/** Freeze the complete batch's manually checked eligible set as the N intent. */
function buildSelectedIntent(): BatchSelectedIntent | null {
  const rows = selectedEligibleItems.value
  if (!rows.length) return null
  const participants = rows.map((row) => ({
    itemId: row.item_id ?? '',
    draftId: row.draft_id ?? '',
    baseRevision: row.draft_revision ?? 1,
  }))
  if (participants.some((participant) => !participant.itemId || !participant.draftId)) return null
  return {
    batchId: batchId.value,
    participants,
    itemIds: participants.map((participant) => participant.itemId),
    counts: batchConfirmScope.value,
    // 安全标题清单与描述符、item_ids 同源：同一批次顺序、同一冻结集合。
    titles: rows.map((row) => displayValue(batchCardTitle(row))),
  }
}

/** True only while the frozen N intent is exactly what would be sent now. */
function selectedIntentIsCurrent(intent: BatchSelectedIntent): boolean {
  if (batchId.value !== intent.batchId) return false
  const rows = selectedEligibleItems.value
  if (rows.length !== intent.participants.length) return false
  return intent.participants.every((participant) => {
    const row = rows.find((item) => item.item_id === participant.itemId)
    if (!row) return false
    return row.draft_id === participant.draftId && (row.draft_revision ?? 1) === participant.baseRevision
  })
}

async function confirmBatchAcceptSelected(): Promise<void> {
  // 与全部入口相同：函数入口先挡住重复调用，避免第二次点击替换一个已打开的确认。
  if (selectedDialogOpen.value || saveInFlight.value) return
  selectedRecheckNotice.value = ''
  const intent = buildSelectedIntent()
  if (!intent) return
  selectedDialogOpen.value = true
  try {
    const copy = batchSelectedConfirmCopy(intent.counts, intent.titles)
    const ok = await confirmDialog.value?.confirm({
      title: copy.title,
      message: copy.message,
      confirmLabel: copy.confirmLabel,
      items: copy.items,
      itemsLabel: copy.itemsLabel,
    })
    if (!ok) return
    if (!selectedIntentIsCurrent(intent)) {
      // 弹窗期间资格、draft_id、revision 或批次绑定变化：零请求，常驻说明并要求重新确认。
      selectedRecheckNotice.value = '已勾选条目的资格或草案版本已变化，本次未发送任何请求；请核对后重新确认。'
      await nextTick()
      selectedRecheckElement.value?.focus()
      return
    }
    const rows = intent.participants
      .map((participant) => items.value.find((item) => item.item_id === participant.itemId))
      .filter((row): row is BatchItem => Boolean(row))
    await submitBatchSaveConfirm(rows, intent.itemIds)
  } finally {
    selectedDialogOpen.value = false
  }
}

/** Freeze the complete batch's confirmable set as the confirm-all intent. */
function buildAcceptAllIntent(): BatchAcceptAllIntent | null {
  const rows = batchConfirmable.value
  if (!rows.length) return null
  const participants = rows.map((row) => ({
    itemId: row.item_id ?? '',
    draftId: row.draft_id ?? '',
    baseRevision: row.draft_revision ?? 1,
  }))
  if (participants.some((participant) => !participant.itemId || !participant.draftId)) return null
  return {
    batchId: batchId.value,
    participants,
    counts: batchConfirmScope.value,
    // US-356: 安全标题清单与描述符、item_ids 同源（同一冻结集合、同一批次顺序）。
    titles: rows.map((row) => displayValue(batchCardTitle(row))),
  }
}

/**
 * True only while the frozen intent is exactly what would be sent now: the same
 * batch, the same eligible rows (neither added nor removed) and the same
 * draft/revision binding per participant. A changed scope always requires a new
 * confirmation instead of silently filtering or padding the old one.
 */
function acceptAllIntentIsCurrent(intent: BatchAcceptAllIntent): boolean {
  if (batchId.value !== intent.batchId) return false
  const rows = batchConfirmable.value
  if (rows.length !== intent.participants.length) return false
  return intent.participants.every((participant) => {
    const row = rows.find((item) => item.item_id === participant.itemId)
    if (!row) return false
    return row.draft_id === participant.draftId && (row.draft_revision ?? 1) === participant.baseRevision
  })
}

async function confirmBatchAcceptAll(): Promise<void> {
  // US-348: the dialog shows one frozen intent, and what it shows is what the
  // request sends. The function-level guard (not only the disabled state) keeps
  // a second invocation from replacing an open confirmation with a different
  // scope.
  if (acceptAllDialogOpen.value || saveInFlight.value) return
  acceptAllRecheckNotice.value = ''
  const intent = buildAcceptAllIntent()
  if (!intent) return
  acceptAllDialogOpen.value = true
  try {
    const copy = batchAcceptAllConfirmCopy(intent.counts, intent.titles)
    const ok = await confirmDialog.value?.confirm({
      title: copy.title,
      message: copy.message,
      confirmLabel: copy.confirmLabel,
      items: copy.items,
      itemsLabel: copy.itemsLabel,
    })
    if (!ok) return
    if (!acceptAllIntentIsCurrent(intent)) {
      // The frozen set or a bound version moved while the dialog was open. Send
      // nothing, keep the scene, and leave a persistent explanation next to the
      // entry instead of a toast; the user confirms again explicitly.
      acceptAllRecheckNotice.value = '完整批次的资格或草案版本已变化，本次未发送任何请求；请核对后重新确认全部。'
      await nextTick()
      acceptAllRecheckElement.value?.focus()
      return
    }
    // Send exactly the frozen participants; submitBatchSaveConfirm still
    // re-checks every one of them and freezes the request for an unknown result.
    const rows = intent.participants
      .map((participant) => items.value.find((item) => item.item_id === participant.itemId))
      .filter((row): row is BatchItem => Boolean(row))
    await submitBatchSaveConfirm(rows, null)
  } finally {
    acceptAllDialogOpen.value = false
  }
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
  void nextTick(() => {
    const heading = document.querySelector<HTMLElement>('#panel-section-批量工作台')
    heading?.setAttribute('tabindex', '-1')
  })
})

onUnmounted(() => {
  acceptToolbarObserver?.disconnect()
  acceptToolbarObserver = null
  for (const { scheduler } of editSchedulers.values()) scheduler.dispose()
  editSchedulers.clear()
})

defineExpose({ parseBatch, generateDraftFromCandidate, submitBatchSaveConfirm, deleteBatchCard })
</script>

<template>
  <PanelSection title="批量工作台" class="batch-workbench-panel">
    <form v-if="!props.hideInput" id="batch-parse-form" class="batch-parse-form" @submit.prevent="parseBatch">
      <label v-if="!props.hideInput" for="batch-raw-input">批量番剧名称</label>
      <AnimeTitleInput
        ref="inputControl"
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

    <div
      v-if="parseStarted || parseLoading || parseError || items.length"
      id="batch-parse-result"
      class="batch-parse-result"
      aria-live="polite"
      aria-relevant="additions text"
      :style="{ '--batch-accept-toolbar-height': `${acceptToolbarHeight}px` }"
    >
      <LoadingState v-if="parseLoading" :message="loadingMessage" />
      <p v-if="parseLoading" id="batch-parse-loading-summary" class="batch-parse-loading-summary" role="status">
        原文：{{ rawInput }}；本次提交规模：{{ parseCount }} 部；整体搜索进行中，暂不展示逐项进度。
      </p>
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
          <!-- US-355: 左列 = 筛选控件 + 卡片列表。控件留在滚动区之外，因此清除
               筛选入口始终可达；滚动区只包含卡片本身，卡片焦点环不会被裁掉。 -->
          <div class="batch-review-list-column">
            <div class="batch-review-controls">
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
            <!-- US-355: 筛选无匹配是「当前条件没有命中」，不是空批次；数据和勾选都还在。 -->
            <p v-if="items.length && !visibleItems.length" id="batch-review-no-match" class="batch-review-no-match" role="status">
              没有符合当前筛选条件的条目；本批次仍有 {{ items.length }} 部，数据、勾选与右栏详情均未改变。请调整或清除筛选条件后继续。
            </p>
            </div>
            <div ref="reviewList" class="batch-card-grid-wrapper">
              <div
                ref="cardGrid"
                class="batch-card-grid"
                role="list"
                aria-label="批量草案卡片"
                tabindex="-1"
              >
            <article
              v-for="item in visibleItems"
              :key="item.item_id ?? item.raw_title ?? ''"
              class="batch-draft-card"
              :class="{ 'is-current': currentItemId === item.item_id }"
              :data-item-id="item.item_id ?? ''"
              :aria-label="`查看条目：${batchCardTitle(item)}（${batchStatusLabel(item.status)}）`"
              role="listitem"
              tabindex="0"
              :ref="(element) => setCardElement(item.item_id, element)"
              @click="selectCurrentItem(item)"
              @keydown="onCardKeydown($event, item)"
            >
              <div class="batch-card-checkbox-cell">
                <CheckboxRow
                  class="batch-card-checkbox-row"
                  :class="{ 'is-selected': selectedItemIds.has(item.item_id ?? '') }"
                  :label="`选择 ${item.raw_title ?? '批量条目'}`"
                  :checked="selectedItemIds.has(item.item_id ?? '')"
                  :disabled="!itemConfirmability(item.item_id ?? '').confirmable || operationLocks(item.item_id ?? '')"
                  @click.stop
                  @update:checked="(value: boolean) => toggleItemSelection(item.item_id ?? '', value)"
                />
              </div>
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
                <span
                  v-if="canChooseBatchCandidate(item)"
                  class="batch-card-poster-placeholder"
                  data-poster-state="unselected"
                  title="待选择真实 MiKan 合集"
                >
                  待选择
                </span>
                <span
                  v-else
                  class="batch-card-poster-placeholder"
                  data-poster-state="unavailable"
                  title="暂无封面"
                >
                  无封面
                </span>
              </div>

              <!-- 默认层：标题、中文状态、阻断/错误、下一步。别名与偏好等辅助
                   信息进下面的「辅助信息」折叠，失败与恢复动作永不折叠。 -->
              <div class="batch-card-main">
                <div class="batch-card-headline">
                  <strong class="batch-card-title">{{ batchCardTitle(item) }}</strong>
                  <span class="batch-status batch-card-status">{{ batchStatusLabel(item.status) }}</span>
                  <span v-if="batchCardNeedsReview(item)" class="batch-status batch-card-review-status">
                    需人工核对
                  </span>
                </div>
                <p class="batch-card-meta">
                  <span class="batch-card-raw-title">输入：{{ displayValue(item.raw_title) }}</span>
                  <span v-if="batchCardRequest(item)" class="batch-card-seeds">有效种子数：{{ batchCardSeedSummary(item) }}</span>
                </p>

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

                <p v-if="draftApplyErrors[item.item_id ?? '']" class="batch-card-reason">
                  {{ draftApplyErrors[item.item_id ?? ''] }}
                </p>
                <p v-if="acceptFeedback[item.item_id ?? '']" class="batch-card-reason">
                  {{ acceptFeedback[item.item_id ?? ''] }}
                </p>
                <p v-if="recoveryFeedback[item.item_id ?? '']" class="batch-card-reason" role="status">
                  {{ recoveryFeedback[item.item_id ?? ''] }}
                </p>
                <p
                  v-if="item.review_hints?.length"
                  class="batch-card-preference-note"
                >
                  {{ item.review_hints.join('；') }}
                </p>

                <p v-if="cardIntentIsExcluded(item)" class="batch-card-intent-note" role="status">
                  已勾选，但当前不可确认：{{ itemBlockers(item.item_id ?? '')[0] ?? '暂不可确认' }}；解决后仍会参与保存确认。
                </p>
                <p
                  v-else-if="!['CONFIRMED', 'SAVED_PENDING_CONFIRM', 'FAILED', 'EMPTY'].includes(String(item.status ?? '')) && !itemConfirmability(item.item_id ?? '').confirmable"
                  class="batch-card-selection-help"
                >
                  {{ itemBlockers(item.item_id ?? '')[0] ?? '当前条目暂不可加入批量确认。' }}
                </p>

                <p class="batch-card-next-step">下一步：{{ cardNextStep(item) }}</p>

                <div v-if="canExpandBatchCard(item) && batchCardRequest(item)" class="batch-card-subtitle-group" @click.stop>
                  <label :for="`batch-card-subtitle-${item.item_id}`">字幕组</label>
                  <select
                    :id="`batch-card-subtitle-${item.item_id}`"
                    :value="cardSubtitleGroupValue(item)"
                    :disabled="operationLocks(item.item_id ?? '') || draftSessions.get(item.item_id ?? '')?.applying.value"
                    @change="applyCardSubtitleGroup(item, ($event.target as HTMLSelectElement).value)"
                  >
                    <option value="">保持当前选择</option>
                    <option v-for="option in subtitleGroupOptions(item)" :key="option.value" :value="option.value">{{ option.label }}</option>
                  </select>
                  <p v-if="draftSessions.get(item.item_id ?? '')?.applying.value" class="field-help" aria-live="polite">正在重新计算资源...</p>
                  <BaseButton
                    v-if="draftSessions.get(item.item_id ?? '')?.canRetry.value"
                    variant="secondary"
                    :disabled="savingItemIds.has(item.item_id ?? '') || draftSessions.get(item.item_id ?? '')?.applying.value"
                    @click.stop="retryCardModify(item)"
                  >重试修改</BaseButton>
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
                  <BaseButton
                    v-else
                    class="batch-card-expand"
                    disabled
                    :aria-label="`查看候选：${item.raw_title ?? '批量条目'}`"
                    title="当前条目没有可选择的候选合集"
                  >
                    查看候选
                  </BaseButton>
                </div>

                <details class="batch-card-more">
                  <summary>辅助信息</summary>
                  <dl class="batch-card-facts">
                    <template v-for="fact in cardAuxiliaryFacts(item)" :key="fact.label">
                      <dt>{{ fact.label }}</dt>
                      <dd>{{ fact.value }}</dd>
                    </template>
                  </dl>
                </details>
              </div>
            </article>
              </div>
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
                compact
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
                  :candidate-summary="selectedCollectionByItem[detailItem.item_id ?? ''] ?? null"
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
                <!-- US-356: 禁用原因常驻可见，不只挂在 title 上。 -->
                <p
                  v-if="!itemConfirmability(detailItem.item_id ?? '').confirmable"
                  class="field-help batch-detail-blocker"
                  role="status"
                >
                  当前条目暂不可加入批量确认：{{ itemConfirmability(detailItem.item_id ?? '').blockers.join('；') }}。
                </p>
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

        <div id="batch-accept-toolbar" :ref="setAcceptToolbarElement" class="batch-accept-toolbar">
          <CheckboxRow
            id="batch-select-all-checkbox"
            :label="'全选当前可见可确认项'"
            :checked="allSelected"
            :disabled="selectable.length === 0 || saveInFlight"
            @update:checked="setAllSelected"
          />
          <span id="batch-accept-selected-count" class="batch-selected-count" role="group">
            <span class="batch-count-group" data-scope="complete-batch">完整批次 {{ items.length }} 部；可确认 {{ batchConfirmableCount }} 部；需处理 {{ batchNeedsProcessingCount }} 部</span>
            <span class="batch-count-group" data-scope="visible">当前可见 {{ visibleItems.length }} 部</span>
            <span class="batch-count-group" data-scope="selection">已勾选 {{ checkedItemCount }} 部；已选且可确认 {{ selectedEligibleCount }} 项；其中被筛选隐藏仍参与 {{ selectedHiddenCount }} 项；已排除 {{ selectedExcludedCount }} 项</span>
            <span v-if="processingCount" class="batch-count-group" data-scope="recalculating">重算中 {{ processingCount }} 部</span>
            <span v-if="saveSummary" id="batch-save-summary" class="batch-count-group" data-scope="last-save">
              {{ batchSaveConfirmOutcomeSummaryText(saveSummary) }}
            </span>
          </span>
          <!-- US-356: 两个入口的范围常驻可见，并同时是按钮的可访问描述。 -->
          <p
            id="batch-accept-selected-scope"
            class="batch-accept-scope"
            :class="{ 'is-blocked': selectedEligibleCount === 0 }"
          >
            {{ batchSelectedScope }}
          </p>
          <p
            v-if="batchSaveOperationalReason"
            id="batch-accept-selected-reason"
            class="batch-accept-reason"
            role="status"
          >
            保存并确认勾选条目暂不可用：{{ batchSaveOperationalReason }}
          </p>
          <!-- US-356: 弹窗打开后资格/版本/批次变化时零请求，常驻说明并要求重新确认。 -->
          <p
            v-if="selectedRecheckNotice"
            id="batch-accept-selected-recheck"
            ref="selectedRecheckElement"
            class="batch-accept-recheck"
            role="status"
            tabindex="-1"
          >
            {{ selectedRecheckNotice }}
          </p>
          <p
            id="batch-accept-all-scope"
            class="batch-accept-scope"
            :class="{ 'is-blocked': batchConfirmableCount === 0 }"
          >
            {{ batchAcceptAllScope }}
          </p>
          <p
            v-if="batchSaveOperationalReason"
            id="batch-accept-all-reason"
            class="batch-accept-reason"
            role="status"
          >
            保存并确认全部暂不可用：{{ batchSaveOperationalReason }}
          </p>
          <!-- US-348: 确认前复核失败时，说明常驻在固定业务区（不是 Toast），
               并获得焦点；不会自动再次打开确认。 -->
          <p
            v-if="acceptAllRecheckNotice"
            id="batch-accept-all-recheck"
            ref="acceptAllRecheckElement"
            class="batch-accept-recheck"
            role="status"
            tabindex="-1"
          >
            {{ acceptAllRecheckNotice }}
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
              :disabled="!canConfirmSelected"
              :loading="saveInFlight"
              :aria-describedby="selectedEntryDescription"
              @click="confirmBatchAcceptSelected"
            >
              保存并确认 {{ selectedEligibleCount }} 部
            </BaseButton>
            <BaseButton
              id="batch-accept-all"
              variant="secondary"
              :disabled="!canConfirmAll"
              :loading="saveInFlight"
              :aria-describedby="allEntryDescription"
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

/* US-355: the list scrolls on its own; filters, counts and the clear-filter
   entry stay outside it (always reachable), and the horizontal padding leaves
   room for the 3px focus ring so card focus is never clipped. */
.batch-card-grid-wrapper {
  max-height: 640px;
  overflow-y: auto;
  padding: 6px;
}

.batch-review-controls {
  display: grid;
  min-width: 0;
}

.batch-review-filters {
  align-items: end;
  display: flex;
  flex-wrap: wrap;
  gap: 0.6rem;
  padding: 0 0 0.5rem;
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
  margin: 0 0 0.5rem;
}

.batch-review-navigation {
  align-items: center;
  display: flex;
  flex-wrap: wrap;
  gap: 0.6rem;
  margin-bottom: 0.5rem;
}

.batch-review-navigation [role='status'] {
  color: var(--color-text-muted);
  font-size: 0.84rem;
}

.batch-filter-hidden {
  color: #8a5a13;
}

/* US-355: 筛选无匹配不是空批次，必须与空批次的 EmptyState 明确区分。 */
.batch-review-no-match {
  color: #8a5a13;
  font-size: 0.84rem;
  margin: 0 0 0.5rem;
  overflow-wrap: anywhere;
}

.batch-review-layout {
  align-items: start;
  display: grid;
  gap: 1rem;
  grid-template-columns: minmax(260px, 36%) minmax(0, 64%);
  /* US-356: 固定操作栏的真实多行高度作为底部滚动空间预留，末卡、字段与错误
     可以滚到固定栏之上，不被遮挡。 */
  padding-bottom: var(--batch-accept-toolbar-height, 0px);
}

.batch-review-list-column {
  display: grid;
  min-width: 0;
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

.batch-detail-blocker {
  color: #8a5a13;
  margin: 0.5rem 0 0;
  overflow-wrap: anywhere;
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
  gap: 10px;
  grid-template-columns: 1fr;
  margin: 0;
  padding: 0;
}

.batch-card-grid:focus-visible {
  outline: var(--focus-ring-width) solid var(--color-focus-ring);
  outline-offset: calc(-1 * var(--focus-ring-width));
}

/* US-355 紧凑左卡：默认层只有标题、中文状态、阻断/错误、下一步与动作；
   别名与偏好进 .batch-card-more，因此 1440×900 能同屏看到多张完整卡。 */
.batch-draft-card {
  background: var(--color-bg);
  border: 1px solid var(--color-border);
  border-radius: 6px;
  display: grid;
  grid-template-columns: auto 48px minmax(0, 1fr);
  gap: 3px 6px;
  min-width: 0;
  padding: 6px 8px;
  position: relative;
  /* US-355 的 8px 焦点环余量 + US-356 的固定栏高度：卡片被聚焦或滚动定位时
     让出固定栏，末卡不会被粘住的保存栏遮住。 */
  scroll-margin: 8px 8px calc(8px + var(--batch-accept-toolbar-height, 0px));
}

.batch-draft-card:focus-visible {
  outline: var(--focus-ring-width) solid var(--color-focus-ring);
  outline-offset: var(--focus-ring-offset);
}

.batch-draft-card.is-current {
  border-color: var(--color-primary);
  box-shadow: 0 0 0 2px color-mix(in srgb, var(--color-primary) 18%, transparent);
}

.batch-card-poster {
  align-items: center;
  background: var(--color-bg-muted);
  border: 1px solid var(--color-border);
  border-radius: 4px;
  color: var(--color-text-muted);
  display: flex;
  font-size: 0.68rem;
  font-weight: 700;
  grid-column: 2;
  grid-row: 1;
  height: 44px;
  overflow: hidden;
  text-align: center;
}

.batch-card-poster-placeholder {
  padding: 2px;
}

.batch-card-main {
  display: grid;
  gap: 3px;
  grid-column: 3;
  grid-row: 1 / span 2;
  min-width: 0;
}

.batch-card-headline {
  align-items: baseline;
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  min-width: 0;
}

.batch-card-title {
  font-size: 1rem;
  font-weight: 600;
  line-height: 1.35;
  overflow-wrap: anywhere;
}

.batch-card-meta {
  color: var(--color-text-muted);
  display: flex;
  flex-wrap: wrap;
  font-size: 0.78rem;
  gap: 0.25rem 0.75rem;
  margin: 0;
}

.batch-card-raw-title,
.batch-card-seeds,
.batch-card-generating-status {
  color: var(--color-text-muted);
  font-size: 0.78rem;
  overflow-wrap: anywhere;
}

/* The generating item is marked in place; the candidates it owns carry the
   aria-busy loading state in the detail pane. */
.batch-card-generating-status {
  color: var(--color-action-primary);
  margin: 0;
}

.batch-card-review-status {
  background: #fdf1dd;
  border: 1px solid #e8c378;
  color: #8a5a13;
}

/* US-355: 默认层常驻的下一步。 */
.batch-card-next-step {
  color: var(--color-text);
  font-size: 0.82rem;
  margin: 0;
  overflow-wrap: anywhere;
}

/* US-355: 已勾选但当前被阻断的条目保留手工意图，并在卡片原位说明为什么被排除。 */
.batch-card-intent-note {
  color: #8a5a13;
  font-size: 0.82rem;
  margin: 0;
  overflow-wrap: anywhere;
}

.batch-card-checkbox-row {
  min-width: 1.25rem;
}

/* US-355: 快捷字幕组编辑与右栏共用同一个 scheduler，改完就地重算；它是紧凑层
   里的快捷动作，因此不进入「辅助信息」折叠。 */
.batch-card-subtitle-group {
  align-items: center;
  display: flex;
  flex-wrap: wrap;
  gap: 0.4rem;
}

.batch-card-subtitle-group label {
  color: var(--color-text-muted);
  font-size: 0.78rem;
}

.batch-card-subtitle-group select {
  background: var(--color-bg);
  border: 1px solid var(--color-border);
  border-radius: 4px;
  color: var(--color-text);
  font-size: 0.82rem;
  min-height: 1.9rem;
  min-width: 9rem;
  padding: 0.15rem 0.4rem;
}

.batch-card-subtitle-group .field-help,
.batch-card-subtitle-group .batch-card-reason {
  flex-basis: 100%;
}

/* CheckboxRow 把 class 透传到原生 input，因此卡片里的这一格由外层 cell 承担。 */
.batch-card-checkbox-cell {
  grid-column: 1;
  grid-row: 1;
  min-width: 1.5rem;
  position: relative;
  z-index: 1;
}

/* 紧凑列表里的复选框按桌面尺寸呈现（touch 目标尺寸留给移动端布局）。 */
.batch-card-checkbox-cell :deep(.base-checkbox) {
  margin-top: 0.1rem;
  min-height: 1.25rem;
  min-width: 1.25rem;
}

/* 复选框的可访问名称仍是「选择 <条目>」，视觉上只保留控件本身，避免在紧凑
   列表里重复条目名称。 */
.batch-card-checkbox-cell :deep(.checkbox-row-label) {
  border: 0;
  clip-path: inset(50%);
  height: 1px;
  overflow: hidden;
  position: absolute;
  white-space: nowrap;
  width: 1px;
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
}

.batch-card-selection-help {
  color: var(--color-text-muted);
}

/* US-355: 长错误/长阻断原因自然增高，不裁切也不截断。 */
.batch-card-reason,
.batch-card-preference-note,
.batch-card-intent-note,
.batch-card-next-step {
  max-height: none;
  overflow: visible;
  text-overflow: clip;
  white-space: normal;
}

.batch-card-delete {
  min-height: 30px;
  min-width: 30px;
  position: absolute;
  right: 6px;
  top: 6px;
}

.batch-card-actions {
  align-items: center;
  display: flex;
  flex-wrap: wrap;
  gap: 0.5rem;
}

/* US-355: 按需展开的辅助信息（别名、检索词、季数、偏好、种子与集数）。 */
.batch-card-more {
  font-size: 0.75rem;
}

.batch-card-more > summary {
  color: var(--color-text-muted);
  cursor: pointer;
  line-height: 1.3;
  width: fit-content;
}

.batch-card-more > summary:focus-visible {
  outline: var(--focus-ring-width) solid var(--color-focus-ring);
  outline-offset: var(--focus-ring-offset);
}

.batch-card-facts {
  color: var(--color-text-muted);
  display: grid;
  gap: 2px 8px;
  grid-template-columns: auto minmax(0, 1fr);
  margin: 4px 0 0;
}

.batch-card-facts dt {
  font-weight: 550;
}

.batch-card-facts dd {
  margin: 0;
  overflow-wrap: anywhere;
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
  display: flex;
  flex-basis: 100%;
  flex-wrap: wrap;
  font-size: 0.84rem;
  gap: 0.3rem 0.5rem;
  min-width: 0;
}

/* US-356: 完整批次 / 当前可见 / 已勾选 / 重算中 / 上次保存各自成组，组内文案自带
   作用域名称，不再是一行难以分辨的连续数字。 */
.batch-count-group {
  background: var(--color-bg-muted);
  border-radius: 4px;
  padding: 0.1rem 0.45rem;
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

/* US-356: 保存中/待核验时两个入口都不可用，这条常驻原因与各自的条目相邻，
   不依赖 title。 */
.batch-accept-reason {
  color: #8a5a13;
  flex-basis: 100%;
  font-size: 0.84rem;
  margin: 0;
  overflow-wrap: anywhere;
}

/* US-348: the rejection of a stale confirmation is permanent business-area
   copy, so it is focusable and always shows a visible focus ring. */
.batch-accept-recheck {
  color: #8d2f20;
  flex-basis: 100%;
  font-size: 0.84rem;
  margin: 0;
  overflow-wrap: anywhere;
}

.batch-accept-recheck:focus {
  outline: 2px solid var(--color-primary);
  outline-offset: 2px;
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
