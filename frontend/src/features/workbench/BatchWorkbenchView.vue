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
//   - each FOUND card opens the shared candidate popover (reuses
//     CandidateCard); choosing a candidate generates a server-authoritative
//     draft (POST /api/v1/requests save_request=false) into the card;
//   - DRAFT cards open BatchDraftPreviewPanel (preview-modify / preview-save)
//     plus a batch-specific 接受当前批量草案 / 删除当前批量卡片
//     action row;
//   - the accept toolbar offers select-all, a live selected count, 批量接受
//     (selected) and 全接受 (all reviewable cards), each through the shared
//     POST /api/v1/batches/{batch_id}/accept endpoint;
//   - batch_id is pushed into the URL so a refresh restores the queue (the
//     queue panel itself lands in US-206).
//
// Security boundary: batch items/candidates are the public whitelist only;
// candidate_context / draft_id live only in component memory (never URL/
// storage/logs). Accept payloads carry only item_id/request_id/title (public
// fields) + storage_dir (relative profile). Destructive/irreversible actions
// go through the shared ConfirmDialog and failures surface fixed Chinese copy
// only.
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import { api } from '@/api/client'
import { useNotificationStore } from '@/app/stores/notification'
import ConfirmDialog from '@/components/feedback/ConfirmDialog.vue'
import EmptyState from '@/components/feedback/EmptyState.vue'
import ErrorState from '@/components/feedback/ErrorState.vue'
import LoadingState from '@/components/feedback/LoadingState.vue'
import BaseButton from '@/components/forms/BaseButton.vue'
import CheckboxRow from '@/components/forms/CheckboxRow.vue'
import PanelSection from '@/components/layout/PanelSection.vue'
import AnimeTitleInput from '@/features/workbench/AnimeTitleInput.vue'
import CandidateCollectionList from '@/features/workbench/CandidateCollectionList.vue'

import {
  acceptFeedbackLabel,
  acceptOutcomeAccepted,
  batchAcceptNotification,
  batchCardNeedsReview,
  batchCardPreferenceSummary,
  batchCardRequest,
  batchCardSeedSummary,
  batchCardTitle,
  batchItemMatchesReviewFilters,
  batchEpisodeProgressText,
  batchItemCount,
  batchStatusLabel,
  buildBatchAcceptPayload,
  buildBatchCandidateCreatePayload,
  buildBatchParsePayload,
  canAcceptBatchCard,
  canChooseBatchCandidate,
  canExpandBatchCard,
  collectBatchAcceptDescriptors,
  orderBatchItemsForReview,
  postBatchAccept,
  queueStatusLabel,
  validateBatchRawInput,
  type BatchAcceptResult,
  type BatchCandidate,
  type BatchItem,
  type BatchParseResult,
  type QueueItem,
} from '@/features/workbench/batchWorkbench'
import BatchCandidatePopover from '@/features/workbench/BatchCandidatePopover.vue'
import BatchDraftPreviewPanel from '@/features/workbench/BatchDraftPreviewPanel.vue'
import { displayValue, type RequestSnapshot } from '@/features/requests/requestDetail'
import { currentStorageDir, storageQuery } from '@/features/requests/requestStorage'
import { routeLocation } from '@/app/router/catalog'

type CreateRequestResult = NonNullable<
  import('@/api/generated/api').operations['createRequest']['responses']['200']['content']['application/json']['result']
>

const route = useRoute()
const router = useRouter()
const notification = useNotificationStore()
const confirmDialog = ref<InstanceType<typeof ConfirmDialog> | null>(null)

const props = withDefaults(defineProps<{ rawInput?: string; hideInput?: boolean }>(), { rawInput: '', hideInput: false })
const emit = defineEmits<{ (event: 'update:rawInput', value: string): void }>()

// Batch parse state.
const rawInput = ref(props.rawInput)

watch(() => props.rawInput, (value) => {
  if (value !== rawInput.value) rawInput.value = value
})

