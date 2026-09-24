<script setup lang="ts">
// Shared candidate collection renderer (US-268).
//
// This component owns the display/selection boundary for both workbenches.
// CandidateCard receives only the public candidate whitelist; opaque
// candidate_context remains in the parent component and is never rendered.
//
// Loading (US-343): `loadingCandidateId` names the single candidate currently
// generating a draft. Only that card is marked as loading; the other cards are
// disabled for the duration (one generation at a time) but keep their idle
// label. `candidateErrors` maps a bangumi id to its sanitized generation
// failure so the message stays beside the candidate that failed.
import CandidateCard from '@/features/workbench/CandidateCard.vue'
import type { MikanCandidate } from '@/features/workbench/candidateSearch'

const props = withDefaults(defineProps<{
  candidates: MikanCandidate[]
  query: string
  disabled?: boolean
  confirmedSeasons?: Record<string, number | null>
  loadingCandidateId?: string | null
  candidateErrors?: Record<string, string>
  compact?: boolean
}>(), {
  disabled: false,
  confirmedSeasons: () => ({}),
  loadingCandidateId: null,
  candidateErrors: () => ({}),
  compact: false,
})

/** True when this candidate owns the in-flight generation. */
function candidateIsLoading(bangumiId: string): boolean {
  return props.loadingCandidateId !== null && props.loadingCandidateId === bangumiId
}

/** A candidate other than the loading one is suspended, not loading. */
function candidateIsSuspended(bangumiId: string): boolean {
  return props.loadingCandidateId !== null && props.loadingCandidateId !== bangumiId
}

const emit = defineEmits<{
  (e: 'select', candidate: MikanCandidate): void
  (e: 'update:confirmedSeason', bangumiId: string, season: number | null): void
}>()
</script>

<template>
  <ul class="candidate-list candidate-collection-list" :class="{ 'is-compact': compact }" aria-label="MiKan 候选合集">
    <CandidateCard
      v-for="candidate in candidates"
      :key="candidate.bangumi_id"
      :candidate="candidate"
      :query="query"
      :compact="compact"
      :disabled="disabled || candidateIsSuspended(candidate.bangumi_id)"
      :loading="candidateIsLoading(candidate.bangumi_id)"
      :error="candidateErrors[candidate.bangumi_id] ?? ''"
      :confirmed-season="confirmedSeasons[candidate.bangumi_id] ?? null"
      @select="emit('select', candidate)"
      @update:confirmed-season="(season: number | null) => emit('update:confirmedSeason', candidate.bangumi_id, season)"
    />
  </ul>
</template>

<style scoped>
/* Issue 110：单番候选 1～4 项始终同排居中，卡片同宽且不随数量拉伸。
 * 宽度取自 1440 标准档内容宽（1440 − 2×32 = 1376）减去 3 个 --space-4 间距
 * 后四等分：(1376 − 48) / 4 = 332px。数量更少时保持 332px 居中。
 * 窄于该行所需宽度时允许收缩，200% 缩放等极窄视口允许换行。 */
.candidate-list {
  --candidate-card-width: 332px;
  display: flex;
  flex-wrap: wrap;
  justify-content: center;
  align-items: stretch;
  gap: var(--space-4);
  list-style: none;
  margin: 0;
  padding: 0;
}

.candidate-list:not(.is-compact) > .candidate-card {
  flex: 0 1 var(--candidate-card-width);
  min-width: 240px;
}

.candidate-list.is-compact {
  display: grid;
  grid-template-columns: 1fr;
  gap: var(--space-2);
}
</style>
