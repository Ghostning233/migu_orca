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
  gap: var(--space-3);
  background: var(--color-surface-subtle);
  border: 1px solid var(--color-border-subtle);
  border-radius: var(--radius-md);
  color: var(--color-text-muted);
  min-height: 120px;
  padding: var(--space-4);
  justify-content: center;
}

.loading-spinner {
  width: var(--space-4);
  height: var(--space-4);
  border: 2px solid var(--color-border-subtle);
  border-top-color: var(--color-action-primary);
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
