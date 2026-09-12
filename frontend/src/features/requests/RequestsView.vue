<script setup lang="ts">
// 追番方案列表—详情 route (US-296).
//
// Migrated from the legacy `/index` request list panel onto the shared
// primitives and the generated OpenAPI client:
//
//   - loads summaries via `GET /api/v1/requests` (trackedApi drives the global
//     loading bar; relative storage profile comes from Settings localStorage),
//   - search (标题/字幕组), status filter and recent-modified sorting are
//     derived by the API-free plans projection,
//   - live count, empty states (no requests / no match) and a safe Chinese
//     error state with retry,
//   - clicking an item selects it and pushes `request_id` into the URL so the
//     selection survives refresh; the detail view itself lands in US-203.
//
// Security boundary: only public summary DTOs are rendered (never raw request
// snapshots); the relative storage profile is the only value ever sent in the
// query and never an absolute path; request_id appears in the URL only as the
// public selection deep-link.
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import { api } from '@/api/client'
import type { operations } from '@/api/generated/api'
import { useNotificationStore } from '@/app/stores/notification'
import EmptyState from '@/components/feedback/EmptyState.vue'
import ErrorState from '@/components/feedback/ErrorState.vue'
import LoadingState from '@/components/feedback/LoadingState.vue'
import BaseButton from '@/components/forms/BaseButton.vue'
import BaseInput from '@/components/forms/BaseInput.vue'
import BaseSelect from '@/components/forms/BaseSelect.vue'
import PanelSection from '@/components/layout/PanelSection.vue'

import {
  availableStatuses,
  statusLabel,
  type RequestSummary,
} from '@/features/requests/requestsList'
import { storageQuery as requestStorageQuery } from '@/features/requests/requestStorage'
import RequestDetailPanel from '@/features/requests/RequestDetailPanel.vue'
import { routeLocation } from '@/app/router/catalog'
import {
  TRACKING_UNAVAILABLE_LABEL,
  planRequestStatusLabel,
  planTitle,
  planTrackingLabel,
  projectPlanRows,
  sortPlanRows,
  filterPlanRows,
  type PlanRow,
  type PlanSortMode,
  type TrackingItem,
} from '@/features/plans/plansProjection'

type ListResult = operations['listRequests']['responses']['200']['content']['application/json']['result']

const route = useRoute()
const router = useRouter()
const notification = useNotificationStore()

const loadedRequests = ref<RequestSummary[]>([])
const loading = ref(false)
const loadFailed = ref(false)
const trackingItems = ref<TrackingItem[]>([])
const trackingLoading = ref(false)
const trackingFailed = ref(false)

const searchTerm = ref('')
const statusFilter = ref('')
const sortMode = ref<PlanSortMode>('default')
// Selection state is driven by the URL query (request_id) so a refresh
// restores the previously selected item; US-203 renders the detail panel.
const selectedRequestId = ref('')

const statusOptions = computed(() => [
  { value: '', label: '全部' },
  ...availableStatuses(loadedRequests.value).map((code) => ({
    value: code,
    label: statusLabel(code),
  })),
])

const filtered = computed(() =>
  filterPlanRows(
    sortPlanRows(projectPlanRows(loadedRequests.value, trackingItems.value), sortMode.value),
    searchTerm.value,
    statusFilter.value,
  ),
)

const selectedRow = computed<PlanRow | null>(() =>
  selectedRequestId.value
    ? projectPlanRows(loadedRequests.value, trackingItems.value).find(
        (row) => row.request.request_id === selectedRequestId.value,
      ) ?? null
    : null,
)

const countText = computed(() => `显示 ${filtered.value.length} / ${loadedRequests.value.length}`)

async function loadList(): Promise<void> {
  loading.value = true
  loadFailed.value = false
  try {
    const result = await api.get<ListResult>('/api/v1/requests', { query: requestStorageQuery() })
    loadedRequests.value = result.requests ?? []
    // Keep the status filter valid: if the currently selected status no longer
    // exists in the list (or never did), fall back to 全部.
    const statuses = availableStatuses(loadedRequests.value)
    if (statusFilter.value && !statuses.includes(statusFilter.value)) {
      statusFilter.value = ''
    }
    syncSelectionToLoadedRequests()
  } catch (error) {
    loadFailed.value = true
    notification.error('订阅方案列表加载失败', '请检查存储目录后重试。')
    void error
  } finally {
    loading.value = false
  }
}

