<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, ref, watch } from 'vue'

import { api, toApiError } from '@/api/client'
import type { operations } from '@/api/generated/api'
import BaseButton from '@/components/forms/BaseButton.vue'
import ErrorState from '@/components/feedback/ErrorState.vue'
import LoadingState from '@/components/feedback/LoadingState.vue'
import { routeLocation } from '@/app/router/catalog'
import { storageQuery } from '@/features/requests/requestStorage'
import {
  createTrackingActionIntent,
  executableTrackingActions,
  projectRevalidateIssues,
  type CapabilityResult,
  type TrackingAction,
  type TrackingActionIntent,
  type TrackingItem,
  type TrackingRevalidateBody,
  type TrackingRevalidateIssueView,
  type TrackingRevalidateResult,
  type TrackingWriteSession,
} from './trackingProjection'

type TrackingDetail = NonNullable<
  operations['getTrackingItemDetail']['responses']['200']['content']['application/json']['result']
>

type RevalidateState = 'IDLE' | 'READY' | 'BLOCKED' | 'CONFLICT' | 'FAILED'

const props = defineProps<{
  trackingId: string
  /** Non-null only while the page holds a credential session (US-307). */
  capabilities?: CapabilityResult | null
  /** True only while the page credential session is live; the page owns it. */
  credentialReady?: boolean
  /** Page-level external write state for one item; the page owns the request. */
  writeSession?: TrackingWriteSession | null
  /** Another item's unresolved external write still holds the single page intent. */
  writeBusy?: boolean
}>()
const emit = defineEmits<{
  (e: 'tracking-updated', tracking: TrackingItem): void
  (e: 'write-requested', payload: { action: TrackingAction; item: TrackingItem }): void
}>()
const detail = ref<TrackingDetail | null>(null)
const loading = ref(false)
const failed = ref(false)
const inspectorHeading = ref<HTMLElement | null>(null)
let requestSequence = 0
let controller: AbortController | null = null

// -- local revalidation (US-309) --------------------------------------------
// Revalidation is a pure-local, revision-aware check: it never carries
// credentials and never contacts Auto Bangumi.  Exactly one intent is held in
// page memory (latest revision + opaque key); a transport retry reuses it and
// a 409 clears it so the user must confirm again against fresh detail.
const revalidateIntent = ref<TrackingActionIntent | null>(null)
const revalidateLoading = ref(false)
const revalidateState = ref<RevalidateState>('IDLE')
const revalidateMessage = ref('')
const revalidateIssues = ref<TrackingRevalidateIssueView[]>([])
let revalidateSequence = 0
let revalidateController: AbortController | null = null

/** The server-computed REVALIDATE action, intersected with known values. */
const revalidateAction = computed(() => (
  detail.value ? executableTrackingActions(detail.value, null).find((action) => action.code === 'REVALIDATE') ?? null : null
))

// -- explicit external submission and retry (US-310, US-311) -----------------
// The page owns the credential and the request; this component only offers the
// server-computed write action when the page session proves the capability, and
// renders the fixed page-level write result.  No key, credential or request
// state ever lives here.  SUBMIT and RETRY are mutually exclusive on the server
// (different source statuses), so at most one of them is ever projected.
const writeInFlight = computed(() => (
  props.writeSession?.trackingId === props.trackingId && props.writeSession.state === 'IN_FLIGHT'
))
const thisWrite = computed(() => (
  props.writeSession && props.writeSession.trackingId === props.trackingId ? props.writeSession : null
))
/** The server-computed write actions, intersected with the proven capability. */
const writeActions = computed(() => (
  detail.value && props.credentialReady === true
    ? executableTrackingActions(detail.value, props.capabilities)
    : []
))
const submitAction = computed(() => writeActions.value.find((action) => action.code === 'SUBMIT') ?? null)
const retryAction = computed(() => writeActions.value.find((action) => action.code === 'RETRY') ?? null)
const writeHint = computed(() => {
  if (props.credentialReady !== true) return '需要先在页面连接 Auto Bangumi，才能提交或重试外部订阅。'
  const offered = (detail.value?.available_actions ?? []).some(
    (action) => action.code === 'SUBMIT' || action.code === 'RETRY',
  )
  return offered ? '当前连接未确认提交能力，已降级为只读。' : '当前状态不可提交或重试外部订阅。'
})

