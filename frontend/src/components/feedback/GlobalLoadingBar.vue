<script setup lang="ts">
// Global loading indicator (US-199).
//
// Driven by the loading store's in-flight counter; shows a slim progress bar
// at the top of the shell while any API request is pending. `aria-hidden`
// since the status is announced by the region/feature-level loading states.
import { storeToRefs } from 'pinia'

import { useLoadingStore } from '@/app/stores/loading'

const loadingStore = useLoadingStore()
const { isLoading } = storeToRefs(loadingStore)
</script>

<template>
  <div v-if="isLoading" class="global-loading-bar" role="status" aria-live="polite">
    正在加载…
  </div>
</template>

<style scoped>
.global-loading-bar {
  position: sticky;
  top: 0;
  z-index: 40;
  padding: 0.25rem 1.25rem;
  background: var(--color-accent);
  color: #ffffff;
  font-size: 0.8125rem;
  text-align: center;
}

@media (prefers-reduced-motion: reduce) {
  .global-loading-bar {
    animation: none;
  }
}
</style>
