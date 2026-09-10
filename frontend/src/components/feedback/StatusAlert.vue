<script setup lang="ts">
// StatusAlert (US-200).
//
// Status/alert primitive for inline form feedback (replaces the legacy
// `.empty-state compact-state` / `success-state` / `error-state` pattern).
// It always carries both a visual style and an explicit ARIA state so the
// status is never conveyed by color alone:
//
// - success/info → `role="status"` (polite live region),
// - error       → `role="alert"` (assertive).
//
// `message` must be pre-sanitized by the caller (see api/client.ts — never
// raw bodies, URLs or credentials). A `label` can be used for an error title.
defineProps<{
  kind: 'success' | 'error' | 'info' | 'empty'
  message: string
  label?: string
}>()
</script>

<template>
  <div
    class="status-alert"
    :class="`status-alert-${kind}`"
    :role="kind === 'error' ? 'alert' : 'status'"
    :aria-live="kind === 'error' ? 'assertive' : 'polite'"
  >
    <p v-if="label" class="status-alert-label">{{ label }}</p>
    <p class="status-alert-message">{{ message }}</p>
  </div>
</template>

<style scoped>
.status-alert {
  border-radius: var(--radius-md);
  min-height: var(--size-status-min);
  padding: var(--space-3) var(--space-4);
  display: grid;
  gap: 0.25rem;
  align-content: center;
}

.status-alert-label {
  margin: 0;
  font-weight: 700;
}

.status-alert-message {
  margin: 0;
}

.status-alert-empty {
  background: var(--color-surface-subtle);
  border: 1px dashed var(--color-border-subtle);
  color: var(--color-text-muted);
}

.status-alert-info {
  background: var(--color-surface-subtle);
  border: 1px solid var(--color-border-subtle);
  color: var(--color-text-primary);
}

.status-alert-success {
  background: var(--color-feedback-success-surface);
  border: 1px solid var(--color-feedback-success-border);
  color: var(--color-feedback-success-text);
}

.status-alert-error {
  background: var(--color-feedback-error-surface);
  border: 1px solid var(--color-feedback-error-border);
  color: var(--color-feedback-error-text);
}
</style>