watch(rawInput, (value) => emit('update:rawInput', value))
const parseLoading = ref(false)
const parseError = ref('')
const parseResult = ref<BatchParseResult | null>(null)
const items = ref<BatchItem[]>([])
const batchId = ref('')
const loadingMessage = ref('')
const parseCount = ref(0)
const currentItemId = ref<string | null>(null)
const inputItemOrder = ref<Map<string, number>>(new Map())

// Selection / accept state.
const selectedItemIds = ref<Set<string>>(new Set())
const acceptInFlight = ref(false)
const acceptFeedback = ref<Record<string, { status: string; reason: string }>>({})

// Candidate popover state (component memory only).
const activeCandidateItemId = ref<string | null>(null)
const seasonConfirmations = ref<Record<string, number | null>>({})
// US-207: remember the trigger button so closing the popover restores focus
// to it (keyboard/AT users keep their place in the batch grid).
const candidateTrigger = ref<HTMLButtonElement | null>(null)

// Draft detail state.
const detailItemId = ref<string | null>(null)

// Review filters affect visibility only. The parsed order remains frozen until
// the user explicitly asks for exception-first sorting.
const reviewQuery = ref('')
const reviewStatus = ref('')
const exceptionsOnly = ref(false)
const exceptionSorted = ref(false)
const reviewList = ref<HTMLElement | null>(null)
const reviewScrollPositions = new Map<string, number>()
const reviewFilterKey = computed(() => `${reviewQuery.value}\u0000${reviewStatus.value}\u0000${exceptionsOnly.value}`)

// Queue state (read-only snapshot after accept; full queue panel is US-206).
const queueItems = ref<QueueItem[]>([])

const selectable = computed(() => items.value.filter(canAcceptBatchCard))
const selectedCount = computed(
  () => items.value.filter((item) => selectedItemIds.value.has(item.item_id ?? '') && canAcceptBatchCard(item)).length,
)
const allSelected = computed(
  () => selectable.value.length > 0 && selectable.value.every((item) => selectedItemIds.value.has(item.item_id ?? '')),
)

const activeItem = computed(() =>
  activeCandidateItemId.value ? items.value.find((item) => item.item_id === activeCandidateItemId.value) ?? null : null,
)
const detailItem = computed(() =>
  (detailItemId.value || currentItemId.value)
    ? items.value.find((item) => item.item_id === (detailItemId.value || currentItemId.value)) ?? null
    : null,
)
const visibleItems = computed(() => items.value.filter((item) => batchItemMatchesReviewFilters(item, {
  query: reviewQuery.value,
  status: reviewStatus.value,
  exceptionsOnly: exceptionsOnly.value,
})))

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
}

function sortExceptionsFirst(): void {
  saveReviewScrollPosition()
  items.value = orderBatchItemsForReview(items.value)
  exceptionSorted.value = true
  void restoreReviewScrollPosition()
}

function selectCurrentItem(item: BatchItem): void {
  currentItemId.value = item.item_id ?? null
  detailItemId.value = item.item_id ?? null
}

function batchQueueStatusText(): string {
  return `队列中 ${queueItems.value.length} 项`
}

function syncBatchIdToUrl(batchIdValue: string): void {
  if (batchIdValue) {
    void router.replace(routeLocation('add', { batch_id: batchIdValue }))
  } else {
    void router.replace(routeLocation('add'))
  }
}