function requestWrite(action: TrackingAction | null): void {
  if (!action || !detail.value || writeInFlight.value || props.writeBusy) return
  // The page confirms, builds the intent (fresh revision + opaque key) and sends.
  emit('write-requested', { action, item: detail.value })
}

function resetRevalidate(): void {
  revalidateSequence += 1
  revalidateController?.abort()
  revalidateController = null
  revalidateIntent.value = null
  revalidateLoading.value = false
  revalidateState.value = 'IDLE'
  revalidateMessage.value = ''
  revalidateIssues.value = []
}

/** Converge the shared summary fields on the server-returned safe tracking. */
function applyReturnedTracking(summary: TrackingItem): void {
  if (!detail.value || summary.tracking_id !== props.trackingId) return
  detail.value = { ...detail.value, ...summary }
  emit('tracking-updated', summary)
}

async function revalidatePlan(): Promise<void> {
  // Revalidation rewrites the local revision, so it is a conflicting action of
  // this item while an external submit is in flight.
  if (revalidateLoading.value || writeInFlight.value || !detail.value) return
  const action = revalidateAction.value
  if (!action) return
  // One intent per user confirmation; a transport retry below reuses the same
  // intent (same revision) instead of building a new one.
  const intent = revalidateIntent.value ?? createTrackingActionIntent(detail.value, action, undefined, null)
  if (!intent) return
  revalidateIntent.value = intent
  const trackingId = props.trackingId
  const sequence = ++revalidateSequence
  revalidateController?.abort()
  const requestController = new AbortController()
  revalidateController = requestController
  revalidateLoading.value = true
  revalidateState.value = 'IDLE'
  revalidateMessage.value = ''
  revalidateIssues.value = []
  try {
    const storageDir = storageQuery().storage_dir
    const body: TrackingRevalidateBody = {
      expected_revision: intent.expectedRevision,
      ...(storageDir ? { storage_dir: storageDir } : {}),
    }
    const result = await api.post<TrackingRevalidateResult>(
      '/api/v1/tracking/items/{tracking_id}/revalidate',
      { path: { tracking_id: trackingId }, body, signal: requestController.signal },
    )
    if (sequence !== revalidateSequence || props.trackingId !== trackingId) return
    // The round trip completed: this intent is spent, so the next user
    // confirmation observes whatever revision the server just returned.
    revalidateIntent.value = null
    revalidateIssues.value = projectRevalidateIssues(result.issues)
    revalidateState.value = result.ready ? 'READY' : 'BLOCKED'
    revalidateMessage.value = result.ready
      ? '复核通过：本地方案有效，尚未向 Auto Bangumi 创建订阅。'
      : '提交前复核未通过，尚未向 Auto Bangumi 创建订阅。'
    applyReturnedTracking(result.tracking)
  } catch (error) {
    if (sequence !== revalidateSequence || props.trackingId !== trackingId) return
    const apiError = toApiError(error)
    if (apiError.cancelled && !apiError.httpError) return
    if (apiError.status === 409) {
      // Revision/state conflict: drop the stale intent, re-read the detail and
      // require an explicit new confirmation — never resend on the user's behalf.
      revalidateIntent.value = null
      revalidateIssues.value = []
      revalidateState.value = 'CONFLICT'
      revalidateMessage.value = '追番记录已变化，正在刷新最新详情；请重新确认后再发起复核。'
      await loadDetail()
      return
    }
    // Transport failures keep the intent so an explicit retry reuses it.
    revalidateState.value = 'FAILED'
    revalidateMessage.value = '复核请求失败，请稍后重试。'
  } finally {
    if (sequence === revalidateSequence) {
      revalidateLoading.value = false
      if (revalidateController === requestController) revalidateController = null
    }
  }
}

