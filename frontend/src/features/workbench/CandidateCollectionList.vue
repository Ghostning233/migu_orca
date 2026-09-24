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
  /** 批量工作台右栏的横向合集候选卡布局（Issue 144）。 */
  batchLayout?: boolean
}>(), {
  disabled: false,
  confirmedSeasons: () => ({}),
  loadingCandidateId: null,
  candidateErrors: () => ({}),
  batchLayout: false,
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
  <ul class="candidate-list candidate-collection-list" :class="{ 'is-batch': batchLayout }" aria-label="MiKan 候选合集">
    <CandidateCard
      v-for="candidate in candidates"
      :key="candidate.bangumi_id"
      :candidate="candidate"
      :query="query"
      :batch-layout="batchLayout"
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
/* #142：单番候选 1～4 项同排居中，卡片同宽、随可用宽度协调变化。
 *
 * 卡宽不再是产品硬要求（旧 332px 只是 #110 在 1440 的实现值）：每张卡占行宽的
 * 四分之一并留 1px 余量，避免亚像素舍入把第四张挤到第二行；数量更少时整行居中。
 * 容器查询以候选区的真实可用宽度判定：装不下四列就直接两列，再窄变单列，
 * 绝不出现 3+1，也不横向溢出。 */
.candidate-list {
  display: flex;
  flex-wrap: wrap;
  justify-content: center;
  align-items: stretch;
  gap: var(--space-4);
  list-style: none;
  margin: 0;
  padding: 0;
}

.candidate-list:not(.is-batch) > .candidate-card {
  flex: 0 1 calc((100% - 3 * var(--space-4)) / 4 - 1px);
  min-width: 0;
}

@container (max-width: 1000px) {
  .candidate-list:not(.is-batch) > .candidate-card {
    flex-basis: calc((100% - var(--space-4)) / 2 - 1px);
  }
}

@container (max-width: 560px) {
  .candidate-list:not(.is-batch) > .candidate-card {
    flex-basis: 100%;
  }
}

/* 批量工作台右栏（#144）：一行一张横向合集候选卡，栏内滚动。 */
.candidate-list.is-batch {
  display: grid;
  grid-template-columns: 1fr;
  gap: var(--space-3);
}
</style>
