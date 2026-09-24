<script setup lang="ts">
// 订阅方案工作台 (US-204).
//
// The workbench migrates the legacy `/index` single-search flow to the new
// frontend:
//
//   1. 单个搜索 — POST /api/v1/mikan/candidates, renders public candidate
//      cards (no auto-selection) with season-evidence confirmation/conflict
//      handling. F4/WP-41-D: the initial page is only the name input and the
//      mode switch — the results panel (and its collapsed parse diagnostics)
//      exists only after a search has been started;
//   2. 直连合集 fallback — a secondary rescue entry rendered inside the results
//      panel only after a started search produced no candidates; it reveals the
//      direct MiKan URL/ID form. Both paths generate an unsaved
//      server-authoritative draft through POST /api/v1/requests;
//   3. 订阅草案 preview — the returned draft_id + display snapshot render in
//      SingleAnimeReviewPanel (editable preview-modify + atomic save-confirm).
//      The review header's「已选哪部/哪一季」comes from the candidate the host
//      still holds in memory, never from an extra request.
//
// Security boundary (US-194): candidate context and draft_id exist only in
// component memory — never in URL, browser storage, history or logs. No
// candidate is ever auto-selected; parser hints are never treated as real
// season evidence (only the explicit confirmation checkbox or the server's
// one-time candidate_context can do that).
import { computed, nextTick, onMounted, ref, watch } from 'vue'

import { api } from '@/api/client'
import type { operations } from '@/api/generated/api'
import { useNotificationStore } from '@/app/stores/notification'
import BaseButton from '@/components/forms/BaseButton.vue'
import BaseInput from '@/components/forms/BaseInput.vue'
import CheckboxRow from '@/components/forms/CheckboxRow.vue'
import ConfirmDialog from '@/components/feedback/ConfirmDialog.vue'
import EmptyState from '@/components/feedback/EmptyState.vue'
import ErrorState from '@/components/feedback/ErrorState.vue'
import LoadingState from '@/components/feedback/LoadingState.vue'

import CandidateCollectionList from '@/features/workbench/CandidateCollectionList.vue'
import SingleAnimeReviewPanel from '@/features/workbench/SingleAnimeReviewPanel.vue'
import SingleAnimeSearchForm from '@/features/workbench/SingleAnimeSearchForm.vue'
import BatchWorkbenchView from '@/features/workbench/BatchWorkbenchView.vue'
import AnimeModeSwitch, { type AnimeMode } from '@/features/workbench/AnimeModeSwitch.vue'
import AnimeTitleInput from '@/features/workbench/AnimeTitleInput.vue'
import {
  buildCandidateCreatePayload,
  buildFallbackCreatePayload,
  hiddenSingleCandidateCount,
  parseSourceLabel,
  parseSeasonNumber,
  selectedCollectionSummary,
  validateCandidateQuery,
  validateFallbackValue,
  visibleSingleCandidates,
  type CandidateSearchResult,
  type MikanCandidate,
} from '@/features/workbench/candidateSearch'
import { batchItemCount, validateBatchRawInput } from '@/features/workbench/batchWorkbench'
import { displayValue } from '@/features/requests/requestDetail'
import type { RequestSnapshot } from '@/features/requests/requestDetail'
import { currentStorageDir, storageQuery } from '@/features/requests/requestStorage'
import { consumeReuseHandoff, type ReuseSuggestion } from '@/features/requests/reuseHandoff'
import {
  candidateResultFailureMessage,
  MIKAN_CANDIDATE_SEARCH_TIMEOUT_MS,
  MIKAN_DRAFT_GENERATION_TIMEOUT_MS,
  mikanFailureMessage,
} from './mikanFeedback'

type CreateRequestResult = NonNullable<
  operations['createRequest']['responses']['200']['content']['application/json']['result']
>

const notification = useNotificationStore()

// Search state.
const query = ref('')
const batchQuery = ref('')
const mode = ref<AnimeMode>('single')
const singleSearchForm = ref<InstanceType<typeof SingleAnimeSearchForm> | null>(null)
const batchInput = ref<InstanceType<typeof AnimeTitleInput> | null>(null)
const batchWorkbench = ref<InstanceType<typeof BatchWorkbenchView> | null>(null)
const batchSearchSubmitting = ref(false)
const selections = ref<Record<AnimeMode, { start: number; end: number }>>({
  single: { start: 0, end: 0 },
  batch: { start: 0, end: 0 },
})
const searchLoading = ref(false)
// US-363: 每个模式各自持有搜索现场。结果、错误与已选候选按模式存储，
// 切换模式只切换视图，绝不清除任一模式的输入、结果或未保存现场。
const modeSession = ref<
  Record<AnimeMode, { result: CandidateSearchResult | null; error: string; candidate: MikanCandidate | null }>
>({
  single: { result: null, error: '', candidate: null },
  batch: { result: null, error: '', candidate: null },
})