/**
 * ``preserve`` keeps the current detail visible while re-reading (US-310 write
 * read-back): blanking or re-focusing the panel after a write would both hide
 * the write result and steal focus from it.
 */
async function fetchDetail(preserve: boolean): Promise<void> {
  const sequence = ++requestSequence
  controller?.abort()
  const requestController = new AbortController()
  controller = requestController
  if (!preserve) {
    loading.value = true
    failed.value = false
    detail.value = null
  }
  try {
    const nextDetail = await api.get<TrackingDetail>('/api/v1/tracking/items/{tracking_id}', {
      path: { tracking_id: props.trackingId },
      query: storageQuery(),
      signal: requestController.signal,
    })
    if (sequence !== requestSequence || requestController.signal.aborted) return
    detail.value = nextDetail
    if (preserve) return
    await nextTick()
    if (sequence === requestSequence) inspectorHeading.value?.focus({ preventScroll: true })
  } catch (error) {
    if (sequence !== requestSequence || requestController.signal.aborted) return
    if (!preserve) failed.value = true
    void error
  } finally {
    if (sequence === requestSequence && !preserve) loading.value = false
  }
}

function loadDetail(): Promise<void> {
  return fetchDetail(false)
}

watch(() => props.trackingId, () => {
  resetRevalidate()
  void loadDetail()
}, { immediate: true })
// A write result supersedes a local revalidate verdict for the same item.
watch(() => props.writeSession, (session) => {
  if (session && session.trackingId === props.trackingId) resetRevalidate()
})
onBeforeUnmount(() => {
  controller?.abort()
  requestSequence += 1
  resetRevalidate()
})
defineExpose({ reload: () => fetchDetail(true) })
</script>

