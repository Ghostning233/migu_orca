<script setup lang="ts">
// Batch compatibility adapter around the shared AnimeDraftEditor (US-273).
// Preview-save and batch accept stay here until the later batch save stories.
import { computed, ref } from 'vue'

import { api } from '@/api/client'
import type { operations } from '@/api/generated/api'
import { useDraftSession, type DraftSession } from '@/app/composables/useDraftSession'
import { useNotificationStore } from '@/app/stores/notification'
import ConfirmDialog from '@/components/feedback/ConfirmDialog.vue'
import BaseButton from '@/components/forms/BaseButton.vue'
import AnimeDraftEditor from '@/features/workbench/AnimeDraftEditor.vue'
import type { PreviewPatch } from '@/features/workbench/candidateSearch'
import type { BatchItem } from '@/features/workbench/batchWorkbench'
import type { RequestSnapshot } from '@/features/requests/requestDetail'
import { storageQuery } from '@/features/requests/requestStorage'

type PreviewSaveResult = NonNullable<
  operations['previewSaveRequest']['responses']['200']['content']['application/json']['result']
>

const props = defineProps<{ item: BatchItem; session?: DraftSession; sharedError?: string }>()
const emit = defineEmits<{
  (e: 'accepted', item: BatchItem, savedRequest: RequestSnapshot): void
  (e: 'deleted', itemId: string): void
  (e: 'expired', itemId: string): void
  (e: 'draft-changed', itemId: string, state: { request: RequestSnapshot; draftId: string; draftRevision: number }): void
}>()

const notification = useNotificationStore()
const confirmDialog = ref<InstanceType<typeof ConfirmDialog> | null>(null)
const editor = ref<InstanceType<typeof AnimeDraftEditor> | null>(null)
const accepting = ref(false)
const formError = ref('')
const initialRequest = computed(() => props.item.preview_request as RequestSnapshot)
const localSession = useDraftSession({ request: initialRequest.value, draftId: props.item.draft_id ?? '', draftRevision: props.item.draft_revision ?? 1 })
// BatchWorkbenchView owns the session when this panel is used in the batch
// flow. Keeping a local fallback preserves the component's compatibility use
// in existing tests and makes the editor reusable in isolation.
const session = props.session ?? localSession
const draftSnapshot = computed(() => (session.request.value ?? initialRequest.value) as RequestSnapshot)
const displayError = computed(() => formError.value || props.sharedError || '')

function notifyDraftExpired(): void {
  notification.error('订阅草案已失效', '请重新生成订阅草案后再试。')
  emit('expired', props.item.item_id ?? '')
}

function handleFailure(): void {
  if (session.invalid.value) {
    notifyDraftExpired()
    return
  }
  formError.value = '订阅草案修改失败，请稍后重试。'
  notification.error('修改失败', formError.value)
}

function handleChanged(): void {
  emit('draft-changed', props.item.item_id ?? '', {
    request: draftSnapshot.value,
    draftId: session.draftId.value ?? '',
    draftRevision: session.draftRevision.value ?? 1,
  })
  notification.success('已应用修改', '订阅草案种子展示已重新计算。')
}

async function applyModify(patch: PreviewPatch): Promise<void> {
  formError.value = ''
  const result = await session.apply(patch, storageQuery().storage_dir ?? null)
  if (result) handleChanged()
  else handleFailure()
}

async function retryModify(): Promise<void> {
  formError.value = ''
  const result = await session.retry()
  if (result) handleChanged()
  else if (session.invalid.value || session.error.value) handleFailure()
}

function resetFailedModify(): void {
  editor.value?.reset()
  session.reset()
  formError.value = ''
}

async function saveDraftAndAccept(): Promise<void> {
  const ok = await confirmDialog.value?.confirm({
    title: '接受当前批量卡片', message: '确认接受当前批量卡片？', confirmLabel: '确认接受', danger: false,
  })
  if (!ok || accepting.value) return
  accepting.value = true
  formError.value = ''
  try {
    if (editor.value?.dirty) {
      const modified = await session.apply(editor.value.patch, storageQuery().storage_dir ?? null)
      if (!modified) { handleFailure(); return }
      handleChanged()
    }
    const saved = await api.post<PreviewSaveResult>('/api/v1/requests/preview-save', {
      body: { draft_id: session.draftId.value ?? '', base_revision: session.draftRevision.value ?? 1, storage_dir: storageQuery().storage_dir ?? null },
    })
    const request = saved?.request as RequestSnapshot | undefined
    if (!request?.request_id) {
      notification.error('接受失败', '订阅草案保存失败，无法接受。')
      return
    }
    session.invalidate()
    emit('accepted', props.item, request)
  } catch (error) {
    const type = (error as { type?: string } | null)?.type ?? ''
    if (['draft_expired', 'draft_evicted', 'draft_replayed', 'draft_revision_conflict'].includes(type)) notifyDraftExpired()
    else notification.error('保存失败', '订阅草案保存失败，请稍后重试。')
  } finally {
    accepting.value = false
  }
}

function removeCard(): void { emit('deleted', props.item.item_id ?? '') }
defineExpose({ acceptCurrentDraft: saveDraftAndAccept })
</script>

<template>
  <div class="batch-draft-panel">
    <AnimeDraftEditor
      ref="editor"
      :request="draftSnapshot"
      id-prefix="batch-preview"
      form-id="detail-preview-edit-form"
      container-id="request-detail-container"
      :applying="session.applying.value"
      :error="displayError"
      :can-retry="session.canRetry.value"
      :disabled="accepting"
      @apply="applyModify"
      @retry="retryModify"
      @reset="resetFailedModify"
    >
      <template #review-note>
        <p class="field-help preview-mode-note">订阅草案（未保存）：可编辑下方订阅方案；点击「应用修改」重新计算种子展示，点击「接受当前批量草案」后进入批量接受流程。</p>
      </template>
    </AnimeDraftEditor>
    <div class="batch-draft-actions" aria-label="批量卡片操作">
      <BaseButton id="batch-detail-accept" variant="primary" :loading="accepting" @click="saveDraftAndAccept">接受当前批量草案</BaseButton>
      <BaseButton id="batch-detail-delete" variant="danger" :disabled="accepting" @click="removeCard">删除当前批量卡片</BaseButton>
    </div>
    <ConfirmDialog ref="confirmDialog" />
  </div>
</template>

<style scoped>
.preview-mode-note { margin: 0.75rem 0 0; }
.batch-draft-actions { display: flex; flex-wrap: wrap; gap: 0.5rem; margin-top: 0.5rem; }
</style>
