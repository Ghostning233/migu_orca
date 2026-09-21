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
import EmptyState from '@/components/feedback/EmptyState.vue'
import ErrorState from '@/components/feedback/ErrorState.vue'
import LoadingState from '@/components/feedback/LoadingState.vue'
import PanelSection from '@/components/layout/PanelSection.vue'

import CandidateCollectionList from '@/features/workbench/CandidateCollectionList.vue'
import SingleAnimeReviewPanel from '@/features/workbench/SingleAnimeReviewPanel.vue'
import BatchWorkbenchView from '@/features/workbench/BatchWorkbenchView.vue'
import AnimeModeSwitch, { type AnimeMode } from '@/features/workbench/AnimeModeSwitch.vue'
import AnimeTitleInput from '@/features/workbench/AnimeTitleInput.vue'
import {
  buildCandidateCreatePayload,
  buildFallbackCreatePayload,
  parseSourceLabel,
  parseSeasonNumber,
  selectedCollectionSummary,
  validateCandidateQuery,
  validateFallbackValue,
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
const singleInput = ref<InstanceType<typeof AnimeTitleInput> | null>(null)
const batchInput = ref<InstanceType<typeof AnimeTitleInput> | null>(null)
const batchWorkbench = ref<InstanceType<typeof BatchWorkbenchView> | null>(null)
const batchSearchSubmitting = ref(false)
const selections = ref<Record<AnimeMode, { start: number; end: number }>>({
  single: { start: 0, end: 0 },
  batch: { start: 0, end: 0 },
})
const searchLoading = ref(false)
const searchError = ref('')
const searchResult = ref<CandidateSearchResult | null>(null)
const lastSearchQuery = ref('')

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
const showSingleHome = computed(
  () => mode.value === 'single' && !hasResults.value && !draftRequest.value,
)
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
const selectedCandidate = ref<MikanCandidate | null>(null)

/** Display-only projection of the selected collection for the review header. */
const selectedCollection = computed(() =>
  selectedCandidate.value
    ? selectedCollectionSummary(selectedCandidate.value, seasonConfirmations.value[selectedCandidate.value.bangumi_id] ?? null)
    : null,
)

const hasResults = computed(() => (searchResult.value?.candidates?.length ?? 0) > 0)

/** Candidate generation state never outlives the search results it belongs to. */
function resetCandidateGenerationState(): void {
  generatingCandidateId.value = null
  candidateErrors.value = {}
}

function editSearch(): void {
  searchResult.value = null
  lastSearchQuery.value = ''
  searchError.value = ''
  selectedCandidate.value = null
  resetCandidateGenerationState()
  void nextTick(() => singleInput.value?.focus())
}

watch(query, (value) => {
  const normalized = value.trim()
  if (!searchResult.value || normalized === lastSearchQuery.value) return
  // A result belongs to the exact title that produced it. Keep the user's
  // edited input, but remove stale candidates and their one-time confirmations.
  searchResult.value = null
  lastSearchQuery.value = ''
  searchError.value = ''
  seasonConfirmations.value = {}
  selectedCandidate.value = null
  resetCandidateGenerationState()
})

async function changeMode(nextMode: AnimeMode): Promise<void> {
  if (nextMode === mode.value || singleBusy.value) return
  const currentInput = mode.value === 'single' ? singleInput.value : batchInput.value
  if (currentInput) selections.value[mode.value] = currentInput.selection()
  mode.value = nextMode
  // A result belongs to the mode that produced it; never present it as the
  // result of the newly selected mode.
  searchResult.value = null
  searchError.value = ''
  selectedCandidate.value = null
  await nextTick()
  const nextInput = nextMode === 'single' ? singleInput.value : batchInput.value
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
  lastSearchQuery.value = query.value.trim()
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
      document.querySelector<HTMLElement>('#mikan-candidate-search-result .candidate-select')?.focus()
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
    lastSearchQuery.value = ''
    searchError.value = ''
  }
  void nextTick(() => singleInput.value?.focus())
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
  void nextTick(() => singleInput.value?.focus())
})

defineExpose({ searchCandidates, generateFromCandidate, generateFromFallback })
</script>