const searchError = computed({
  get: () => modeSession.value[mode.value].error,
  set: (value: string) => {
    modeSession.value[mode.value].error = value
  },
})
const searchResult = computed({
  get: () => modeSession.value[mode.value].result,
  set: (value: CandidateSearchResult | null) => {
    modeSession.value[mode.value].result = value
  },
})
/**
 * F4: the initial page is a name input plus the mode switch — no empty result
 * panel before a search. The results panel (and the direct-collection rescue
 * entry inside it) only exists once a search has actually been started.
 */
const searchStarted = computed(
  () => searchLoading.value || Boolean(searchError.value) || searchResult.value !== null,
)
const batchCount = computed(() => batchItemCount(batchQuery.value))
const batchValidationError = computed(() => validateBatchRawInput(batchQuery.value))
const batchSearchDisabled = computed(() => batchSearchSubmitting.value || Boolean(batchValidationError.value))

async function submitBatchSearch(): Promise<void> {
  if (batchSearchDisabled.value) return
  batchSearchSubmitting.value = true
  try {
    await batchWorkbench.value?.parseBatch()
  } finally {
    batchSearchSubmitting.value = false
  }
}

/** A started search that is no longer in flight and produced no candidates. */
const searchSettled = computed(
  () => !searchLoading.value && (Boolean(searchError.value) || searchResult.value !== null),
)

// Fallback (direct-collection) state.
const fallbackEnabled = ref(false)
const fallbackValue = ref('')
const fallbackError = ref('')
const fallbackLoading = ref(false)

// Draft-preview state (component memory only).
const draftRequest = ref<RequestSnapshot | null>(null)
const draftId = ref('')
const draftRevision = ref(1)
const draftLoading = ref(false)
// A single page-level busy lock covers search, direct fallback generation and
// candidate draft generation.  The individual flags remain for accurate UI
// labels, while this lock prevents two long MiKan plans from racing.
const singleBusy = ref(false)

// US-363 (Stage 47 几何基线): 单番英雄区承载「尚未产出候选、也没有草案」的首页状态。
// 用 !hasResults 而不是 !searchStarted：点击搜索后英雄区必须留在原位（仅取消垂直居中），
// 否则搜索一开始容器就被卸载，输入与主按钮会发生布局跳变与宽度变化。
// US-363 AC3: 批量工作台一旦进入过就保持挂载，只用 v-show 切换可见性。
// 否则切回单番会卸载 BatchWorkbenchView，其内部的候选、草案、筛选与勾选现场会被丢弃。
const batchMounted = ref(false)
watch(
  mode,
  (value) => {
    if (value === 'batch') batchMounted.value = true
  },
  { immediate: true },
)

// Issue 110: 单番是同一页面的上下两屏。搜索首屏常驻，候选工作台是第二屏；
// 「返回搜索首屏」只滚动与聚焦，绝不清空下方未保存的候选现场。
const showSingleJourney = computed(() => mode.value === 'single')
const showCandidateScreen = computed(
  () => mode.value === 'single' && hasResults.value && !draftRequest.value,
)
const showDraftScreen = computed(
  () => mode.value === 'single' && Boolean(draftRequest.value && draftId.value),
)
const heroScreen = ref<HTMLElement | null>(null)
const workbenchScreen = ref<HTMLElement | null>(null)
const confirmDialog = ref<InstanceType<typeof ConfirmDialog> | null>(null)
// US-343: which candidate owns the in-flight generation, and the sanitized
// failure that stays beside a candidate after its generation failed.
const generatingCandidateId = ref<string | null>(null)
const candidateErrors = ref<Record<string, string>>({})
const reuseSuggestion = ref<ReuseSuggestion | null>(null)
const reuseSource = ref<{ title: string; mikanBangumiId: string } | null>(null)
// Track per-candidate season confirmation in memory (never persisted).
const seasonConfirmations = ref<Record<string, number | null>>({})
// The candidate that produced the current draft, kept in memory only so the
// review step can answer「已选哪部/哪一季」without a second backend read
// (F4; the unsaved draft snapshot has no season/total-episode fields and
// D40-01 forbids safe-info for an unsaved draft).
const selectedCandidate = computed({
  get: () => modeSession.value[mode.value].candidate,
  set: (value: MikanCandidate | null) => {
    modeSession.value[mode.value].candidate = value
  },
})

/** Display-only projection of the selected collection for the review header. */
const selectedCollection = computed(() =>
  selectedCandidate.value
    ? selectedCollectionSummary(selectedCandidate.value, seasonConfirmations.value[selectedCandidate.value.bangumi_id] ?? null)
    : null,
)

const hasResults = computed(() => (searchResult.value?.candidates?.length ?? 0) > 0)

/** Issue 110: 1～4 项同排展示；超出的候选只提示不渲染、不自动选择。 */
const visibleCandidates = computed(() => visibleSingleCandidates(searchResult.value?.candidates ?? []))
const hiddenCandidateCount = computed(() => hiddenSingleCandidateCount(searchResult.value?.candidates ?? []))

