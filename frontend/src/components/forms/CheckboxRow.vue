<script setup lang="ts">
// CheckboxRow (US-200, #156).
//
// Labeled checkbox built on the shared native control: the visible box is the
// 18px `base-checkbox` (global styles in `styles/main.css`), while the click
// target comes from the two label associations — the box wrapper and the text
// label both point at the same input with `for`, and the input stays the only
// element that carries the id.
//
// Layout: the box is centered on the *first line* of the label/help column, so
// single- and multi-line rows align without per-page negative margins. The
// offset is derived from the label line box Token, not hard-coded per page.
//
// `indeterminate` is a DOM property (not an attribute), so it is applied to the
// input explicitly; the native `checked`/`disabled`/keyboard semantics and the
// controlled `v-model:checked` binding are untouched.
import { computed, useAttrs, useId } from 'vue'

defineProps<{
  label: string
  help?: string
  checked?: boolean
  indeterminate?: boolean
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
    <label class="checkbox-row-control" :for="checkboxId">
      <input
        :id="checkboxId"
        type="checkbox"
        class="base-checkbox"
        :checked="checked"
        :indeterminate="indeterminate === true"
        v-bind="attrs"
        @change="onChange"
      />
    </label>
    <div class="checkbox-row-copy">
      <label :for="checkboxId" class="checkbox-row-label">{{ label }}</label>
      <p v-if="help" class="field-help checkbox-row-help">{{ help }}</p>
    </div>
  </div>
</template>

<style scoped>
.checkbox-row {
  align-items: flex-start;
  display: flex;
  gap: var(--space-3);
}

/* 方框不承载 44px 触控目标：外层 label 只提供一小圈可点区域，方框本身保持
 * --control-checkbox-size。文字标签同样通过 for 关联，提供整行可点区域。 */
.checkbox-row-control {
  align-items: flex-start;
  cursor: pointer;
  display: inline-flex;
  flex: 0 0 auto;
  justify-content: center;
  /* 方框中心对齐标签首行的中心：首行行高由 label 字号 × 正文行高 Token 决定，
   * 不用固定负 margin 修补单一页面。 */
  min-block-size: var(--control-checkbox-hit);
  min-inline-size: var(--control-checkbox-hit);
  padding-block-start: calc(
    (var(--control-checkbox-hit) - var(--control-checkbox-size)) / 2
  );
}

.checkbox-row-copy {
  display: grid;
  gap: var(--space-1);
  min-width: 0;
}

.checkbox-row-label {
  cursor: pointer;
  font-size: var(--font-size-sm);
  font-weight: var(--font-weight-medium);
  line-height: var(--line-height-body);
  min-block-size: var(--control-checkbox-hit);
  padding-block-start: calc(
    (var(--control-checkbox-hit) - var(--font-size-sm) * var(--line-height-body)) / 2
  );
}

.checkbox-row-help {
  margin: 0;
}

/* 键盘焦点：可见焦点环取自共享 Token（与 BaseInput/BaseButton 同一规则）。 */
.checkbox-row .base-checkbox:focus-visible {
  outline: var(--focus-ring-width) solid var(--color-focus-ring);
  outline-offset: var(--focus-ring-offset);
}

.checkbox-row-control:has(.base-checkbox:disabled) {
  cursor: not-allowed;
}
</style>
