<script setup lang="ts">
// 订阅方案（Request 列表）route (US-202).
//
// Migrated from the legacy `/index` request list panel onto the shared
// primitives and the generated OpenAPI client:
//
//   - loads summaries via `GET /api/v1/requests` (trackedApi drives the global
//     loading bar; relative storage profile comes from Settings localStorage),
//   - search (标题/request_id/字幕组/folder_name), status filter and sort
//     behave exactly like the legacy list (same helpers in requestsList.ts),
//   - live count, empty states (no requests / no match) and a safe Chinese
//     error state with retry,
//   - clicking an item selects it and pushes `request_id` into the URL so the
//     selection survives refresh; the detail view itself lands in US-203.
//
// Security boundary: only public summary DTOs are rendered (never raw request
// snapshots); the relative storage profile is the only value ever sent in the
// query and never an absolute path; request_id appears in the URL only because
// the legacy app did the same for refresh recovery (it is a public saved
// request identifier, not a credential).
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
  fieldValue,
  filterRequests,
  requestLabel,
  sortRequests,
  statusLabel,
  type RequestSummary,
  type SortMode,
} from '@/features/requests/requestsList'
import { storageQuery as requestStorageQuery } from '@/features/requests/requestStorage'
import RequestDetailPanel from '@/features/requests/RequestDetailPanel.vue'
import { routeLocation } from '@/app/router/catalog'

type ListResult = operations['listRequests']['responses']['200']['content']['application/json']['result']

const route = useRoute()
const router = useRouter()
const notification = useNotificationStore()

const loadedRequests = ref<RequestSummary[]>([])
const loading = ref(false)
const loadFailed = ref(false)

const searchTerm = ref('')
const statusFilter = ref('')
const sortMode = ref<SortMode>('default')

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
  sortRequests(filterRequests(loadedRequests.value, searchTerm.value, statusFilter.value), sortMode.value),
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
  } catch (error) {
    loadFailed.value = true
    notification.error('订阅方案列表加载失败', '请检查存储目录后重试。')
    void error
  } finally {
    loading.value = false
  }
}

function selectRequest(requestId: string | null | undefined): void {
  const id = requestId ?? ''
  selectedRequestId.value = id
  if (id) {
    void router.push(routeLocation('plans', { request_id: id }))
  } else {
    void router.push(routeLocation('plans'))
  }
}

async function copyRequestId(requestId: string): Promise<void> {
  try {
    await navigator.clipboard.writeText(requestId)
    notification.success('已复制 request_id', requestId)
  } catch {
    notification.error('复制失败', '无法访问剪贴板，请手动选择复制。')
  }
}

function retry(): void {
  void loadList()
}

function onDetailChanged(): void {
  void loadList()
}

function onDetailDeleted(requestId: string): void {
  // Clear the URL selection and drop the deleted item from the loaded list.
  loadedRequests.value = loadedRequests.value.filter((summary) => summary.request_id !== requestId)
  selectedRequestId.value = ''
  void router.push(routeLocation('plans'))
  void loadList()
}

onMounted(() => {
  const fromQuery = typeof route.query.request_id === 'string' ? route.query.request_id : ''
  selectedRequestId.value = fromQuery
  void loadList()
})

// If the user edits/clears the URL request_id while on the page, update the
// selected item (US-202: refresh restores, clearing deselects).
watch(
  () => route.query.request_id,
  (value) => {
    selectedRequestId.value = typeof value === 'string' ? value : ''
  },
)
</script>

