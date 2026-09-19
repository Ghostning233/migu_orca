<script setup lang="ts">
// Single-anime review step (US-277 / US-344). The shared editor is the only
// editing surface; this host owns the component-local draft session, the edit
// scheduler that decides when a preview-modify leaves the browser, and the
// step actions.
import { computed, onUnmounted, ref } from 'vue'
import { useRouter } from 'vue-router'

import { api, toApiError } from '@/api/client'
import { useDraftSession } from '@/app/composables/useDraftSession'
import { useLeaveGuard } from '@/app/composables/useLeaveGuard'
import {
  useSingleAnimeJourney,
  type AcceptRequestResult,
  type ConfirmRequestSaveBody,
  type ConfirmRequestSaveResult,
  type TrackingItemsResult,
} from '@/app/composables/useSingleAnimeJourney'
import { useNotificationStore } from '@/app/stores/notification'
import ConfirmDialog from '@/components/feedback/ConfirmDialog.vue'
import BaseButton from '@/components/forms/BaseButton.vue'
import LoadingState from '@/components/feedback/LoadingState.vue'
import AnimeDraftEditor from '@/features/workbench/AnimeDraftEditor.vue'
import { useDraftEditScheduler } from '@/features/workbench/draftEditScheduler'
import type { PreviewEditState, SelectedCollectionSummary } from '@/features/workbench/candidateSearch'
import { effectiveSeeds, type RequestSnapshot } from '@/features/requests/requestDetail'
import { storageQuery } from '@/features/requests/requestStorage'
import { isPublicRouteIdentifier, routeLocation } from '@/app/router/catalog'
import type { ReuseSuggestion } from '@/features/requests/reuseHandoff'

const props = defineProps<{
  request: RequestSnapshot
  draftId: string
  draftRevision?: number
  reuseSuggestion?: ReuseSuggestion | null
  /**
   * F4: in-memory projection of the candidate this draft came from, used only
   * to answer「已选哪部/哪一季」in the review default layer. It is never sent
   * anywhere and never reaches the URL, storage or history.
   */
  selectedCollection?: SelectedCollectionSummary | null
}>()

const emit = defineEmits<{
  (event: 'changed', state: { request: RequestSnapshot; draftId: string; draftRevision: number }): void
  (event: 'discard', destination: 'candidates' | 'input'): void
}>()

const notification = useNotificationStore()
const router = useRouter()
const confirmDialog = ref<InstanceType<typeof ConfirmDialog> | null>(null)
const editor = ref<InstanceType<typeof AnimeDraftEditor> | null>(null)
const session = useDraftSession({ request: props.request, draftId: props.draftId, draftRevision: props.draftRevision })
const draftSnapshot = computed(() => (session.request.value ?? props.request) as RequestSnapshot)

// US-344: subtitle groups commit immediately, filter rules after 1.5s, the
// folder name only through the explicit 保存修改 flush. Every success replaces
// the snapshot, resource summary, rules and revision in one step.
const scheduler = useDraftEditScheduler({
  session,
  storageDir: () => storageQuery().storage_dir ?? null,
  onApplied: () => onDraftApplied(),
  onInvalid: () => onDraftInvalidated(),
  onFailed: () => onDraftModifyFailed(),
})
const formError = ref('')
const navigationLoading = ref(false)
const dirty = ref(false)
const reuseSuggestionApplied = ref(false)
const journey = useSingleAnimeJourney()
const confirmLoading = ref(false)
const confirmError = ref('')
const confirmedRequestId = ref<string | null>(null)
const acceptError = ref('')
const trackingLocated = ref(false)
const trackingLocationState = ref<'not_found' | 'failed' | null>(null)

const leaveGuard = useLeaveGuard({
  shouldGuard: () => {
    // A generated draft is an unsaved capability until save-confirm consumes
    // it. During confirmation/apply, protect the in-flight operation too;
    // saved-pending-confirm is intentionally recoverable without a warning.
    return Boolean(
      session.draftId.value &&
      journey.state.phase === 'review' ||
      session.applying.value ||
      journey.state.busy !== null,
    )
  },
  confirm: async () => {
    const confirmed = await confirmDialog.value?.confirm({
      title: '离开审核步骤',
      message: '离开审核步骤将丢弃当前订阅草案和已应用编辑，是否继续？',
      confirmLabel: '确认离开',
      cancelLabel: '留在此页',
      danger: true,
    })
    return confirmed === true
  },
  cleanup: () => {
    session.invalidate()
    journey.discard()
    // The shell brand can request the same /app/add route while this panel is
    // mounted. Notify the workbench explicitly so the in-memory draft is
    // discarded even though Vue Router does not remount the route.
    emit('discard', 'input')
  },
})

