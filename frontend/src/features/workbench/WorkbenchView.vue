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
import { useAddAnimeScreenScroll } from '@/app/composables/useAddAnimeScreenScroll'
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
import type { BatchParseOutcome } from '@/features/workbench/batchWorkbench'
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
// Issue 112：逐部进度只来自服务端真实完成事件；搜索期间留在首屏，
// 整批拿到稳定结果后才切到工作台。
const batchProgress = ref<{ completed: number; total: number } | null>(null)
const batchSearchSettled = ref(false)
// 子组件报告的「批量数据已稳定可展示」；父组件据此在搜索收尾后唯一一次切屏。
const batchResultReady = ref(false)
// 整批解析成功但服务端没有返回任何条目：留在搜索首屏就地说明（不是 MiKan 故障）。
const batchEmptyResult = ref(false)
const batchWorkbenchScreen = ref<HTMLElement | null>(null)
// 批量搜索首屏：批量模式下的「第一屏」切屏目标（与单番 hero 互斥挂载）。
const batchSearchScreen = ref<HTMLElement | null>(null)
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
/**
 * #159：批量首屏与单番英雄区共用「空闲态垂直居中 / 搜索态回到文档流顶部」这一条规则，
 * 避免进度、失败或空结果出现时任务区被重新居中而产生跳动。
 */
const batchSearchActive = computed(
  () => batchSearchSubmitting.value || Boolean(batchProgress.value) || batchEmptyResult.value,
)

/**
 * 模式切换的禁用条件必须包含「批量搜索进行中」：批量请求仍在飞时切到单番，会让
 * 结果在没有 batch 屏的情况下完成，用户切回来时结果仍然被隐藏、也不会自动进入
 * 工作台。单番搜索（singleBusy）与批量搜索（batchSearchSubmitting）都不允许切换。
 */
const modeSwitchDisabled = computed(() => singleBusy.value || batchSearchSubmitting.value)

async function submitBatchSearch(): Promise<void> {
  if (batchSearchDisabled.value) return
  batchSearchSubmitting.value = true
  batchSearchSettled.value = false
  batchResultReady.value = false
  batchEmptyResult.value = false
  // 进度条按输入部数分段，从 0 开始；只有真实完成事件才会推进。
  batchProgress.value = { completed: 0, total: batchCount.value }
  try {
    await batchWorkbench.value?.parseBatch((progress) => {
      batchProgress.value = progress
    })
  } finally {
    // 搜索状态的收尾必须先于切屏：按钮 loading 与进度条都会改变首屏高度，
    // 在它们撤掉之前取切屏目标会拿到中间态布局。
    batchSearchSubmitting.value = false
    batchProgress.value = null
  }
  await enterBatchWorkbench()
}

/**
 * 子组件只表达「批量数据已稳定可展示」；是否切屏、何时切屏由父组件唯一决定，
 * 避免子组件与父组件同时抢焦点或滚动。
 *
 * 只有「至少有一个可展示条目」才允许进入工作台：`items=[]` 表示服务端没有返回任何
 * 条目（不是 MiKan 故障），此时留在搜索首屏就地说明，而不是切进一个空工作台。
 * 全部条目都是 EMPTY/FAILED 仍算有条目，必须进入工作台逐项处理。
 */
function onBatchParseSettled(outcome: BatchParseOutcome): void {
  batchResultReady.value = !outcome.failed && outcome.itemCount > 0
  batchEmptyResult.value = !outcome.failed && outcome.itemCount === 0
}

/**
 * Issue 112/113：整批完成且搜索状态收尾后，唯一一次进入第二屏。
 *
 * `goToSecondScreen()` 会先等第二屏的文档 top 与高度连续两帧稳定，再在最终布局上取
 * 切屏目标；焦点也在这个时点之后落到工作台标题，因此不再需要叠加 `nextTick()`。
 * 失败、空 items 或当前不在 batch 模式时保持 false／不变，仍然留在搜索首屏。
 */
