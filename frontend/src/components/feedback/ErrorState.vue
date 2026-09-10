<script setup lang="ts">
// Shared error-state primitive (US-199). Renders a sanitized Chinese error
// message with an optional retry action. `message` must already be safe to
// display (see api/client.ts — never raw bodies, URLs or credentials).
defineProps<{
  title?: string
  message: string
  retryLabel?: string
}>()

const emit = defineEmits<{
  (e: 'retry'): void
}>()
</script>

<template>
  <div class="error-state" role="alert">
    <p class="error-state-title">{{ title ?? '请求失败' }}</p>
    <p class="error-state-message">{{ message }}</p>
    <button v-if="retryLabel" type="button" class="secondary-button" @click="emit('retry')">
      {{ retryLabel }}
    </button>
  </div>
</template>

<style scoped>
.error-state {
  background: var(--color-feedback-error-surface);
  border: 1px solid var(--color-feedback-error-border);
  border-radius: var(--radius-md);
  color: var(--color-text);
  min-height: 120px;
  padding: var(--space-4);
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
  align-items: flex-start;
  justify-content: center;
}

.error-state-title {
  margin: 0;
  font-weight: 600;
  color: var(--color-feedback-error-text);
}

.error-state-message {
  margin: 0;
  color: var(--color-text-muted);
}
</style>