journey.setCandidates(1)
journey.transition('candidates')
journey.selectCandidate()
journey.setDraft(props.draftId, props.draftRevision ?? 1)

// FE-01/US-341: the save action has exactly one reactive source. The button's
// disabled state and the in-place Chinese reason are both derived from this
// list, so a blocked button can never claim it is available. Every entry is
// evaluated on each read: an early reason must not short-circuit the reactive
// dependencies of the later ones.
const saveBlockers = computed(() => {
  const reasons: string[] = []
  if (confirmLoading.value) reasons.push('正在保存并确认')
  if (session.invalid.value) reasons.push('订阅草案已失效')
  if (journey.state.phase !== 'review') reasons.push('当前订阅方案已进入确认恢复流程')
  if (session.applying.value) reasons.push('正在重新计算订阅方案')
  // A pending local edit is never submitted by the confirm click itself: the
  // scheduler owns every preview-modify, so the primary action stays blocked
  // until it has something server-consistent to confirm.
  if (scheduler.waiting.value) reasons.push('有尚未应用的编辑，正在等待过滤规则自动更新')
  else if (scheduler.folderPending.value) reasons.push('有尚未应用的编辑，等待提交目录名')
  else if (dirty.value) reasons.push('有尚未应用的编辑')
  if (session.error.value) reasons.push('存在未恢复的字段修改失败')
  if (!draftSnapshot.value.confirmable_config?.selected_subtitle_group) reasons.push('尚未选择字幕组')
  if (!effectiveSeeds(draftSnapshot.value).length) reasons.push('没有有效资源')
  if (!session.draftId.value || session.draftRevision.value === null) reasons.push('订阅草案版本不可用')
  if (!journey.canConfirm()) reasons.push('当前订阅方案不可确认')
  return reasons
})

const saveButtonDisabled = computed(() => saveBlockers.value.length > 0)

function handoffFrom(result: ConfirmRequestSaveResult): NonNullable<ConfirmRequestSaveResult['handoff']> | null {
  const handoff = result.handoff
  if (!handoff) return null
  if (result.outcome !== 'CONFIRMED') return null
  if (!isPublicRouteIdentifier(handoff.request_id)) return null
  if (handoff.status !== 'CONFIRMED' || handoff.next_action !== 'TRACKING') return null
  if (!isPublicRouteIdentifier(handoff.tracking_id)) return null
  if (typeof handoff.tracking_ready !== 'boolean') return null
  if (handoff.tracking_status !== null && typeof handoff.tracking_status !== 'string') return null
  if (handoff.safe_message !== null && typeof handoff.safe_message !== 'string') return null
  return handoff
}

type TrackingLocationResult = 'found' | 'not_found' | 'failed'

async function locateTracking(requestId: string): Promise<TrackingLocationResult> {
  try {
    const result = await api.get<TrackingItemsResult>('/api/v1/tracking/items', { query: storageQuery() })
    const item = result.items.find((candidate) => candidate.request_id === requestId)
    if (!item || !isPublicRouteIdentifier(item.request_id) || item.request_id !== requestId || !isPublicRouteIdentifier(item.tracking_id)) return 'not_found'
    journey.finishTracking(item.tracking_id)
    trackingLocated.value = true
    if (router.hasRoute('tracking')) {
      await router.replace(routeLocation('tracking', { tracking_id: item.tracking_id }))
    }
    return 'found'
  } catch {
    return 'failed'
  }
}

async function saveAndConfirm(): Promise<void> {
  const key = journey.newConfirmOperation()
  const draft = session.draftId.value
  const revision = session.draftRevision.value
  if (!key || !draft || revision === null) return
  if (!journey.begin('saving')) return
  confirmLoading.value = true
  confirmError.value = ''
  const body: ConfirmRequestSaveBody = {
    draft_id: draft,
    base_revision: revision,
    idempotency_key: key,
    storage_dir: storageQuery().storage_dir ?? null,
  }
  try {
    const result = await api.post<ConfirmRequestSaveResult>('/api/v1/requests/save-confirm', { body })
    const handoff = handoffFrom(result)
    if (!handoff) throw { type: 'request_error' }
    confirmedRequestId.value = handoff.request_id
    journey.finishConfirm({ requestId: handoff.request_id })
    session.invalidate()
    await router.replace(routeLocation('tracking', { tracking_id: handoff.tracking_id }))
  } catch (cause) {
    const safeError = toApiError(cause)
    journey.fail(safeError)
    confirmError.value = journey.state.error?.message ?? '保存并确认失败，请重试。'
    if (safeError.type === 'save_confirm_failed' && journey.state.phase === 'saved_pending_confirm') {
      session.invalidate()
    }
    if (['draft_expired', 'draft_evicted', 'draft_replayed', 'draft_revision_conflict'].includes(safeError.type)) {
      session.invalidate()
      notification.error('订阅草案已失效', '订阅草案已失效，请重新选择合集。')
      emit('discard', 'candidates')
    }
  } finally {
    confirmLoading.value = false
  }
}

