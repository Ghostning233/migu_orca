<script setup lang="ts">
// CheckboxRow (US-200).
//
// Labeled checkbox with the legacy "checkbox-row" layout: label text next to
// the native checkbox (not a wrapping label, so the id/for pair stays
// explicit). `label` is the accessible name; the checkbox itself receives
// `v-bind="$attrs"` (id, name, checked via v-model, ...). The label/for id is
// unique per instance via Vue's useId.
import { useId } from 'vue'

defineProps<{
  label: string
  help?: string
}>()

const checkboxId = useId()
</script>

<template>
  <div class="checkbox-row">
    <input :id="checkboxId" type="checkbox" class="base-checkbox" v-bind="$attrs" />
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
  gap: 0.5rem;
}

.checkbox-row-copy {
  display: grid;
  gap: 0.15rem;
}

.checkbox-row-label {
  font-weight: 500;
  font-size: 0.875rem;
}

.checkbox-row-help {
  margin: 0;
}

.base-checkbox {
  width: 1.05rem;
  height: 1.05rem;
  margin-top: 0.15rem;
  accent-color: var(--color-accent);
}
</style>
