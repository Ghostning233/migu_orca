<script setup lang="ts">
// BaseSelect (US-200).
//
// Select primitive: renders a labeled `<select>` with the given options.
// `options` values may be the display text itself or an explicit
// `{ value, label }` pair; features pass Chinese labels for display and
// stable internal codes as values (internal codes are never rendered as text).
// All extra attributes (id, name, disabled, ...) fall through to `<select>`.
import { computed } from 'vue'

const props = defineProps<{
  label: string
  options: ReadonlyArray<string | { value: string; label: string }>
  invalid?: boolean
  modelValue?: string
}>()

const emit = defineEmits<{
  (e: 'update:modelValue', value: string): void
}>()

const normalized = computed(() =>
  props.options.map((option) =>
    typeof option === 'string' ? { value: option, label: option } : option,
  ),
)

function onChange(event: Event): void {
  const value = (event.target as HTMLSelectElement).value
  emit('update:modelValue', value)
}
</script>

<template>
  <select
    class="base-select"
    :aria-label="label"
    :aria-invalid="invalid || undefined"
    :value="modelValue"
    v-bind="$attrs"
    @change="onChange"
  >
    <option v-for="option in normalized" :key="option.value" :value="option.value">
      {{ option.label }}
    </option>
  </select>
</template>

<style scoped>
.base-select {
  width: 100%;
  min-height: var(--control-height);
  padding: var(--control-padding-block) var(--control-padding-inline);
  border: var(--control-border-width) solid var(--color-control-border);
  border-radius: var(--radius-sm);
  background: var(--color-control-surface);
  color: var(--color-text);
  font: inherit;
  transition: border-color var(--control-transition), box-shadow var(--control-transition);
}

.base-select:focus-visible {
  outline: var(--focus-ring-width) solid var(--color-focus-ring);
  outline-offset: var(--focus-ring-offset);
}

.base-select[aria-invalid='true'] {
  border-color: var(--color-danger);
}

.base-select:disabled {
  color: var(--color-control-disabled);
  background: var(--color-surface-subtle);
  cursor: not-allowed;
}
</style>
