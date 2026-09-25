<script setup lang="ts">
// CandidateCard (US-204 / WP-41-D；#142 卡片几何与状态稳定).
//
// One public MiKan candidate card in the workbench search results. The default
// layer shows only the public decision evidence: poster, title, season
// evidence, total episodes and the explicit "选择此合集" action. #142 removed
// the 高级信息 entry: the collection id and the parse query are diagnostics
// that stay in the page-level 搜索诊断 (`details.title-parse-summary`), so a
// card never carries a control with no current decision value and no
// replacement popover. It never auto-selects a candidate and never renders raw
// URLs / candidate_context.
//
// Season evidence (US-204): a NEEDS_CONFIRMATION candidate shows the explicit
// confirmation checkbox (confirmedSeason bound by the parent); a CONFLICT
// candidate shows the warning and disables selection. The parser hint is only
// ever turned into evidence through the confirmation checkbox or the server's
// candidate_context — never through displayed fields.
//
// Loading (US-343): `loading` marks this candidate as the one generating a
// draft. The state is carried by the button label plus `aria-busy` (the parent
// passes `loading` only for the clicked candidate, so the others stay disabled
// without being marked as loading). `error` keeps a sanitized generation
// failure beside this candidate and re-offers the action as a retry.
//
// Geometry (#142): the feedback area keeps a reserved height so short states
// (season confirmation / generating / failure) replace empty space instead of
// stretching the neighbouring card or moving the content below; the primary
// action is bottom-aligned so a 1～4 card row lines up its buttons.
import { computed, ref } from 'vue'

import BaseButton from '@/components/forms/BaseButton.vue'

import {
  candidateSelectionIsBlocked,
  episodeProgressText,
  needsSeasonConfirmation,
  seasonEvidenceText,
  type MikanCandidate,
} from '@/features/workbench/candidateSearch'

const props = withDefaults(defineProps<{
  candidate: MikanCandidate
  query: string
  /** 批量工作台右栏的横向合集候选卡布局（#144）。 */
  batchLayout?: boolean
  disabled?: boolean
  confirmedSeason: number | null
  loading?: boolean
  error?: string
}>(), {
  disabled: false,
  batchLayout: false,
  loading: false,
  error: '',
})

const emit = defineEmits<{
  (e: 'select'): void
  (e: 'update:confirmedSeason', season: number | null): void
}>()

const blocked = computed(() => candidateSelectionIsBlocked(props.candidate, props.confirmedSeason))
const needsConfirmation = computed(() => needsSeasonConfirmation(props.candidate))
const errorId = computed(() => `candidate-generate-error-${props.candidate.bangumi_id}`)
const seasonNumber = computed(() => {
  const season = props.candidate.season_evidence?.season
  return Number.isInteger(season) && season !== null ? Number(season) : null
})

function onSeasonChange(event: Event): void {
  const checked = (event.target as HTMLInputElement).checked
  const season = seasonNumber.value
  emit('update:confirmedSeason', checked && season !== null && season >= 1 && season <= 99 ? season : null)
}

const posterSrc = computed(() => {
  // The poster_url is a same-origin opaque key path served by the poster
  // endpoint (never a credential); fall back to the placeholder on error.
  const url = props.candidate.poster_url
  return url && /^\/api\/v1\/mikan\/posters\//.test(url) ? url : null
})
const posterFailed = ref(false)
const showPoster = computed(() => posterSrc.value !== null && !posterFailed.value)
const candidateTitle = computed(() => props.candidate.title || '未命名合集')

function onPosterError(): void {
  posterFailed.value = true
}
</script>

<template>
  <li class="candidate-card" :class="{ 'is-generating': loading, 'is-batch': batchLayout }">
    <div class="candidate-card-poster">
      <img
        v-if="showPoster"
        class="candidate-poster"
        :src="posterSrc ?? undefined"
        alt=""
        loading="lazy"
        decoding="async"
        @error="onPosterError"
      >
      <div v-else class="candidate-poster candidate-poster-placeholder">暂无封面</div>
    </div>

    <div class="candidate-card-content">
      <div class="candidate-card-info">
        <strong class="candidate-title" :title="candidateTitle">{{ candidateTitle }}</strong>

        <span v-if="candidate.recommendation" class="candidate-recommendation">
          {{ candidate.recommendation }}
        </span>

        <div class="candidate-card-facts">
          <div class="candidate-progress">{{ episodeProgressText(candidate.total_episodes) }}</div>
          <p v-if="candidate.season_evidence?.status === 'CONFLICT'" class="candidate-season-conflict">
            候选合集季数与搜索识别结果冲突，请先人工核对。
          </p>
          <p v-else class="candidate-season-evidence">{{ seasonEvidenceText(candidate) }}</p>
        </div>
      </div>

      <!-- 预留短反馈区：季数核对、生成中与生成失败在这里就地替换，常规桌面
           不会因此拉长邻卡、推动下方内容或让主按钮跳位。 -->
      <div class="candidate-card-feedback">
        <label
          v-if="needsConfirmation && seasonNumber !== null"
          class="candidate-season-confirmation"
        >
          <input
            type="checkbox"
            class="base-checkbox"
            :checked="confirmedSeason === seasonNumber"
            :aria-describedby="`candidate-season-confirmation-help-${candidate.bangumi_id}`"
            @change="onSeasonChange"
          >
          <span :id="`candidate-season-confirmation-help-${candidate.bangumi_id}`">
            我确认此合集为第{{ seasonNumber }}季（候选标题未提供季数证据）
          </span>
        </label>
        <p v-if="loading" class="candidate-generating-status" role="status">
          正在生成订阅草案…
        </p>
        <p v-else-if="error" :id="errorId" class="candidate-generate-error" role="alert">
          {{ error }}
        </p>
      </div>

      <BaseButton
        class="candidate-select"
        variant="primary"
        :disabled="disabled || blocked"
        :loading="loading"
        loading-label="正在生成草案…"
        :aria-disabled="String(disabled || blocked || loading)"
        :aria-label="`${error ? '重试生成草案' : '选择此合集'}：${candidateTitle}`"
        :aria-describedby="error ? errorId : undefined"
        @click="emit('select')"
      >
        {{ error ? '重试生成草案' : '选择此合集' }}
      </BaseButton>
    </div>
  </li>