/** Candidate generation state never outlives the search results it belongs to. */
function resetCandidateGenerationState(): void {
  generatingCandidateId.value = null
  candidateErrors.value = {}
}

/** Issue 110: 已有候选或未保存草案时，重新搜索会替换现场，需要先确认。 */
const hasUnsavedSingleWork = computed(() => hasResults.value || draftRequest.value !== null)

/** 尊重缩减动态效果：不做平滑滚动。 */
function prefersReducedMotion(): boolean {
  return (
    typeof window !== 'undefined' &&
    typeof window.matchMedia === 'function' &&
    window.matchMedia('(prefers-reduced-motion: reduce)').matches
  )
}

function scrollScreenIntoView(element: HTMLElement | null): void {
  if (!element || typeof element.scrollIntoView !== 'function') return
  element.scrollIntoView({ behavior: prefersReducedMotion() ? 'auto' : 'smooth', block: 'start' })
}

/** 明确按钮或模块外空白滚动都只是回到首屏，不清空第二屏现场。 */
function backToSearch(): void {
  scrollScreenIntoView(heroScreen.value)
  void nextTick(() => singleSearchForm.value?.focusInput())
}

/** 搜索入口：先确认是否会替换未保存工作，再真正发起搜索。 */
async function requestSearch(): Promise<void> {
  if (singleBusy.value) return
  if (hasUnsavedSingleWork.value) {
    const confirmed = await confirmDialog.value?.confirm({
      title: '重新搜索会清除下方未保存内容',
      message: '下方未保存的候选或草案修改会被清除，确定重新搜索吗？',
      confirmLabel: '重新搜索',
      cancelLabel: '留在此页',
    })
    if (!confirmed) return
  }
  await searchCandidates()
}

// Issue 110: 编辑输入不再静默清空第二屏。结果只属于产生它的那次搜索；
// 真正替换未保存现场的时机是「重新搜索」，由 requestSearch 先确认。

async function changeMode(nextMode: AnimeMode): Promise<void> {
  if (nextMode === mode.value || singleBusy.value) return
  const currentInput = mode.value === 'single' ? singleSearchForm.value : batchInput.value
  if (currentInput) selections.value[mode.value] = currentInput.selection()
  // 结果/错误/已选候选按模式存储（modeSession），这里只切换视图：
  // 既不会把单番结果显示成批量结果，也不会清除任一模式的输入或未保存现场。
  mode.value = nextMode
  await nextTick()
  const nextInput = nextMode === 'single' ? singleSearchForm.value : batchInput.value
  nextInput?.focus()
  const selection = selections.value[nextMode]
  nextInput?.restoreSelection(selection.start, selection.end)
}

function parseSummaryRows(): Array<[string, string]> {
  const parse = searchResult.value?.parse_result
  if (!parse || typeof parse !== 'object') return []
  const seasonNumber = parseSeasonNumber(parse)
  const recognizedTitle =
    String(parse.normalized_title ?? parse.base_title ?? searchResult.value?.query ?? '').trim() || '未识别'
  const rows: Array<[string, string]> = [
    ['识别标题', recognizedTitle],
    ['识别季度', seasonNumber !== null ? `第${seasonNumber}季` : '未识别'],
    ['解析来源', parseSourceLabel((parse as { source?: unknown }).source as string | null | undefined)],
  ]
  return rows
}

function parseReviewHints(): string[] {
  const hints: string[] = []
  for (const source of [searchResult.value?.parse_result, searchResult.value]) {
    if (!source || typeof source !== 'object') continue
    const reviewHints = (source as { review_hints?: unknown }).review_hints
    if (!Array.isArray(reviewHints)) continue
    for (const hint of reviewHints) {
      const text = String(hint ?? '').trim()
      if (text && !hints.includes(text)) {
        hints.push(text)
      }
    }
  }
  return hints
}

/** True when the parse summary flags a human-review requirement. */
const parseNeedsReview = computed(() => {
  const parse = searchResult.value?.parse_result
  return (
    (parse && typeof parse === 'object' && (parse as { needs_user_review?: unknown }).needs_user_review === true) ||
    parseReviewHints().length > 0
  )
})

function attemptedQueryTexts(): string[] {
  const attempted = Array.isArray(searchResult.value?.attempted_queries)
    ? (searchResult.value.attempted_queries as Array<{ query?: unknown }>)
    : []
  if (!attempted.length) {
    const plan = (searchResult.value?.parse_result as { query_plan?: unknown } | undefined)?.query_plan
    if (Array.isArray(plan)) {
      return (plan as Array<{ query?: unknown }>)
        .map((entry) => String(entry.query ?? '').trim())
        .filter(Boolean)
    }
    return []
  }
  return attempted.map((entry) => String(entry.query ?? '').trim()).filter(Boolean)
}