async function loadTracking(): Promise<void> {
  trackingLoading.value = true
  trackingFailed.value = false
  try {
    const result = await api.get<operations['listTrackingItems']['responses']['200']['content']['application/json']['result']>(
      '/api/v1/tracking/items',
      { query: { ...requestStorageQuery(), sort: 'updated_at' } },
    )
    trackingItems.value = result?.items ?? []
  } catch (error) {
    trackingItems.value = []
    trackingFailed.value = true
    void error
  } finally {
    trackingLoading.value = false
  }
}

function syncSelectionToLoadedRequests(): void {
  const rawQueryId = route.query.request_id
  const queryId = typeof rawQueryId === 'string' && rawQueryId.trim() ? rawQueryId : ''
  const exists = queryId && loadedRequests.value.some((summary) => summary.request_id === queryId)
  if (exists) {
    selectedRequestId.value = queryId
    return
  }
  selectedRequestId.value = ''
  // Invalid, duplicated, or unknown public identifiers are sanitized without
  // adding a history entry.  A valid identifier is only selected once it is
  // confirmed by the loaded Request summaries.
  if (rawQueryId !== undefined) void router.replace(routeLocation('plans'))
}

function selectRequest(requestId: string | null | undefined): void {
  const id = requestId ?? ''
  selectedRequestId.value = id
  if (id) {
    void router.push(routeLocation('plans', { request_id: id }))
  } else {
    void router.replace(routeLocation('plans'))
  }
}

function retry(): void {
  void loadList()
}

function retryTracking(): void {
  void loadTracking()
}

function onDetailChanged(): void {
  void loadList()
}

function onDetailDeleted(requestId: string): void {
  // Clear the URL selection and drop the deleted item from the loaded list.
  loadedRequests.value = loadedRequests.value.filter((summary) => summary.request_id !== requestId)
  selectedRequestId.value = ''
  void router.replace(routeLocation('plans'))
  void loadList()
}

onMounted(() => {
  void loadList()
  void loadTracking()
})

// If the user edits/clears the URL request_id while on the page, update the
// selected item (US-202: refresh restores, clearing deselects).
watch(
  () => route.query.request_id,
  (value) => {
    const nextId = typeof value === 'string' && value.trim() ? value : ''
    if (typeof value !== 'string' || !value.trim()) {
      selectedRequestId.value = ''
      if (value !== undefined) void router.replace(routeLocation('plans'))
      return
    }
    selectedRequestId.value = loadedRequests.value.some((summary) => summary.request_id === nextId)
      ? nextId
      : ''
    if (!selectedRequestId.value && !loading.value) {
      void router.replace(routeLocation('plans'))
    }
  },
)
</script>

<template>
  <div class="plans-layout">
    <PanelSection title="追番方案" class="requests-panel plans-list-pane">
      <template #actions>
        <BaseButton id="request-list-refresh" aria-label="刷新订阅方案列表" :loading="loading" @click="loadList">
          刷新
        </BaseButton>
      </template>

      <div class="request-list-controls" aria-label="订阅方案列表筛选">
        <label for="request-list-search">搜索标题或字幕组</label>
        <BaseInput id="request-list-search" v-model="searchTerm" type="search" placeholder="标题或字幕组" />
        <label for="request-list-status-filter">方案状态</label>
        <BaseSelect id="request-list-status-filter" v-model="statusFilter" label="方案状态筛选" :options="statusOptions" />
        <label for="request-list-sort">排序</label>
        <BaseSelect id="request-list-sort" v-model="sortMode" label="排序方式" :options="[
          { value: 'default', label: '最近修改' },
          { value: 'title_asc', label: '标题升序' },
        ]" />
      </div>

      <p id="request-list-count" class="request-list-count" aria-live="polite">{{ countText }}</p>

      <div id="request-list-container" class="request-list-container" aria-live="polite" aria-relevant="additions text">
        <LoadingState v-if="loading && !loadedRequests.length" message="正在加载订阅方案列表..." />
        <ErrorState v-else-if="loadFailed" title="订阅方案列表加载失败" message="无法读取已保存的订阅方案。请确认存储目录后重试。" retry-label="重试" @retry="retry" />
        <EmptyState v-else-if="!loadedRequests.length" message="暂无已保存的订阅方案。" />
        <EmptyState v-else-if="!filtered.length" message="没有匹配的订阅方案。清空搜索或筛选后可恢复列表。" />
        <ul v-else class="request-list" aria-label="订阅方案列表">
          <li v-for="(row, index) in filtered" :key="row.request.request_id ?? row.request.bangumi_title ?? index">
            <button
              type="button"
              class="request-list-item plan-list-item"
              :class="{ 'is-selected': row.request.request_id === selectedRequestId }"
              :data-request-id="row.request.request_id ?? ''"
              :aria-current="row.request.request_id === selectedRequestId ? 'true' : undefined"
              :aria-label="`查看订阅方案详情：${planTitle(row)}`"
              @click="selectRequest(row.request.request_id)"
            >
              <strong>{{ planTitle(row) }}</strong>
              <span class="plan-list-field">季度：{{ row.request.season ? `第 ${row.request.season} 季` : '未设置' }}</span>
              <span class="plan-list-field">字幕组：{{ row.request.selected_subtitle_group || '未设置' }}</span>
              <span class="plan-list-field">方案状态：{{ planRequestStatusLabel(row) }}</span>
              <span class="plan-list-field">修改时间：{{ row.request.updated_at || '未设置' }}</span>
              <span class="plan-list-tracking" :class="{ 'is-unavailable': trackingFailed || row.trackingUnavailable, 'is-loading': trackingLoading }" role="status">
                追番状态：{{ trackingLoading ? '正在读取追番状态...' : trackingFailed ? TRACKING_UNAVAILABLE_LABEL : planTrackingLabel(row) }}
              </span>
            </button>
          </li>
        </ul>
      </div>
      <p v-if="trackingLoading" class="plans-tracking-loading" role="status">正在读取追番状态...</p>
      <div v-else-if="trackingFailed" class="plans-tracking-error" role="alert">
        <span>{{ TRACKING_UNAVAILABLE_LABEL }}</span>
        <BaseButton variant="secondary" @click="retryTracking">重试追番状态</BaseButton>
      </div>
    </PanelSection>

    <section id="plans-detail-container" class="plans-detail-pane" aria-labelledby="plans-detail-heading">
      <h2 id="plans-detail-heading">方案详情</h2>
      <p v-if="!selectedRow" class="plans-detail-empty" role="status">请选择一个订阅方案查看详情。</p>
      <RequestDetailPanel
        v-else
        :key="selectedRequestId"
        :request-id="selectedRequestId"
        @changed="onDetailChanged"
        @deleted="onDetailDeleted"
      />
    </section>
  </div>
