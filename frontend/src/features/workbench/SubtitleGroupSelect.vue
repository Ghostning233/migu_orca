<script setup lang="ts">
// SubtitleGroupSelect (US-269).
//
// A controlled selector for the public subtitle-group options in a draft.
// It owns no draft value and never calls the API; the parent remains the
// single owner of the editable form and emits the selected value upstream.
import BaseSelect from '@/components/forms/BaseSelect.vue'

export interface SubtitleGroupOption {
  value: string
  label: string
}

const props = defineProps<{
  modelValue: string
  options: ReadonlyArray<SubtitleGroupOption>
  disabled?: boolean
  applying?: boolean
  error?: string
  inputId?: string
}>()

const emit = defineEmits<{
  (e: 'update:modelValue', value: string): void
}>()
</script>

<template>
  <div class="subtitle-group-select">
    <BaseSelect
      :id="props.inputId ?? 'preview-subtitle-group'"
      label="字幕组"
      :model-value="props.modelValue"
      :options="props.options"
      :disabled="props.disabled || props.applying"
      :aria-describedby="props.error ? 'subtitle-group-error' : undefined"
      @update:model-value="emit('update:modelValue', $event)"
    />
    <p v-if="props.applying" class="field-help" aria-live="polite">正在重新计算资源...</p>
    <p v-if="props.error" id="subtitle-group-error" class="field-error" role="alert">{{ props.error }}</p>
  </div>
</template>
