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
    aria-live="polite"
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
  gap: 1rem;
  border-radius: 8px;
  padding: 0.875rem 1rem;
  margin: 0 auto 1rem;
  max-width: 1180px;
}

.global-notification-success {
  background: #edf8f0;
  border: 1px solid #abd3b6;
  color: #1f5f34;
}

.global-notification-error {
  background: #fff3f1;
  border: 1px solid #e3bbb4;
  color: #8d2f20;
}

.global-notification-info {
  background: var(--color-bg-muted);
  border: 1px solid var(--color-border);
  color: var(--color-text);
}

.global-notification-copy {
  display: grid;
  gap: 0.25rem;
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