async function parseBatch(): Promise<void> {
  const validationError = validateBatchRawInput(rawInput.value)
  if (validationError) {
    parseError.value = validationError
    parseResult.value = null
    items.value = []
    batchId.value = ''
    queueItems.value = []
    notification.error('校验失败', validationError)
    return
  }
  parseError.value = ''
  parseLoading.value = true
  const count = batchItemCount(rawInput.value)
  parseCount.value = count
  loadingMessage.value = `正在搜索 ${count} 个批量条目的 MiKan 候选（解析进度：0 / ${count} 部）`
  try {
    const payload = buildBatchParsePayload(rawInput.value, currentStorageDir())
    const result = await api.post<BatchParseResult>('/api/v1/batches/parse', { body: payload })
    parseResult.value = result
    const parsedItems = result.items ?? []
    inputItemOrder.value = new Map(
      parsedItems.map((item, index) => [item.item_id ?? '', index]),
    )
    items.value = orderBatchItemsForReview(parsedItems)
    batchId.value = result.batch_id ?? ''
    syncBatchIdToUrl(batchId.value)
    selectedItemIds.value = new Set()
    acceptInFlight.value = false
    activeCandidateItemId.value = null
    detailItemId.value = null
    currentItemId.value = items.value[0]?.item_id ?? null
    detailItemId.value = currentItemId.value
    acceptFeedback.value = {}
    seasonConfirmations.value = {}
    queueItems.value = []
    notification.success('批量搜索完成', `已返回 ${items.value.length} 个条目的候选搜索状态。`)
  } catch (error) {
    void error
    parseResult.value = null
    items.value = []
    batchId.value = ''
    queueItems.value = []
    parseError.value = '批量草案获取失败。请稍后重试。'
    notification.error('批量草案获取失败', '批量草案获取失败。请稍后重试。')
  } finally {
    parseLoading.value = false
  }
}

function toggleItemSelection(itemId: string, selected: boolean): void {
  const next = new Set(selectedItemIds.value)
  if (selected) {
    next.add(itemId)
  } else {
    next.delete(itemId)
  }
  selectedItemIds.value = next
}

function setAllSelected(selected: boolean): void {
  const next = new Set<string>()
  if (selected) {
    for (const item of selectable.value) {
      if (item.item_id) next.add(item.item_id)
    }
  }
  selectedItemIds.value = next
}

async function generateDraftFromCandidate(candidate: BatchCandidate): Promise<void> {
  const item = activeItem.value
  if (!item) return
  acceptInFlight.value = true
  try {
    const payload = buildBatchCandidateCreatePayload(candidate, {
      storageDir: currentStorageDir(),
      confirmedSeason: seasonConfirmations.value[candidate.bangumi_id] ?? null,
    })
    const result = await api.post<CreateRequestResult>('/api/v1/requests', {
      body: { ...payload, storage_dir: storageQuery().storage_dir ?? null },
    })
    const request = result?.request as RequestSnapshot | undefined
    if (!request) {
      throw new Error('candidate preview returned no request')
    }
    const draftId = result?.draft_id ?? ''
    const draftRevision =
      typeof result?.draft_revision === 'number' ? result.draft_revision : 1
    items.value = items.value.map((current) =>
      current.item_id === item.item_id
        ? { ...current, status: 'DRAFT', preview_request: request, draft_id: draftId, draft_revision: draftRevision }
        : current,
    )
    activeCandidateItemId.value = null
    notification.success('订阅草案已生成', '已根据所选 MiKan 合集生成当前批量条目的订阅草案。')
  } catch (error) {
    void error
    notification.error('生成订阅草案失败', '从 MiKan 合集生成订阅草案失败。请重试。')
  } finally {
    acceptInFlight.value = false
  }
}

function openCandidateChoices(item: BatchItem, trigger?: HTMLElement | null): void {
  selectCurrentItem(item)
  if (activeCandidateItemId.value === item.item_id) {
    closeCandidateChoices()
    return
  }
  // Prefer the explicit trigger element (click target); fall back to the
  // currently focused element (keyboard activation) so focus restore on close
  // always has a target (US-207).
  candidateTrigger.value =
    (trigger as HTMLButtonElement | null) ??
    (document.activeElement as HTMLButtonElement | null)
  activeCandidateItemId.value = item.item_id
}

function closeCandidateChoices(): void {
  const trigger = candidateTrigger.value
  activeCandidateItemId.value = null
  candidateTrigger.value = null
  // Restore focus to the trigger button *before* the popover unmounts: the
  // browser moves focus to <body> when the focused close button is removed,
  // and the popover unmounts on the next tick, so focus must be restored
  // synchronously here (US-207 keyboard accessibility).
  trigger?.focus()
}

