<script setup lang="ts">
export type AnimeMode = 'single' | 'batch'

const props = withDefaults(
  defineProps<{
    modelValue?: AnimeMode
    disabled?: boolean
  }>(),
  { modelValue: 'single', disabled: false },
)

const emit = defineEmits<{
  (event: 'update:modelValue', value: AnimeMode): void
}>()

function select(mode: AnimeMode): void {
  if (!props.disabled && mode !== props.modelValue) emit('update:modelValue', mode)
}

function onKeydown(event: KeyboardEvent, mode: AnimeMode): void {
  if (event.key === 'ArrowLeft' || event.key === 'ArrowRight') {
    event.preventDefault()
    const next = mode === 'single' ? 'batch' : 'single'
    select(next)
    document.getElementById(`anime-mode-${next}`)?.focus()
  } else if (event.key === ' ' || event.key === 'Enter') {
    event.preventDefault()
    select(mode)
  }
}
</script>

<template>
  <div id="anime-mode-switch" class="anime-mode-switch" role="tablist" aria-label="添加方式">
    <button
      v-for="mode in (['single', 'batch'] as const)"
      :id="`anime-mode-${mode}`"
      :key="mode"
      type="button"
      role="tab"
      class="anime-mode-option"
      :class="{ 'is-selected': props.modelValue === mode }"
      :aria-selected="props.modelValue === mode ? 'true' : 'false'"
      :tabindex="props.modelValue === mode ? 0 : -1"
      :disabled="props.disabled"
      @click="select(mode)"
      @keydown="onKeydown($event, mode)"
    >
      {{ mode === 'single' ? '单番搜索' : '批量搜索' }}
    </button>
  </div>
</template>

<style scoped>
.anime-mode-switch {
  /* Stage 47 几何基线：两个选项各 112px，轨道总宽 238px。 */
  --anime-mode-option-min-width: 112px;
  display: inline-flex;
  gap: var(--space-1);
  padding: var(--space-1);
  border: var(--border-default);
  border-radius: var(--radius-pill);
  background: var(--color-surface-subtle);
}

/* Stage 46 (US-362): the segmented control is a light track with one clearly
 * selected block, sized with the shared "home page large control" token. Every
 * value comes from the semantic tokens; the selected block uses the coral
 * accent because the design reserves it for the current choice, which is not a
 * second general-purpose primary button. */
.anime-mode-option {
  min-height: var(--control-height-lg);
  min-width: var(--anime-mode-option-min-width);
  padding-inline: var(--space-6);
  border: 0;
  border-radius: var(--radius-pill);
  background: transparent;
  color: var(--color-text-secondary);
  font: inherit;
  font-size: var(--font-size-md);
  font-weight: var(--font-weight-medium);
  cursor: pointer;
}

.anime-mode-option.is-selected {
  background: var(--color-accent);
  color: var(--color-text-inverse);
  font-weight: var(--font-weight-semibold);
}

.anime-mode-option:focus-visible {
  outline: var(--focus-ring-width) solid var(--color-focus-ring);
  outline-offset: var(--focus-ring-offset);
}

.anime-mode-option:disabled {
  cursor: not-allowed;
  opacity: 0.6;
}

@media (prefers-reduced-motion: no-preference) {
  .anime-mode-option {
    transition:
      background-color var(--motion-duration-fast) var(--motion-easing-standard),
      color var(--motion-duration-fast) var(--motion-easing-standard);
  }
}
</style>
