<script setup lang="ts">
/**
 * Issue #98: one operation-level submission choice.
 *
 * Fixing the entry button to “提交方案” keeps the page wording stable while the
 * user decides, and opening this dialog alone sends nothing. The dialog explains
 * both external effects, starts focus on 取消 (so Enter alone can never submit),
 * and lets Escape/取消 cancel only before the external write has started. It
 * reuses the shared focus-trap + Teleport pattern of ConfirmDialog.
 *
 * Issue #234 (D9): the approved design gives the two modes distinct weights —
 * 持续追番 is the primary action and 下载现有资源 the outlined one — and states
 * *when* to pick which. The primary colour is hierarchy only: no mode is
 * preselected, and opening still sends nothing. The dialog has to carry its own
 * scoped modal styles because `ConfirmDialog` styles are scoped to that
 * component and never reach this markup. The action sizes are pinned so the
 * in-progress labels (“持续追番…”, “下载现有资源…”) never change button width.
 */
import { nextTick, onBeforeUnmount, ref, useId, watch } from 'vue'

import { useFocusTrap } from '@/app/composables/useFocusTrap'

export type SubmissionMode = 'DOWNLOAD_EXISTING' | 'CONTINUE_TRACKING'

const props = defineProps<{
  /** Whether the dialog is visible. */
  open: boolean
  /** The mode already chosen: every action stays disabled while it is set. */
  pendingMode?: SubmissionMode | null
  /** A write/recovery elsewhere already owns the page's single intent. */
  busy?: boolean
  /** Issue #100: how many selected plans this one choice applies to. */
  batchCount?: number
}>()

const emit = defineEmits<{
  (e: 'choose', mode: SubmissionMode): void
  (e: 'cancel'): void
}>()

const dialogEl = ref<HTMLElement | null>(null)
const cancelEl = ref<HTMLButtonElement | null>(null)
const titleId = useId()
const bodyId = useId()

const { activate, deactivate } = useFocusTrap(dialogEl, () => cancel())

function choose(mode: SubmissionMode): void {
  if (props.busy || props.pendingMode) return
  emit('choose', mode)
}

function cancel(): void {
  // AC 4: cancelling is only honoured before the external write starts.
  if (props.pendingMode) return
  emit('cancel')
}

watch(
  () => props.open,
  async (open) => {
    if (!open) {
      deactivate()
      return
    }
    await nextTick()
    activate()
    // AC 4: the default focus is 取消, never either external action.
    cancelEl.value?.focus()
  },
  { immediate: true },
)

onBeforeUnmount(() => deactivate())
</script>

<template>
  <Teleport to="body">
    <div v-if="props.open" ref="dialogEl" class="confirm-dialog-backdrop" @click.self="cancel">
      <div
        class="confirm-dialog tracking-mode-dialog"
        role="alertdialog"
        aria-modal="true"
        :aria-labelledby="titleId"
        :aria-describedby="bodyId"
      >
        <h2 :id="titleId" class="confirm-dialog-title">选择提交方式</h2>
        <p v-if="props.batchCount" id="tracking-mode-batch" class="field-help">
          本次选择将统一应用于所选 {{ props.batchCount }} 条追番方案。
        </p>
        <div class="tracking-mode-body">
          <p class="tracking-mode-lede">
            现在只想把已符合方案的资源加入下载，选「下载现有资源」；想让后续新资源持续自动下载，选「持续追番」。
          </p>
          <ul class="tracking-mode-options">
            <li class="tracking-mode-option">
              <p class="tracking-mode-option-title">下载现有资源</p>
              <p class="tracking-mode-option-detail">只把当前已符合方案的资源交给 Auto Bangumi 加入下载一次；不建立持续追番订阅，后续新资源不会自动下载。</p>
            </li>
            <li class="tracking-mode-option">
              <p class="tracking-mode-option-title">持续追番</p>
              <p class="tracking-mode-option-detail">在 Auto Bangumi 建立受控外部订阅，后续新资源持续自动下载。</p>
            </li>
          </ul>
          <p :id="bodyId" class="confirm-dialog-message">两种方式都只作用于本次提交，不会改变本地方案；打开这个弹窗不会提交任何内容。</p>
        </div>
        <div class="confirm-dialog-actions">
          <button
            id="tracking-mode-cancel"
            ref="cancelEl"
            type="button"
            class="secondary-button"
            :disabled="Boolean(props.pendingMode)"
            @click="cancel"
          >
            取消
          </button>
          <button
            id="tracking-mode-download"
            type="button"
            class="secondary-button tracking-mode-action"
            :disabled="props.busy || Boolean(props.pendingMode)"
            :aria-busy="props.pendingMode === 'DOWNLOAD_EXISTING'"
            @click="choose('DOWNLOAD_EXISTING')"
          >
            {{ props.pendingMode === 'DOWNLOAD_EXISTING' ? '下载现有资源…' : '下载现有资源' }}
          </button>
          <button
            id="tracking-mode-continue"
            type="button"
            class="primary-button tracking-mode-action"
            :disabled="props.busy || Boolean(props.pendingMode)"
            :aria-busy="props.pendingMode === 'CONTINUE_TRACKING'"
            @click="choose('CONTINUE_TRACKING')"
          >
            {{ props.pendingMode === 'CONTINUE_TRACKING' ? '持续追番…' : '持续追番' }}
          </button>
        </div>
      </div>
    </div>
  </Teleport>
