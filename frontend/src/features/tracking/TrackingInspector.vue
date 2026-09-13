<script setup lang="ts">
import { nextTick, onBeforeUnmount, ref, watch } from 'vue'

import { api } from '@/api/client'
import type { operations } from '@/api/generated/api'
import ErrorState from '@/components/feedback/ErrorState.vue'
import LoadingState from '@/components/feedback/LoadingState.vue'
import { routeLocation } from '@/app/router/catalog'
import { storageQuery } from '@/features/requests/requestStorage'

type TrackingDetail = NonNullable<
  operations['getTrackingItemDetail']['responses']['200']['content']['application/json']['result']
>

const props = defineProps<{ trackingId: string; fallbackRequestId?: string | null }>()
const detail = ref<TrackingDetail | null>(null)
const loading = ref(false)
const failed = ref(false)
const inspectorHeading = ref<HTMLElement | null>(null)
let requestSequence = 0
let controller: AbortController | null = null

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

watch(() => props.trackingId, () => { void loadDetail() }, { immediate: true })
onBeforeUnmount(() => { controller?.abort(); requestSequence += 1 })
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

      <p v-if="detail.status === 'EXTERNAL_ONLY' || !detail.request_id" class="field-help" role="status">
        该记录没有可返回的本地订阅方案。
      </p>
      <RouterLink v-else class="tracking-plan-link" :to="routeLocation('plans', { request_id: detail.request_id })">
        查看本地订阅方案
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
</style>
