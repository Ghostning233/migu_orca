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
    /** `md` is the default 44px control; `lg` is the 52px home-page control. */
    size?: 'md' | 'lg'
  }>(),
  {
    variant: 'secondary',
    type: 'button',
    disabled: false,
    loading: false,
    loadingLabel: '处理中…',
    size: 'md',
  },
)
</script>

<template>
  <button
    :class="`base-button ${variant}-button base-button-${size}`"
    :type="type"
    :disabled="disabled || loading"
    :aria-busy="loading || undefined"
  >
    <span class="base-button-stack">
      <span class="base-button-slot" :class="{ 'is-loading': loading }"><slot /></span>
      <span v-if="loading" class="base-button-loading">
        <span aria-hidden="true" class="base-button-spinner" />
        <span class="base-button-loading-label">{{ loadingLabel }}</span>
      </span>
    </span>
  </button>
</template>

<style scoped>
/* US-362: the idle label stays in the layout while loading (invisible but still
 * sizing the button) and the in-progress layer is absolutely positioned inside
 * it. The button therefore keeps its exact idle width even when the loading
 * label is longer than the idle label, and the in-progress text is never
 * replaced by a bare spinner. */
.base-button-stack {
  position: relative;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  max-width: 100%;
}

.base-button-slot.is-loading {
  visibility: hidden;
}

.base-button-loading {
  position: absolute;
  inset: 0;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: var(--space-2);
  max-width: 100%;
  overflow: hidden;
}

.base-button-loading-label {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

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

/* Home-page large control: 52px tall, body-size label. Loading keeps this
   geometry so the button never shrinks or collapses to a bare spinner. */
.base-button-lg {
  min-height: var(--control-height-lg);
  padding-inline: var(--space-5);
  font-size: var(--font-size-md);
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