<template>
  <section class="tracking-inspector-content" aria-labelledby="tracking-inspector-heading">
    <h2 id="tracking-inspector-heading">检查器</h2>
    <div v-if="loading" class="tracking-inspector-loading"><LoadingState message="正在读取安全详情…" /></div>
    <ErrorState v-else-if="failed" title="追番详情读取失败" message="暂时无法读取该追番详情，请稍后重试。" retry-label="重试详情" @retry="loadDetail" />
    <div v-else-if="detail" class="tracking-inspector-detail">
      <section ref="inspectorHeading" tabindex="-1" class="tracking-inspector-summary" aria-labelledby="tracking-inspector-title">
        <p class="field-help">安全追番摘要</p>
        <h3 id="tracking-inspector-title">{{ detail.title || '未命名番剧' }}</h3>
        <dl>
          <div><dt>季度</dt><dd>{{ detail.season ?? '未设置' }}</dd></div>
          <div><dt>字幕组</dt><dd>{{ detail.subtitle_group || '未设置' }}</dd></div>
          <div><dt>有效资源</dt><dd>{{ detail.valid_resource_count }}</dd></div>
          <div><dt>总集数</dt><dd>{{ detail.total_episodes ?? '待获取' }}</dd></div>
          <div><dt>已更新集数</dt><dd>待开发</dd></div>
          <div><dt>本地状态</dt><dd>{{ detail.status_label }}</dd></div>
        </dl>
      </section>

      <section v-if="detail.external_mapping" class="tracking-inspector-section" aria-labelledby="tracking-external-heading">
        <h4 id="tracking-external-heading">外部安全摘要</h4>
        <dl>
          <div><dt>关联状态</dt><dd>{{ detail.external_mapping.match_reason || '未提供' }}</dd></div>
          <div><dt>启用状态</dt><dd>{{ detail.external_mapping.enabled ? '已启用' : '未启用' }}</dd></div>
          <div><dt>外部删除</dt><dd>{{ detail.external_mapping.external_deleted ? '是' : '否' }}</dd></div>
        </dl>
      </section>

      <section v-if="detail.current_operation" class="tracking-inspector-section" aria-labelledby="tracking-operation-heading">
        <h4 id="tracking-operation-heading">最近操作</h4>
        <p>{{ detail.current_operation.operation }} · {{ detail.current_operation.state }} · 第 {{ detail.current_operation.attempt }} 次</p>
      </section>

      <section v-if="detail.revalidation_issues?.length" class="tracking-inspector-section" aria-labelledby="tracking-issues-heading">
        <h4 id="tracking-issues-heading">复核问题</h4>
        <ul><li v-for="issue in detail.revalidation_issues" :key="`${issue.code}-${issue.field ?? ''}`">{{ issue.message }}</li></ul>
      </section>

      <section v-if="detail.audit_events?.length" class="tracking-inspector-section" aria-labelledby="tracking-audit-heading">
        <h4 id="tracking-audit-heading">安全审计</h4>
        <ul><li v-for="event in detail.audit_events" :key="`${event.action}-${event.created_at}`">{{ event.safe_message || event.action }} · {{ event.created_at }}</li></ul>
      </section>

      <section class="tracking-inspector-section tracking-revalidate" aria-labelledby="tracking-revalidate-heading">
        <h4 id="tracking-revalidate-heading">本地方案复核</h4>
        <p class="field-help">复核只在本地读取订阅方案，不携带任何 Auto Bangumi 凭据，也不会创建外部订阅。</p>
        <BaseButton
          v-if="revalidateAction"
          id="tracking-revalidate"
          variant="secondary"
          :loading="revalidateLoading"
          :disabled="revalidateLoading || writeInFlight"
          @click="revalidatePlan"
        >{{ revalidateAction.label }}</BaseButton>
        <p v-else class="field-help">当前状态不可发起本地复核。</p>
        <div
          v-if="revalidateState !== 'IDLE'"
          id="tracking-revalidate-result"
          class="tracking-revalidate-result"
          :class="`is-${revalidateState.toLowerCase()}`"
          role="status"
        >
          <p class="tracking-revalidate-verdict">{{ revalidateMessage }}</p>
          <ul v-if="revalidateIssues.length" class="tracking-revalidate-issues" aria-label="复核问题">
            <li v-for="issue in revalidateIssues" :key="issue.code">{{ issue.message }}</li>
          </ul>
        </div>
      </section>

      <section class="tracking-inspector-section tracking-submit" aria-labelledby="tracking-submit-heading">
        <h4 id="tracking-submit-heading">提交到 Auto Bangumi</h4>
        <template v-if="submitAction">
          <p class="field-help">提交会使用本页面已探测的连接，在 Auto Bangumi 创建外部订阅并可能触发下载；每次提交都需要单独确认。</p>
          <BaseButton
            id="tracking-submit"
            :loading="writeInFlight"
            :disabled="writeInFlight || writeBusy"
            @click="requestWrite(submitAction)"
          >{{ submitAction.label }}</BaseButton>
        </template>
        <template v-else-if="retryAction">
          <p class="field-help">该记录上次提交明确失败。重试会使用本页面已探测的连接，重新在 Auto Bangumi 创建外部订阅并可能触发下载；每次重试都需要单独确认。</p>
          <BaseButton
            id="tracking-retry"
            :loading="writeInFlight"
            :disabled="writeInFlight || writeBusy"
            @click="requestWrite(retryAction)"
          >{{ retryAction.label }}</BaseButton>
        </template>
        <p v-else class="field-help">{{ writeHint }}</p>
        <div
          v-if="thisWrite"
          id="tracking-submit-result"
          class="tracking-submit-result"
          :class="`is-${thisWrite.state.toLowerCase()}`"
          role="status"
        >
          <p class="tracking-submit-verdict">{{ thisWrite.message }}</p>
          <ul v-if="thisWrite.issues.length" class="tracking-submit-issues" aria-label="提交问题">
            <li v-for="issue in thisWrite.issues" :key="issue.code">{{ issue.message }}</li>
          </ul>
        </div>
      </section>

      <p v-if="detail.status === 'EXTERNAL_ONLY'" class="field-help" role="status">
        该记录是外部孤立项，没有可返回的本地订阅方案。
      </p>
      <p v-else-if="!detail.request_id" class="field-help" role="status">
        该记录没有可返回的本地订阅方案。
      </p>
      <RouterLink v-else class="tracking-plan-link" :to="routeLocation('plans', { request_id: detail.request_id })">
        返回修改方案
      </RouterLink>
      <ul v-if="detail.safe_info?.resources?.valid_file_names?.length" class="tracking-resource-names" aria-label="有效资源名称">
        <li v-for="name in detail.safe_info.resources.valid_file_names" :key="name">{{ name }}</li>
      </ul>
      <p v-if="detail.warnings?.length" class="field-help" role="status">{{ detail.warnings[0] }}</p>
    </div>
    <p v-else class="field-help">选择一条追番记录查看安全检查器。</p>
  </section>
