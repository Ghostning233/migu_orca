<script setup lang="ts">
// BaseTextarea (US-200).
//
// Textarea primitive mirroring BaseInput: supports v-model, forwards an
// optional `label` as `aria-label`, sets `aria-invalid` from `invalid`, and
// passes every other attribute (id, name, placeholder, rows, ...) to the
// native element.
defineProps<{
  label?: string
  invalid?: boolean
  modelValue?: string
}>()

const emit = defineEmits<{
  (e: 'update:modelValue', value: string): void
}>()

function onInput(event: Event): void {
  emit('update:modelValue', (event.target as HTMLTextAreaElement).value)
}
</script>

<template>
  <textarea
    class="base-textarea"
    :value="modelValue"
    :aria-label="label || undefined"
    :aria-invalid="invalid || undefined"
    v-bind="$attrs"
    @input="onInput"
  ></textarea>
</template>

<style scoped>
.base-textarea {
  width: 100%;
  min-height: 72px;
  padding: 0.5rem 0.625rem;
  border: 1px solid var(--color-border);
  border-radius: 6px;
  background: var(--color-bg);
  color: var(--color-text);
  font: inherit;
  resize: vertical;
}

.base-textarea:focus-visible {
  outline: 2px solid var(--color-accent);
  outline-offset: 2px;
}

.base-textarea[aria-invalid='true'] {
  border-color: var(--color-danger);
}
</style>
