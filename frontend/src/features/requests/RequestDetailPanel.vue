<script setup lang="ts">
// RequestDetailPanel (US-203).
//
// The detail panel for a saved Request, migrated from the legacy
// `renderDetailPayload` (app.js). Renders Overview / Source / Filter / Seeds /
// Audit sections and the status-dependent management actions:
//
// - PENDING_CONFIRM → 确认 (accept) / 取消 (cancel) / 修改 (modify),
// - ACCEPTED       → 本地修改 / 删除 (delete),
// - CANCELLED      → 不可操作 note.
//
// All destructive/irreversible actions go through the shared ConfirmDialog;
// action failures surface only fixed Chinese feedback (never the server's
// raw error, which may embed credentials/endpoints). The panel reloads the
// detail after every successful action so the displayed state stays the
// server-authoritative snapshot.
//
// Security boundary: only typed public fields of the generated detail DTO are
// rendered; URL-looking values are redacted at display time and the request
// snapshot's raw URLs (rss_url / mikan_url / poster_url) are never rendered.
// No value here is persisted, logged or put into the URL.
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'

import { api, toApiError } from '@/api/client'
import type { operations } from '@/api/generated/api'
import { routeLocation } from '@/app/router/catalog'
import { useNotificationStore } from '@/app/stores/notification'
import ConfirmDialog from '@/components/feedback/ConfirmDialog.vue'
import ErrorState from '@/components/feedback/ErrorState.vue'
import LoadingState from '@/components/feedback/LoadingState.vue'
import BaseButton from '@/components/forms/BaseButton.vue'
import BaseTextarea from '@/components/forms/BaseTextarea.vue'
import PanelSection from '@/components/layout/PanelSection.vue'
import FormField from '@/components/layout/FormField.vue'
import AnimeDraftEditor from '@/features/workbench/AnimeDraftEditor.vue'
import type { PreviewPatch } from '@/features/workbench/candidateSearch'

import {
  actionLabel,
  completeSeedGroups,
  displayValue,
  effectiveSeeds,
  excludedSeeds,
  scrubConfig,
  totalCompleteSeedCount,
  type RequestDetailResult,
  type RequestDetailSnapshot,
} from '@/features/requests/requestDetail'
import SafeInfoDialog from '@/features/requests/SafeInfoDialog.vue'
import { statusLabel as detailStatusLabel } from '@/features/requests/requestsList'
import { storageQuery } from '@/features/requests/requestStorage'

type ActionResult = NonNullable<
  operations['acceptRequest']['responses']['200']['content']['application/json']['result']
>
type ModifyResult = NonNullable<
  operations['modifyRequest']['responses']['200']['content']['application/json']['result']
>
type ModifyRequestBodyContract = NonNullable<
  operations['modifyRequest']['requestBody']
>['content']['application/json']
/** Generated saved-modify patch is historical Record<string, never>; adapt it
 * to the generated preview whitelist without accepting arbitrary keys. */
type ModifyRequestBody = Omit<ModifyRequestBodyContract, 'patch'> & { patch: PreviewPatch }
type AcceptRequestBody = NonNullable<
  operations['acceptRequest']['requestBody']
>['content']['application/json']
type CancelRequestBody = NonNullable<
  operations['cancelRequest']['requestBody']
>['content']['application/json']
type LocalActionBody = AcceptRequestBody | CancelRequestBody
type TrackingStatus = 'loading' | 'failed' | 'unavailable' | 'not_linked' | 'linked'

const props = defineProps<{
  requestId: string
  trackingId?: string | null
  trackingStatus?: TrackingStatus
  trackingStatusLabel?: string | null
}>()

const emit = defineEmits<{
  (e: 'changed'): void
  (e: 'deleted', requestId: string): void
}>()

const notification = useNotificationStore()
const router = useRouter()
const confirmDialog = ref<InstanceType<typeof ConfirmDialog> | null>(null)

const loading = ref(false)
const loadFailed = ref(false)
const detail = ref<RequestDetailResult | null>(null)
const lastLoadError = ref<ReturnType<typeof toApiError> | null>(null)
const actionInFlight = ref(false)
const safeInfoOpen = ref(false)

// Inline form visibility (legacy hidden toggles).
const cancelFormOpen = ref(false)
const modifyFormOpen = ref(false)

