<script setup lang="ts">
// CandidateCard (US-204 / WP-41-D).
//
// One public MiKan candidate card in the workbench search results. The default
// layer (F4) shows only the public decision evidence: poster, title,
// recommendation label, episode progress, season evidence and the explicit
// "选择此合集" action. The opaque collection id and the parse search query are
// diagnostics, so they live behind the collapsed 高级信息 details. It never
// auto-selects a candidate and never renders raw URLs / candidate_context.
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
import { computed } from 'vue'

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
  disabled?: boolean
  confirmedSeason: number | null
  loading?: boolean
  error?: string
}>(), {
  disabled: false,
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
</script>

<template>
  <li class="candidate-card" :class="{ 'is-generating': loading }">
    <strong class="candidate-title">{{ candidate.title || '未命名合集' }}</strong>

    <span v-if="candidate.recommendation" class="candidate-recommendation">
      {{ candidate.recommendation }}
    </span>

    <div class="candidate-progress">{{ episodeProgressText(candidate.total_episodes) }}</div>

    <img
      v-if="posterSrc"
      class="candidate-poster"
      :src="posterSrc"
      alt=""
      loading="lazy"
      decoding="async"
    >
    <div v-else class="candidate-poster candidate-poster-placeholder">暂无封面</div>

    <template v-if="needsConfirmation && seasonNumber !== null">
      <label class="candidate-season-confirmation">
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
    </template>
    <p v-else-if="candidate.season_evidence?.status === 'CONFLICT'" class="candidate-season-conflict">
      候选合集季数与搜索识别结果冲突，请先人工核对。
    </p>
    <p v-else class="candidate-season-evidence">{{ seasonEvidenceText(candidate) }}</p>

    <BaseButton
      class="candidate-select"
      variant="primary"
      :disabled="disabled || blocked"
      :loading="loading"
      loading-label="正在生成草案…"
      :aria-disabled="String(disabled || blocked || loading)"
      :aria-describedby="error ? errorId : undefined"
      @click="emit('select')"
    >
      {{ error ? '重试生成草案' : '选择此合集' }}
    </BaseButton>

    <p v-if="loading" class="candidate-generating-status" role="status">
      正在生成订阅草案…
    </p>
    <p v-else-if="error" :id="errorId" class="candidate-generate-error" role="alert">
      {{ error }}
    </p>

    <!-- F4: 公开封面对应的技术编号与解析搜索词属于诊断信息，默认层不显示；
         需要核对时按需展开。 -->
    <details class="candidate-advanced">
      <summary>高级信息</summary>
      <dl class="candidate-advanced-grid">
        <div class="candidate-advanced-row"><dt>合集编号</dt><dd>{{ candidate.bangumi_id }}</dd></div>
        <div class="candidate-advanced-row"><dt>匹配搜索词</dt><dd>{{ candidate.source_query || query }}</dd></div>
      </dl>
    </details>
  </li>
</template>

<style scoped>
.candidate-card {
  display: grid;
  gap: 0.35rem;
  border: 1px solid var(--color-border);
  border-radius: 6px;
  padding: 0.75rem;
  background: var(--color-bg);
}

.candidate-title {
  font-weight: 600;
}

.candidate-recommendation {
  justify-self: start;
  background: var(--color-bg-muted);
  border: 1px solid var(--color-border);
  border-radius: 999px;
  padding: 0.125rem 0.5rem;
  font-size: 0.8125rem;
  color: var(--color-text-muted);
}

.candidate-progress,
.candidate-season-evidence {
  font-size: 0.875rem;
  color: var(--color-text-muted);
}

.candidate-advanced {
  border-top: 1px solid var(--color-border);
  padding-top: 0.35rem;
  font-size: 0.875rem;
}

.candidate-advanced summary {
  cursor: pointer;
  color: var(--color-text-muted);
}

.candidate-advanced-grid {
  margin: 0.35rem 0 0;
  display: grid;
  gap: 0.2rem 1rem;
  grid-template-columns: max-content 1fr;
}

.candidate-advanced-row {
  display: contents;
}

.candidate-advanced-row dt {
  font-weight: 600;
  color: var(--color-text-muted);
}

.candidate-advanced-row dd {
  margin: 0;
  overflow-wrap: anywhere;
}

.candidate-poster {
  max-width: 8rem;
  border-radius: 4px;
}

.candidate-poster-placeholder {
  display: flex;
  align-items: center;
  justify-content: center;
  min-height: 6rem;
  border: 1px dashed var(--color-border);
  color: var(--color-text-muted);
  font-size: 0.8125rem;
}

.candidate-season-confirmation {
  display: flex;
  align-items: flex-start;
  gap: 0.4rem;
  font-size: 0.875rem;
}

.candidate-season-conflict {
  margin: 0;
  color: var(--color-danger);
  font-size: 0.875rem;
}

.candidate-select {
  justify-self: start;
}

.candidate-generating-status,
.candidate-generate-error {
  margin: 0;
  font-size: 0.875rem;
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
