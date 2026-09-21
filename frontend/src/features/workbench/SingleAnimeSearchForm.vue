<script setup lang="ts">
// US-363 (Stage 47): 单番搜索表单的唯一实现。
//
// 单番首页（英雄区）与单番未保存草案态都会渲染这套「标题输入 + 52px 主搜索按钮」，
// 因此抽成一个组件，避免两处各写一份导致状态、可访问性或几何漂移。
// 批量搜索使用独立的 `#batch-parse-form`，不经由本组件。
import { ref } from 'vue'

import BaseButton from '@/components/forms/BaseButton.vue'
import AnimeTitleInput from '@/features/workbench/AnimeTitleInput.vue'

withDefaults(
  defineProps<{
    query?: string
    loading?: boolean
    disabled?: boolean
  }>(),
  { query: '', loading: false, disabled: false },
)

const emit = defineEmits<{
  (event: 'update:query', value: string): void
  (event: 'submit'): void
}>()

const input = ref<InstanceType<typeof AnimeTitleInput> | null>(null)

defineExpose({
  focus: () => input.value?.focusInput(),
  focusInput: () => input.value?.focusInput(),
  selection: () => input.value?.selection() ?? { start: 0, end: 0 },
  restoreSelection: (start: number, end: number) => input.value?.restoreSelection(start, end),
})
</script>

<template>
  <form id="mikan-candidate-search-form" class="workbench-search-form" @submit.prevent="emit('submit')">
    <div class="search-control-row">
      <div class="search-field">
        <label for="mikan-candidate-query">番剧标题</label>
        <AnimeTitleInput
          ref="input"
          id="mikan-candidate-query"
          :model-value="query"
          mode="single"
          :disabled="disabled"
          @update:model-value="emit('update:query', $event)"
        />
      </div>
      <BaseButton
        id="mikan-candidate-search-submit"
        type="submit"
        variant="primary"
        size="lg"
        :loading="loading"
        :disabled="disabled || !query.trim()"
      >
        搜索候选合集
      </BaseButton>
    </div>
  </form>
</template>

<style scoped>
.workbench-search-form {
  /* Stage 47 获批页面专属值（基线文档第 11 节）：主搜索按钮宽度。 */
  --single-search-submit-width: 176px;
  display: grid;
  gap: var(--space-3);
}

.search-control-row {
  display: flex;
  align-items: end;
  gap: var(--space-3);
}

.search-field {
  display: grid;
  flex: 1 1 auto;
  gap: var(--space-2);
  min-width: 0;
}

.workbench-search-form label {
  font-weight: 500;
  font-size: var(--font-size-sm);
}

/* Stage 47 几何基线：主搜索按钮 176×52（--control-height-lg），
 * 输入框占满剩余宽度（1440 英雄区下为 532px）。 */
#mikan-candidate-search-submit {
  flex: 0 0 auto;
  width: var(--single-search-submit-width);
}

@media (max-width: 720px) {
  .search-control-row {
    align-items: stretch;
    flex-direction: column;
  }

  #mikan-candidate-search-submit {
    width: 100%;
  }
}
</style>
