<script setup lang="ts">
import { nextTick, onMounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'

import { api } from '@/api/client'
import type { operations } from '@/api/generated/api'
import EmptyState from '@/components/feedback/EmptyState.vue'
import ErrorState from '@/components/feedback/ErrorState.vue'
import LoadingState from '@/components/feedback/LoadingState.vue'
import BaseButton from '@/components/forms/BaseButton.vue'
import PanelSection from '@/components/layout/PanelSection.vue'
import QueueView from '@/features/queue/QueueView.vue'
import { storageQuery } from '@/features/requests/requestStorage'

type TrackingDetail = NonNullable<
  operations['getTrackingItemDetail']['responses']['200']['content']['application/json']['result']
>

const route = useRoute()
const trackingId = ref('')
const detail = ref<TrackingDetail | null>(null)
const loading = ref(false)
const failed = ref(false)
const heading = ref<HTMLElement | null>(null)
let loadSequence = 0

function readTrackingId(): string {
  return typeof route.query.tracking_id === 'string' ? route.query.tracking_id : ''
}

async function loadDetail(): Promise<void> {
  const sequence = ++loadSequence
  const requestedTrackingId = trackingId.value
  if (!trackingId.value) {
    detail.value = null
    failed.value = false
    loading.value = false
    return
  }
  loading.value = true
  failed.value = false
  try {
    const nextDetail = await api.get<TrackingDetail>('/api/v1/tracking/items/{tracking_id}', {
      path: { tracking_id: trackingId.value },
      query: storageQuery(),
    })
    if (sequence !== loadSequence || requestedTrackingId !== trackingId.value) return
    detail.value = nextDetail
    await nextTick()
    if (sequence === loadSequence && requestedTrackingId === trackingId.value) {
      heading.value?.focus({ preventScroll: true })
    }
  } catch (error) {
    if (sequence !== loadSequence || requestedTrackingId !== trackingId.value) return
    detail.value = null
    failed.value = true
    // The detail endpoint's raw error is never part of the tracking handoff UI.
    void error
  } finally {
    if (sequence === loadSequence) loading.value = false
  }
}

function syncRoute(): void {
  trackingId.value = readTrackingId()
  void loadDetail()
}

onMounted(syncRoute)
watch(() => route.query.tracking_id, syncRoute)
</script>

<template>
  <QueueView v-if="!trackingId" />
  <PanelSection v-else title="追番管理" class="tracking-detail-panel">
    <template #actions>
      <BaseButton
        id="tracking-detail-refresh"
        aria-label="刷新追番记录"
        :disabled="!trackingId"
        :loading="loading"
        @click="loadDetail"
      >
        刷新
      </BaseButton>
    </template>

    <div v-if="loading" class="tracking-detail-state"><LoadingState message="正在读取追番记录..." /></div>
    <ErrorState
      v-else-if="failed"
      title="追番记录读取失败"
      message="无法读取这条追番记录。请稍后重试。"
      retry-label="重试定位"
      @retry="loadDetail"
    />
    <EmptyState
      v-else-if="!detail"
      message="没有可定位的追番记录。请从已确认结果重新进入。"
    />
    <section
      v-else
      id="tracking-detail-target"
      ref="heading"
      tabindex="-1"
      aria-labelledby="tracking-detail-heading"
      class="tracking-detail"
    >
      <p class="field-help">已确认方案的只读落点</p>
      <h2 id="tracking-detail-heading">{{ detail.title || '未命名番剧' }}</h2>
      <p class="tracking-detail-status" role="status">状态：{{ detail.status_label }}</p>
      <dl class="tracking-detail-summary">
        <div><dt>有效资源</dt><dd>{{ detail.valid_resource_count }}</dd></div>
        <div><dt>总集数</dt><dd>{{ detail.total_episodes ?? '待获取' }}</dd></div>
        <div><dt>已更新集数</dt><dd>待开发</dd></div>
      </dl>
      <p v-if="detail.status === 'UNKNOWN'" class="field-help" role="status">
        已保留确认结果，但暂时无法完成追番定位。请稍后重试定位。
      </p>
    </section>
  </PanelSection>
</template>

<style scoped>
.tracking-detail { display: grid; gap: 0.65rem; }
.tracking-detail h2, .tracking-detail p { margin: 0; }
.tracking-detail-status { font-weight: 600; }
.tracking-detail-summary { display: grid; gap: 0.55rem; margin: 0; max-width: 34rem; }
.tracking-detail-summary div { display: flex; justify-content: space-between; gap: 1rem; border-bottom: 1px solid var(--color-border); padding: 0.45rem 0; }
.tracking-detail-summary dd { margin: 0; font-weight: 600; }
.tracking-detail-state { min-height: 5rem; }
</style>
