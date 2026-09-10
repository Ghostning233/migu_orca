<script setup lang="ts">
// Shared empty-state primitive (US-199). Features pass a safe Chinese
// message; the component renders a consistent, accessible empty panel.
defineProps<{
  message: string
}>()
</script>

<template>
  <div class="empty-state" role="status">
    <p class="empty-state-message">{{ message }}</p>
  </div>
</template>

<style scoped>
.empty-state {
  background: var(--color-surface-subtle);
  border: 1px dashed var(--color-border-subtle);
  border-radius: var(--radius-md);
  color: var(--color-text-muted);
  min-height: 120px;
  padding: var(--space-4);
  display: flex;
  align-items: center;
  justify-content: center;
}

.empty-state-message {
  margin: 0;
}
</style>