function openDraftDetail(item: BatchItem): void {
  selectCurrentItem(item)
}

function deleteBatchCard(itemId: string): void {
  const next = new Set(selectedItemIds.value)
  next.delete(itemId)
  selectedItemIds.value = next
  if (activeCandidateItemId.value === itemId) {
    activeCandidateItemId.value = null
  }
  if (detailItemId.value === itemId) {
    detailItemId.value = null
  }
  const feedback = { ...acceptFeedback.value }
  delete feedback[itemId]
  acceptFeedback.value = feedback
  items.value = items.value.filter((item) => item.item_id !== itemId)
}

function applyAcceptResult(result: BatchAcceptResult, savedRequests: Map<string, RequestSnapshot>): void {
  const outcomeCounts: Record<string, number> = {}
  const feedback: Record<string, { status: string; reason: string }> = {}
  const nextItems = items.value.map((row) => {
    let updated = row
    for (const item of result.items ?? []) {
      if (item.item_id !== row.item_id) continue
      outcomeCounts[item.status ?? ''] = (outcomeCounts[item.status ?? ''] ?? 0) + 1
      if (acceptOutcomeAccepted(item)) {
        const savedRequest =
          savedRequests.get(row.item_id ?? '') ?? (row.preview_request as RequestSnapshot | null) ?? {}
        updated = {
          ...row,
          status: 'ACCEPTED',
          preview_request: { ...(savedRequest as RequestSnapshot), status: 'ACCEPTED' },
          // The draft was consumed by preview-save before accept; a consumed
          // draft must never be re-referenced (draft_id or revision).
          draft_id: null,
          draft_revision: null,
          queue_status: item.status === 'accepted' ? 'READY_TO_SUBMIT' : row.queue_status ?? null,
        }
        const selected = new Set(selectedItemIds.value)
        selected.delete(row.item_id ?? '')
        selectedItemIds.value = selected
      } else {
        feedback[row.item_id ?? ''] = { status: item.status ?? '', reason: item.reason ?? '接受失败' }
      }
    }
    return updated
  })
  items.value = nextItems
  acceptFeedback.value = { ...acceptFeedback.value, ...feedback }

  // Sync the authoritative queue statuses onto matching accepted cards.
  const queue = result.queue
  const queueList = queue?.items ?? []
  if (queueList.length) {
    items.value = items.value.map((row) => {
      if (row.status !== 'ACCEPTED') return row
      const qItem = queueList.find((entry) => entry.item_id === row.item_id)
      return qItem ? { ...row, queue_status: qItem.status ?? null } : row
    })
    queueItems.value = queueList as QueueItem[]
  }
}

async function submitBatchAccept(rows: BatchItem[], options: { single?: boolean; itemIds?: string[] }): Promise<void> {
  if (!batchId.value) {
    notification.error('接受失败', '缺少批次标识，请重新获取批量草案。')
    return
  }
  acceptInFlight.value = true
  try {
    const descriptors = collectBatchAcceptDescriptors(rows).sort(
      (left, right) =>
        (inputItemOrder.value.get(left.item_id) ?? Number.MAX_SAFE_INTEGER) -
        (inputItemOrder.value.get(right.item_id) ?? Number.MAX_SAFE_INTEGER),
    )
    if (!descriptors.length) {
      notification.error('接受失败', '没有可接受的批量卡片。')
      return
    }
    const payload = buildBatchAcceptPayload(descriptors, options.itemIds ?? null, currentStorageDir())
    const result = await postBatchAccept(batchId.value, payload)
    const savedRequests = new Map<string, RequestSnapshot>()
    for (const row of rows) {
      const saved = batchCardRequest(row)
      if (saved?.request_id) {
        savedRequests.set(row.item_id ?? '', saved)
      }
    }
    applyAcceptResult(result, savedRequests)
    const outcomeCounts = result.summary ?? {}
    const notif = batchAcceptNotification(outcomeCounts, options.single === true)
    notification.show(notif.kind, notif.title, notif.message)
  } catch (error) {
    void error
    notification.error('接受失败', '批量接受失败。请稍后重试。')
  } finally {
    acceptInFlight.value = false
  }
}

