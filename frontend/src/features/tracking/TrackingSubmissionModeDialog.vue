<script setup lang="ts">
/**
 * Issue #98: one operation-level submission choice.
 *
 * Fixing the entry button to “提交方案” keeps the page wording stable while the
 * user decides, and opening this dialog alone sends nothing. The dialog explains
 * both external effects, starts focus on 取消 (so Enter alone can never submit),
 * and lets Escape/取消 cancel only before the external write has started. It
 * reuses the shared focus-trap + Teleport pattern of ConfirmDialog.
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
    <div v-if="props.open" ref="dialogEl" class="confirm-dialog-backdrop">
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
        <p :id="bodyId" class="confirm-dialog-message">
          下载现有资源：把当前符合追番方案的资源交给 Auto Bangumi 加入下载，不建立持续检查的 RSS 订阅，后续新资源不会自动下载。
          持续追番：在 Auto Bangumi 建立受控外部订阅，持续检查并下载后续资源。
          两种方式都只作用于本次提交，不会改变本地方案。
        </p>
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
            class="primary-button"
            :disabled="props.busy || Boolean(props.pendingMode)"
            :aria-busy="props.pendingMode === 'DOWNLOAD_EXISTING'"
            @click="choose('DOWNLOAD_EXISTING')"
          >
            {{ props.pendingMode === 'DOWNLOAD_EXISTING' ? '下载现有资源…' : '下载现有资源' }}
          </button>
          <button
            id="tracking-mode-continue"
            type="button"
            class="primary-button"
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