async function searchCandidates(): Promise<void> {
  if (singleBusy.value) return
  const validationError = validateCandidateQuery(query.value)
  if (validationError) {
    searchError.value = validationError
    searchResult.value = null
    notification.error('校验失败', validationError)
    return
  }
  searchError.value = ''
  searchResult.value = null
  seasonConfirmations.value = {}
  selectedCandidate.value = null
  resetCandidateGenerationState()
  singleBusy.value = true
  searchLoading.value = true
  try {
    const result = await api.post<CandidateSearchResult>('/api/v1/mikan/candidates', {
      body: { query: query.value.trim() },
      timeoutMs: MIKAN_CANDIDATE_SEARCH_TIMEOUT_MS,
    })
    searchResult.value = result
    const failedMessage = candidateResultFailureMessage(result)
    if (failedMessage) {
      searchError.value = failedMessage
      notification.error('候选搜索失败', failedMessage)
      return
    }
    const count = result.candidates?.length ?? 0
    if (count) {
      notification.success('候选搜索完成', `找到 ${count} 个候选合集。`)
    } else {
      notification.info('未找到候选合集', '可调整番剧标题后重试。')
    }
  } catch (error) {
    void error
    searchResult.value = null
    searchError.value = mikanFailureMessage(error, '候选搜索')
    notification.error('候选搜索失败', searchError.value)
  } finally {
    searchLoading.value = false
    singleBusy.value = false
    await nextTick()
    if (searchResult.value?.candidates?.length) {
      // Issue 110：成功后自动进入下方工作台，并把键盘焦点移到结果标题。
      scrollScreenIntoView(workbenchScreen.value)
      document.querySelector<HTMLElement>('#candidate-search-heading')?.focus({ preventScroll: true })
    } else {
      // 失败或无候选都留在搜索首屏就地恢复；不抢焦点（Stage 42 无障碍保证），
      // 用户仍停在输入或原控件上，可直接修正后重试。
      scrollScreenIntoView(heroScreen.value)
    }
  }
}

async function generateFromCandidate(candidate: MikanCandidate): Promise<void> {
  // One candidate generation at a time; a click while one is in flight is a
  // no-op rather than a second racing plan.
  if (singleBusy.value || generatingCandidateId.value !== null) return
  const bangumiId = candidate.bangumi_id
  const payload = buildCandidateCreatePayload(candidate, {
    storageDir: currentStorageDir(),
    confirmedSeason: confirmedSeasonFor(candidate),
  })
  generatingCandidateId.value = bangumiId
  // A retry starts clean: the previous failure must not linger while the new
  // attempt is in flight.
  if (candidateErrors.value[bangumiId]) {
    const next = { ...candidateErrors.value }
    delete next[bangumiId]
    candidateErrors.value = next
  }
  try {
    const { ok, message } = await generateDraft(payload)
    if (ok) {
      // The review step answers「已选哪部/哪一季」from this remembered
      // candidate; nothing extra leaves the browser.
      selectedCandidate.value = candidate
    } else if (message) {
      // US-343: the failure stays beside the candidate that produced it.
      candidateErrors.value = { ...candidateErrors.value, [bangumiId]: message }
    }
  } finally {
    generatingCandidateId.value = null
  }
}

async function generateFromFallback(): Promise<void> {
  if (singleBusy.value || fallbackLoading.value) return
  const validationError = validateFallbackValue(fallbackValue.value)
  if (validationError) {
    fallbackError.value = validationError
    return
  }
  fallbackError.value = ''
  const payload = buildFallbackCreatePayload(fallbackValue.value, {
    storageDir: currentStorageDir(),
    title: query.value.trim(),
  })
  fallbackLoading.value = true
  try {
    const generated = await generateDraft(payload)
    if (generated.ok) {
      fallbackValue.value = ''
    }
  } finally {
    fallbackLoading.value = false
  }
}

async function generateDraft(
  payload: Record<string, unknown>,
): Promise<{ ok: boolean; message: string }> {
  if (singleBusy.value) return { ok: false, message: '' }
  singleBusy.value = true
  draftLoading.value = true
  try {
    const result = await api.post<CreateRequestResult>('/api/v1/requests', {
      body: { ...payload, storage_dir: storageQuery().storage_dir ?? null },
      timeoutMs: MIKAN_DRAFT_GENERATION_TIMEOUT_MS,
    })
    if (result?.draft_id && result?.request) {
      draftId.value = result.draft_id
      draftRequest.value = result.request as RequestSnapshot
      // US-211: keep the monotonic draft_revision in component memory only.
      draftRevision.value =
        typeof result.draft_revision === 'number' ? result.draft_revision : 1
      notification.success('预览已生成', '这是未保存的订阅草案；保存后可确认、修改或删除。')
      return { ok: true, message: '' }
    }
    const message = '订阅草案生成失败，请重试。'
    notification.error('生成失败', message)
    return { ok: false, message }
  } catch (error) {
    void error
    const message = mikanFailureMessage(error, '从 MiKan 合集生成订阅草案')
    notification.error('生成失败', message)
    return { ok: false, message }
  } finally {
    draftLoading.value = false
    singleBusy.value = false
  }
}