</template>

<style scoped>
.candidate-card {
  position: relative;
  /* #142：单番候选是竖排卡片（封面在上、信息与主操作在下），1～4 项同排居中。 */
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
  min-width: 0;
  height: auto;
  border: 1px solid var(--color-border);
  border-radius: var(--radius-lg);
  /* The 1px border is included in the 16px baseline inset. */
  padding: calc(var(--space-4) - var(--control-border-width));
  background: var(--color-surface);
  box-shadow: var(--shadow-card);
}

.candidate-card-poster,
.candidate-poster {
  width: 100%;
  /* 单番候选封面按设计图的横向比例；具体高度由宽度和比例决定。 */
  aspect-ratio: 16 / 9;
}

.candidate-poster {
  display: block;
  flex: 0 0 auto;
  object-fit: cover;
  border-radius: var(--radius-md);
}

.candidate-card-content {
  min-width: 0;
  display: flex;
  flex: 1 1 auto;
  flex-direction: column;
  align-items: stretch;
  gap: var(--space-2);
}

.candidate-card-info {
  display: flex;
  flex-direction: column;
  align-items: stretch;
  gap: var(--space-2);
  min-width: 0;
}

.candidate-title {
  display: -webkit-box;
  min-height: calc(var(--type-card-title) * 1.4);
  overflow: hidden;
  font-size: var(--type-card-title);
  font-weight: var(--font-weight-semibold);
  line-height: 1.4;
  -webkit-box-orient: vertical;
  -webkit-line-clamp: 2;
  overflow-wrap: anywhere;
}

.candidate-recommendation {
  align-self: flex-start;
  background: var(--color-bg-muted);
  border: 1px solid var(--color-border);
  border-radius: 999px;
  padding: 0.125rem 0.5rem;
  font-size: 0.8125rem;
  color: var(--color-text-muted);
}

.candidate-card-facts {
  display: grid;
  gap: 0.125rem;
}

.candidate-season-evidence,
.candidate-season-conflict {
  margin: 0;
  font-size: var(--type-label);
  line-height: 1.5;
  color: var(--color-text-muted);
  overflow-wrap: anywhere;
}

.candidate-season-conflict {
  color: var(--color-danger);
}

.candidate-progress {
  color: var(--color-text-muted);
  font-size: var(--type-caption);
  line-height: 1.5;
  overflow-wrap: anywhere;
}

/* 预留短反馈高度（两行 14px/1.5）：季数核对、生成中与失败都落在这里。 */
.candidate-card-feedback {
  display: grid;
  gap: 0.25rem;
  min-height: calc(var(--type-label) * 1.5 * 2);
}

.candidate-poster-placeholder {
  display: flex;
  align-items: center;
  justify-content: center;
  border: 1px dashed var(--color-border);
  color: var(--color-text-muted);
  font-size: 0.8125rem;
}

.candidate-season-confirmation {
  display: flex;
  align-items: flex-start;
  gap: 0.4rem;
  font-size: var(--type-label);
  line-height: 1.5;
}

.candidate-select {
  width: 100%;
  max-width: 100%;
  margin-top: auto;
}

/* 批量工作台右栏（Issue 144）：一行一张横向合集候选卡——较大的横向封面在左、
   判断信息在中、「选择此合集」在右。它不是左栏「批量条目卡」的紧凑尺寸。 */
.candidate-card.is-batch {
  display: grid;
  grid-template-columns: minmax(120px, 28%) minmax(0, 1fr) auto;
  align-items: center;
  gap: var(--space-4);
  padding: var(--space-3) var(--space-4);
  border-radius: var(--radius-md);
}

.candidate-card.is-batch .candidate-poster,
.candidate-card.is-batch .candidate-poster-placeholder {
  width: 100%;
  height: auto;
  aspect-ratio: 16 / 9;
  border-radius: var(--radius-md);
}

.candidate-card.is-batch .candidate-card-content {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  grid-template-areas:
    'info action'
    'feedback action';
  align-items: center;
  gap: 0.25rem var(--space-4);
}

.candidate-card.is-batch .candidate-card-info {
  grid-area: info;
  gap: 0.25rem;
}

.candidate-card.is-batch .candidate-title {
  min-height: 0;
  font-size: var(--type-card-title);
  -webkit-line-clamp: 2;
}

.candidate-card.is-batch .candidate-card-facts {
  grid-area: auto;
}

.candidate-card.is-batch .candidate-card-feedback {
  grid-area: feedback;
  min-height: 0;
}

.candidate-card.is-batch .candidate-select {
  grid-area: action;
  width: auto;
  margin-top: 0;
  align-self: center;
}

.candidate-card.is-batch .candidate-generating-status,
.candidate-card.is-batch .candidate-generate-error {
  margin: 0;
}

.candidate-generating-status,
.candidate-generate-error {
  margin: 0;
  font-size: var(--type-label);
  line-height: 1.5;
}

.candidate-generating-status {
  color: var(--color-text-muted);
}

.candidate-generate-error {
  color: var(--color-danger);
}

.candidate-card.is-generating {
  border-color: var(--color-action-primary);
}
</style>
