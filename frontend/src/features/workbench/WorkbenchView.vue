<script setup lang="ts">
// 订阅方案工作台 (US-204).
//
// The workbench migrates the legacy `/index` single-search flow to the new
// frontend:
//
//   1. 单个搜索 — POST /api/v1/mikan/candidates, renders public candidate
//      cards (no auto-selection) with season-evidence confirmation/conflict
//      handling and the auditable title-parse summary;
//   2. 直连合集 fallback — optional checkbox reveals the direct MiKan
//      URL/ID form; both paths generate an unsaved server-authoritative draft
//      (save_request=false) through POST /api/v1/requests;
//   3. 订阅草案 preview — the returned draft_id + display snapshot render in
//      DraftPreviewPanel (editable preview-modify + one-shot preview-save).
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
  validateCandidateQuery,
  validateFallbackValue,
  type CandidateSearchResult,
  type MikanCandidate,
} from '@/features/workbench/candidateSearch'
import { displayValue } from '@/features/requests/requestDetail'
import type { RequestSnapshot } from '@/features/requests/requestDetail'
import { currentStorageDir, storageQuery } from '@/features/requests/requestStorage'

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
const selections = ref<Record<AnimeMode, { start: number; end: number }>>({
  single: { start: 0, end: 0 },
  batch: { start: 0, end: 0 },
})
const searchLoading = ref(false)
const searchError = ref('')
const searchResult = ref<CandidateSearchResult | null>(null)
const lastSearchQuery = ref('')

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
// Track per-candidate season confirmation in memory (never persisted).
const seasonConfirmations = ref<Record<string, number | null>>({})

const hasResults = computed(() => (searchResult.value?.candidates?.length ?? 0) > 0)

watch(query, (value) => {
  const normalized = value.trim()
  if (!searchResult.value || normalized === lastSearchQuery.value) return
  // A result belongs to the exact title that produced it. Keep the user's
  // edited input, but remove stale candidates and their one-time confirmations.
  searchResult.value = null
  lastSearchQuery.value = ''
  searchError.value = ''
  seasonConfirmations.value = {}
})

async function changeMode(nextMode: AnimeMode): Promise<void> {
  if (nextMode === mode.value || searchLoading.value || draftLoading.value) return
  const currentInput = mode.value === 'single' ? singleInput.value : batchInput.value
  if (currentInput) selections.value[mode.value] = currentInput.selection()
  mode.value = nextMode
  // A result belongs to the mode that produced it; never present it as the
  // result of the newly selected mode.
  searchResult.value = null
  searchError.value = ''
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
  if (searchLoading.value) return
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
  lastSearchQuery.value = query.value.trim()
  searchLoading.value = true
  try {
    const result = await api.post<CandidateSearchResult>('/api/v1/mikan/candidates', {
      body: { query: query.value.trim() },
    })
    searchResult.value = result
    const count = result.candidates?.length ?? 0
    if (count) {
      notification.success('候选搜索完成', `找到 ${count} 个候选合集。`)
    } else {
      notification.info('未找到候选合集', '可调整番剧标题后重试。')
    }
  } catch (error) {
    void error
    searchResult.value = null
    searchError.value = '候选搜索失败。请稍后重试。'
    notification.error('候选搜索失败', '候选搜索失败。请稍后重试。')
  } finally {
    searchLoading.value = false
    await nextTick()
    if (searchResult.value?.candidates?.length) {
      document.querySelector<HTMLElement>('#mikan-candidate-search-result .candidate-select')?.focus()
    }
  }
}

async function generateFromCandidate(candidate: MikanCandidate): Promise<void> {
  const payload = buildCandidateCreatePayload(candidate, {
    storageDir: currentStorageDir(),
    confirmedSeason: confirmedSeasonFor(candidate),
  })
  await generateDraft(payload)
}

async function generateFromFallback(): Promise<void> {
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
  const generated = await generateDraft(payload)
  if (generated) {
    fallbackValue.value = ''
  }
}