function confirmedSeasonFor(candidate: MikanCandidate): number | null {
  const key = candidate.bangumi_id
  return seasonConfirmations.value[key] ?? null
}

function onDraftChanged(state: { request: RequestSnapshot; draftId: string; draftRevision: number }): void {
  draftRequest.value = state.request
  draftId.value = state.draftId
  draftRevision.value = state.draftRevision
}

function discardDraft(destination: 'candidates' | 'input'): void {
  draftRequest.value = null
  draftId.value = ''
  draftRevision.value = 1
  seasonConfirmations.value = {}
  selectedCandidate.value = null
  reuseSuggestion.value = null
  reuseSource.value = null
  resetCandidateGenerationState()
  if (destination === 'input') {
    searchResult.value = null
    searchError.value = ''
  }
  void nextTick(() => singleSearchForm.value?.focusInput())
}

onMounted(() => {
  const handoff = consumeReuseHandoff()
  if (handoff) {
    query.value = handoff.title
    reuseSuggestion.value = handoff.suggestion
    reuseSource.value = { title: handoff.title, mikanBangumiId: handoff.mikanBangumiId }
  }
  // The workbench has no persisted state; the storage profile comes from
  // Settings localStorage (relative only). Nothing to preload here.
  // The real application shell enters this view at /app/add; focus the first
  // actionable single-anime control after the shell has rendered it.
  void nextTick(() => singleSearchForm.value?.focusInput())
})

defineExpose({ searchCandidates, generateFromCandidate, generateFromFallback })
</script>

