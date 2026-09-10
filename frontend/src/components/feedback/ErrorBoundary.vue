<script setup lang="ts">
// Global error boundary (US-199).
//
// Catches render errors from any descendant feature and shows a safe,
// generic Chinese fallback instead of crashing the whole shell. The error
// object itself is never rendered (it may embed URLs/bodies), and nothing
// sensitive is logged to the page.
import { onErrorCaptured, ref } from 'vue'

const hasError = ref(false)
const message = ref('页面发生意外错误，请刷新后重试。')

onErrorCaptured((_err: unknown, _instance: unknown, info: string): boolean => {
  // We deliberately do not log `err` (it may contain sensitive content);
  // `info` is a safe lifecycle hint like "render function".
  hasError.value = true
  message.value = `页面发生意外错误，请刷新后重试。(${info})`
  return false
})

function retry(): void {
  hasError.value = false
  message.value = '页面发生意外错误，请刷新后重试。'
}
</script>

<template>
  <div v-if="hasError" class="error-boundary" role="alert">
    <h2 class="error-boundary-title">页面出错了</h2>
    <p class="error-boundary-message">{{ message }}</p>
    <button type="button" class="secondary-button" @click="retry">重试</button>
  </div>
  <slot v-else />
</template>

<style scoped>
.error-boundary {
  border: 1px solid var(--color-feedback-error-border);
  border-radius: var(--radius-md);
  padding: var(--space-5);
  margin: var(--space-4) 0;
  background: var(--color-feedback-error-surface);
}

.error-boundary-title {
  margin: 0 0 var(--space-2);
  color: var(--color-feedback-error-text);
  font-size: var(--font-size-lg);
}

.error-boundary-message {
  margin: 0 0 var(--space-3);
  color: var(--color-text-muted);
}
</style>
