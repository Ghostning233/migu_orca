<script setup lang="ts">
import { nextTick, ref, watch } from 'vue'

import BaseInput from '@/components/forms/BaseInput.vue'
import BaseTextarea from '@/components/forms/BaseTextarea.vue'

export type AnimeTitleInputMode = 'single' | 'batch'

const props = withDefaults(
  defineProps<{
    modelValue?: string
    mode?: AnimeTitleInputMode
    disabled?: boolean
    id?: string
  }>(),
  { modelValue: '', mode: 'single', disabled: false },
)

const emit = defineEmits<{
  (event: 'update:modelValue', value: string): void
}>()

const input = ref<HTMLElement | { $el?: HTMLElement } | null>(null)

function nativeInput(): HTMLInputElement | HTMLTextAreaElement | null {
  const value = input.value
  if (!value) return null
  if (value instanceof HTMLInputElement || value instanceof HTMLTextAreaElement) return value
  const element = '$el' in value ? value.$el : undefined
  return element instanceof HTMLInputElement || element instanceof HTMLTextAreaElement ? element : null
}

function onInput(value: string): void {
  const normalized = props.mode === 'single' ? value.replace(/[\r\n]+/g, ' ') : value
  emit('update:modelValue', normalized)
}

function resize(): void {
  const element = nativeInput()
  if (!element || props.mode !== 'batch') return
  element.style.height = 'auto'
  element.style.height = `${Math.min(element.scrollHeight, 240)}px`
  element.style.overflowY = element.scrollHeight > 240 ? 'auto' : 'hidden'
}

watch(
  () => [props.mode, props.modelValue],
  async () => {
    await nextTick()
    resize()
  },
  { immediate: true },
)

defineExpose({
  focus: () => nativeInput()?.focus(),
  focusInput: () => nativeInput()?.focus(),
  selection: () => ({
    start: nativeInput()?.selectionStart ?? 0,
    end: nativeInput()?.selectionEnd ?? 0,
  }),
  restoreSelection: (start: number, end: number) => {
    nativeInput()?.setSelectionRange(start, end)
  },
})
</script>

<template>
  <BaseInput
    v-if="props.mode === 'single'"
    ref="input"
    :id="props.id || 'anime-title-input-single'"
    type="text"
    autocomplete="off"
    placeholder="例如：葬送的芙莉莲"
    :model-value="props.modelValue"
    :disabled="props.disabled"
    @update:model-value="onInput"
  />
  <BaseTextarea
    v-else
    ref="input"
    :id="props.id || 'anime-title-input-batch'"
    class="anime-title-input-batch"
    rows="1"
    placeholder="萌王S4&#10;路哥S4&#10;杖剑谭S2"
    :model-value="props.modelValue"
    :disabled="props.disabled"
    @update:model-value="onInput"
  />
</template>

<style scoped>
.anime-title-input-batch {
  max-height: 240px;
  overflow-y: hidden;
  resize: none;
}
</style>
