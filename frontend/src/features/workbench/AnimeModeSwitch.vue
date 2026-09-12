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
  display: inline-flex;
  gap: 0.2rem;
  padding: 0.2rem;
  border: 1px solid var(--color-border);
  border-radius: 999px;
  background: var(--color-surface-subtle);
}

.anime-mode-option {
  min-height: var(--control-height);
  padding: 0.35rem 0.9rem;
  border: 0;
  border-radius: 999px;
  background: transparent;
  color: var(--color-text-muted);
  font: inherit;
  font-size: var(--font-size-sm);
  cursor: pointer;
}

.anime-mode-option.is-selected {
  background: var(--color-accent);
  color: var(--color-text-inverse);
  font-weight: var(--font-weight-semibold);
}

.anime-mode-option:disabled {
  cursor: not-allowed;
  opacity: 0.6;
}

@media (prefers-reduced-motion: no-preference) {
  .anime-mode-option {
    transition: background-color var(--motion-duration-fast) var(--motion-easing-standard), color var(--motion-duration-fast) var(--motion-easing-standard);
  }
}
</style>
