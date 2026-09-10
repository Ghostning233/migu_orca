<script setup lang="ts">
// BatchCandidatePopover (US-205).
//
// The anchored candidate-choices popover for a FOUND batch card. It reuses
// the shared CandidateCard primitive (public whitelist, season-confirmation
// checkbox, conflict disable) so the batch flow never duplicates the
// single-search candidate logic. The popover is fixed-position with a
// role=dialog, an Escape/backdrop close and focus return to the trigger.
//
// Security boundary: only the strict public candidate whitelist is rendered
// (never raw URLs / candidate_context). The parent owns the in-memory
// season-confirmation state; nothing here is persisted or logged.
//
// US-207 keyboard accessibility: opening moves focus into the dialog (close
// button), Escape closes it and the parent restores focus to the trigger
// button. The dialog is `aria-modal="false"` (it does not block the rest of
// the page) so no focus trap is applied — matching the legacy popover.
import { onBeforeUnmount, onMounted, ref } from 'vue'

import CandidateCollectionList from '@/features/workbench/CandidateCollectionList.vue'
import type { BatchCandidate } from '@/features/workbench/batchWorkbench'

defineProps<{
  title: string
  candidates: BatchCandidate[]
  query: string
  disabled?: boolean
  confirmedSeasons: Record<string, number | null>
}>()

const emit = defineEmits<{
  (e: 'select', candidate: BatchCandidate): void
  (e: 'update:confirmedSeason', bangumiId: string, season: number | null): void
  (e: 'close'): void
}>()

const rootEl = ref<HTMLElement | null>(null)
const closeButton = ref<HTMLButtonElement | null>(null)

function onKeydown(event: KeyboardEvent): void {
  if (event.key === 'Escape') {
    event.stopPropagation()
    emit('close')
  }
}

onMounted(() => {
  // Initial focus moves into the dialog so keyboard users land inside the
  // candidate list rather than tabbing through the page behind it.
  closeButton.value?.focus()
  rootEl.value?.addEventListener('keydown', onKeydown)
})

onBeforeUnmount(() => {
  rootEl.value?.removeEventListener('keydown', onKeydown)
})

defineExpose({ focusClose: () => closeButton.value?.focus() })
</script>

<template>
  <div
    id="batch-candidate-choices"
    ref="rootEl"
    class="batch-candidate-choices"
    role="dialog"
    aria-modal="false"
    aria-labelledby="batch-candidate-choices-title"
  >
    <h3 id="batch-candidate-choices-title">候选合集：{{ title }}</h3>
    <button
      ref="closeButton"
      type="button"
      class="icon-button batch-candidate-close"
      aria-label="关闭候选合集"
      @click="emit('close')"
    >
      ×
    </button>
    <p class="field-help">请选择一个真实 MiKan 合集后生成订阅草案。</p>
    <CandidateCollectionList
      class="batch-candidate-list"
      :candidates="candidates"
      :query="query"
      :disabled="disabled"
      :confirmed-seasons="confirmedSeasons"
      @select="emit('select', $event)"
      @update:confirmed-season="(bangumiId: string, season: number | null) => emit('update:confirmedSeason', bangumiId, season)"
    />
  </div>
</template>

<style scoped>
.batch-candidate-choices {
  background: var(--color-bg);
  border: 1px solid var(--color-border);
  border-radius: 6px;
  display: grid;
  gap: 0.625rem;
  left: 12px;
  max-height: calc(100vh - 24px);
  overflow: auto;
  padding: 14px;
  position: fixed;
  top: 12px;
  width: min(760px, calc(100vw - 24px));
  z-index: 20;
}

.batch-candidate-choices h3 {
  font-size: 0.98rem;
  margin: 0;
  padding-right: 32px;
}

.batch-candidate-close {
  min-height: 30px;
  min-width: 30px;
  position: absolute;
  right: 8px;
  top: 8px;
}

.batch-candidate-choices .field-help {
  margin: 0;
}

.batch-candidate-list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
  gap: 0.75rem;
}
</style>
