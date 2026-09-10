<script setup lang="ts">
// Shared candidate collection renderer (US-268).
//
// This component owns the display/selection boundary for both workbenches.
// CandidateCard receives only the public candidate whitelist; opaque
// candidate_context remains in the parent component and is never rendered.
import CandidateCard from '@/features/workbench/CandidateCard.vue'
import type { MikanCandidate } from '@/features/workbench/candidateSearch'

withDefaults(defineProps<{
  candidates: MikanCandidate[]
  query: string
  disabled?: boolean
  confirmedSeasons?: Record<string, number | null>
}>(), {
  disabled: false,
  confirmedSeasons: () => ({}),
})

const emit = defineEmits<{
  (e: 'select', candidate: MikanCandidate): void
  (e: 'update:confirmedSeason', bangumiId: string, season: number | null): void
}>()
</script>

<template>
  <ul class="candidate-list" aria-label="MiKan 候选合集">
    <CandidateCard
      v-for="candidate in candidates"
      :key="candidate.bangumi_id"
      :candidate="candidate"
      :query="query"
      :disabled="disabled"
      :confirmed-season="confirmedSeasons[candidate.bangumi_id] ?? null"
      @select="emit('select', candidate)"
      @update:confirmed-season="(season: number | null) => emit('update:confirmedSeason', candidate.bangumi_id, season)"
    />
  </ul>
</template>
