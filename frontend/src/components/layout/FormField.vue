<script setup lang="ts">
// FormField (US-200).
//
// Form layout primitive: pairs a `<label>` with a slot for the control plus an
// optional `help` text. It derives an accessible id for `aria-describedby`
// from the label text so feature forms do not need to hand-wire ids.
// A `required` indicator (visually hidden from the label text, still read by
// screen readers) is rendered when `required` is true.
import { computed } from 'vue'

const props = defineProps<{
  label: string
  help?: string
  required?: boolean
  /** HTML `for` target id; when omitted the label wraps the slotted control. */
  inputId?: string
}>()

const fieldId = computed(() => `form-field-${props.label}`)
const helpId = computed(() => `${fieldId.value}-help`)
</script>

<template>
  <div class="form-field" :class="{ 'form-field-required': required }">
    <label v-if="inputId" :for="inputId" class="form-field-label">
      {{ label }}<span v-if="required" class="visually-hidden">（必填）</span>
    </label>
    <label v-else class="form-field-label">
      {{ label }}<span v-if="required" class="visually-hidden">（必填）</span>
      <slot />
    </label>
    <p v-if="help" :id="helpId" class="field-help">{{ help }}</p>
  </div>
</template>

<style scoped>
.form-field {
  display: grid;
  gap: 0.35rem;
}

.form-field-label {
  font-weight: 600;
  font-size: 0.875rem;
}

.visually-hidden {
  position: absolute;
  width: 1px;
  height: 1px;
  padding: 0;
  margin: -1px;
  overflow: hidden;
  clip: rect(0 0 0 0);
  white-space: nowrap;
  border: 0;
}
</style>