</template>

<style scoped>
/* The shared `confirm-dialog-*` classes are styled inside ConfirmDialog.vue's
 * scoped block, which cannot reach this markup, so the dialog carries its own
 * modal surface built from the same tokens (Token V1 / design baseline). */
.confirm-dialog-backdrop {
  position: fixed;
  inset: 0;
  z-index: var(--z-overlay);
  display: flex;
  align-items: center;
  justify-content: center;
  background: var(--color-feedback-scrim);
  padding: var(--space-4);
}

.tracking-mode-dialog {
  display: grid;
  gap: var(--space-3);
  width: 100%;
  /* The approved design measures ~686px wide on the 1440 canvas; 680px keeps
   * that proportion with round numbers. */
  max-width: 680px;
  max-height: calc(100vh - 2 * var(--space-4));
  overflow-y: auto;
  padding: var(--space-6) var(--space-8);
  border: var(--control-border-width) solid var(--color-border-subtle);
  border-radius: var(--radius-lg);
  background: var(--color-surface-raised);
  color: var(--color-text);
  box-shadow: var(--shadow-dialog);
}

.confirm-dialog-title {
  margin: 0;
  font-size: var(--font-size-lg);
}

/* The batch count line keeps the shared `field-help` type but drops its
 * paragraph margins so the dialog's own grid gap is the single rhythm. */
.tracking-mode-dialog .field-help {
  margin: 0;
}

.tracking-mode-body {
  display: grid;
  gap: var(--space-3);
}

.tracking-mode-lede {
  margin: 0;
  color: var(--color-text-muted);
  font-size: var(--font-size-sm);
  line-height: var(--line-height-body);
}

.tracking-mode-options {
  display: grid;
  gap: var(--space-2);
  margin: 0;
  padding: 0;
  list-style: none;
}

.tracking-mode-option {
  display: grid;
  gap: var(--space-1);
  padding: var(--space-3) var(--space-4);
  border: var(--control-border-width) solid var(--color-border-subtle);
  border-radius: var(--radius-md);
  background: var(--color-surface-raised);
}

.tracking-mode-option-title {
  margin: 0;
  font-size: var(--type-card-title);
  font-weight: var(--font-weight-semibold);
}

.tracking-mode-option-detail {
  margin: 0;
  color: var(--color-text-muted);
  font-size: var(--font-size-sm);
  line-height: var(--line-height-body);
}

.confirm-dialog-message {
  margin: 0;
  color: var(--color-text-muted);
  font-size: var(--font-size-sm);
  line-height: var(--line-height-body);
}

.confirm-dialog-actions {
  display: flex;
  flex-wrap: wrap;
  justify-content: flex-end;
  gap: var(--space-2);
}

/* `min-width` is what keeps the two mode buttons the same width while
 * `pendingMode` swaps in a one-character-longer label: 6 CJK glyphs of
 * “下载现有资源…” plus 1.5em for the trailing ellipsis, the control padding and
 * the border. Everything scales with the label token, so a future
 * `--type-label` change cannot make the pending label grow the button. */
.confirm-dialog-actions .tracking-mode-action {
  min-width: calc(7.5em + 2 * var(--control-padding-inline) + 2 * var(--control-border-width));
}

/* The approved design paints 取消's focus ring because it is the dialog's
 * default focus. Chromium's :focus-visible heuristic hides that native ring when
 * the dialog was opened by mouse, so the default focus is made visible
 * explicitly — it never removes an indicator, only adds the one the design
 * shows (and keyboard users already get it from the shared focus-visible rule). */
.tracking-mode-dialog #tracking-mode-cancel:focus {
  outline: var(--focus-ring-width) solid var(--color-focus-ring);
  outline-offset: var(--focus-ring-offset);
}

@media (max-width: 480px) {
  .tracking-mode-dialog {
    padding: var(--space-4);
  }

  .confirm-dialog-actions {
    justify-content: stretch;
  }

  .confirm-dialog-actions > button {
    flex: 1;
  }
}
</style>
