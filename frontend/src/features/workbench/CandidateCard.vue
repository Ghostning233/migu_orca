<script setup lang="ts">
// CandidateCard (US-204).
//
// One public MiKan candidate card in the workbench search results. It renders
// only the whitelisted public metadata (title, bangumi id, episode progress,
// recommendation label, source query, poster via the opaque poster endpoint)
// and the explicit "选择此合集" action. It never auto-selects a candidate and
// never renders raw URLs / candidate_context.
//
// Season evidence (US-204): a NEEDS_CONFIRMATION candidate shows the explicit
// confirmation checkbox (confirmedSeason bound by the parent); a CONFLICT
// candidate shows the warning and disables selection. The parser hint is only
// ever turned into evidence through the confirmation checkbox or the server's
// candidate_context — never through displayed fields.
import { computed } from 'vue'

import BaseButton from '@/components/forms/BaseButton.vue'

import {
  candidateSelectionIsBlocked,
  episodeProgressText,
  needsSeasonConfirmation,
  type MikanCandidate,
} from '@/features/workbench/candidateSearch'

const props = defineProps<{
  candidate: MikanCandidate
  query: string
  disabled?: boolean
  confirmedSeason: number | null
}>()

const emit = defineEmits<{
  (e: 'select'): void
  (e: 'update:confirmedSeason', season: number | null): void
}>()

const blocked = computed(() => candidateSelectionIsBlocked(props.candidate, props.confirmedSeason))
const needsConfirmation = computed(() => needsSeasonConfirmation(props.candidate))
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
  <li class="candidate-card">
    <strong class="candidate-title">{{ candidate.title || '未命名合集' }}</strong>

    <span v-if="candidate.recommendation" class="candidate-recommendation">
      {{ candidate.recommendation }}
    </span>

    <div class="candidate-meta">MiKan ID: {{ candidate.bangumi_id }}</div>
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

    <div class="candidate-source">搜索词：{{ candidate.source_query || query }}</div>

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

    <BaseButton
      class="candidate-select"
      variant="primary"
      :disabled="disabled || blocked"
      :aria-disabled="String(disabled || blocked)"
      @click="emit('select')"
    >
      选择此合集
    </BaseButton>
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

.candidate-meta,
.candidate-progress,
.candidate-source {
  font-size: 0.875rem;
  color: var(--color-text-muted);
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
</style>
