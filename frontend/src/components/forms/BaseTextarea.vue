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
  min-height: calc(var(--control-height) * 1.8);
  padding: var(--control-padding-block) var(--control-padding-inline);
  border: var(--control-border-width) solid var(--color-border-strong);
  border-radius: var(--radius-md);
  background: var(--color-control-surface);
  color: var(--color-text);
  font: inherit;
  resize: vertical;
  transition: border-color var(--control-transition), box-shadow var(--control-transition);
}

.base-textarea:focus-visible {
  outline: 3px solid var(--color-focus-ring);
  outline-offset: var(--focus-ring-offset);
}

.base-textarea[aria-invalid='true'] {
  border-color: var(--color-danger);
}

.base-textarea:disabled {
  color: var(--color-control-disabled);
  background: var(--color-surface-subtle);
  cursor: not-allowed;
}
</style>