<template>
  <!-- US-363 (Stage 47 几何基线): 单番初始态是只组织一次搜索任务的居中英雄区。
       搜索开始前不得渲染结果区、救援面板、候选卡、草案审核区或有效资源数。 -->
  <div v-if="showSingleHome" class="single-home-hero" :class="{ 'is-searching': searchStarted }">
    <div class="single-home-intro">
      <h1 id="workbench-heading" class="workbench-title">添加番剧</h1>
      <p class="single-home-subtitle">输入番剧名称 → 人工选择真实 MiKan 合集 → 审核并保存确认。</p>
    </div>

    <AnimeModeSwitch :model-value="mode" :disabled="singleBusy" @update:model-value="changeMode" />

    <form id="mikan-candidate-search-form" class="workbench-search-form" @submit.prevent="searchCandidates">
      <div class="search-control-row">
        <div class="search-field">
          <label for="mikan-candidate-query">番剧标题</label>
          <AnimeTitleInput
            ref="singleInput"
            id="mikan-candidate-query"
            v-model="query"
            mode="single"
            :disabled="singleBusy"
          />
        </div>
        <BaseButton id="mikan-candidate-search-submit" type="submit" variant="primary" size="lg" :loading="searchLoading" :disabled="singleBusy || !query.trim()">
          搜索候选合集
        </BaseButton>
      </div>
    </form>

    <p class="field-help single-home-help" id="mikan-candidate-help">
      输入番剧标题，从真实 MiKan 搜索候选合集。候选不会自动选择，需手动点击「选择此合集」生成订阅草案。
    </p>
    <p v-if="reuseSource" id="reuse-handoff-summary" class="field-help" role="status">
      已载入复制方案起点：{{ reuseSource.title }}（公开合集编号 {{ reuseSource.mikanBangumiId }}）。请重新搜索并选择真实合集。
    </p>
    <p v-if="searchError" id="mikan-candidate-search-error" class="field-error" role="alert">
      {{ searchError }}
    </p>

    <ol class="journey-steps single-home-steps" aria-label="添加番剧步骤">
      <li class="is-current">输入名称</li>
      <li>选择真实合集</li>
      <li>审核并保存确认</li>
    </ol>
  </div>

  <h1 v-else id="workbench-heading" class="workbench-title">添加番剧</h1>

  <!-- 非英雄区状态（批量 / 已有候选 / 草案）沿用既有面板结构；
       空结果或搜索中仍显示英雄区，因此这里用 !showSingleHome 而不是 v-else，
       以便下面的「搜索结果」面板能与英雄区共存。 -->
  <PanelSection v-if="!showSingleHome" title="搜索候选合集" class="workbench-panel">
    <ol class="journey-steps" aria-label="添加番剧步骤">
      <li class="is-current">输入名称</li>
      <li>选择真实合集</li>
      <li>审核并保存确认</li>
    </ol>
    <!-- ── single search ──────────────────────────────────────────── -->
    <AnimeModeSwitch :model-value="mode" :disabled="singleBusy" @update:model-value="changeMode" />

    <form v-if="mode === 'single' && !hasResults" id="mikan-candidate-search-form" class="workbench-search-form" @submit.prevent="searchCandidates">
      <div class="search-control-row">
        <div class="search-field">
          <label for="mikan-candidate-query">番剧标题</label>
          <AnimeTitleInput
            ref="singleInput"
            id="mikan-candidate-query"
            v-model="query"
            mode="single"
            :disabled="singleBusy"
          />
        </div>
        <BaseButton id="mikan-candidate-search-submit" type="submit" variant="primary" size="lg" :loading="searchLoading" :disabled="singleBusy || !query.trim()">
          搜索候选合集
        </BaseButton>
      </div>
      <p class="field-help" id="mikan-candidate-help">
        输入番剧标题，从真实 MiKan 搜索候选合集。候选不会自动选择，需手动点击「选择此合集」生成订阅草案。
      </p>
      <p v-if="reuseSource" id="reuse-handoff-summary" class="field-help" role="status">
        已载入复制方案起点：{{ reuseSource.title }}（公开合集编号 {{ reuseSource.mikanBangumiId }}）。请重新搜索并选择真实合集。
      </p>
      <p v-if="searchError" id="mikan-candidate-search-error" class="field-error" role="alert">
        {{ searchError }}
      </p>
    </form>
  </PanelSection>

    <!-- ── search results: created by a search, never before one ──────── -->
    <PanelSection
      v-if="mode === 'single' && !draftRequest && searchStarted"
      title="搜索结果"
      class="search-results-panel"
    >
      <div
        id="mikan-candidate-search-result"
        class="candidate-list-wrapper"
        aria-live="polite"
        aria-relevant="additions text"
      >
        <LoadingState v-if="searchLoading" :message="`正在搜索「${query}」的 MiKan 候选...`" />
        <ErrorState
          v-else-if="searchError"
          title="候选搜索失败"
          :message="searchError"
          retry-label="重试"
          @retry="searchCandidates"
        />
        <EmptyState
          v-else-if="searchResult && !hasResults"
          message="未找到候选合集。可调整番剧标题后重试，或使用下方直连合集生成订阅草案。"
        />
        <section v-if="searchSettled && !hasResults" class="candidate-fallback-rescue">
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
        <template v-if="searchResult && hasResults">
          <p class="step-label">步骤 2 · 选择合集</p>
          <p class="candidate-search-summary" role="status" aria-live="polite">
            已搜索「{{ searchResult.query }}」，请选择要审核的真实 MiKan 合集。
          </p>
          <div class="search-summary-actions">
            <span class="search-summary-label">搜索摘要</span>
            <BaseButton id="mikan-edit-search" variant="secondary" @click="editSearch">修改搜索</BaseButton>
          </div>
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
          <CandidateCollectionList
            :candidates="searchResult.candidates"
            :query="searchResult.query"
            :disabled="searchLoading || (draftLoading && generatingCandidateId === null)"
            :loading-candidate-id="generatingCandidateId"
            :candidate-errors="candidateErrors"
            :confirmed-seasons="seasonConfirmations"
            @select="generateFromCandidate"
            @update:confirmed-season="(bangumiId: string, season: number | null) => (seasonConfirmations = { ...seasonConfirmations, [bangumiId]: season })"
          />
        </template>
      </div>
      <p v-if="parseNeedsReview && hasResults" class="field-help" id="candidate-parse-review-note">
        标题解析结果需人工核对；展开「标题解析摘要」查看识别标题、季度与解析来源。
      </p>
    </PanelSection>

    <!-- ── draft preview ───────────────────────────────────────────── -->
    <SingleAnimeReviewPanel
      v-if="mode === 'single' && draftRequest && draftId"
      :key="draftId"
      :request="draftRequest"
      :draft-id="draftId"
      :draft-revision="draftRevision"
      :reuse-suggestion="reuseSuggestion"
      :selected-collection="selectedCollection"
      @changed="onDraftChanged"
      @discard="discardDraft"
    />
  <LoadingState
    v-if="mode === 'single' && draftLoading && !draftRequest && generatingCandidateId === null"
    message="正在从候选生成订阅草案..."
  />

  <!-- ── batch workbench (US-205) ────────────────────────────────── -->
  <template v-if="mode === 'batch'">
    <form id="batch-parse-form" class="batch-parse-form" @submit.prevent="submitBatchSearch">
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
      ref="batchWorkbench"
      class="batch-workbench-section"
      v-model:raw-input="batchQuery"
      hide-input
      @restore-search-focus="batchInput?.focusInput()"
    />
  </template>