async function confirmBatchAcceptSelected(): Promise<void> {
  const rows = items.value.filter((item) => selectedItemIds.value.has(item.item_id ?? '') && canAcceptBatchCard(item))
  if (!rows.length || acceptInFlight.value) return
  const ok = await confirmDialog.value?.confirm({
    title: '批量接受',
    message: `确认接受选中的 ${rows.length} 个批量卡片？`,
    confirmLabel: '确认接受',
  })
  if (!ok) return
  await submitBatchAccept(rows, { itemIds: rows.map((row) => row.item_id ?? '') })
}

async function confirmBatchAcceptAll(): Promise<void> {
  const rows = selectable.value
  if (!rows.length || acceptInFlight.value) return
  const ok = await confirmDialog.value?.confirm({
    title: '全接受',
    message: '确认接受全部批量卡片？',
    confirmLabel: '确认接受',
  })
  if (!ok) return
  // Legacy parity: accept-all sends every card (including FOUND/EMPTY/FAILED
  // ones) so the server returns a per-card unacceptable reason for the cards
  // that cannot be accepted; item_ids is omitted to preserve batch order.
  await submitBatchAccept(items.value, {})
}

async function onAccepted(item: BatchItem, savedRequest: RequestSnapshot): Promise<void> {
  // Single-card accept from the draft panel (preview already saved).
  const row = { ...item, preview_request: savedRequest, status: 'DRAFT' }
  await submitBatchAccept([row], { single: true })
}

function onDraftChanged(
  itemId: string,
  state: { request: RequestSnapshot; draftId: string; draftRevision: number },
): void {
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
}

function onDraftDeleted(itemId: string): void {
  deleteBatchCard(itemId)
  notification.info('已删除批量卡片', '当前批量卡片已从本批结果中移除。')
}

function onDraftExpired(itemId: string): void {
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
  detailItemId.value = null
}

onMounted(() => {
  const fromQuery = typeof route.query.batch_id === 'string' ? route.query.batch_id : ''
  if (fromQuery) {
    batchId.value = fromQuery
    // The queue panel (US-206) will restore the queue on refresh; the batch
    // card grid itself is never persisted server-side, so a refresh can only
    // restore the queue context, not the cards.
  }
})