const modifyError = ref('')
const modifyEditor = ref<InstanceType<typeof AnimeDraftEditor> | null>(null)
const lastModifyPatch = ref<PreviewPatch | null>(null)
const modifyResultUnknown = ref(false)
const actionUnknown = ref<'accept' | 'cancel' | 'delete' | null>(null)

const cancelReason = ref('')

const request = computed<RequestDetailSnapshot | null>(() => detail.value?.request ?? null)
const isAccepted = computed(() => request.value?.status === 'ACCEPTED')
const isPending = computed(() => request.value?.status === 'PENDING_CONFIRM')
const isCancelled = computed(() => request.value?.status === 'CANCELLED')
const effectiveTrackingStatus = computed(() => props.trackingStatus ?? 'not_linked')

const effective = computed(() => (request.value ? effectiveSeeds(request.value) : []))
const excluded = computed(() => (request.value ? excludedSeeds(request.value) : []))
const completeGroups = computed(() => (request.value ? completeSeedGroups(request.value) : []))
const completeTotal = computed(() => (request.value ? totalCompleteSeedCount(request.value) : 0))

const selectedGroupName = computed(
  () => request.value?.confirmable_config?.selected_subtitle_group ?? '未选择字幕组',
)

function reuseRequest(): void {
  safeInfoOpen.value = false
  void router.push(routeLocation('add'))
}

interface LoadDetailOptions {
  closeForms?: boolean
}

type DetailFetch =
  | { result: RequestDetailResult; error: null }
  | { result: null; error: ReturnType<typeof toApiError> }

async function fetchDetailSnapshot(): Promise<DetailFetch> {
  try {
    const result = await api.get<RequestDetailResult>('/api/v1/requests/{request_id}', {
      path: { request_id: props.requestId },
      query: storageQuery(),
    })
    return { result, error: null }
  } catch (error) {
    return { result: null, error: toApiError(error) }
  }
}

function commitDetail(result: RequestDetailResult): void {
  detail.value = result
  lastLoadError.value = null
}

async function loadDetail(options: LoadDetailOptions = {}): Promise<boolean> {
  if (!props.requestId) return false
  loading.value = true
  loadFailed.value = false
  const fetched = await fetchDetailSnapshot()
  if (fetched.result) {
    commitDetail(fetched.result)
    if (options.closeForms !== false) {
      cancelFormOpen.value = false
      modifyFormOpen.value = false
      cancelReason.value = ''
    }
    loading.value = false
    return true
  }
  lastLoadError.value = fetched.error
  detail.value = null
  loadFailed.value = true
  notification.error('订阅方案详情加载失败', '请确认 request_id 是否存在。')
  loading.value = false
  return false
}

async function confirmAccept(): Promise<void> {
  if (actionUnknown.value || modifyResultUnknown.value) return
  const ok = await confirmDialog.value?.confirm({
    title: '确认订阅方案',
    message: '确认接受此订阅方案？',
    confirmLabel: '确认',
    danger: false,
  })
  if (!ok) return
  await performAction('accept', {})
}

function toggleCancelForm(): void {
  if (actionUnknown.value || modifyResultUnknown.value) return
  cancelFormOpen.value = !cancelFormOpen.value
}

function toggleModifyForm(): void {
  if (actionUnknown.value || modifyResultUnknown.value) return
  modifyFormOpen.value = !modifyFormOpen.value
  if (modifyFormOpen.value) {
    modifyError.value = ''
  }
}

async function confirmCancel(): Promise<void> {
  if (actionUnknown.value || modifyResultUnknown.value) return
  const reason = cancelReason.value.trim()
  const ok = await confirmDialog.value?.confirm({
    title: '取消订阅方案',
    message: '确认取消此订阅方案？',
    confirmLabel: '提交取消',
    danger: true,
  })
  if (!ok) return
  await performAction('cancel', { cancel_reason: reason || undefined })
}

function submitModify(patch: PreviewPatch): void {
  if (modifyResultUnknown.value || actionUnknown.value) return
  if (!Object.keys(patch).length) {
    modifyError.value = '请至少修改或清空一个字段。'
    return
  }
  modifyError.value = ''
  modifyResultUnknown.value = false
  lastModifyPatch.value = patch
  void performModify(patch)
}