<template>
  <!-- Issue 110：单番使用同一页面的上下两屏（搜索首屏 + 候选工作台）。
       搜索首屏常驻，第二屏只承载候选／草案；模块内部滚动到边界不触发切屏。 -->
  <div v-if="showSingleJourney" class="add-anime-screens">
    <section
      ref="heroScreen"
      class="add-screen single-home-hero"
      :class="{ 'is-searching': searchLoading || (searchStarted && !hasResults) }"
    >
      <div class="single-home-intro">
        <h1 id="workbench-heading" class="workbench-title">添加番剧</h1>
        <p class="single-home-subtitle">输入番剧名称 → 人工选择真实 MiKan 合集 → 审核并保存确认。</p>
      </div>

      <AnimeModeSwitch :model-value="mode" :disabled="singleBusy" @update:model-value="changeMode" />

      <SingleAnimeSearchForm
        ref="singleSearchForm"
        v-model:query="query"
        :loading="searchLoading"
        :disabled="singleBusy"
        @submit="requestSearch"
      />

      <p class="field-help single-home-help" id="mikan-candidate-help">
        输入番剧标题，从真实 MiKan 搜索候选合集。候选不会自动选择，需手动点击「选择此合集」生成订阅草案。
      </p>
      <p v-if="reuseSource" id="reuse-handoff-summary" class="field-help" role="status">
        已载入复制方案起点：{{ reuseSource.title }}（公开合集编号 {{ reuseSource.mikanBangumiId }}）。请重新搜索并选择真实合集。
      </p>

      <!-- 就地反馈：搜索中、失败、无候选都留在搜索首屏，保留输入与下一步操作。 -->
      <div
        v-if="searchStarted && !hasResults && !draftRequest"
        id="mikan-candidate-search-result"
        class="search-feedback"
        aria-live="polite"
        aria-relevant="additions text"
      >
        <LoadingState v-if="searchLoading" :message="`正在搜索「${query}」的 MiKan 候选...`" />
        <ErrorState
          v-else-if="searchError"
          id="mikan-candidate-search-error"
          title="候选搜索失败"
          :message="searchError"
        />
        <EmptyState
          v-else-if="searchResult"
          message="未找到候选合集。请核对番剧名称或季度后重试，或使用下方直连合集生成订阅草案。"
        />
      </div>

      <template v-if="searchSettled && !hasResults && !draftRequest">
        <BaseButton
          id="mikan-search-feedback-action"
          variant="secondary"
          :disabled="singleBusy"
          @click="requestSearch"
        >
          {{ searchError ? '重试搜索' : '重新搜索' }}
        </BaseButton>

        <!-- 直连救援入口默认收起：只有用户主动勾选后才展开表单。 -->
        <section class="candidate-fallback-rescue">
          <CheckboxRow
            id="mikan-fallback-enabled"
            v-model:checked="fallbackEnabled"
            label="搜索无结果时使用直连合集"
            help="可选：勾选后可粘贴 MiKan 合集 URL 或数字 ID 直接生成订阅草案；仅用于本次生成，不写入浏览器存储、URL、history 或订阅方案 JSON。"
          />
          <form
            v-if="fallbackEnabled"
            id="mikan-fallback-form"
            class="candidate-fallback-form"
            @submit.prevent="generateFromFallback"
          >
            <label for="mikan-fallback-bangumi">MiKan 合集 URL 或 ID</label>
            <BaseInput
              id="mikan-fallback-bangumi"
              v-model="fallbackValue"
              type="text"
              autocomplete="off"
              placeholder="mikan.example/Home/Bangumi/2353 或 2353"
              :disabled="singleBusy"
            />
            <p class="field-help" id="mikan-fallback-help">
              仅接受数字 ID 或同源 HTTP(S) /Home/Bangumi/&lt;id&gt; URL；生成成功后清空。
            </p>
            <p v-if="fallbackError" id="mikan-fallback-error" class="field-error" role="alert">
              {{ fallbackError }}
            </p>
            <div class="notification-actions">
              <BaseButton id="mikan-fallback-generate" type="submit" variant="secondary" :loading="fallbackLoading" :disabled="singleBusy">
                使用直连合集生成
              </BaseButton>
            </div>
          </form>
        </section>
      </template>

      <ol class="journey-steps single-home-steps" aria-label="添加番剧步骤">
        <li class="is-current">输入名称</li>
        <li>选择真实合集</li>
        <li>审核并保存确认</li>
      </ol>
    </section>

    <!-- ── 第二屏：候选工作台 ─────────────────────────────────────── -->
    <section
      v-if="showCandidateScreen"
      ref="workbenchScreen"
      class="add-screen candidate-workbench-screen"
      aria-labelledby="candidate-search-heading"
    >
      <p class="candidate-search-summary" role="status" aria-live="polite">
        已搜索「{{ searchResult?.query }}」
      </p>
      <BaseButton id="mikan-back-to-search" variant="secondary" @click="backToSearch">↑ 返回搜索首屏</BaseButton>
      <h2 id="candidate-search-heading" class="candidate-workbench-title" tabindex="-1">选择真实合集</h2>
      <p class="candidate-workbench-subtitle">请根据标题和季度信息，选择与您想添加的番剧一致的合集。</p>

      <div class="candidate-list-wrapper">
        <CandidateCollectionList
          :candidates="visibleCandidates"
          :query="searchResult?.query ?? ''"
          :disabled="searchLoading || (draftLoading && generatingCandidateId === null)"
          :loading-candidate-id="generatingCandidateId"
          :candidate-errors="candidateErrors"
          :confirmed-seasons="seasonConfirmations"
          @select="generateFromCandidate"
          @update:confirmed-season="(bangumiId: string, season: number | null) => (seasonConfirmations = { ...seasonConfirmations, [bangumiId]: season })"
        />
        <p v-if="hiddenCandidateCount" id="candidate-truncation-note" class="field-help" role="status">
          搜索结果较多，仅显示前 4 个合集；请先核对关键词，或用更精确的标题缩小范围。
        </p>
        <p v-if="parseNeedsReview" class="field-help" id="candidate-parse-review-note">
          标题解析结果需人工核对；展开「标题解析摘要」查看识别结果、季度与解析来源。
        </p>
        <details class="title-parse-summary">
          <summary>标题解析摘要（诊断信息）</summary>
          <dl class="detail-grid">
            <template v-for="[label, value] in parseSummaryRows()" :key="label">
              <div class="detail-row"><dt>{{ label }}</dt><dd>{{ displayValue(value) }}</dd></div>
            </template>
          </dl>
          <template v-if="attemptedQueryTexts().length">
            <h4 class="parse-subheading">实际搜索词</h4>
            <ul class="title-parse-query-list">
              <li v-for="text in attemptedQueryTexts()" :key="text">{{ text }}</li>
            </ul>
          </template>
          <template v-if="parseNeedsReview">
            <h4 class="parse-subheading">需人工核对</h4>
            <ul class="title-parse-review-hints">
              <li v-for="hint in parseReviewHints().length ? parseReviewHints() : ['该解析结果需要人工核对。']" :key="hint">
                {{ hint }}
              </li>
            </ul>
          </template>
        </details>
      </div>
    </section>

    <!-- ── 第二屏：草案审核 ───────────────────────────────────────── -->
    <section v-if="showDraftScreen" ref="workbenchScreen" class="add-screen candidate-workbench-screen draft-screen">
      <SingleAnimeReviewPanel
        :key="draftId"
        :request="draftRequest!"
        :draft-id="draftId"
        :draft-revision="draftRevision"
        :reuse-suggestion="reuseSuggestion"
        :selected-collection="selectedCollection"
        @changed="onDraftChanged"
        @discard="discardDraft"
        @change-mode="changeMode"
      />
    </section>

    <LoadingState
      v-if="draftLoading && !draftRequest && generatingCandidateId === null"
      message="正在从候选生成订阅草案..."
    />
  </div>

  <!-- ── 批量：搜索首屏标题、模式切换与步骤预告 ─────────────────── -->
  <template v-if="mode === 'batch'">
    <h1 id="workbench-heading" class="workbench-title">添加番剧</h1>
    <AnimeModeSwitch :model-value="mode" :disabled="singleBusy" @update:model-value="changeMode" />
    <p v-if="reuseSource" id="reuse-handoff-summary" class="field-help" role="status">
      已载入复制方案起点：{{ reuseSource.title }}（公开合集编号 {{ reuseSource.mikanBangumiId }}）。请重新搜索并选择真实合集。
    </p>
    <ol class="journey-steps" aria-label="添加番剧步骤">
      <li class="is-current">输入名称</li>
      <li>选择真实合集</li>
      <li>审核并保存确认</li>
    </ol>
  </template>

  <!-- ── batch workbench (US-205) ────────────────────────────────── -->
  <template v-if="batchMounted">
    <form
      v-show="mode === 'batch'"
      id="batch-parse-form"
      class="batch-parse-form"
      @submit.prevent="submitBatchSearch"
    >
      <label for="batch-raw-input">批量番剧名称</label>
      <AnimeTitleInput
        ref="batchInput"
        id="batch-raw-input"
        v-model="batchQuery"
        mode="batch"
        :disabled="batchSearchSubmitting"
        aria-describedby="batch-raw-input-help batch-input-count"
      />
      <p class="field-help" id="batch-raw-input-help">每行一个番剧简称或不完整标题；系统会逐项解析并搜索候选合集，结果需人工审核。</p>
      <p id="batch-input-count" class="batch-input-count" role="status">
        当前 {{ batchCount }} 部；可输入 1～36 部。{{ batchValidationError || '输入有效，可以开始搜索。' }}
      </p>
      <p v-if="batchValidationError" id="batch-input-validation" class="field-error" role="alert">{{ batchValidationError }}</p>
      <div class="notification-actions">
        <BaseButton id="batch-parse-submit" type="submit" variant="primary" size="lg" :loading="batchSearchSubmitting" :disabled="batchSearchDisabled">
          搜索候选合集
        </BaseButton>
      </div>
    </form>
    <BatchWorkbenchView
      v-show="mode === 'batch'"
      ref="batchWorkbench"
      class="batch-workbench-section"
      v-model:raw-input="batchQuery"
      hide-input
      @restore-search-focus="batchInput?.focusInput()"
    />
  </template>

  <!-- Issue 110：重新搜索会替换未保存现场时的简短确认。 -->
  <ConfirmDialog ref="confirmDialog" />
