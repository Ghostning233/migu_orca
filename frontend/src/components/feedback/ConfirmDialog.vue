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
import { computed, nextTick, onBeforeUnmount, ref, useId } from 'vue'

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
let dialogGeneration = 0

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
  const generation = ++dialogGeneration
  if (open.value) {
    state.value?.resolve(false)
  }
  return new Promise((resolve) => {
    const nextState = { ...options, resolve }
    state.value = nextState
    open.value = true
    // Vue's nextTick is the DOM update boundary. The generation and state
    // guards prevent a replacement/close before the tick from activating a
    // stale trap and making the page inert again.
    void nextTick().then(() => {
      if (generation === dialogGeneration && open.value && state.value?.resolve === resolve) activate()
    })
  })
}

function close(result: boolean): void {
  if (!open.value) return
  dialogGeneration += 1
  deactivate()
  open.value = false
  const resolver = state.value?.resolve
  state.value = null
  resolver?.(result)
}

onBeforeUnmount(() => {
  dialogGeneration += 1
  deactivate()
  state.value?.resolve(false)
  state.value = null
  open.value = false
})

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
  z-index: var(--z-overlay);
  display: flex;
  align-items: center;
  justify-content: center;
  background: var(--color-feedback-scrim);
  padding: var(--space-4);
}

.confirm-dialog {
  background: var(--color-surface-raised);
  color: var(--color-text);
  border: 1px solid var(--color-border-subtle);
  border-radius: var(--radius-lg);
  box-shadow: var(--shadow-dialog);
  padding: var(--space-5) var(--space-6);
  max-width: 420px;
  width: 100%;
  display: grid;
  gap: var(--space-3);
}

.confirm-dialog-danger .confirm-dialog-title {
  color: var(--color-danger-emphasis);
}

.confirm-dialog-title {
  margin: 0;
  font-size: var(--font-size-lg);
}

.confirm-dialog-message {
  margin: 0;
  color: var(--color-text-muted);
}

.confirm-dialog-actions {
  display: flex;
  flex-wrap: wrap;
  justify-content: flex-end;
  gap: var(--space-2);
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
