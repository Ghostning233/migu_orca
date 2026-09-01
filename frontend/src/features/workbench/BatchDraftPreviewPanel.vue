<script setup lang="ts">
// BatchDraftPreviewPanel (US-205).
//
// The reviewable draft panel for one batch card. It reuses the shared
// DraftPreviewPanel (server-authoritative draft edit + preview-modify/
// preview-save) and adds the batch-specific actions:
//
//   - 接受当前批量草案 — accepts this single card through the batch accept
//     API (US-146: single-card accept and batch accept share the same
//     endpoint), preview-save first when the card still holds an unsaved
//     draft;
//   - 删除当前批量卡片 — removes this card from the in-memory batch grid
//     (the server never persists the parsed batch).
//
// Security boundary: only the public draft snapshot is rendered (the shared
// panel redacts URLs at display time); the opaque draft_id lives only in
// component memory and is never written to URL/browser storage/logs.
import { ref } from 'vue'

import { useNotificationStore } from '@/app/stores/notification'
import ConfirmDialog from '@/components/feedback/ConfirmDialog.vue'
import BaseButton from '@/components/forms/BaseButton.vue'

import DraftPreviewPanel from '@/features/workbench/DraftPreviewPanel.vue'
import type { BatchItem } from '@/features/workbench/batchWorkbench'
import type { RequestSnapshot } from '@/features/requests/requestDetail'

const props = defineProps<{
  item: BatchItem
}>()

const emit = defineEmits<{
  (e: 'accepted', item: BatchItem, savedRequest: RequestSnapshot): void
  (e: 'deleted', itemId: string): void
}>()

const notification = useNotificationStore()
const confirmDialog = ref<InstanceType<typeof ConfirmDialog> | null>(null)

const draftPanel = ref<InstanceType<typeof DraftPreviewPanel> | null>(null)
const accepting = ref(false)

// The shared panel owns the draft_id + snapshot; we only read its current
// request display for the accept descriptor.
async function acceptCurrentDraft(): Promise<void> {
  const ok = await confirmDialog.value?.confirm({
    title: '接受当前批量卡片',
    message: '确认接受当前批量卡片？',
    confirmLabel: '确认接受',
    danger: false,
  })
  if (!ok) return

  accepting.value = true
  try {
    const savedRequest = await draftPanel.value?.saveDraftAndReturn()
    if (!savedRequest) {
      notification.error('接受失败', '订阅草案保存失败，无法接受。')
      return
    }
    emit('accepted', props.item, savedRequest)
  } finally {
    accepting.value = false
  }
}

function removeCard(): void {
  emit('deleted', props.item.item_id ?? '')
}

defineExpose({ acceptCurrentDraft })
</script>

<template>
  <div class="batch-draft-panel">
    <DraftPreviewPanel
      ref="draftPanel"
      :request="(item.preview_request as RequestSnapshot)"
      :draft-id="(item.draft_id ?? '')"
    />

    <div class="batch-draft-actions" aria-label="批量卡片操作">
      <BaseButton
        id="batch-detail-accept"
        variant="primary"
        :loading="accepting"
        @click="acceptCurrentDraft"
      >
        接受当前批量草案
      </BaseButton>
      <BaseButton id="batch-detail-delete" variant="danger" :disabled="accepting" @click="removeCard">
        删除当前批量卡片
      </BaseButton>
    </div>

    <ConfirmDialog ref="confirmDialog" />
  </div>
</template>

<style scoped>
.batch-draft-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 0.5rem;
  margin-top: 0.5rem;
}
</style>