async function retrySavedConfirmation(): Promise<void> {
  const requestId = journey.state.requestId
  if (!requestId || !journey.begin('accepting')) return
  confirmLoading.value = true
  acceptError.value = ''
  trackingLocated.value = false
  trackingLocationState.value = null
  try {
    await api.post<AcceptRequestResult>(`/api/v1/requests/{request_id}/accept`, {
      path: { request_id: requestId },
      body: { storage_dir: storageQuery().storage_dir ?? null },
    })
    const located = await locateTracking(requestId)
    if (located !== 'found') {
      // The accept response was explicit and successful; only location is
      // pending, so this state must never reopen accept recovery.
      journey.finishTracking()
      trackingLocationState.value = located
      acceptError.value = '方案已确认，但暂未定位到追番记录。可稍后重试定位。'
      return
    }
  } catch (cause) {
    // Any uncertain accept result is verified through the read-only tracking
    // projection first. A failed verification must never trigger another
    // accept request.
    const safeError = toApiError(cause)
    const transport = cause && typeof cause === 'object' ? cause as { network?: unknown; nonJson?: unknown; status?: unknown } : {}
    const status = typeof transport.status === 'number' ? transport.status : 0
    const requiresVerification = Boolean(transport.network === true || transport.nonJson === true || status >= 500) ||
      ['network_error', 'request_timeout', 'upstream_timeout', 'conflict', 'invalid_request_status'].includes(safeError.type)
    if (!requiresVerification) {
      journey.fail(safeError)
      acceptError.value = '确认未完成，请根据错误提示处理后再试。'
      return
    }
    const located = await locateTracking(requestId)
    if (located === 'found') return
    trackingLocationState.value = located
    if (located === 'failed') {
      journey.finishVerificationPending()
      acceptError.value = '确认结果暂无法核验。请重试定位，不会重复确认。'
    } else {
      journey.fail(safeError)
      acceptError.value = '确认结果已核验，但暂未找到追番记录。可明确重试确认。'
    }
  } finally {
    confirmLoading.value = false
  }
}

/** One successful preview-modify publishes the new snapshot and revision. */
function onDraftApplied(): void {
  formError.value = ''
  emit('changed', {
    request: draftSnapshot.value,
    draftId: session.draftId.value ?? '',
    draftRevision: session.draftRevision.value ?? 1,
  })
  journey.setDraft(session.draftId.value ?? '', session.draftRevision.value ?? 1)
}

function onDraftModifyFailed(): void {
  formError.value = '订阅草案修改失败，请稍后重试。'
}

function onDraftInvalidated(): void {
  notification.error('订阅草案已失效', '请重新选择合集后再试。')
  emit('discard', 'candidates')
}

function onSubtitleGroupChange(value: string): void {
  if (journey.state.phase !== 'review') return
  scheduler.setSubtitleGroup(value)
}

function onFilterChange(state: PreviewEditState): void {
  if (journey.state.phase !== 'review') return
  scheduler.setFilter(state)
}

function onFolderNameChange(value: string): void {
  if (journey.state.phase !== 'review') return
  scheduler.setFolderName(value)
}

/** 保存修改: flush the not-yet-due filter input and the folder name now. */
async function flushModify(): Promise<void> {
  await scheduler.flush()
}

async function retryModify(): Promise<void> {
  formError.value = ''
  await scheduler.retry()
}

function resetFailedModify(): void {
  editor.value?.reset()
  scheduler.restore()
  formError.value = ''
}

onUnmounted(() => scheduler.dispose())

function applyReuseSuggestion(): void {
  if (!props.reuseSuggestion) return
  editor.value?.applySuggestion(props.reuseSuggestion)
  reuseSuggestionApplied.value = true
}

async function retryTrackingLocation(): Promise<void> {
  const requestId = journey.state.requestId
  if (!requestId || confirmLoading.value || !['verification_pending', 'confirmed_pending_tracking'].includes(journey.state.phase)) return
  confirmLoading.value = true
  acceptError.value = ''
  const located = await locateTracking(requestId)
  trackingLocationState.value = located === 'found' ? null : located
  if (located === 'not_found' && journey.state.phase === 'verification_pending') journey.returnToSavedPending()
  if (located !== 'found') {
      acceptError.value = located === 'failed'
        ? '确认结果暂无法核验。请稍后重试定位。'
        : journey.state.phase === 'saved_pending_confirm'
          ? '确认结果已核验，但暂未找到追番记录。可明确重试确认。'
          : '方案已确认，但暂未定位到追番记录。请稍后重试定位。'
  }
  confirmLoading.value = false
}