defineExpose({ parseBatch, generateDraftFromCandidate, submitBatchAccept, deleteBatchCard })
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
        :disabled="parseLoading"
      />
      <p v-if="!props.hideInput" class="field-help" id="batch-parse-help">
        每行一个番剧简称或不完整标题；系统会逐项解析并搜索候选合集，结果需人工审核。
      </p>
      <p v-if="parseError" id="batch-parse-error" class="field-error" role="alert">
        {{ parseError }}
      </p>
      <div class="notification-actions">
        <BaseButton id="batch-parse-submit" type="submit" variant="primary" :loading="parseLoading">
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
                  <option v-for="status in ['FAILED', 'EMPTY', 'FOUND', 'DRAFT', 'ACCEPTED']" :key="status" :value="status">
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
              @click="selectCurrentItem(item)"
              @keydown.enter.prevent="selectCurrentItem(item)"
            >
              <CheckboxRow
                class="batch-card-checkbox-row"
                :class="{ 'is-selected': selectedItemIds.has(item.item_id ?? '') }"
                :label="`选择 ${item.raw_title ?? '批量条目'}`"
                :checked="selectedItemIds.has(item.item_id ?? '')"
                :disabled="!canAcceptBatchCard(item) || acceptInFlight"
                @click.stop
                @update:checked="(value: boolean) => toggleItemSelection(item.item_id ?? '', value)"
              />
              <button
                v-if="String(item.status ?? '') !== 'ACCEPTED'"
                type="button"
                class="icon-button batch-card-delete"
                :aria-label="`删除 ${item.raw_title ?? '批量条目'}`"
                title="删除"
                :disabled="acceptInFlight"
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
                <span
                  v-if="item.queue_status"
                  class="batch-status batch-card-queue-status"
                >
                  {{ queueStatusLabel(typeof item.queue_status === 'string' ? item.queue_status : null) }}
                </span>
                <span v-if="batchCardNeedsReview(item)" class="batch-status batch-card-review-status">
                  需人工核对
                </span>
              </div>

              <strong class="batch-card-title">{{ batchCardTitle(item) }}</strong>
              <div class="batch-card-raw-title">输入：{{ displayValue(item.raw_title) }}</div>
              <div class="batch-card-source">候选来源：{{ canChooseBatchCandidate(item) || batchCardRequest(item) ? 'MiKan 候选搜索' : 'MiKan 候选搜索' }}</div>
              <div class="batch-card-preference">{{ batchCardPreferenceSummary(item) }}</div>
              <div class="batch-card-seeds">有效种子数：{{ batchCardSeedSummary(item) }}</div>
              <div class="batch-card-progress">{{ batchEpisodeProgressText(undefined) }}</div>

              <p v-if="String(item.status ?? '') === 'EMPTY'" class="batch-candidate-feedback">
                未找到匹配的 MiKan 合集。
              </p>
              <p v-else-if="String(item.status ?? '') === 'FAILED'" class="batch-candidate-feedback">
                {{ displayValue(item.error?.error_message) || '搜索失败。可重新获取批量草案后重试。' }}
              </p>
              <p
                v-if="String(item.status ?? '') !== 'ACCEPTED' && !canAcceptBatchCard(item)"
                class="batch-card-selection-help"
              >
                当前条目需先生成可审核草案，暂不可加入批量确认。
              </p>

              <p
                v-if="item.review_hints?.length"
                class="batch-card-preference-note"
              >
                {{ item.review_hints.join('；') }}
              </p>

              <div v-if="acceptFeedback[item.item_id ?? '']" class="batch-card-reason">
                {{ acceptFeedbackLabel(acceptFeedback[item.item_id ?? '']?.status) }}{{ acceptFeedback[item.item_id ?? '']?.reason }}
              </div>

              <div class="batch-card-actions">
                <BaseButton
                  v-if="canChooseBatchCandidate(item)"
                  :class="{ 'batch-card-expand': true }"
                  :aria-expanded="activeCandidateItemId === item.item_id ? 'true' : 'false'"
                  :aria-controls="'batch-candidate-choices'"
                  :aria-label="`${activeCandidateItemId === item.item_id ? '收起候选' : '查看候选'}：${item.raw_title ?? '批量条目'}`"
                  :disabled="acceptInFlight"
                  @click.stop
                  @click="openCandidateChoices(item, $event.currentTarget as HTMLElement)"
                >
                  {{ activeCandidateItemId === item.item_id ? '收起候选' : '查看候选' }}
                </BaseButton>
                <BaseButton
                  v-else-if="canExpandBatchCard(item)"
                  class="batch-card-expand"
                  :aria-expanded="detailItemId === item.item_id ? 'true' : 'false'"
                  aria-controls="request-detail-panel"
                  :aria-label="`查看草案：${item.raw_title ?? '批量条目'}`"
                  :disabled="acceptInFlight"
                  @click.stop
                  @click="openDraftDetail(item)"
                >
                  查看草案
                </BaseButton>
                <BaseButton v-else class="batch-card-expand" disabled title="当前条目没有可选择的候选合集">
                  查看候选
                </BaseButton>
                </div>
            </article>
            </div>
          </div>

          <aside class="batch-detail-pane" aria-label="当前批量条目详情">
            <template v-if="detailItem && canChooseBatchCandidate(detailItem)">
              <h3 class="batch-detail-title">候选合集：{{ batchCardTitle(detailItem) }}</h3>
              <p class="field-help">请选择一个真实 MiKan 合集后生成订阅草案。</p>
              <CandidateCollectionList
                class="batch-candidate-list"
                :candidates="detailItem.candidates ?? []"
                :query="batchCardTitle(detailItem)"
                :disabled="acceptInFlight"
                :confirmed-seasons="seasonConfirmations"
                @select="generateDraftFromCandidate"
                @update:confirmed-season="(bangumiId: string, season: number | null) => (seasonConfirmations = { ...seasonConfirmations, [bangumiId]: season })"
              />
            </template>
            <template v-else-if="detailItem && canExpandBatchCard(detailItem) && batchCardRequest(detailItem)">
              <BatchDraftPreviewPanel
                :key="`detail-${detailItem.item_id ?? detailItem.raw_title ?? ''}`"
                :item="detailItem"
                @accepted="onAccepted"
                @deleted="onDraftDeleted"
                @expired="onDraftExpired"
                @draft-changed="onDraftChanged"
              />
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

        <BatchCandidatePopover
          v-if="activeItem && canChooseBatchCandidate(activeItem)"
          :title="batchCardTitle(activeItem)"
          :candidates="activeItem.candidates ?? []"
          :query="batchCardTitle(activeItem)"
          :disabled="acceptInFlight"
          :confirmed-seasons="seasonConfirmations"
          @select="generateDraftFromCandidate"
          @update:confirmed-season="(bangumiId: string, season: number | null) => (seasonConfirmations = { ...seasonConfirmations, [bangumiId]: season })"
          @close="closeCandidateChoices"
        />

        <div id="batch-accept-toolbar" class="batch-accept-toolbar">
          <CheckboxRow
            id="batch-select-all-checkbox"
            :label="'全选'"
            :checked="allSelected"
            :disabled="selectable.length === 0 || acceptInFlight"
            @update:checked="setAllSelected"
          />
          <span id="batch-accept-selected-count" class="batch-selected-count">
            已选择 {{ selectedCount }} 项
          </span>
          <div class="notification-actions batch-accept-actions">
            <BaseButton
              id="batch-accept-submit"
              variant="primary"
              :disabled="selectedCount === 0 || acceptInFlight"
              :loading="acceptInFlight"
              @click="confirmBatchAcceptSelected"
            >
              批量接受
            </BaseButton>
            <BaseButton
              id="batch-accept-all"
              variant="secondary"
              :disabled="selectable.length === 0 || acceptInFlight"
              :loading="acceptInFlight"
              @click="confirmBatchAcceptAll"
            >
              全接受
            </BaseButton>
          </div>
        </div>

        <div v-if="batchId" class="batch-queue-summary" aria-live="polite">
          <p class="field-help" id="batch-queue-context">
            批次标识：{{ batchId }}。已接受卡片进入提交前队列，可在「提交队列」查看与提交。
          </p>
          <p id="batch-queue-count" class="request-list-count">{{ batchQueueStatusText() }}</p>
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
  aspect-ratio: 3 / 4;
  background: var(--color-bg-muted);
  border: 1px solid var(--color-border);
  border-radius: 4px;
  color: var(--color-text-muted);
  display: flex;
  font-size: 0.82rem;
  font-weight: 700;
  justify-content: center;
  overflow: hidden;
  text-align: center;
}

.batch-card-poster-placeholder {
  padding: 8px;
}

.batch-card-title {
  overflow-wrap: anywhere;
}

.batch-card-raw-title,
.batch-card-source,
.batch-card-preference,
.batch-card-seeds,
.batch-card-progress {
  color: var(--color-text-muted);
  font-size: 0.84rem;
  overflow-wrap: anywhere;
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
}

.batch-accept-toolbar {
  align-items: center;
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  margin-top: 12px;
}

.batch-selected-count {
  color: var(--color-text-muted);
  font-size: 0.84rem;
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
</style>