function modifyPatchApplied(patch: PreviewPatch, snapshot: RequestDetailResult): boolean {
  const config = snapshot.request?.confirmable_config
  if (!config) return false
  if (patch.selected_subtitle_group !== undefined && patch.selected_subtitle_group !== config.selected_subtitle_group) return false
  if (patch.expected_folder_name !== undefined && patch.expected_folder_name !== config.expected_folder_name) return false
  if (patch.filter_rule) {
    const rule = config.filter_rule
    if (!rule) return false
    for (const key of ['must_contain', 'must_not_contain', 'use_regex', 'case_sensitive'] as const) {
      if (patch.filter_rule[key] !== undefined && patch.filter_rule[key] !== rule[key]) return false
    }
  }
  return true
}

function isUncertainWrite(error: unknown): boolean {
  const apiError = toApiError(error)
  const raw = error && typeof error === 'object' ? error as {
    type?: unknown
    status?: unknown
    network?: unknown
    cancelled?: unknown
    nonJson?: unknown
  } : {}
  const type = typeof apiError.type === 'string' ? apiError.type : raw.type
  return apiError.network || apiError.cancelled || apiError.nonJson
    || apiError.status >= 500
    || raw.network === true || raw.cancelled === true || raw.nonJson === true
    || (typeof raw.status === 'number' && raw.status >= 500)
    || type === 'network_error' || type === 'request_cancelled' || type === 'server_error'
    || type === 'upstream_timeout' || type === 'upstream_unavailable'
}

type ModifyCheck =
  | { state: 'applied' | 'not_applied'; snapshot: RequestDetailResult }
  | { state: 'unknown' }

async function recheckModify(patch: PreviewPatch): Promise<ModifyCheck> {
  const fetched = await fetchDetailSnapshot()
  if (!fetched.result) {
    lastLoadError.value = fetched.error
    return { state: 'unknown' }
  }
  return {
    state: modifyPatchApplied(patch, fetched.result) ? 'applied' : 'not_applied',
    snapshot: fetched.result,
  }
}

async function recoverModify(): Promise<void> {
  if (actionInFlight.value) return
  actionInFlight.value = true
  try {
    const fetched = await fetchDetailSnapshot()
    if (fetched.result) {
      commitDetail(fetched.result)
      modifyError.value = ''
      modifyResultUnknown.value = false
      modifyEditor.value?.reset()
    } else {
      lastLoadError.value = fetched.error
      modifyError.value = '结果暂无法确认，请重新确认结果。'
      modifyResultUnknown.value = true
    }
  } finally {
    actionInFlight.value = false
  }
}

function commitModifySuccess(snapshot: RequestDetailResult): void {
  commitDetail(snapshot)
  modifyResultUnknown.value = false
  modifyFormOpen.value = false
  lastModifyPatch.value = null
  notification.success('修改成功', `订阅方案 ${props.requestId}`)
  emit('changed')
}

async function retryModify(): Promise<void> {
  if (actionInFlight.value) return
  const patch = lastModifyPatch.value
  if (!patch) return
  if (modifyResultUnknown.value) {
    actionInFlight.value = true
    try {
      const result = await recheckModify(patch)
      if (result.state === 'applied') {
        commitModifySuccess(result.snapshot)
      } else if (result.state === 'not_applied') {
        modifyResultUnknown.value = false
        modifyError.value = '修改未生效，请重试。'
      } else {
        modifyError.value = '结果暂无法确认，请重新确认结果。'
      }
    } finally {
      actionInFlight.value = false
    }
    return
  }
  void performModify(patch)
}

async function performModify(patch: PreviewPatch): Promise<void> {
  actionInFlight.value = true
  modifyError.value = ''
  try {
    const body: ModifyRequestBody = {
      patch,
      storage_dir: storageQuery().storage_dir ?? null,
    }
    await api.post<ModifyResult>('/api/v1/requests/{request_id}/modify', {
      path: { request_id: props.requestId },
      query: storageQuery(),
      body,
    })
    const fetched = await fetchDetailSnapshot()
    if (!fetched.result) {
      lastLoadError.value = fetched.error
      modifyError.value = '结果暂无法确认，请重新确认结果。'
      modifyResultUnknown.value = true
      return
    }
    if (!modifyPatchApplied(patch, fetched.result)) {
      modifyResultUnknown.value = false
      modifyError.value = '修改未生效，请重试。'
      return
    }
    commitModifySuccess(fetched.result)
  } catch (error) {
    if (isUncertainWrite(error)) {
      const result = await recheckModify(patch)
      if (result.state === 'applied') {
        commitModifySuccess(result.snapshot)
      } else if (result.state === 'not_applied') {
        modifyResultUnknown.value = false
        modifyError.value = '修改未生效，请重试。'
      } else {
        modifyResultUnknown.value = true
        modifyError.value = '结果暂无法确认，请重新确认结果。'
      }
    } else {
      modifyResultUnknown.value = false
      modifyError.value = '修改失败，请稍后重试。'
    }
  } finally {
    actionInFlight.value = false
  }
}

