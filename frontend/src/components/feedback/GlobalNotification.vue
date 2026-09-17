<script setup lang="ts">
// Global notification toast (US-199, Stage 42 / US-346).
//
// One floating `aria-live` toast for non-critical success/info/error
// summaries. It is `position: fixed`, so it never joins the `main` document
// flow and never shifts the page under the user. It is deliberately not a
// carrier for anything actionable: field validation, candidate/draft/batch
// failures, their retry entries and save-confirm blocks all stay next to their
// own controls, and this toast only adds a short summary on top of them.
//
// The floating layer is click-through (`pointer-events: none`) so a toast can
// never swallow a click aimed at a page control it happens to cover; the close
// button opts back in. Nothing here moves focus, and messages arrive already
// sanitized by the caller (api/client.ts + notification store): no endpoints,
// tokens, cookies, raw bodies, absolute paths or full Requests.
import { storeToRefs } from 'pinia'
import { computed, onBeforeUnmount } from 'vue'

import { useNotificationStore } from '@/app/stores/notification'

const notificationStore = useNotificationStore()
const { current } = storeToRefs(notificationStore)

// Fail closed outside the two polite kinds: an unexpected kind is announced
// assertively instead of being silently downgraded to a status message.
const isPolite = computed(
  () => current.value?.kind === 'success' || current.value?.kind === 'info',
)

// The store owns the auto-close timers; unmounting has to take the pending one
// with it so it cannot outlive the toast and mutate the shell afterwards.
onBeforeUnmount(() => {
  notificationStore.clear()
})
</script>

<template>
  <div
    v-if="current"
    class="global-notification"
    :class="`global-notification-${current.kind}`"
    :role="isPolite ? 'status' : 'alert'"
    :aria-live="isPolite ? 'polite' : 'assertive'"
    aria-atomic="true"
  >
    <div class="global-notification-copy">
      <strong class="global-notification-title">{{ current.title }}</strong>
      <p v-if="current.message" class="global-notification-message">
        {{ current.message }}
      </p>
    </div>
    <button
      type="button"
      class="secondary-button global-notification-close"
      @click="notificationStore.clear()"
    >
      关闭
    </button>
  </div>
</template>

<style scoped>
/* Anchored to the viewport (not the main flow) under the shell header, in the
   corner opposite the batch toolbar's fixed save/confirm actions. */
.global-notification {
  position: fixed;
  top: calc(var(--size-shell-header) + var(--space-4));
  right: var(--space-5);
  z-index: var(--z-overlay);
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: var(--space-4);
  max-width: min(30rem, calc(100vw - var(--space-5) * 2));
  border-radius: var(--radius-md);
  padding: var(--space-3) var(--space-4);
  box-shadow: var(--shadow-shell);
  pointer-events: none;
}

.global-notification-close {
  flex-shrink: 0;
  pointer-events: auto;
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
</style>
