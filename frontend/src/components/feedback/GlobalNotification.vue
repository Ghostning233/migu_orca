<script setup lang="ts">
// Global notification region (US-199).
//
// A single `aria-live` container in the shell: success/info use role=status
// (polite), errors use role=alert. Messages are pre-sanitized by the caller
// (api/client.ts + notification store) and never contain sensitive values.
import { storeToRefs } from 'pinia'
import { computed } from 'vue'

import { useNotificationStore } from '@/app/stores/notification'

const notificationStore = useNotificationStore()
const { current } = storeToRefs(notificationStore)

const role = computed(() => (current.value?.kind === 'error' ? 'alert' : 'status'))
</script>

<template>
  <div
    v-if="current"
    class="global-notification"
    :class="`global-notification-${current.kind}`"
    :role="role"
    :aria-live="current.kind === 'error' ? 'assertive' : 'polite'"
    aria-atomic="true"
  >
    <div class="global-notification-copy">
      <strong class="global-notification-title">{{ current.title }}</strong>
      <p v-if="current.message" class="global-notification-message">
        {{ current.message }}
      </p>
    </div>
    <button type="button" class="secondary-button global-notification-close" @click="notificationStore.clear()">
      关闭
    </button>
  </div>
</template>

<style scoped>
.global-notification {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: var(--space-4);
  border-radius: var(--radius-md);
  padding: var(--space-3) var(--space-4);
  margin: 0 auto var(--space-4);
  max-width: 1180px;
}

.global-notification-success {
  background: var(--color-feedback-success-surface);
  border: 1px solid var(--color-feedback-success-border);
  color: var(--color-feedback-success-text);
}

.global-notification-error {
  background: var(--color-feedback-error-surface);
  border: 1px solid var(--color-feedback-error-border);
  color: var(--color-feedback-error-text);
}

.global-notification-info {
  background: var(--color-bg-muted);
  border: 1px solid var(--color-border-subtle);
  color: var(--color-text-primary);
}

.global-notification-copy {
  display: grid;
  gap: var(--space-1);
}

.global-notification-title {
  font-weight: 600;
}

.global-notification-message {
  margin: 0;
}

.global-notification-close {
  flex-shrink: 0;
}
</style>
