<script setup lang="ts">
// BaseInput (US-200).
//
// Text/number/password/url input primitive. Supports v-model (modelValue +
// update:modelValue) so feature forms can bind directly. `label` is rendered
// by the parent (usually FormField) or used as `aria-label`; `invalid` sets
// `aria-invalid` so screen readers announce the error state. All other
// attributes (id, name, autocomplete, placeholder, ...) fall through to the
// native input via `$attrs`.
//
// Type is restricted to the safe subset used by feature forms; the legacy
// `textarea`/`select` variants live in BaseTextarea/BaseSelect.
defineProps<{
  type?: 'text' | 'number' | 'password' | 'url' | 'email' | 'search'
  label?: string
  invalid?: boolean
  modelValue?: string | number
}>()

const emit = defineEmits<{
  (e: 'update:modelValue', value: string): void
}>()

function onInput(event: Event): void {
  emit('update:modelValue', (event.target as HTMLInputElement).value)
}
</script>

<template>
  <input
    :type="type"
    class="base-input"
    :value="modelValue"
    :aria-label="label || undefined"
    :aria-invalid="invalid || undefined"
    v-bind="$attrs"
    @input="onInput"
  />
</template>

<style scoped>
.base-input {
  width: 100%;
  min-height: 40px;
  padding: 0.5rem 0.625rem;
  border: 1px solid var(--color-border);
  border-radius: 6px;
  background: var(--color-bg);
  color: var(--color-text);
  font: inherit;
}

.base-input:focus-visible {
  outline: 2px solid var(--color-accent);
  outline-offset: 2px;
}

.base-input[aria-invalid='true'] {
  border-color: var(--color-danger);
}
</style>
