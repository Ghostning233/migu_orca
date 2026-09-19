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
import { computed, onBeforeUnmount, watch } from 'vue'

import { useNotificationStore } from '@/app/stores/notification'

const notificationStore = useNotificationStore()
const { current } = storeToRefs(notificationStore)

// Fail closed outside the two polite kinds: an unexpected kind is announced
// assertively instead of being silently downgraded to a status message.
const isPolite = computed(
  () => current.value?.kind === 'success' || current.value?.kind === 'info',
)

type ToastViewport = { x: number; y: number }
type ToastEnvironment = {
  viewport: ToastViewport
  scrollBehavior: string
  htmlOverflowAnchor: string
  bodyOverflowAnchor: string
  scrollRestoration: ScrollRestoration
}

let toastEnvironment: ToastEnvironment | null = null

function captureToastEnvironment(): void {
  if (toastEnvironment) return
  const htmlStyle = document.documentElement.style
  const bodyStyle = document.body.style
  toastEnvironment = {
    viewport: { x: window.scrollX, y: window.scrollY },
    scrollBehavior: htmlStyle.scrollBehavior,
    htmlOverflowAnchor: htmlStyle.overflowAnchor,
    bodyOverflowAnchor: bodyStyle.overflowAnchor,
    scrollRestoration: history.scrollRestoration,
  }
  htmlStyle.scrollBehavior = 'auto'
  htmlStyle.overflowAnchor = 'none'
  bodyStyle.overflowAnchor = 'none'
  history.scrollRestoration = 'manual'
}

function restoreToastEnvironment(): void {
  const saved = toastEnvironment
  if (!saved) return
  const htmlStyle = document.documentElement.style
  const bodyStyle = document.body.style
  restoreViewport(saved.viewport.x, saved.viewport.y)
  htmlStyle.scrollBehavior = saved.scrollBehavior
  htmlStyle.overflowAnchor = saved.htmlOverflowAnchor
  bodyStyle.overflowAnchor = saved.bodyOverflowAnchor
  history.scrollRestoration = saved.scrollRestoration
  restoreViewport(saved.viewport.x, saved.viewport.y)
  toastEnvironment = null
}

watch(current, (value) => {
  if (value) captureToastEnvironment()
  else restoreToastEnvironment()
}, { flush: 'sync' })

function dismiss(): void {
  // Removing a focused fixed element can trigger Chromium's scroll anchoring
  // even though the toast is outside document flow. Preserve the viewport so
  // dismissing a summary cannot move the page it is announcing.
  captureToastEnvironment()
  if (toastEnvironment) {
    toastEnvironment.viewport = { x: window.scrollX, y: window.scrollY }
  }
  if (document.activeElement instanceof HTMLElement) {
    document.activeElement.blur()
  }
  notificationStore.clear()
  requestAnimationFrame(() => restoreToastEnvironment())
}

function restoreViewport(scrollX: number, scrollY: number): void {
  if (navigator.userAgent.toLowerCase().includes('jsdom')) return
  try {
    window.scrollTo({ left: scrollX, top: scrollY, behavior: 'instant' })
  } catch {
    // jsdom does not implement scrolling; the browser path above is the
    // layout-preserving behavior.
  }
  document.documentElement.scrollTop = scrollY
  document.body.scrollTop = scrollY
}

// The store owns the auto-close timers; unmounting has to take the pending one
// with it so it cannot outlive the toast and mutate the shell afterwards.
onBeforeUnmount(() => {
  restoreToastEnvironment()
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
      @click="dismiss"
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
  /* Keep the fixed layer below wrapped desktop navigation as well as the
     nominal 72px shell height. */
  top: calc(var(--size-shell-header) + var(--space-6));
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
