<script setup lang="ts">
// Single-item compatibility host (US-272). The shared AnimeDraftEditor owns
// review UI; this adapter owns draft-session transport and legacy preview-save.
import { computed, ref } from 'vue'
import { api } from '@/api/client'
import type { operations } from '@/api/generated/api'
import { useNotificationStore } from '@/app/stores/notification'
import BaseButton from '@/components/forms/BaseButton.vue'
import LoadingState from '@/components/feedback/LoadingState.vue'
import PanelSection from '@/components/layout/PanelSection.vue'
import { useDraftSession } from '@/app/composables/useDraftSession'
import AnimeDraftEditor from '@/features/workbench/AnimeDraftEditor.vue'
import type { PreviewPatch } from '@/features/workbench/candidateSearch'
import type { RequestSnapshot } from '@/features/requests/requestDetail'
import { storageQuery } from '@/features/requests/requestStorage'

type PreviewSaveResult = NonNullable<operations['previewSaveRequest']['responses']['200']['content']['application/json']['result']>

const props = defineProps<{ request: RequestSnapshot; draftId: string; draftRevision?: number }>()
const emit = defineEmits<{
  (e: 'saved', requestId: string): void
  (e: 'expired'): void
  (e: 'failed'): void
  (e: 'changed', state: { request: RequestSnapshot; draftId: string; draftRevision: number }): void
}>()

const notification = useNotificationStore()
const session = useDraftSession({ request: props.request, draftId: props.draftId, draftRevision: props.draftRevision })
const editor = ref<InstanceType<typeof AnimeDraftEditor> | null>(null)
const draftSnapshot = computed(() => (session.request.value ?? props.request) as RequestSnapshot)
const draftCapability = session.draftId
const draftRevisionState = session.draftRevision
const applying = session.applying
const saving = ref(false)
const formError = ref('')

function isDraftError(error: unknown): boolean {
  const type = (error as { type?: string } | null)?.type ?? ''
  return ['draft_expired', 'draft_evicted', 'draft_replayed', 'draft_revision_conflict'].includes(type)
}

function notifyDraftExpired(): void {
  notification.error('订阅草案已失效', '请重新生成订阅草案后再试。')
  emit('expired')
}

function handleFailure(): void {
  if (session.invalid.value) return notifyDraftExpired()
  formError.value = session.error.value?.message ?? '订阅草案修改失败，请稍后重试。'
  notification.error('修改失败', '订阅草案修改失败，请稍后重试。')
  emit('failed')
}

function handleChanged(): void {
  emit('changed', { request: draftSnapshot.value, draftId: draftCapability.value ?? '', draftRevision: draftRevisionState.value ?? 1 })
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

async function saveDraft(): Promise<RequestSnapshot | null> {
  saving.value = true
  formError.value = ''
  try {
    // Keep the legacy save contract: persist exactly what the user reviewed.
    // The shared editor exposes only its minimal patch, never a full Request.
    if (editor.value?.dirty) {
      const modified = await session.apply(editor.value.patch, storageQuery().storage_dir ?? null)
      if (!modified) {
        handleFailure()
        return null
      }
      handleChanged()
    }
    const saved = await api.post<PreviewSaveResult>('/api/v1/requests/preview-save', {
      body: { draft_id: draftCapability.value ?? '', base_revision: draftRevisionState.value ?? 1, storage_dir: storageQuery().storage_dir ?? null },
    })
    draftCapability.value = ''
    const request = saved?.request as RequestSnapshot | undefined
    if (request?.request_id) {
      emit('saved', request.request_id)
      return request
    }
    emit('failed')
  } catch (error) {
    if (isDraftError(error)) notifyDraftExpired()
    else {
      notification.error('保存失败', '订阅草案保存失败，请稍后重试。')
      emit('failed')
    }
  } finally {
    saving.value = false
  }
  return null
}

defineExpose({ request: draftSnapshot, draftId: draftCapability, draftRevision: draftRevisionState, saveDraftAndReturn: saveDraft })
</script>

<template>
  <PanelSection title="订阅方案详情" class="request-detail-panel draft-preview-panel">
    <div id="request-detail-container" class="draft-preview-content">
    <div class="detail-actions" aria-label="订阅方案操作">
      <p class="field-help preview-mode-note">订阅草案（未保存）：可编辑下方订阅方案；点击「应用修改」重新计算种子展示，点击「保存草案」后进入待确认流程。</p>
      <BaseButton id="draft-save-button" variant="primary" :loading="saving || applying" @click="saveDraft">保存草案</BaseButton>
    </div>
    <AnimeDraftEditor
      ref="editor"
      :request="draftSnapshot"
      id-prefix="preview"
      form-id="detail-preview-edit-form"
      :applying="applying"
      :error="formError"
      :can-retry="session.canRetry.value"
      :disabled="saving"
      @apply="applyModify"
      @retry="retryModify"
      @reset="resetFailedModify"
    />
    <LoadingState v-if="saving" message="正在保存订阅草案..." />
    </div>
  </PanelSection>
</template>

<style scoped>
.detail-actions { display: flex; flex-wrap: wrap; align-items: center; gap: 0.5rem; margin-bottom: 1rem; }
.detail-actions .field-help { margin: 0; }
</style>