async function generateDraft(payload: Record<string, unknown>): Promise<boolean> {
  draftLoading.value = true
  try {
    const result = await api.post<CreateRequestResult>('/api/v1/requests', {
      body: { ...payload, storage_dir: storageQuery().storage_dir ?? null },
    })
    if (result?.draft_id && result?.request) {
      draftId.value = result.draft_id
      draftRequest.value = result.request as RequestSnapshot
      // US-211: keep the monotonic draft_revision in component memory only.
      draftRevision.value =
        typeof result.draft_revision === 'number' ? result.draft_revision : 1
      notification.success('预览已生成', '这是未保存的订阅草案；保存后可确认、修改或删除。')
      return true
    }
    notification.error('生成失败', '订阅草案生成失败，请重试。')
    return false
  } catch (error) {
    void error
    notification.error('生成失败', '从 MiKan 合集生成订阅草案失败。请重试。')
    return false
  } finally {
    draftLoading.value = false
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
  if (destination === 'input') {
    searchResult.value = null
    lastSearchQuery.value = ''
    searchError.value = ''
  }
  void nextTick(() => singleInput.value?.focus())
}

onMounted(() => {
  // The workbench has no persisted state; the storage profile comes from
  // Settings localStorage (relative only). Nothing to preload here.
  // The application shell keeps the skip link as the first keyboard stop on
  // a direct page load. Standalone mounts (including focused component tests)
  // still receive the convenient title-input focus.
  if (!document.getElementById('app-main')) {
    void nextTick(() => singleInput.value?.focus())
  }
})

defineExpose({ searchCandidates, generateFromCandidate, generateFromFallback })
</script>

<template>
  <h2 id="workbench-heading" class="workbench-title">订阅方案工作台</h2>

  <PanelSection title="创建订阅方案" class="workbench-panel">
    <!-- ── single search ──────────────────────────────────────────── -->
    <AnimeModeSwitch :model-value="mode" :disabled="searchLoading || draftLoading" @update:model-value="changeMode" />

    <form v-if="mode === 'single'" id="mikan-candidate-search-form" class="workbench-search-form" @submit.prevent="searchCandidates">
      <label for="mikan-candidate-query">番剧标题</label>
      <AnimeTitleInput
        ref="singleInput"
        id="mikan-candidate-query"
        v-model="query"
        mode="single"
        :disabled="searchLoading"
      />
      <p class="field-help" id="mikan-candidate-help">
        输入番剧标题，从真实 MiKan 搜索候选合集。候选不会自动选择，需手动点击「选择此合集」生成订阅草案。
      </p>
      <p v-if="searchError" id="mikan-candidate-search-error" class="field-error" role="alert">
        {{ searchError }}
      </p>
      <div class="notification-actions">
        <BaseButton id="mikan-candidate-search-submit" type="submit" variant="primary" :loading="searchLoading">
          搜索候选
        </BaseButton>
      </div>
    </form>

    <!-- ── direct fallback (single mode only) ────────────────────── -->
    <template v-if="mode === 'single'">
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
          :disabled="fallbackLoading"
        />
        <p class="field-help" id="mikan-fallback-help">
          仅接受数字 ID 或同源 HTTP(S) /Home/Bangumi/&lt;id&gt; URL；生成成功后清空。
        </p>
        <p v-if="fallbackError" id="mikan-fallback-error" class="field-error" role="alert">
          {{ fallbackError }}
        </p>
        <div class="notification-actions">
          <BaseButton id="mikan-fallback-generate" type="submit" variant="secondary" :loading="fallbackLoading">
            使用直连合集生成
          </BaseButton>
        </div>
      </form>
    </template>
  </PanelSection>

  <!-- ── search results ──────────────────────────────────────────── -->
  <PanelSection v-if="mode === 'single' && !draftRequest" title="搜索结果" class="search-results-panel">
    <div
      id="mikan-candidate-search-result"
      class="candidate-list-wrapper"
      aria-live="polite"
      aria-relevant="additions text"
    >
      <LoadingState v-if="searchLoading" :message="`正在搜索「${query}」的 MiKan 候选...`" />
      <ErrorState
        v-else-if="searchError && !searchResult"
        title="候选搜索失败"
        message="候选搜索失败。请稍后重试。"
        retry-label="重试"
        @retry="searchCandidates"
      />
      <EmptyState
        v-else-if="searchResult && !hasResults"
        message="未找到候选合集。可调整番剧标题后重试，或勾选「搜索无结果时使用直连合集」直接生成订阅草案。"
      />
      <template v-else-if="searchResult && hasResults">
        <p class="candidate-search-summary" role="status">
          已搜索「{{ searchResult.query }}」，请选择要审核的 MiKan 合集。
        </p>
        <section v-if="parseSummaryRows().length" class="title-parse-summary" aria-label="标题解析摘要">
          <h3 class="detail-section-heading">标题解析摘要</h3>
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
        </section>
        <CandidateCollectionList
          :candidates="searchResult.candidates"
          :query="searchResult.query"
          :disabled="searchLoading || draftLoading"
          :confirmed-seasons="seasonConfirmations"
          @select="generateFromCandidate"
          @update:confirmed-season="(bangumiId: string, season: number | null) => (seasonConfirmations = { ...seasonConfirmations, [bangumiId]: season })"
        />
      </template>
      <EmptyState v-else message="输入番剧标题后搜索候选合集。" />
    </div>
  </PanelSection>

  <!-- ── draft preview ───────────────────────────────────────────── -->
  <SingleAnimeReviewPanel
    v-if="mode === 'single' && draftRequest && draftId"
    :key="draftId"
    :request="draftRequest"
    :draft-id="draftId"
    :draft-revision="draftRevision"
    @changed="onDraftChanged"
    @discard="discardDraft"
  />
  <LoadingState v-if="mode === 'single' && draftLoading && !draftRequest" message="正在从候选生成订阅草案..." />

  <!-- ── batch workbench (US-205) ────────────────────────────────── -->
  <template v-if="mode === 'batch'">
    <label for="batch-raw-input">批量番剧名称</label>
    <AnimeTitleInput ref="batchInput" id="batch-raw-input" v-model="batchQuery" mode="batch" />
    <p class="field-help" id="batch-raw-input-help">每行一个番剧简称或不完整标题；系统会逐项解析并搜索候选合集，结果需人工审核。</p>
    <BatchWorkbenchView class="batch-workbench-section" v-model:raw-input="batchQuery" hide-input />
  </template>
</template>

<style scoped>
.workbench-search-form,
.candidate-fallback-form {
  display: grid;
  gap: 0.75rem;
}

.workbench-search-form label,
.candidate-fallback-form label {
  font-weight: 500;
  font-size: 0.875rem;
}

.workbench-title {
  margin: 0;
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
  .detail-grid {
    grid-template-columns: 1fr;
    gap: 0.2rem;
  }
}
</style>