</template>

<style scoped>
/* Issue 110：单番两屏容器。容器自身纵向滚动并轻柔吸附；模块内部滚动带
 * overscroll-behavior: contain，滚到边界也不会把整页切到另一屏。 */
.add-anime-screens {
  display: block;
  height: calc(100vh - var(--size-shell-header) - var(--space-6) * 2);
  overflow-y: auto;
  overscroll-behavior: contain;
  scroll-snap-type: y proximity;
}

.add-screen {
  height: 100%;
  scroll-snap-align: start;
}

.add-screen.draft-screen {
  height: auto;
  min-height: 100%;
}

/* US-363: 单番搜索首页英雄区（Stage 47 几何基线）。
 * 容器 720px 居中；内容在内容区内垂直居中；间距/字号/控件高全部取冻结 Token。 */
.single-home-hero {
  /* Stage 47 获批页面专属几何：英雄区宽度（基线文档第 11 节 8 项清单之一）。
   * 其余几何全部取自语义 Token。 */
  --single-home-hero-width: 720px;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  width: min(100%, var(--single-home-hero-width));
  min-height: calc(100vh - var(--size-shell-header) - var(--space-6) * 2);
  margin-inline: auto;
}

/* 搜索一旦开始（loading 或空结果）英雄区回到文档流顶部，与结果区顺序排布，
 * 避免从「垂直居中」跳到「结果面板」造成的布局跳变。 */
.single-home-hero.is-searching {
  justify-content: flex-start;
  min-height: auto;
  padding-top: var(--space-2);
}

.single-home-intro {
  display: grid;
  gap: var(--space-2);
  width: 100%;
  text-align: center;
}

.single-home-hero .workbench-title {
  display: -webkit-box;
  /* 固定单行高度 = display 字号 × display 行高 Token（40 × 1.2 = 48px）。 */
  height: calc(var(--type-display) * var(--type-display-line-height));
  overflow: hidden;
  font-size: var(--type-display);
  font-weight: var(--font-weight-bold);
  line-height: var(--type-display-line-height);
  -webkit-box-orient: vertical;
  -webkit-line-clamp: 1;
}

