<script setup lang="ts">
/**
 * Issue #223: the batch delete confirmation.
 *
 * One explicit scope decision for the whole batch: local plans only (the
 * default) or local plans plus their controlled external subscriptions.  The
 * dialog states how many entries are affected, which entries the local
 * pre-check already excludes and why, and what the default scope means
 * (Auto Bangumi keeps running the subscriptions; MiGuOrca stops managing them).
 *
 * It is a confirmation, not an executor: it never sends anything, never picks a
 * scope by default and starts focus on 取消 so Enter alone cannot delete.  The
 * external scope is opt-in through a native checkbox and is refused when no
 * saved connection exists.
 */
import { nextTick, onBeforeUnmount, ref, useId, watch } from 'vue'

import { useFocusTrap } from '@/app/composables/useFocusTrap'

export interface BatchDeleteSkip {
  readonly trackingId: string
  readonly title: string
  /** Fixed, already-safe local reason (never raw server text). */
  readonly reason: string
}

const props = defineProps<{
  open: boolean
  /** How many selected entries this dialog will delete. */
  count: number
  /** Selected entries the local pre-check excludes, with their reason. */
  skipped?: readonly BatchDeleteSkip[]
  /** A saved Auto Bangumi connection exists, so the external scope is possible. */
  externalAvailable: boolean
  /** A batch is already in flight elsewhere on the page. */
  busy?: boolean
}>()

const emit = defineEmits<{
  (e: 'confirm', deleteExternal: boolean): void
  (e: 'cancel'): void
}>()

const dialogEl = ref<HTMLElement | null>(null)
const cancelEl = ref<HTMLButtonElement | null>(null)
const deleteExternal = ref(false)
const titleId = useId()
const bodyId = useId()

const { activate, deactivate } = useFocusTrap(dialogEl, () => cancel())

watch(
  () => props.open,
  async (open) => {
    if (!open) {
      deactivate()
      return
    }
    // Every opening starts at the safe default again.
    deleteExternal.value = false
    await nextTick()
    activate()
    cancelEl.value?.focus()
  },
  { immediate: true },
)

function confirm(): void {
  if (props.busy) return
  if (deleteExternal.value && !props.externalAvailable) return
  emit('confirm', deleteExternal.value)
}

function cancel(): void {
  if (props.busy) return
  emit('cancel')
}

onBeforeUnmount(() => deactivate())
</script>

<template>
  <Teleport to="body">
    <div v-if="props.open" ref="dialogEl" class="confirm-dialog-backdrop" @click.self="cancel">
      <div
        class="confirm-dialog tracking-batch-delete-dialog"
        role="alertdialog"
        aria-modal="true"
        :aria-labelledby="titleId"
        :aria-describedby="bodyId"
      >
        <h2 :id="titleId" class="confirm-dialog-title">删除追番方案</h2>
        <div :id="bodyId" class="tracking-batch-delete-body">
          <p class="confirm-dialog-message">
            本次将删除 {{ props.count }} 条追番方案的本地记录与方案快照。
          </p>
          <div v-if="props.skipped?.length" class="tracking-batch-delete-skipped">
            <p class="tracking-batch-delete-skipped-title">
              另有 {{ props.skipped.length }} 条将被跳过，不会被删除：
            </p>
            <ul>
              <li v-for="entry in props.skipped" :key="entry.trackingId">
                <strong>{{ entry.title }}</strong>：{{ entry.reason }}
              </li>
            </ul>
          </div>
          <label class="tracking-batch-delete-scope">
            <input
              id="tracking-batch-delete-external"
              v-model="deleteExternal"
              type="checkbox"
              :disabled="props.busy || !props.externalAvailable"
            >
            <span>同时删除 Auto Bangumi 中的受控外部订阅</span>
          </label>
          <p v-if="!props.externalAvailable" class="field-help">
            缺少已保存连接时只能删除本地记录。
          </p>
          <p v-if="deleteExternal" class="tracking-batch-delete-warning">
            将先删除这 {{ props.count }} 条在 Auto Bangumi 中的受控外部订阅，确认成功后才删除本地记录；
            外部删除失败或结果未知的条目会完整保留，已下载的媒体不会删除。
          </p>
          <p v-else class="confirm-dialog-message">
            仅删除本地记录：Auto Bangumi 中的订阅会继续运行，MiGuOrca 不再管理它们；已下载的媒体不会删除。
          </p>
        </div>
        <div class="confirm-dialog-actions">
          <button
            id="tracking-batch-delete-cancel"
            ref="cancelEl"
            type="button"
            class="secondary-button"
            :disabled="props.busy"
            @click="cancel"
          >
            取消
          </button>
          <button
            id="tracking-batch-delete-confirm"
            type="button"
            class="danger-button"
            :disabled="props.busy"
            :aria-busy="Boolean(props.busy)"
            @click="confirm"
          >
            {{ props.busy ? '正在删除…' : '删除' }}
          </button>
        </div>
      </div>
    </div>
  </Teleport>
</template>

<style scoped>
/* The shared `confirm-dialog-*` classes are styled inside ConfirmDialog.vue's
 * scoped block, which cannot reach this markup, so this dialog carries its own
 * surface built from the same tokens (Token V1). */
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

.tracking-batch-delete-dialog {
  display: grid;
  gap: var(--space-3);
  width: 100%;
  /* Wider than a two-action confirm because it carries the affected count and
   * the pre-check skip list; still inside the 760px shell reflow tier. */
  max-width: 560px;
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

.tracking-batch-delete-body {
  display: grid;
  gap: var(--space-3);
}

.confirm-dialog-message {
  margin: 0;
  color: var(--color-text-muted);
  font-size: var(--font-size-sm);
  line-height: var(--line-height-body);
}

.tracking-batch-delete-skipped {
  display: grid;
  gap: var(--space-1);
  padding: var(--space-3) var(--space-4);
  border: var(--control-border-width) solid var(--color-warning-border);
  border-radius: var(--radius-md);
  background: var(--color-warning-surface);
  font-size: var(--font-size-sm);
}

.tracking-batch-delete-skipped-title {
  margin: 0;
  color: var(--color-warning);
  font-weight: var(--font-weight-semibold);
}

.tracking-batch-delete-skipped ul {
  margin: 0;
  padding-inline-start: 1.25rem;
  max-height: 8rem;
  overflow-y: auto;
  color: var(--color-text-muted);
}

.tracking-batch-delete-scope {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  min-block-size: var(--control-target-min);
  font-size: var(--font-size-sm);
  cursor: pointer;
}

.tracking-batch-delete-scope input {
  inline-size: var(--control-checkbox-size);
  block-size: var(--control-checkbox-size);
  accent-color: var(--color-primary);
}

.tracking-batch-delete-warning {
  margin: 0;
  color: var(--color-warning);
  font-size: var(--font-size-sm);
  line-height: var(--line-height-body);
}

.confirm-dialog-actions {
  display: flex;
  flex-wrap: wrap;
  justify-content: flex-end;
  gap: var(--space-2);
}

@media (max-width: 480px) {
  .tracking-batch-delete-dialog {
    padding: var(--space-4);
  }
}
</style>