</template>

<style scoped>
.tracking-inspector-content { display: grid; gap: var(--space-3); }
.tracking-inspector-content h2, .tracking-inspector-content h3, .tracking-inspector-content h4, .tracking-inspector-content p { margin: 0; }
.tracking-inspector-detail, .tracking-inspector-summary, .tracking-inspector-section { display: grid; gap: .55rem; }
.tracking-inspector-summary, .tracking-inspector-section { padding: var(--space-3); border: 1px solid var(--color-border); border-radius: var(--radius-md); }
.tracking-inspector-summary:focus-visible { outline: 2px solid var(--color-primary); outline-offset: 2px; }
.tracking-inspector-detail dl { display: grid; gap: .35rem; margin: 0; }
.tracking-inspector-detail dl div { display: flex; justify-content: space-between; gap: 1rem; }
.tracking-inspector-detail dt { color: var(--color-text-muted); }
.tracking-inspector-detail dd { margin: 0; text-align: right; font-weight: 600; }
.tracking-inspector-section ul, .tracking-resource-names { display: grid; gap: .3rem; margin: 0; padding-left: 1.2rem; }
.tracking-plan-link { font-weight: 600; }
.tracking-inspector-loading { min-height: 8rem; }
.tracking-revalidate { gap: .65rem; }
.tracking-revalidate-result { display: grid; gap: .4rem; padding: var(--space-3); border: 1px solid var(--color-border-subtle); border-left: 0.3rem solid var(--color-text-muted); border-radius: var(--radius-sm); background: var(--color-surface-raised); }
.tracking-revalidate-result.is-ready { border-left-color: var(--color-feedback-success-border); }
.tracking-revalidate-result.is-blocked, .tracking-revalidate-result.is-conflict { border-left-color: var(--color-accent-emphasis); }
.tracking-revalidate-result.is-failed { border-left-color: var(--color-feedback-error-border); }
.tracking-revalidate-verdict { font-weight: 600; }
.tracking-revalidate-issues { padding-left: 1.2rem; }
.tracking-submit { gap: .65rem; }
.tracking-submit-result { display: grid; gap: .4rem; padding: var(--space-3); border: 1px solid var(--color-border-subtle); border-left: 0.3rem solid var(--color-text-muted); border-radius: var(--radius-sm); background: var(--color-surface-raised); }
.tracking-submit-result.is-active { border-left-color: var(--color-feedback-success-border); }
.tracking-submit-result.is-submit_failed, .tracking-submit-result.is-conflict, .tracking-submit-result.is-rejected, .tracking-submit-result.is-unknown { border-left-color: var(--color-feedback-error-border); }
.tracking-submit-result.is-needs_reconfirm, .tracking-submit-result.is-verifying_external, .tracking-submit-result.is-recovery_required { border-left-color: var(--color-accent-emphasis); }
.tracking-submit-verdict { font-weight: 600; }
.tracking-submit-issues { padding-left: 1.2rem; }
</style>