</template>

<style scoped>
.plans-layout {
  display: grid;
  grid-template-columns: minmax(17rem, 38%) minmax(0, 1fr);
  gap: var(--space-4);
  align-items: start;
}
.plans-list-pane, .plans-detail-pane { min-width: 0; }
.plans-detail-pane {
  background: var(--color-surface);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  padding: var(--space-4);
  min-height: 14rem;
}
.plans-detail-pane h2 { margin: 0 0 var(--space-3); }
.plans-detail-empty { color: var(--color-text-muted); }
.plan-list-item { display: grid; gap: 0.25rem; text-align: left; width: 100%; }
.plan-list-field, .plan-list-tracking { color: var(--color-text-muted); font-size: 0.9rem; }
.plan-list-tracking { font-weight: 600; color: var(--color-text); }
.plan-list-tracking.is-unavailable { color: var(--color-feedback-error-text); }
.plans-tracking-loading, .plans-tracking-error { margin: var(--space-3) 0 0; }
.plans-tracking-error { display: flex; flex-wrap: wrap; gap: var(--space-2); align-items: center; color: var(--color-feedback-error-text); }
@media (max-width: 900px) {
  .plans-layout { grid-template-columns: 1fr; }
}
.request-list-controls {
  display: grid;
  grid-template-columns: auto 1fr auto minmax(8rem, 14rem) auto minmax(8rem, 12rem);
  align-items: center;
  gap: 0.5rem 0.75rem;
  margin-bottom: 0.75rem;
}
.request-list-controls label {
  font-size: 0.875rem;
  color: var(--color-text-muted);
  white-space: nowrap;
}
.request-list-count { margin: 0 0 0.75rem; font-size: 0.875rem; color: var(--color-text-muted); }
.request-list-container { min-height: 120px; }
.request-list { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 0.5rem; }
.request-list li { display: flex; align-items: center; gap: 0.5rem; }
.request-list-item {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 0.25rem;
  text-align: left;
  padding: 0.625rem 0.75rem;
  border: 1px solid var(--color-border);
  border-radius: 6px;
  background: var(--color-bg);
  color: var(--color-text);
  cursor: pointer;
  font: inherit;
}
.request-list-item:hover { background: var(--color-bg-muted); }
.request-list-item.is-selected {
  border-color: var(--color-accent);
  background: var(--color-bg-muted);
  box-shadow: 0 0 0 1px var(--color-accent) inset;
}
@media (max-width: 720px) {
  .request-list-controls {
    grid-template-columns: 1fr 1fr;
  }

  .request-list-controls label {
    white-space: normal;
  }
}
</style>
