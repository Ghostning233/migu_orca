<script setup lang="ts">
// Shared loading-state primitive (US-199). Renders a non-jarring loading
// indicator with an aria-busy region; respects reduced-motion via CSS.
defineProps<{
  message: string
}>()
</script>

<template>
  <div class="loading-state" role="status" aria-live="polite" aria-busy="true">
    <span class="loading-spinner" aria-hidden="true"></span>
    <span class="loading-message">{{ message }}</span>
  </div>
</template>

<style scoped>
.loading-state {
  display: flex;
  align-items: center;
  gap: 0.75rem;
  background: var(--color-bg-muted);
  border: 1px solid var(--color-border);
  border-radius: 6px;
  color: var(--color-text-muted);
  min-height: 120px;
  padding: 16px;
  justify-content: center;
}

.loading-spinner {
  width: 1rem;
  height: 1rem;
  border: 2px solid var(--color-border);
  border-top-color: var(--color-accent);
  border-radius: 50%;
  animation: loading-spin 0.8s linear infinite;
}

.loading-message {
  margin: 0;
}

@keyframes loading-spin {
  to {
    transform: rotate(360deg);
  }
}

@media (prefers-reduced-motion: reduce) {
  .loading-spinner {
    animation: none;
  }
}
</style>
