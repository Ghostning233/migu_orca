<script setup lang="ts">
// BaseButton (US-200).
//
// Button primitive with the three legacy variants (primary / secondary /
// danger). All attributes (type, disabled, aria-label, ...) fall through to
// the native `<button>`; `loading` replaces the label with `loadingLabel`
// (neutral "处理中…" by default) and disables the button. The label is the
// carrier of the in-progress state: under `prefers-reduced-motion: reduce` the
// spinner is suppressed so a motionless arc is never the only signal. The
// native focus-visible outline comes from the shared design baseline
// (styles/main.css).
withDefaults(
  defineProps<{
    variant?: 'primary' | 'secondary' | 'danger'
    type?: 'button' | 'submit' | 'reset'
    disabled?: boolean
    loading?: boolean
    loadingLabel?: string
  }>(),
  {
    variant: 'secondary',
    type: 'button',
    disabled: false,
    loading: false,
    loadingLabel: '处理中…',
  },
)
</script>

<template>
  <button
    :class="`base-button ${variant}-button`"
    :type="type"
    :disabled="disabled || loading"
    :aria-busy="loading || undefined"
  >
    <span v-if="loading" aria-hidden="true" class="base-button-spinner" />
    <span v-if="loading" class="base-button-loading-label">{{ loadingLabel }}</span>
    <slot v-else />
  </button>
</template>

<style scoped>
.base-button {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: var(--space-2);
  min-height: var(--control-height-md);
  min-width: var(--control-target-min);
  border-radius: var(--radius-md);
  padding: var(--control-padding-block) var(--control-padding-inline);
  font-size: var(--font-size-sm);
  font-weight: var(--font-weight-medium);
  line-height: var(--line-height-tight);
  cursor: pointer;
  border: 1px solid transparent;
  text-decoration: none;
  transition:
    background-color var(--control-transition),
    border-color var(--control-transition),
    color var(--control-transition),
    transform var(--control-transition);
}

.base-button:hover:not(:disabled) {
  transform: translateY(calc(var(--motion-distance) * -1));
}

.base-button:focus-visible {
  outline: var(--focus-ring-width) solid var(--color-focus-ring);
  outline-offset: var(--focus-ring-offset);
}

.base-button:disabled {
  cursor: not-allowed;
  opacity: 0.55;
}

.base-button-spinner {
  width: 0.75rem;
  height: 0.75rem;
  border: 2px solid currentColor;
  border-top-color: transparent;
  border-radius: 50%;
  animation: base-button-spin 0.8s linear infinite;
}

.base-button-loading-label {
  white-space: nowrap;
}

@keyframes base-button-spin {
  to {
    transform: rotate(360deg);
  }
}

/* A frozen arc says nothing about progress; the loading label and aria-busy
   carry the state instead. */
@media (prefers-reduced-motion: reduce) {
  .base-button-spinner {
    display: none;
  }
}
</style>