type ActionCheck =
  | { state: 'applied' | 'not_applied'; snapshot?: RequestDetailResult }
  | { state: 'unknown' }

async function recheckAction(action: 'accept' | 'cancel' | 'delete'): Promise<ActionCheck> {
  const fetched = await fetchDetailSnapshot()
  if (!fetched.result) {
    lastLoadError.value = fetched.error
    if (action === 'delete' && fetched.error.status === 404) return { state: 'applied' }
    return { state: 'unknown' }
  }
  if (action === 'delete') return { state: 'not_applied', snapshot: fetched.result }
  const expectedStatus = action === 'accept' ? 'ACCEPTED' : 'CANCELLED'
  return {
    state: fetched.result.request?.status === expectedStatus ? 'applied' : 'not_applied',
    snapshot: fetched.result,
  }
}

function actionSuccessMessage(action: 'accept' | 'cancel' | 'delete'): string {
  return action === 'accept' ? '确认成功' : action === 'cancel' ? '取消成功' : '删除成功'
}

function commitActionSuccess(action: 'accept' | 'cancel', snapshot: RequestDetailResult): void {
  commitDetail(snapshot)
  actionUnknown.value = null
  cancelFormOpen.value = false
  notification.success(actionSuccessMessage(action), `订阅方案 ${props.requestId}`)
  emit('changed')
}

async function recheckPendingAction(): Promise<void> {
  const action = actionUnknown.value
  if (!action) return
  actionInFlight.value = true
  const checked = await recheckAction(action)
  if (checked.state === 'applied') {
    actionUnknown.value = null
    if (action === 'delete') {
      notification.success('删除成功', `已删除订阅方案 ${props.requestId}`)
      emit('deleted', props.requestId)
    } else if (checked.snapshot) {
      commitActionSuccess(action, checked.snapshot)
    }
  } else if (checked.state === 'not_applied') {
    actionUnknown.value = null
    notification.error('操作未生效', '操作未生效，请确认后重新发起。')
  }
  actionInFlight.value = false
}

async function confirmDelete(): Promise<void> {
  if (actionUnknown.value || modifyResultUnknown.value) return
  const ok = await confirmDialog.value?.confirm({
    title: '删除订阅方案',
    message: '确认删除此订阅方案？此操作不可恢复。',
    confirmLabel: '删除',
    danger: true,
  })
  if (!ok) return
  actionInFlight.value = true
  try {
    await api.post('/api/v1/requests/{request_id}/delete', {
      path: { request_id: props.requestId },
      query: storageQuery(),
      body: { storage_dir: storageQuery().storage_dir ?? null },
    })
    const checked = await recheckAction('delete')
    if (checked.state === 'applied') {
      notification.success('删除成功', `已删除订阅方案 ${props.requestId}`)
      emit('deleted', props.requestId)
    } else if (checked.state === 'not_applied') {
      notification.error('操作未生效', '删除未生效，请确认后重新发起。')
    } else {
      actionUnknown.value = 'delete'
      notification.error('结果暂无法确认', '操作结果暂无法确认，请重新确认结果。')
    }
  } catch (error) {
    if (isUncertainWrite(error)) {
      const checked = await recheckAction('delete')
      if (checked.state === 'applied') {
        notification.success('删除成功', `已删除订阅方案 ${props.requestId}`)
        emit('deleted', props.requestId)
      } else if (checked.state === 'not_applied') {
        notification.error('操作未生效', '删除未生效，请确认后重新发起。')
      } else {
        actionUnknown.value = 'delete'
        notification.error('结果暂无法确认', '操作结果暂无法确认，请重新确认结果。')
      }
    } else {
      void error
      notification.error('删除失败', '删除订阅方案失败，请稍后重试。')
    }
  } finally {
    actionInFlight.value = false
  }
}

