<script setup lang="ts">
// ConfirmDialog (US-200).
//
// Accessible confirmation modal for destructive/irreversible actions (delete,
// cancel, restore defaults, real external submits). Unlike `window.confirm`,
// it is fully stylable and keyboard accessible:
//
// - opened via the exported `confirm()` promise (resolve true/false),
// - Escape or the cancel button resolves false; confirm resolves true,
// - focus is trapped inside while open and restored to the triggering element
//   on close (useFocusTrap + inert siblings),
// - the dialog carries `role="alertdialog"` with an `aria-describedby`
//   reference to the body text.
//
// The title/body copy is supplied by the caller and must stay safe Chinese
// business language; this component never logs or persists anything.
import { computed, ref, useId } from 'vue'

import { useFocusTrap } from '@/app/composables/useFocusTrap'

interface ConfirmState {
  title: string
  message: string
  confirmLabel?: string
  cancelLabel?: string
  danger?: boolean
  resolve: (value: boolean) => void
}

const open = ref(false)
const state = ref<ConfirmState | null>(null)
const dialogEl = ref<HTMLElement | null>(null)

const titleId = useId()
const bodyId = useId()

const confirmLabel = computed(() => state.value?.confirmLabel ?? '确认')
const cancelLabel = computed(() => state.value?.cancelLabel ?? '取消')

const { activate, deactivate } = useFocusTrap(dialogEl, () => {
  close(false)
})

function confirm(options: {
  title: string
  message: string
  confirmLabel?: string
  cancelLabel?: string
  danger?: boolean
}): Promise<boolean> {
  if (open.value) {
    state.value?.resolve(false)
  }
  return new Promise((resolve) => {
    state.value = { ...options, resolve }
    open.value = true
    // Focus trap runs after the dialog is rendered so the DOM exists.
    requestAnimationFrame(() => activate())
  })
}

function close(result: boolean): void {
  if (!open.value) return
  deactivate()
  open.value = false
  const resolver = state.value?.resolve
  state.value = null
  resolver?.(result)
}

function onConfirm(): void {
  close(true)
}

function onCancel(): void {
  close(false)
}

defineExpose({ confirm })
</script>

<template>
  <Teleport to="body">
    <!-- The focus trap anchors on the backdrop (the teleported root): marking
         its siblings inert hides the whole #app while the dialog is open. -->
    <div
      v-if="open"
      ref="dialogEl"
      class="confirm-dialog-backdrop"
      @click.self="onCancel"
    >
      <div
        class="confirm-dialog"
        :class="{ 'confirm-dialog-danger': state?.danger }"
        role="alertdialog"
        aria-modal="true"
        :aria-labelledby="titleId"
        :aria-describedby="bodyId"
      >
        <h2 :id="titleId" class="confirm-dialog-title">{{ state?.title }}</h2>
        <p :id="bodyId" class="confirm-dialog-message">{{ state?.message }}</p>
        <div class="confirm-dialog-actions">
          <button type="button" class="secondary-button" @click="onCancel">
            {{ cancelLabel }}
          </button>
          <button
            type="button"
            :class="state?.danger ? 'danger-button' : 'primary-button'"
            @click="onConfirm"
          >
            {{ confirmLabel }}
          </button>
        </div>
      </div>
    </div>
  </Teleport>
</template>

<style scoped>
.confirm-dialog-backdrop {
  position: fixed;
  inset: 0;
  z-index: 100;
  display: flex;
  align-items: center;
  justify-content: center;
  background: rgba(0, 0, 0, 0.45);
  padding: 1rem;
}

.confirm-dialog {
  background: var(--color-bg);
  color: var(--color-text);
  border: 1px solid var(--color-border);
  border-radius: 10px;
  box-shadow: 0 12px 32px rgba(0, 0, 0, 0.2);
  padding: 1.25rem 1.5rem;
  max-width: 420px;
  width: 100%;
  display: grid;
  gap: 0.75rem;
}

.confirm-dialog-danger .confirm-dialog-title {
  color: var(--color-danger);
}

.confirm-dialog-title {
  margin: 0;
  font-size: 1.1rem;
}

.confirm-dialog-message {
  margin: 0;
  color: var(--color-text-muted);
}

.confirm-dialog-actions {
  display: flex;
  flex-wrap: wrap;
  justify-content: flex-end;
  gap: 0.5rem;
}

@media (max-width: 480px) {
  .confirm-dialog-actions {
    justify-content: stretch;
  }

  .confirm-dialog-actions :deep(button) {
    flex: 1;
  }
}
</style>
