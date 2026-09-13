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
  type TrackingActionIntent,
  type TrackingItem,
  type TrackingRevalidateBody,
  type TrackingRevalidateIssueView,
  type TrackingRevalidateResult,
} from './trackingProjection'

type TrackingDetail = NonNullable<
  operations['getTrackingItemDetail']['responses']['200']['content']['application/json']['result']
>

type RevalidateState = 'IDLE' | 'READY' | 'BLOCKED' | 'CONFLICT' | 'FAILED'

const props = defineProps<{ trackingId: string }>()
const emit = defineEmits<{ (e: 'tracking-updated', tracking: TrackingItem): void }>()
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
  if (revalidateLoading.value || !detail.value) return
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

async function loadDetail(): Promise<void> {
  const sequence = ++requestSequence
  controller?.abort()
  controller = new AbortController()
  loading.value = true
  failed.value = false
  detail.value = null
  try {
    const nextDetail = await api.get<TrackingDetail>('/api/v1/tracking/items/{tracking_id}', {
      path: { tracking_id: props.trackingId },
      query: storageQuery(),
      signal: controller.signal,
    })
    if (sequence !== requestSequence || controller.signal.aborted) return
    detail.value = nextDetail
    await nextTick()
    if (sequence === requestSequence) inspectorHeading.value?.focus({ preventScroll: true })
  } catch (error) {
    if (sequence !== requestSequence || controller.signal.aborted) return
    failed.value = true
    void error
  } finally {
    if (sequence === requestSequence) loading.value = false
  }
}

watch(() => props.trackingId, () => {
  resetRevalidate()
  void loadDetail()
}, { immediate: true })
onBeforeUnmount(() => {
  controller?.abort()
  requestSequence += 1
  resetRevalidate()
})
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
</style>