.single-home-subtitle {
  display: -webkit-box;
  /* 固定单行高度 = 正文字号 × 正文行高 Token（15 × 1.6 = 24px）。 */
  height: calc(var(--type-body) * var(--line-height-body));
  margin: 0;
  overflow: hidden;
  color: var(--color-text-muted);
  font-size: var(--font-size-md);
  line-height: var(--line-height-body);
  -webkit-box-orient: vertical;
  -webkit-line-clamp: 1;
}

.single-home-hero > .anime-mode-switch {
  margin-top: var(--space-6);
}

.single-home-hero > .workbench-search-form {
  width: 100%;
  margin-top: var(--space-8);
}

.single-home-help {
  width: 100%;
  margin: var(--space-4) 0 0;
  text-align: center;
}

.single-home-hero > #reuse-handoff-summary,
.single-home-hero > #mikan-candidate-search-error {
  width: 100%;
  margin: var(--space-4) 0 0;
}

.single-home-hero .journey-steps {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: var(--space-3);
  width: 100%;
  min-height: var(--space-16);
  margin: var(--space-10) 0 0;
  text-align: center;
  list-style-position: inside;
}

/* 就地反馈区与可操作的重试／重新搜索都留在搜索首屏（Issue 110）。 */
.search-feedback {
  width: 100%;
  margin-top: var(--space-4);
}

.single-home-hero > #mikan-search-feedback-action {
  margin-top: var(--space-4);
}

.single-home-hero > .candidate-fallback-rescue {
  width: 100%;
  margin-top: var(--space-4);
  text-align: left;
}

/* 第二屏：候选工作台 / 草案审核。内容面板各自内部滚动，不撑长整页。 */
.candidate-workbench-screen {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: var(--space-3);
  width: 100%;
  height: 100%;
  padding-block: var(--space-8);
  text-align: center;
}

.candidate-search-summary {
  margin: 0;
  color: var(--color-text-muted);
  font-size: var(--font-size-sm);
}

.candidate-workbench-title {
  margin: 0;
  font-size: var(--type-display);
  font-weight: var(--font-weight-bold);
  line-height: var(--type-display-line-height);
}

.candidate-workbench-subtitle {
  margin: 0;
  color: var(--color-text-muted);
  font-size: var(--font-size-md);
}

.candidate-workbench-screen .candidate-list-wrapper {
  flex: 1 1 auto;
  min-height: 0;
  width: 100%;
  overflow-y: auto;
  overscroll-behavior: contain;
  text-align: left;
}

.candidate-workbench-screen.draft-screen {
  /* 草案审核屏沿用既有面板几何（#111 负责）；这里不额外居中或加内边距。 */
  align-items: stretch;
  padding-block: 0;
  text-align: left;
  gap: 0;
}

.candidate-workbench-screen.draft-screen .candidate-list-wrapper {
  overflow: visible;
}
.batch-parse-form,
.candidate-fallback-form {
  display: grid;
  gap: 0.75rem;
}

.batch-parse-form label,
.candidate-fallback-form label {
  font-weight: 500;
  font-size: 0.875rem;
}

.batch-input-count {
  margin: 0;
  color: var(--color-text-muted);
  font-size: var(--font-size-sm);
}

.workbench-title {
  margin: 0;
}

.journey-steps {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-4);
  margin: 0 0 var(--space-4);
  padding: 0;
  color: var(--color-text-muted);
  list-style-position: inside;
}

.journey-steps .is-current {
  color: var(--color-text);
  font-weight: var(--font-weight-semibold);
}

.candidate-list-wrapper {
  display: block;
  container-type: inline-size;
}

.title-parse-summary {
  display: grid;
  gap: 0.5rem;
  border: 1px solid var(--color-border);
  border-radius: 6px;
  padding: 0.75rem;
}

.title-parse-summary summary {
  cursor: pointer;
  font-weight: 600;
  color: var(--color-text-muted);
}

/* F4: the direct-collection form is a secondary rescue path that only appears
   after a started search found no candidates. */
.candidate-fallback-rescue {
  display: grid;
  gap: 0.6rem;
  border: 1px dashed var(--color-border);
  border-radius: 6px;
  padding: 0.75rem;
  margin-top: 0.25rem;
}

.detail-grid {
  margin: 0;
  display: grid;
  gap: 0.3rem 1rem;
  grid-template-columns: max-content 1fr;
}

.detail-row {
  display: contents;
}

.detail-row dt {
  font-weight: 600;
  color: var(--color-text-muted);
}

.detail-row dd {
  margin: 0;
  overflow-wrap: anywhere;
}

.parse-subheading {
  margin: 0.5rem 0 0;
  font-size: 0.9rem;
}

.title-parse-query-list,
.title-parse-review-hints {
  margin: 0.25rem 0 0;
  padding-left: 1.25rem;
  display: grid;
  gap: 0.25rem;
}

.batch-workbench-section {
  margin-top: 1.25rem;
}

.notification-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 0.5rem;
}

@media (max-width: 720px) {
  .detail-grid {
    grid-template-columns: 1fr;
    gap: 0.2rem;
  }
}
</style>