<template>
  <PanelSection title="订阅方案列表" class="requests-panel">
    <template #actions>
      <BaseButton
        id="request-list-refresh"
        aria-label="刷新订阅方案列表"
        :loading="loading"
        @click="loadList"
      >
        刷新
      </BaseButton>
    </template>

    <div class="request-list-controls" aria-label="订阅方案列表筛选和排序">
      <label for="request-list-search">搜索</label>
      <BaseInput
        id="request-list-search"
        v-model="searchTerm"
        type="search"
        placeholder="标题、request_id、字幕组或 folder_name"
      />
      <label for="request-list-status-filter">状态</label>
      <BaseSelect
        id="request-list-status-filter"
        v-model="statusFilter"
        label="状态筛选"
        :options="statusOptions"
      />
      <label for="request-list-sort">排序</label>
      <BaseSelect
        id="request-list-sort"
        v-model="sortMode"
        label="排序方式"
        :options="[
          { value: 'default', label: '默认顺序' },
          { value: 'title_asc', label: '标题升序' },
          { value: 'request_id_asc', label: 'request_id 升序' },
        ]"
      />
    </div>

    <p id="request-list-count" class="request-list-count" aria-live="polite">
      {{ countText }}
    </p>

    <div
      id="request-list-container"
      class="request-list-container"
      aria-live="polite"
      aria-relevant="additions text"
    >
      <LoadingState v-if="loading && !loadedRequests.length" message="正在加载订阅方案列表..." />
      <ErrorState
        v-else-if="loadFailed"
        title="订阅方案列表加载失败"
        message="无法读取已保存的订阅方案。请确认存储目录后重试。"
        retry-label="重试"
        @retry="retry"
      />
      <EmptyState v-else-if="!loadedRequests.length" message="暂无已保存的订阅方案。" />
      <EmptyState v-else-if="!filtered.length" message="没有匹配的订阅方案。清空搜索或筛选后可恢复列表。" />
      <ul v-else class="request-list" aria-label="订阅方案列表">
        <li
          v-for="(summary, index) in filtered"
          :key="summary.request_id ?? summary.bangumi_title ?? summary.selected_subtitle_group ?? index"
        >
          <button
            type="button"
            class="request-list-item"
            :class="{ 'is-selected': summary.request_id === selectedRequestId }"
            :data-request-id="summary.request_id ?? ''"
            :aria-current="summary.request_id === selectedRequestId ? 'true' : undefined"
            :aria-label="`查看订阅方案详情：${requestLabel(summary)}`"
            @click="selectRequest(summary.request_id)"
          >
            <strong>{{ requestLabel(summary) }}</strong>
            <span class="request-list-meta">
              {{ [
                statusLabel(summary.status),
                fieldValue(summary.selected_subtitle_group),
                fieldValue(summary.expected_folder_name),
              ].join(' / ') }}
            </span>
          </button>
          <button
            v-if="summary.request_id"
            type="button"
            class="copy-request-id"
            :aria-label="`复制 request_id：${summary.request_id}`"
            @click.stop="copyRequestId(summary.request_id)"
          >
            复制
          </button>
        </li>
      </ul>
    </div>
  </PanelSection>

  <!-- US-203: detail panel. Mounted whenever a request_id is selected; the
       panel owns its own loading/error/empty states and management actions. -->
  <RequestDetailPanel
    v-if="selectedRequestId"
    :key="selectedRequestId"
    :request-id="selectedRequestId"
    @changed="onDetailChanged"
    @deleted="onDetailDeleted"
  />
</template>

<style scoped>
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

.request-list-count {
  margin: 0 0 0.75rem;
  font-size: 0.875rem;
  color: var(--color-text-muted);
}

.request-list-container {
  min-height: 120px;
}

.request-list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
}

.request-list li {
  display: flex;
  align-items: center;
  gap: 0.5rem;
}

.request-list-item {
  flex: 1;
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

.request-list-item:hover {
  background: var(--color-bg-muted);
}

.request-list-item.is-selected {
  border-color: var(--color-accent);
  background: var(--color-bg-muted);
  box-shadow: 0 0 0 1px var(--color-accent) inset;
}

.request-list-meta {
  font-size: 0.8125rem;
  color: var(--color-text-muted);
}

.copy-request-id {
  flex: none;
  border: 1px solid var(--color-border);
  border-radius: 6px;
  background: var(--color-bg);
  color: var(--color-text);
  font-size: 0.8125rem;
  padding: 0.375rem 0.625rem;
  cursor: pointer;
}

.copy-request-id:hover {
  background: var(--color-bg-muted);
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