</template>

<style scoped>
/* US-363: 单番搜索首页英雄区（Stage 47 几何基线）。
 * 容器 720px 居中；内容在内容区内垂直居中；间距/字号/控件高全部取冻结 Token。 */
.single-home-hero {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  width: min(100%, 720px);
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
  font-size: var(--type-display);
  font-weight: 700;
  line-height: 1.2;
}

.single-home-subtitle {
  margin: 0;
  color: var(--color-text-muted);
  font-size: var(--font-size-md);
  line-height: var(--line-height-body);
}

.single-home-hero > .anime-mode-switch {
  margin-top: var(--space-6);
}

.single-home-hero > .workbench-search-form {
  width: 100%;
  margin-top: var(--space-8);
}

.single-home-hero .search-control-row {
  align-items: end;
}

.single-home-hero #mikan-candidate-search-submit {
  flex: 0 0 auto;
  width: 176px;
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
  min-height: 64px;
  margin: var(--space-10) 0 0;
  text-align: center;
  list-style-position: inside;
}
.workbench-search-form,
.batch-parse-form,
.candidate-fallback-form {
  display: grid;
  gap: 0.75rem;
}

.workbench-search-form label,
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

.search-control-row {
  display: flex;
  align-items: end;
  gap: var(--space-3);
}

.search-field {
  display: grid;
  flex: 1 1 24rem;
  gap: var(--space-2);
  min-width: 0;
}

.search-control-row > button {
  flex: 0 0 auto;
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

.search-summary-actions {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--space-3);
}

.search-summary-label {
  color: var(--color-text-muted);
  font-size: var(--font-size-sm);
  font-weight: var(--font-weight-semibold);
}

.candidate-list-wrapper {
  display: grid;
  gap: 0.75rem;
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

.candidate-list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: grid;
  gap: 0.75rem;
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
  .search-control-row {
    align-items: stretch;
    flex-direction: column;
  }

  .search-control-row > button {
    width: 100%;
  }

  .detail-grid {
    grid-template-columns: 1fr;
    gap: 0.2rem;
  }
}
</style>