async function performAction(action: 'accept' | 'cancel', body: LocalActionBody): Promise<void> {
  if (actionUnknown.value || modifyResultUnknown.value) return
  actionInFlight.value = true
  try {
    const options = {
      path: { request_id: props.requestId },
      query: storageQuery(),
      body: { ...body, storage_dir: storageQuery().storage_dir ?? null },
    }
    await api.post<ActionResult>(`/api/v1/requests/{request_id}/${action}`, options)
    const checked = await recheckAction(action)
    if (checked.state === 'applied' && checked.snapshot) {
      commitActionSuccess(action, checked.snapshot)
    } else if (checked.state === 'not_applied') {
      notification.error('操作未生效', '操作未生效，请确认后重新发起。')
    } else {
      actionUnknown.value = action
      notification.error('结果暂无法确认', '操作结果暂无法确认，请重新确认结果。')
    }
  } catch (error) {
    if (isUncertainWrite(error)) {
      const checked = await recheckAction(action)
      if (checked.state === 'applied' && checked.snapshot) {
        commitActionSuccess(action, checked.snapshot)
      } else if (checked.state === 'not_applied') {
        notification.error('操作未生效', '操作未生效，请确认后重新发起。')
      } else {
        actionUnknown.value = action
        notification.error('结果暂无法确认', '操作结果暂无法确认，请重新确认结果。')
      }
      return
    }
    const messages: Record<string, string> = {
      accept: '确认失败，请稍后重试。',
      cancel: '取消失败，请稍后重试。',
    }
    notification.error('操作失败', messages[action] ?? '操作失败，请稍后重试。')
  } finally {
    actionInFlight.value = false
  }
}

defineExpose({ loadDetail })

onMounted(() => {
  void loadDetail()
})

