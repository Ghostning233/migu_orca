<script setup lang="ts">
// Single-anime review step (US-277). The shared editor is the only editing
// surface; this host owns the component-local draft session and step actions.
import { computed, ref } from 'vue'

import { useDraftSession } from '@/app/composables/useDraftSession'
import { useNotificationStore } from '@/app/stores/notification'
import ConfirmDialog from '@/components/feedback/ConfirmDialog.vue'
import BaseButton from '@/components/forms/BaseButton.vue'
import LoadingState from '@/components/feedback/LoadingState.vue'
import AnimeDraftEditor from '@/features/workbench/AnimeDraftEditor.vue'
import type { PreviewPatch } from '@/features/workbench/candidateSearch'
import { effectiveSeeds, type RequestSnapshot } from '@/features/requests/requestDetail'
import { storageQuery } from '@/features/requests/requestStorage'

const props = defineProps<{
  request: RequestSnapshot
  draftId: string
  draftRevision?: number
}>()

const emit = defineEmits<{
  (event: 'changed', state: { request: RequestSnapshot; draftId: string; draftRevision: number }): void
  (event: 'discard', destination: 'candidates' | 'input'): void
}>()

const notification = useNotificationStore()
const confirmDialog = ref<InstanceType<typeof ConfirmDialog> | null>(null)
const editor = ref<InstanceType<typeof AnimeDraftEditor> | null>(null)
const session = useDraftSession({ request: props.request, draftId: props.draftId, draftRevision: props.draftRevision })
const draftSnapshot = computed(() => (session.request.value ?? props.request) as RequestSnapshot)
const formError = ref('')
const navigationLoading = ref(false)
const dirty = ref(false)

const blockingReasons = computed(() => {
  const reasons: string[] = []
  if (session.applying.value) reasons.push('正在重新计算订阅方案')
  if (dirty.value) reasons.push('有尚未应用的编辑')
  if (!draftSnapshot.value.confirmable_config?.selected_subtitle_group) reasons.push('尚未选择字幕组')
  if (!effectiveSeeds(draftSnapshot.value).length) reasons.push('没有有效资源')
  if (session.invalid.value) reasons.push('订阅草案已失效')
  if (session.error.value) reasons.push('存在未恢复的字段修改失败')
  return reasons
})

async function applyModify(patch: PreviewPatch): Promise<void> {
  formError.value = ''
  const result = await session.apply(patch, storageQuery().storage_dir ?? null)
  if (!result) {
    if (session.invalid.value) {
      notification.error('订阅草案已失效', '请重新选择合集后再试。')
      emit('discard', 'candidates')
      return
    }
    formError.value = '订阅草案修改失败，请稍后重试。'
    notification.error('修改失败', formError.value)
    return
  }
  emit('changed', {
    request: draftSnapshot.value,
    draftId: session.draftId.value ?? '',
    draftRevision: session.draftRevision.value ?? 1,
  })
  notification.success('已应用修改', '订阅草案种子展示已重新计算。')
}

async function retryModify(): Promise<void> {
  formError.value = ''
  const result = await session.retry()
  if (result) {
    emit('changed', { request: draftSnapshot.value, draftId: session.draftId.value ?? '', draftRevision: session.draftRevision.value ?? 1 })
  } else if (session.error.value || session.invalid.value) {
    formError.value = session.invalid.value ? '订阅草案已失效，请重新选择合集。' : '订阅草案修改失败，请稍后重试。'
  }
}

function resetFailedModify(): void {
  editor.value?.reset()
  session.reset()
  formError.value = ''
}

async function leave(destination: 'candidates' | 'input'): Promise<void> {
  if (navigationLoading.value) return
  navigationLoading.value = true
  const confirmed = await confirmDialog.value?.confirm({
    title: destination === 'candidates' ? '重新选择合集' : '修改番剧搜索',
    message: '离开审核步骤将丢弃当前订阅草案和已应用编辑，是否继续？',
    confirmLabel: '确认离开',
    cancelLabel: '留在此页',
    danger: true,
  })
  navigationLoading.value = false
  if (!confirmed) return
  session.invalidate()
  emit('discard', destination)
}

defineExpose({ session, editor })
</script>

<template>
  <section id="single-anime-review-step" aria-labelledby="single-anime-review-heading">
    <div class="review-step-header">
      <div>
        <p class="step-label">步骤 3</p>
        <h2 id="single-anime-review-heading">审核订阅方案</h2>
        <p class="field-help">已选择 MiKan 合集，请核对字幕组、筛选规则和有效资源后再继续。</p>
      </div>
      <div class="review-navigation" aria-label="审核步骤导航">
        <BaseButton id="single-review-back-candidates" variant="secondary" :disabled="navigationLoading || session.applying.value" @click="leave('candidates')">重新选择合集</BaseButton>
        <BaseButton id="single-review-edit-search" variant="secondary" :disabled="navigationLoading || session.applying.value" @click="leave('input')">修改搜索</BaseButton>
      </div>
    </div>

    <div id="request-detail-container">
      <p class="review-summary preview-mode-note" role="status">订阅草案（未保存）：当前修改只保留在本次页面操作中。</p>
      <div class="review-confirmation-block" aria-live="polite">
        <BaseButton id="single-review-save-button" variant="primary" disabled aria-describedby="single-review-save-blockers">保存并确认</BaseButton>
        <p id="single-review-save-blockers" class="field-help">保存并确认暂不可用：{{ blockingReasons.length ? blockingReasons.join('；') : '将在下一步接入。' }}。</p>
      </div>

      <AnimeDraftEditor
        ref="editor"
        :request="draftSnapshot"
        id-prefix="preview"
        form-id="detail-preview-edit-form"
        :applying="session.applying.value"
        :error="formError"
        :can-retry="session.canRetry.value"
        :disabled="navigationLoading"
        @apply="applyModify"
        @dirty-change="dirty = $event"
        @retry="retryModify"
        @reset="resetFailedModify"
      >
        <template #review-note>
          <p class="review-note">审核完成后由保存宿主执行确认；本步骤不会保存、确认或触发外部订阅动作。</p>
        </template>
      </AnimeDraftEditor>
    </div>
    <LoadingState v-if="navigationLoading" message="正在处理返回操作..." />
    <ConfirmDialog ref="confirmDialog" />
  </section>
</template>

<style scoped>
#single-anime-review-step { display: grid; gap: 1rem; }
.review-step-header { display: flex; justify-content: space-between; gap: 1rem; align-items: flex-start; }
.review-step-header h2 { margin: 0; font-size: 1.2rem; }
.step-label { margin: 0 0 0.25rem; color: var(--color-text-muted); font-size: 0.85rem; }
.review-navigation, .review-confirmation-block { display: flex; flex-wrap: wrap; gap: 0.5rem; align-items: center; }
.review-summary, .review-note { margin: 0; color: var(--color-text-muted); }
.review-confirmation-block { border: 1px solid var(--color-border); border-radius: 6px; padding: 0.75rem; }
.review-confirmation-block .field-help { margin: 0; }
@media (max-width: 720px) { .review-step-header { flex-direction: column; } }
</style>