async function enterBatchWorkbench(): Promise<void> {
  if (!batchResultReady.value || mode.value !== 'batch' || batchSearchSettled.value) return
  batchSearchSettled.value = true
  await screenScroll.goToSecondScreen({
    onReady: () => {
      document.querySelector<HTMLElement>('#panel-section-批量工作台')?.focus({ preventScroll: true })
    },
  })
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

/**
 * #140/#141/#143：两屏滚动所有权。
 *
 * 搜索首屏常驻；第二屏按当前模式取单番候选/草案屏或批量工作台屏，未挂载（搜索中、
 * 失败、无候选、整批未完成）时不会切屏。滚动属于文档，模块外空白区同样可切屏；
 * 批量左右栏以 `data-screen-scroll="inner"` 声明为内部滚动所有者。
 */
// 首屏同样按模式取：单番 hero 与批量搜索屏互斥挂载。批量模式下 heroScreen 为空，
// 若只绑单番 hero，「返回搜索首屏」与「模块外空白向上滚」都没有切屏目标。
const firstScreen = computed<HTMLElement | null>(() =>
  mode.value === 'single' ? heroScreen.value : batchSearchScreen.value,
)
const secondScreen = computed<HTMLElement | null>(() =>
  mode.value === 'single' ? workbenchScreen.value : batchWorkbenchScreen.value,
)
const screenScroll = useAddAnimeScreenScroll({
  firstScreen,
  secondScreen,
})

/**
 * 结果已就绪但当时不在 batch 模式（例如某个合法入口在请求完成后才切回批量）时，
 * 切回批量必须明确恢复已完成的结果，而不是依赖偶然的焦点滚动。`enterBatchWorkbench`
 * 是幂等的：已经进入过（`batchSearchSettled` 为真）时不会重复切屏。
 */
watch(mode, (value) => {
  if (value !== 'batch') return
  void enterBatchWorkbench()
})

/**
 * 明确按钮或模块外空白滚动都只是回到首屏，不清空第二屏现场。
 * 平滑定位结束后才聚焦输入，避免焦点把页面瞬移回另一处。
 */
async function backToSearch(): Promise<void> {
  await screenScroll.goToFirstScreen()
  singleSearchForm.value?.focusInput()
}

/**
 * #145：批量工作台页头的「返回搜索首屏」——只切屏与聚焦批量输入，绝不清除下方
 * 未保存的候选、草案、筛选与勾选现场（与单番返回入口同一语义）。
 */
async function backToBatchSearch(): Promise<void> {
  await screenScroll.goToFirstScreen()
  batchInput.value?.focusInput()
}

// #141：候选切到草案时工作台内容会变长（也可能被滚动锚定带动），
// 因此进入草案状态后把工作台重新对齐到顶部，让审核标题与返回按钮可见。
watch(showDraftScreen, async (visible) => {
  if (!visible) return
  await nextTick()
  await screenScroll.goToSecondScreen()
})

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
      // 焦点与滚动都发生在第二屏的最终稳定布局就位之后（`onReady`），因此取到的
      // 切屏目标一定是最新坐标，也不会让焦点把一个还在收尾的布局带偏。
      await screenScroll.goToSecondScreen({
        onReady: () => {
          document
            .querySelector<HTMLElement>('#candidate-search-heading')
            ?.focus({ preventScroll: true })
        },
      })
    } else {
      // 失败或无候选都留在搜索首屏就地恢复；不抢焦点（Stage 42 无障碍保证），
      // 用户仍停在输入或原控件上，可直接修正后重试。
      await screenScroll.goToFirstScreen()
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

      <AnimeModeSwitch :model-value="mode" :disabled="modeSwitchDisabled" @update:model-value="changeMode" />

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
      <!-- Issue 141：长草案沿「添加番剧」页面唯一的外层滚动轴连续展示，
           不再有第二条内部纵向滚动轴；标题与返回按钮随内容一起移动。 -->
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

  <!-- ── 批量：搜索首屏 + 批量工作台两屏（Issue 113） ─────────────── -->
  <div v-show="mode === 'batch'" class="add-anime-screens batch-screens">
    <!-- 首屏只在批量模式下挂载：单番容器已提供自己的标题、模式切换与步骤，
         两者同时存在会产生重复的 id 与导航语义。 -->
    <section
      v-if="mode === 'batch'"
      ref="batchSearchScreen"
      class="add-screen batch-search-screen"
      :class="{ 'is-searching': batchSearchActive }"
    >
      <!-- #159：批量首屏与单番首屏共用同一套标题层级、中心轴与模式切换锚点；只有输入
           形态（多行文本框）按任务保留自然高度。 -->
      <div class="batch-search-intro">
        <h1 id="workbench-heading" class="workbench-title">添加番剧</h1>
        <p class="batch-search-subtitle">粘贴番剧名称 → 逐部选择真实 MiKan 合集 → 审核并保存确认。</p>
      </div>
      <AnimeModeSwitch :model-value="mode" :disabled="modeSwitchDisabled" @update:model-value="changeMode" />

      <form
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
        当前 {{ batchCount }} 部；可输入 1～36 部。
      </p>
      <!-- #159：非法输入只在下面这一条 role="alert" 里说明一次；容量提示行不重复同一句
           错误文案，任务区因此不会被同一句话撑成两行。 -->
      <p v-if="batchValidationError" id="batch-input-validation" class="field-error" role="alert">{{ batchValidationError }}</p>
      <!-- #145 F：整批成功但服务端没有返回任何条目 → 留在搜索首屏就地说明，
           既不进入空工作台，也不把它描述成 MiKan 故障。 -->
      <p v-if="batchEmptyResult" id="batch-empty-result" class="field-help" role="status">
        整批解析已完成，但服务端没有返回任何条目；请核对输入后重新搜索。
      </p>
      <!-- Issue 112：按实际完成部数推进的分段进度；不做时间估算。 -->
      <div v-if="batchProgress" id="batch-search-progress" class="batch-search-progress">
        <p class="batch-progress-label" role="status" aria-live="polite">
          正在逐部搜索：已完成 {{ batchProgress.completed }} / {{ batchProgress.total }} 部
        </p>
        <ol class="batch-progress-track" aria-hidden="true">
          <li
            v-for="index in batchProgress.total"
            :key="index"
            class="batch-progress-segment"
            :class="{ 'is-complete': index <= batchProgress.completed }"
          ></li>
        </ol>
        <p class="field-help" id="batch-progress-note">
          进度只保留在当前页面：刷新或关闭后需要重新搜索；服务端请求不因此被取消。
        </p>
      </div>
      <div class="notification-actions">
        <BaseButton id="batch-parse-submit" type="submit" variant="primary" size="lg" :loading="batchSearchSubmitting" :disabled="batchSearchDisabled">
          搜索候选合集
        </BaseButton>
      </div>
      </form>

      <p v-if="reuseSource" id="reuse-handoff-summary" class="field-help" role="status">
        已载入复制方案起点：{{ reuseSource.title }}（公开合集编号 {{ reuseSource.mikanBangumiId }}）。请重新搜索并选择真实合集。
      </p>

      <ol class="journey-steps batch-search-steps" aria-label="添加番剧步骤">
        <li class="is-current">输入名称</li>
        <li>选择真实合集</li>
        <li>审核并保存确认</li>
      </ol>
    </section>

    <!-- 第二屏：批量双栏工作台。整批完成、拿到稳定结果后才显示并切入。 -->
    <section
      v-if="batchMounted"
      v-show="batchSearchSettled"
      ref="batchWorkbenchScreen"
      class="add-screen batch-workbench-screen"
      data-screen-scroll="overflow"
    >
      <BatchWorkbenchView
        ref="batchWorkbench"
        class="batch-workbench-section"
        v-model:raw-input="batchQuery"
        hide-input
        @restore-search-focus="batchInput?.focusInput()"
        @back-to-search="backToBatchSearch"
        @parse-settled="onBatchParseSettled"
      />
    </section>
  </div>

  <!-- Issue 110：重新搜索会替换未保存现场时的简短确认。 -->
  <ConfirmDialog ref="confirmDialog" />
</template>

<style scoped>
/* #140/#141/#143：单番与批量的两屏都是文档内的普通区块。
 *
 * 外层滚动所有权属于文档（见 main.css 的 `html.add-anime-scroll`），因此
 * `#app-main` 的内容、内边距与宽屏两侧留白都能驱动切屏，顶部导航保持可见。
 * 每一屏至少占满一屏可用高度；单番候选与草案可以沿同一页面滚动轴继续变长，
 * 不再有第二条内部纵向滚动轴。 */
.add-anime-screens {
  display: block;
  /* #159：单番首屏空闲态的获批任务区高度（Stage 47 基线，全部由冻结 Token 推导）：
     标题 48 + 说明间距 8 + 说明 24 + 模式切换间距 24 + 模式切换 62
     （--control-height-mode-switch）+ 表单间距 32 +（标签 22.4 + 字段间距 8 + 输入 52）
     + 说明间距 16 + 说明 22.4 + 步骤间距 40 + 步骤 64。批量首屏用它把任务区顶端对齐
     到单番的居中位置：批量内容自然更高，直接居中会让标题与模式切换整体上移约 108px。
     这是页面专属的几何镜像，单番首屏改变间距时必须同步；实际偏差由
     tests/browser/test_app_add_mode_continuity.py 在 1280/1440/1920 上逐视口复核。 */
  --first-screen-task-height: calc(
    (var(--type-display) * var(--type-display-line-height)) + var(--space-2)
      + (var(--type-body) * var(--line-height-body)) + var(--space-6)
      + var(--control-height-mode-switch) + var(--space-8)
      + (var(--font-size-sm) * var(--line-height-body)) + var(--space-2) + var(--control-height-lg)
      + var(--space-4) + (var(--font-size-sm) * var(--line-height-body))
      + var(--space-10) + var(--space-16)
  );
}

.add-screen {
  min-height: calc(100vh - var(--size-shell-header) - var(--space-6) * 2);
}

/* 单番候选工作台：内容沿页面滚动轴连续排布，标题、返回按钮与卡片一起移动。
 * 不使用 height/overflow，避免与外层滚动争夺同一个滚轮事件。 */
.candidate-workbench-screen {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: var(--space-3);
  width: 100%;
  padding-block: var(--space-8);
  text-align: center;
}

.candidate-workbench-screen.draft-screen {
  /* 草案审核沿用既有面板几何（#141）；这里不额外居中或加内边距。 */
  align-items: stretch;
  padding-block: 0;
  text-align: left;
  gap: 0;
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

.single-home-hero .workbench-title,
.batch-search-screen .workbench-title {
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

.single-home-subtitle,
.batch-search-subtitle {
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

.single-home-hero > .anime-mode-switch,
.batch-search-screen > .anime-mode-switch {
  margin-top: var(--space-6);
}

.single-home-hero > .workbench-search-form,
.batch-search-screen > .batch-parse-form {
  width: 100%;
  margin-top: var(--space-8);
  /* #159：批量任务区比单番多出文本框、容量提示与主操作；行距收一档，让空闲态的
     任务区连同 24px 顶端锚点仍在一屏内，不把旅程步骤挤到首屏之外。 */
  gap: var(--space-2);
}

/* 任务区内的说明行由栅格间距分隔，不再叠加 field-help 自带的外边距。 */
.batch-search-screen > .batch-parse-form > .field-help {
  margin-block: 0;
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

/* 第二屏：候选工作台 / 草案审核。两者共用页面唯一的外层滚动轴。 */
.candidate-search-summary {
  margin: 0;
  color: var(--color-text-muted);
  font-size: var(--font-size-sm);
}

/* 保持返回入口在不同系统字体度量下的居中几何；文字放大时仍可自然撑宽。 */
#mikan-back-to-search {
  min-width: 8rem;
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

/* #141：候选列表不再自带纵向滚动，卡片变多时由页面滚动轴继续展示。 */
.candidate-workbench-screen .candidate-list-wrapper {
  width: 100%;
  text-align: left;
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

.batch-search-screen {
  /* #159：批量首屏与单番英雄区共用 720px 任务宽度、水平中心轴与任务区顶端锚点；
     只有输入形态（多行文本框）按任务保留自然高度。间距与单番一样由各子项的
     Token 边距决定，不用 flex gap 叠加出第二套节奏。 */
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 0;
  /* 顶端锚点：把批量任务区顶端放在单番空闲态居中后的同一位置（内容更高时自然向下
     延伸，不影响标题与模式切换的位置）。视口装不下时归零，与单番一样自然滚动。 */
  justify-content: flex-start;
  padding-block-start: max(
    0px,
    calc(
      (100vh - var(--size-shell-header) - var(--space-6) * 2 - var(--first-screen-task-height)) / 2
    )
  );
  width: min(100%, 720px);
  min-height: calc(100vh - var(--size-shell-header) - var(--space-6) * 2);
  margin-inline: auto;
}

/* 搜索一旦开始（loading／逐部进度／空结果）任务区回到文档流顶部，与单番首屏同一
   条规则，避免居中与结果面板之间来回跳变。 */
.batch-search-screen.is-searching {
  justify-content: flex-start;
  min-height: auto;
  padding-top: var(--space-2);
}

.batch-search-intro {
  display: grid;
  gap: var(--space-2);
  width: 100%;
  text-align: center;
}

.batch-search-screen > #reuse-handoff-summary {
  width: 100%;
  margin: var(--space-4) 0 0;
}

.batch-search-screen .journey-steps {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: var(--space-3);
  width: 100%;
  min-height: var(--space-16);
  margin: var(--space-10) 0 0;
  text-align: center;
  list-style-position: inside;
}

.batch-workbench-screen {
  /* #143：批量工作台屏固定为一屏——顶部标题与底部操作栏必须同时可见，因此长列表
     与长草案由双栏各自的内部滚动承载，不撑长这一屏，也不与外层滚动争夺滚轮。
     正常桌面双栏装得下时它没有溢出，滚轮仍由外层负责切屏；只有极窄视口／200% 缩放
     装不下时才退化为这一屏自身内部滚动，优先保证内容完整可读。 */
  display: flex;
  flex-direction: column;
  height: calc(100vh - var(--size-shell-header) - var(--space-6) * 2);
  min-height: 0;
  overflow-y: auto;
  overscroll-behavior: contain;
  /* 退化滚动时不自带可见滚动条：避免滚动条出现/消失改变内容宽度造成抖动；
     双栏内部的可见滚动条不受影响。 */
  scrollbar-width: none;
  /* 批量工作台不再有包裹双栏的外框；仍需保留轻微水平留白，避免页头、两栏与
     底栏直接贴住添加页内容边界。此留白属于工作台屏，不影响两栏各自的滚动所有权。 */
  box-sizing: border-box;
  padding-inline: var(--space-3);
  width: 100%;
}

.batch-workbench-screen::-webkit-scrollbar {
  display: none;
}

/* 面板在固定一屏内按列分配高度：双栏占满剩余空间，操作栏取自己的真实高度。 */
.batch-workbench-panel {
  display: flex;
  flex-direction: column;
  height: 100%;
  min-height: 0;
}

/* Issue 112：批量逐部进度——分段只按真实完成数点亮。 */
.batch-search-progress {
  display: grid;
  gap: var(--space-2);
  margin-top: var(--space-3);
}

.batch-progress-label {
  margin: 0;
  color: var(--color-text);
  font-size: var(--font-size-sm);
  font-weight: var(--font-weight-medium);
}

.batch-progress-track {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-1);
  margin: 0;
  padding: 0;
  list-style: none;
}

.batch-progress-segment {
  flex: 1 1 var(--space-3);
  min-width: var(--space-3);
  height: var(--space-2);
  border-radius: var(--radius-pill);
  background: var(--color-surface-subtle);
  border: 1px solid var(--color-border);
}

.batch-progress-segment.is-complete {
  background: var(--color-primary);
  border-color: var(--color-primary);
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