</script>
<template>
  <PanelSection v-if="!loading && !loadFailed && detail" title="订阅方案详情" class="request-detail-panel">
    <template #actions>
      <BaseButton id="detail-safe-info-button" :disabled="actionInFlight" @click="safeInfoOpen = true">全部信息</BaseButton>
      <RouterLink
        v-if="props.trackingId && effectiveTrackingStatus === 'linked'"
        id="detail-tracking-entry"
        class="base-button secondary-button"
        :to="routeLocation('tracking', { tracking_id: props.trackingId })"
      >前往追番管理</RouterLink>
      <span v-else-if="effectiveTrackingStatus === 'loading'" class="field-help">追番状态：正在读取追番状态...</span>
      <span v-else-if="effectiveTrackingStatus === 'failed' || effectiveTrackingStatus === 'unavailable'" class="field-help">追番状态：追番状态暂不可用</span>
      <span v-else class="field-help">追番状态：{{ props.trackingStatusLabel || '未进入追番管理' }}</span>
    </template>

    <div id="request-detail-container" class="request-detail" aria-live="polite" aria-relevant="additions text">
      <h3 class="request-detail-title">{{ detail.request?.input?.raw_title || detail.request?.source_info?.matched_bangumi?.title || '订阅方案' }}</h3>

      <!-- ── actions ─────────────────────────────────────────────── -->
      <div class="detail-actions" aria-label="订阅方案操作">
        <template v-if="isPending">
          <BaseButton id="detail-accept-button" variant="primary" :loading="actionInFlight" :disabled="Boolean(actionUnknown) || modifyResultUnknown" @click="confirmAccept">
            确认
          </BaseButton>
          <BaseButton id="detail-cancel-toggle" :disabled="actionInFlight || Boolean(actionUnknown) || modifyResultUnknown" @click="toggleCancelForm">
            取消
          </BaseButton>
          <BaseButton id="detail-modify-toggle" :disabled="actionInFlight || Boolean(actionUnknown) || modifyResultUnknown" @click="toggleModifyForm">
            修改
          </BaseButton>
        </template>

        <template v-else-if="isAccepted">
          <p class="field-help">
            此订阅方案已{{ detailStatusLabel(request?.status) }}，可进行本地方案修改或删除。
          </p>
          <BaseButton id="detail-accepted-modify-toggle" :disabled="actionInFlight || Boolean(actionUnknown) || modifyResultUnknown" @click="toggleModifyForm">
            修改
          </BaseButton>
          <BaseButton id="detail-delete-button" variant="danger" :disabled="actionInFlight || Boolean(actionUnknown) || modifyResultUnknown" @click="confirmDelete">
            删除
          </BaseButton>
        </template>

        <template v-else-if="isCancelled">
          <p class="field-help">此订阅方案已{{ detailStatusLabel(request?.status) }}，不可操作。</p>
        </template>
      </div>

      <div v-if="actionUnknown" class="detail-action-recovery" role="alert">
        <span class="field-error">结果暂无法确认</span>
        <BaseButton id="detail-action-recheck-button" type="button" variant="secondary" :loading="actionInFlight" @click="recheckPendingAction">
          重新确认结果
        </BaseButton>
      </div>

      <!-- ── inline cancel form ──────────────────────────────────── -->
      <form
        v-if="cancelFormOpen"
        id="detail-cancel-form"
        class="detail-inline-form"
        @submit.prevent="confirmCancel"
      >
        <h4 class="detail-form-heading">取消订阅方案</h4>
        <FormField label="取消原因（可选）" inputId="cancel-reason">
          <BaseTextarea
            id="cancel-reason"
            v-model="cancelReason"
            rows="3"
            placeholder="例如：暂时不订阅，或匹配结果不符合预期"
          />
        </FormField>
        <div class="detail-form-actions">
          <BaseButton id="detail-cancel-submit" type="submit" variant="danger" :loading="actionInFlight" :disabled="Boolean(actionUnknown) || modifyResultUnknown">
            提交取消
          </BaseButton>
          <BaseButton type="button" :disabled="actionInFlight" @click="cancelFormOpen = false">
            收起
          </BaseButton>
        </div>
      </form>

      <AnimeDraftEditor
        v-if="modifyFormOpen && request"
        ref="modifyEditor"
        :request="request"
        mode="saved"
        heading="修改订阅方案"
        form-heading="编辑已保存方案"
        apply-label="保存方案修改"
        id-prefix="modify"
        container-id="detail-modify-editor"
        form-id="detail-modify-form"
        :applying="actionInFlight"
        :error="modifyError"
        :can-retry="Boolean(modifyError)"
        :retry-label="modifyResultUnknown ? '重新确认结果' : '重试修改'"
        :disabled="Boolean(actionUnknown) || modifyResultUnknown"
        @apply="submitModify"
        @empty-apply="submitModify({})"
        @retry="retryModify"
        @reset="recoverModify"
      />

      <!-- ── Overview ────────────────────────────────────────────── -->
      <section class="detail-section overview-section" aria-label="Overview">
        <h4 class="detail-section-heading">Overview</h4>
        <dl class="detail-grid">
          <div class="detail-row"><dt>request_id</dt><dd>{{ displayValue(request?.request_id) }}</dd></div>
          <div class="detail-row"><dt>状态</dt><dd>{{ detailStatusLabel(request?.status) }}</dd></div>
          <div class="detail-row"><dt>修改时间</dt><dd>{{ displayValue(request?.updated_at) }}</dd></div>
          <div class="detail-row"><dt>保存状态</dt><dd>已保存</dd></div>
          <div class="detail-row"><dt>原始标题</dt><dd>{{ displayValue(request?.input?.raw_title) }}</dd></div>
          <div class="detail-row">
            <dt>匹配标题</dt>
            <dd>{{ displayValue(request?.source_info?.matched_bangumi?.title) }}</dd>
          </div>
        </dl>
      </section>

      <!-- ── Source ──────────────────────────────────────────────── -->
      <section class="detail-section source-section" aria-label="Source">
        <h4 class="detail-section-heading">Source</h4>
        <dl class="detail-grid">
          <div class="detail-row">
            <dt>字幕组</dt>
            <dd>{{ displayValue(request?.confirmable_config?.selected_subtitle_group) }}</dd>
          </div>
          <div class="detail-row">
            <dt>RSS 来源</dt>
            <dd>{{ request?.confirmable_config?.selected_rss_url ? '已选择' : '未选择' }}</dd>
          </div>
          <div class="detail-row">
            <dt>匹配番剧标题</dt>
            <dd>{{ displayValue(request?.source_info?.matched_bangumi?.title) }}</dd>
          </div>
        </dl>
      </section>

      <!-- ── Filter ──────────────────────────────────────────────── -->
      <section class="detail-section filter-section" aria-label="Filter">
        <h4 class="detail-section-heading">Filter</h4>
        <dl class="detail-grid">
          <div class="detail-row">
            <dt>包含规则</dt>
            <dd>{{ displayValue(request?.confirmable_config?.filter_rule?.must_contain) }}</dd>
          </div>
          <div class="detail-row">
            <dt>排除规则</dt>
            <dd>{{ displayValue(request?.confirmable_config?.filter_rule?.must_not_contain) }}</dd>
          </div>
          <div class="detail-row">
            <dt>匹配模式</dt>
            <dd>{{ request?.confirmable_config?.filter_rule?.use_regex === true ? '正则' : '普通字符' }}</dd>
          </div>
          <div class="detail-row">
            <dt>大小写</dt>
            <dd>{{ request?.confirmable_config?.filter_rule?.case_sensitive === true ? '区分大小写' : '不区分大小写' }}</dd>
          </div>
          <div class="detail-row">
            <dt>folder_name</dt>
            <dd>{{ displayValue(request?.confirmable_config?.expected_folder_name) }}</dd>
          </div>
          <div class="detail-row">
            <dt>有效种子数</dt>
            <dd>{{ effective.length }}</dd>
          </div>
          <div class="detail-row">
            <dt>排除种子数</dt>
            <dd>{{ excluded.length }}</dd>
          </div>
        </dl>
      </section>

      <!-- ── Seeds ───────────────────────────────────────────────── -->
      <section class="detail-section seeds-section" aria-label="Seeds">
        <h4 class="detail-section-heading">Seeds</h4>

        <details class="seed-details seed-group effective-seed-group" open>
          <summary>有效种子（当前选中字幕组：{{ selectedGroupName }}）({{ effective.length }})</summary>
          <ul v-if="effective.length" class="seed-list">
            <li v-for="seed in effective" :key="seed">{{ seed }}</li>
          </ul>
          <p v-else class="muted-text">无有效种子标题。</p>
        </details>

        <details class="seed-details complete-seed-details">
          <summary>完整种子（按字幕组分组）({{ completeTotal }})</summary>
          <div class="seed-groups complete-seed-groups">
            <template v-if="completeGroups.length">
              <details v-for="group in completeGroups" :key="group.subtitleGroup" class="subgroup-seed-group">
                <summary>{{ group.subtitleGroup }} ({{ group.seedNames.length }})</summary>
                <ul v-if="group.seedNames.length" class="seed-list">
                  <li v-for="seed in group.seedNames" :key="seed">{{ seed }}</li>
                </ul>
                <p v-else class="muted-text">无种子标题。</p>
              </details>
            </template>
            <p v-else class="muted-text">无种子标题。</p>
          </div>
        </details>

        <details class="seed-details excluded-seed-details">
          <summary>排除种子 ({{ excluded.length }})</summary>
          <div class="seed-group">
            <ul v-if="excluded.length" class="seed-list excluded-seed-list">
              <li v-for="seed in excluded" :key="`${seed.name}-${seed.reason}`">
                {{ seed.name }}<span v-if="seed.reason" class="seed-exclude-reason"> - {{ seed.reason }}</span>
              </li>
            </ul>
            <p v-else class="muted-text">无排除种子标题。</p>
          </div>
        </details>
      </section>

      <!-- ── Audit ───────────────────────────────────────────────── -->
      <section class="detail-section audit-section" aria-label="Audit">
        <h4 class="detail-section-heading">Audit</h4>

        <div class="audit-group">
          <h5 class="audit-heading">状态历史</h5>
          <template v-if="detail.history?.error">
            <p class="muted-text">状态历史暂不可用。</p>
          </template>
          <template v-else-if="detail.history?.events?.length">
            <table class="history-table">
              <thead>
                <tr><th>操作</th><th>前一状态</th><th>后一状态</th><th>时间</th></tr>
              </thead>
              <tbody>
                <tr v-for="(event, index) in detail.history.events" :key="`${event.timestamp}-${index}`">
                  <td>{{ actionLabel(event.action) }}</td>
                  <td>{{ detailStatusLabel(event.previous_status) }}</td>
                  <td>{{ detailStatusLabel(event.next_status) }}</td>
                  <td>{{ displayValue(event.timestamp) }}</td>
                </tr>
              </tbody>
            </table>
          </template>
          <p v-else class="muted-text">暂无状态历史。</p>
        </div>

        <div class="audit-group">
          <h5 class="audit-heading">Auto Bangumi 结果</h5>
          <template v-if="detail.ab_result?.error">
            <p class="muted-text">提交结果暂不可用。</p>
          </template>
          <template v-else-if="detail.ab_result?.record?.ab_submit_result">
            <dl class="detail-grid">
              <div class="detail-row">
                <dt>success</dt><dd>{{ String(detail.ab_result.record.ab_submit_result.success ?? '未设置') }}</dd>
              </div>
              <div class="detail-row">
                <dt>ab_subscription_id</dt>
                <dd>{{ displayValue(detail.ab_result.record.ab_submit_result.ab_subscription_id) }}</dd>
              </div>
              <div class="detail-row">
                <dt>fallback_config</dt>
                <dd>{{ detail.ab_result.record.ab_submit_result.fallback_config ? '存在' : '无' }}</dd>
              </div>
            </dl>
            <details v-if="detail.ab_result.record.ab_submit_result.fallback_config" class="fallback-config">
              <summary>查看 fallback_config</summary>
              <pre class="fallback-config-content">{{
                JSON.stringify(
                  scrubConfig(detail.ab_result.record.ab_submit_result.fallback_config),
                  null,
                  2,
                )
              }}</pre>
            </details>
          </template>
          <p v-else class="muted-text">暂无 Auto Bangumi 提交结果。</p>
        </div>
      </section>
    </div>

    <ConfirmDialog ref="confirmDialog" />
    <SafeInfoDialog :open="safeInfoOpen" :request-id="props.requestId" @close="safeInfoOpen = false" @reuse="reuseRequest" />
  </PanelSection>

  <PanelSection v-else title="订阅方案详情" class="request-detail-panel">
    <div id="request-detail-container" class="request-detail">
      <LoadingState v-if="loading" message="正在加载订阅方案详情..." />
      <ErrorState
        v-else-if="loadFailed"
        title="订阅方案详情加载失败"
        message="请确认 request_id 是否存在。"
        retry-label="重试"
        @retry="loadDetail"
      />
      <p v-else class="muted-text">选择一个订阅方案后查看详情。</p>
    </div>
  </PanelSection>