async function openUnlocatedTracking(): Promise<void> {
  if (confirmLoading.value) return
  await router.replace(routeLocation('tracking'))
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

defineExpose({ session, editor, leaveGuard })
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
        <BaseButton
          v-if="reuseSuggestion && journey.state.phase === 'review'"
          id="single-review-apply-reuse-suggestion"
          variant="secondary"
          :disabled="navigationLoading || session.applying.value"
          @click="applyReuseSuggestion"
        >
          {{ reuseSuggestionApplied ? '已载入复制方案建议' : '应用复制方案建议' }}
        </BaseButton>
        <BaseButton id="single-review-back-candidates" variant="secondary" :disabled="navigationLoading || session.applying.value" @click="leave('candidates')">重新选择合集</BaseButton>
        <BaseButton id="single-review-edit-search" variant="secondary" :disabled="navigationLoading || session.applying.value" @click="leave('input')">修改搜索</BaseButton>
      </div>
    </div>

    <div id="request-detail-container">
      <p v-if="journey.state.phase === 'review'" class="review-summary preview-mode-note" role="status">订阅草案（未保存）：当前修改只保留在本次页面操作中。</p>
      <AnimeDraftEditor
        ref="editor"
        :request="draftSnapshot"
        id-prefix="preview"
        form-id="detail-preview-edit-form"
        :candidate-summary="props.selectedCollection ?? null"
        apply-variant="secondary"
        :applying="session.applying.value"
        :error="formError"
        :can-retry="session.canRetry.value"
        :disabled="navigationLoading || session.invalid.value || journey.state.phase !== 'review'"
        @apply="flushModify"
        @subtitle-group-change="onSubtitleGroupChange"
        @filter-change="onFilterChange"
        @folder-change="onFolderNameChange"
        @dirty-change="dirty = $event; journey.setDirty($event)"
        @retry="retryModify"
        @reset="resetFailedModify"
      >
        <template #review-note>
          <p class="review-note">字幕组会立即重新计算；筛选规则在停止输入 1.5 秒后自动更新；目录名只在「保存修改」时提交。保存修改仅更新当前服务端草案，不会保存本地方案或触发外部订阅动作。</p>
        </template>
      </AnimeDraftEditor>

      <!-- 最终确认必须在完整审核内容之后；这是保存本地方案的入口，
           追番管理仍会再次要求用户确认外部提交。 -->
      <div class="review-confirmation-block" aria-live="polite">
        <p class="review-confirmation-boundary">仅保存本地方案、追番管理再次确认外部提交。</p>
        <BaseButton v-if="journey.state.phase === 'review'" id="single-review-save-button" variant="primary" :loading="confirmLoading" :disabled="saveButtonDisabled" aria-describedby="single-review-save-blockers" @click="saveAndConfirm">保存并确认</BaseButton>
        <BaseButton v-else-if="journey.state.phase === 'saved_pending_confirm'" id="single-review-retry-accept" variant="primary" :loading="confirmLoading" :disabled="confirmLoading" @click="retrySavedConfirmation">重试确认</BaseButton>
        <BaseButton v-if="journey.state.phase === 'verification_pending' || journey.state.phase === 'confirmed_pending_tracking'" id="single-review-retry-locate" variant="secondary" :loading="confirmLoading" :disabled="confirmLoading" @click="retryTrackingLocation">重试定位</BaseButton>
        <BaseButton v-if="journey.state.phase === 'confirmed_pending_tracking'" id="single-review-open-unlocated" variant="secondary" :disabled="confirmLoading" @click="openUnlocatedTracking">打开无定位追番管理</BaseButton>
        <p v-if="trackingLocated" id="single-review-tracking-success" class="field-help" role="status">订阅方案已确认，并已定位到追番记录。</p>
        <p v-else-if="confirmedRequestId" id="single-review-save-success" class="field-help" role="status">订阅方案已经确认，正在准备后续定位。</p>
        <p v-else-if="journey.state.phase === 'saved_pending_confirm'" id="single-review-accept-recovery" class="field-help" role="status">订阅方案已保存但确认未完成，可直接重试确认；不会重复保存。</p>
        <p v-else-if="confirmError" id="single-review-save-error" class="field-error" role="alert">{{ confirmError }}</p>
        <p v-if="acceptError" id="single-review-accept-error" class="field-error" role="alert">{{ acceptError }}</p>
        <p v-else id="single-review-save-blockers" class="field-help">保存并确认{{ saveBlockers.length ? `暂不可用：${saveBlockers.join('；')}` : '可用' }}。</p>
      </div>
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
