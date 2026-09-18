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
  <ul class="candidate-list" :class="{ 'is-compact': compact }" aria-label="MiKan 候选合集">
    <CandidateCard
      v-for="candidate in candidates"
      :key="candidate.bangumi_id"
      :candidate="candidate"
      :query="query"
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
.candidate-list {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(min(100%, 17rem), 1fr));
  gap: 0.75rem;
  list-style: none;
  margin: 0;
  padding: 0;
}

.candidate-list.is-compact {
  grid-template-columns: 1fr;
  gap: 0.5rem;
}
</style>
