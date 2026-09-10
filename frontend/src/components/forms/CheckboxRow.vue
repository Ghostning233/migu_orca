<script setup lang="ts">
// CheckboxRow (US-200).
//
// Labeled checkbox with the legacy "checkbox-row" layout: label text next to
// the native checkbox (not a wrapping label, so the id/for pair stays
// explicit). Supports `v-model:checked` (checked prop + update:checked emit)
// like the other form primitives; `label` is the accessible name.
//
// Attribute handling: the root is a wrapper div, so `inheritAttrs` is disabled
// and only the checkbox-relevant attributes (id, name, disabled, ...) are
// forwarded to the native input — `id` must reach the input (FormField uses it
// for the label `for`), never a duplicate on the wrapper.
import { computed, useAttrs, useId } from 'vue'

defineProps<{
  label: string
  help?: string
  checked?: boolean
}>()

const emit = defineEmits<{
  (e: 'update:checked', value: boolean): void
}>()

defineOptions({ inheritAttrs: false })

const attrs = useAttrs()
const generatedId = useId()
const checkboxId = computed(() => (typeof attrs.id === 'string' ? attrs.id : generatedId))

function onChange(event: Event): void {
  emit('update:checked', (event.target as HTMLInputElement).checked)
}
</script>

<template>
  <div class="checkbox-row">
    <input
      :id="checkboxId"
      type="checkbox"
      class="base-checkbox"
      :checked="checked"
      v-bind="attrs"
      @change="onChange"
    />
    <div class="checkbox-row-copy">
      <label :for="checkboxId" class="checkbox-row-label">{{ label }}</label>
      <p v-if="help" class="field-help checkbox-row-help">{{ help }}</p>
    </div>
  </div>
</template>

<style scoped>
.checkbox-row {
  display: flex;
  align-items: flex-start;
  gap: var(--space-2);
}

.checkbox-row-copy {
  display: grid;
  gap: var(--space-1);
}

.checkbox-row-label {
  font-weight: var(--font-weight-medium);
  font-size: var(--font-size-sm);
}

.checkbox-row-help {
  margin: 0;
}

.base-checkbox {
  width: var(--control-checkbox-size);
  height: var(--control-checkbox-size);
  margin-top: var(--space-1);
  accent-color: var(--color-action-primary);
}

.base-checkbox:focus-visible {
  outline: var(--focus-ring-width) solid var(--color-focus-ring);
  outline-offset: var(--focus-ring-offset);
}

.base-checkbox:disabled {
  cursor: not-allowed;
}
</style>