</template>

<style scoped>
.request-detail {
  display: grid;
  gap: 1rem;
}

.request-detail-title {
  margin: 0;
  font-size: 1.15rem;
}

.detail-actions {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 0.5rem;
}

.detail-actions .field-help {
  margin: 0;
}

.detail-inline-form {
  display: grid;
  gap: 0.75rem;
  border: 1px solid var(--color-border);
  border-radius: 6px;
  padding: 1rem;
}

.detail-form-heading {
  margin: 0;
  font-size: 1rem;
}

.detail-form-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 0.5rem;
}

.filter-options {
  display: flex;
  flex-wrap: wrap;
  gap: 0.5rem 1.25rem;
}

.detail-section {
  display: grid;
  gap: 0.5rem;
}

.detail-section-heading {
  margin: 0;
  font-size: 1rem;
  border-bottom: 1px solid var(--color-border);
  padding-bottom: 0.25rem;
}

.detail-grid {
  margin: 0;
  display: grid;
  gap: 0.3rem 1rem;
  grid-template-columns: max-content 1fr;
}

.detail-row {
  display: contents;
}

.detail-row dt {
  font-weight: 600;
  color: var(--color-text-muted);
}

.detail-row dd {
  margin: 0;
  overflow-wrap: anywhere;
}

.seed-details {
  border: 1px solid var(--color-border);
  border-radius: 6px;
  padding: 0.5rem 0.75rem;
}

.seed-details summary {
  cursor: pointer;
  font-weight: 500;
}

.seed-list {
  margin: 0.5rem 0 0;
  padding-left: 1.25rem;
  display: grid;
  gap: 0.25rem;
}

.excluded-seed-list .seed-exclude-reason {
  color: var(--color-text-muted);
}

.muted-text {
  color: var(--color-text-muted);
  margin: 0.25rem 0 0;
}

.audit-group {
  display: grid;
  gap: 0.5rem;
}

.audit-heading {
  margin: 0;
  font-size: 0.95rem;
}

.history-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 0.875rem;
}

.history-table th,
.history-table td {
  border: 1px solid var(--color-border);
  padding: 0.375rem 0.5rem;
  text-align: left;
}

.fallback-config-content {
  overflow-x: auto;
  background: var(--color-bg-muted);
  padding: 0.75rem;
  border-radius: 6px;
  font-size: 0.8125rem;
  max-width: 100%;
}

@media (max-width: 720px) {
  .detail-grid {
    grid-template-columns: 1fr;
    gap: 0.2rem;
  }

  .history-table {
    display: block;
    overflow-x: auto;
  }
}
</style>
