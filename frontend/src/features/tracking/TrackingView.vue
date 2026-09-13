<script setup lang="ts">
/** Formal tracking overview (US-305). The first management screen is read-only. */
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import { api } from '@/api/client'
import type { operations } from '@/api/generated/api'
import EmptyState from '@/components/feedback/EmptyState.vue'
import ErrorState from '@/components/feedback/ErrorState.vue'
import LoadingState from '@/components/feedback/LoadingState.vue'
import BaseButton from '@/components/forms/BaseButton.vue'
import BaseInput from '@/components/forms/BaseInput.vue'
import BaseSelect from '@/components/forms/BaseSelect.vue'
import PanelSection from '@/components/layout/PanelSection.vue'
import { routeLocation } from '@/app/router/catalog'
import { storageQuery } from '@/features/requests/requestStorage'
import {
  filterTrackingItems,
  projectTrackingOverview,
  sortTrackingItems,
  TRACKING_STATUS_GROUPS,
  type TrackingItem,
  type TrackingStatusGroup,
} from './trackingProjection'
import TrackingInspector from './TrackingInspector.vue'

type ListResult = NonNullable<
  operations['listTrackingItems']['responses']['200']['content']['application/json']['result']
>

const route = useRoute()
const router = useRouter()
const items = ref<TrackingItem[]>([])
const loading = ref(false)
const failed = ref(false)
const searchTerm = ref('')
const statusFilter = ref<TrackingStatusGroup | ''>('')
const selectedTrackingId = ref('')
const listContainer = ref<HTMLElement | null>(null)
let loadSequence = 0

const statusLabels: Record<TrackingStatusGroup, string> = {
  PENDING: '待处理', PROCESSING: '处理中', ACTIVE: '追番中',
  ATTENTION: '需处理', INACTIVE: '已停用/已删除',
}
const overview = computed(() => projectTrackingOverview(items.value))
const filteredItems = computed(() => sortTrackingItems(filterTrackingItems(items.value, {
  query: searchTerm.value, statusGroup: statusFilter.value,
})))
const selectedItem = computed(() => items.value.find(
  (item) => item.tracking_id === selectedTrackingId.value,
) ?? null)
const selectedHidden = computed(() => Boolean(
  selectedItem.value && !filteredItems.value.some((item) => item.tracking_id === selectedTrackingId.value),
))

function queryTrackingId(): string | null {
  const value = route.query.tracking_id
  return typeof value === 'string' ? value.trim() || null : null
}

async function focusSelection(): Promise<void> {
  await nextTick()
  const selected = listContainer.value?.querySelector<HTMLElement>('[aria-current="true"]')
  ;(selected ?? listContainer.value)?.focus({ preventScroll: true })
}

function syncSelection(forceAbsentCheck = false): void {
  const queryId = queryTrackingId()
  const next = queryId && items.value.some(
    (item) => item.tracking_id === queryId && item.status !== 'EXTERNAL_DELETED',
  ) ? queryId : ''
  selectedTrackingId.value = next
  if (queryId && !next && (!loading.value || forceAbsentCheck)) {
    void router.replace(routeLocation('tracking'))
    void focusSelection()
  }
}

async function loadList(): Promise<void> {
  const sequence = ++loadSequence
  loading.value = true
  failed.value = false
  try {
    const result = await api.get<ListResult>('/api/v1/tracking/items', {
      query: { ...storageQuery(), sort: 'updated_at' },
    })
    if (sequence !== loadSequence) return
    const previous = selectedTrackingId.value
    items.value = result?.items ?? []
    syncSelection(true)
    if (selectedTrackingId.value && selectedTrackingId.value !== previous) await focusSelection()
  } catch (error) {
    if (sequence !== loadSequence) return
    failed.value = true
    void error
  } finally {
    if (sequence === loadSequence) {
      loading.value = false
    }
  }
}

function selectItem(trackingId: string): void {
  selectedTrackingId.value = trackingId
  void router.push(routeLocation('tracking', { tracking_id: trackingId }))
}

function clearFilters(): void {
  searchTerm.value = ''
  statusFilter.value = ''
}

onMounted(() => {
  void loadList().then(() => {
    if (selectedTrackingId.value) void focusSelection()
  })
})
watch(() => route.query.tracking_id, () => {
  syncSelection()
  void focusSelection()
})
watch(selectedTrackingId, (trackingId) => {
  if (trackingId) void focusSelection()
}, { flush: 'post' })
</script>

<template>
  <section id="tracking-overview" class="tracking-overview" aria-labelledby="tracking-heading">
    <PanelSection title="追番管理" class="tracking-header">
      <template #actions>
        <BaseButton id="tracking-refresh" variant="secondary" :loading="loading" @click="loadList">刷新列表</BaseButton>
      </template>
      <p id="tracking-heading" class="tracking-lede">查看本地追番状态。选择单条记录后，右侧将显示检查器入口。</p>
    </PanelSection>

    <section class="tracking-status-overview" aria-labelledby="tracking-status-heading">
      <h2 id="tracking-status-heading">状态总览</h2>
      <div class="tracking-status-cards">
        <button v-for="group in TRACKING_STATUS_GROUPS" :key="group" type="button" class="tracking-status-card"
          :class="{ 'is-selected': statusFilter === group }" :aria-pressed="statusFilter === group"
          @click="statusFilter = statusFilter === group ? '' : group">
          <span>{{ statusLabels[group] }}</span><strong>{{ overview.byGroup[group] }}</strong>
        </button>
      </div>
      <p class="tracking-status-total" role="status">共 {{ overview.total }} 条追番记录</p>
    </section>

    <section class="tracking-workspace" aria-label="追番记录与检查器">
      <PanelSection title="追番列表" class="tracking-list-panel">
        <template #actions><span class="tracking-count" aria-live="polite">显示 {{ filteredItems.length }} / {{ items.length }}</span></template>
        <div class="tracking-filters">
          <label for="tracking-search">搜索标题或字幕组</label>
          <BaseInput id="tracking-search" v-model="searchTerm" type="search" placeholder="输入公开标题或字幕组" />
          <label for="tracking-status-filter">状态筛选</label>
          <BaseSelect id="tracking-status-filter" v-model="statusFilter" label="状态筛选"
            :options="[{ value: '', label: '全部状态' }, ...TRACKING_STATUS_GROUPS.map((group) => ({ value: group, label: statusLabels[group] }))]" />
          <BaseButton v-if="searchTerm || statusFilter" variant="secondary" @click="clearFilters">清除筛选</BaseButton>
        </div>
        <div v-if="loading" class="tracking-list-state"><LoadingState message="正在读取追番列表…" /></div>
        <ErrorState v-else-if="failed" title="追番列表读取失败" message="暂时无法读取本地追番列表，请稍后重试。" retry-label="重试读取" @retry="loadList" />
        <EmptyState v-else-if="!items.length" message="还没有本地追番记录。" />
        <EmptyState v-else-if="!filteredItems.length" message="没有符合当前搜索或状态筛选的记录。" />
        <div v-else id="tracking-list-container" ref="listContainer" class="tracking-list" tabindex="-1" aria-label="追番记录列表">
          <button v-for="item in filteredItems" :key="item.tracking_id" type="button" class="tracking-list-item"
            :class="{ 'is-selected': selectedTrackingId === item.tracking_id }" :data-tracking-id="item.tracking_id"
            :aria-current="selectedTrackingId === item.tracking_id ? 'true' : undefined" @click="selectItem(item.tracking_id)">
            <span class="tracking-list-indicator" aria-hidden="true" />
            <span class="tracking-list-copy"><strong>{{ item.title || '未命名番剧' }}</strong><span>{{ item.subtitle_group || '未设置字幕组' }}</span></span>
            <span class="tracking-list-meta"><span>{{ item.status_label }}</span><small>{{ item.updated_episode_status === 'NOT_IMPLEMENTED' ? '更新集数待开发' : '更新信息不可用' }}</small></span>
          </button>
        </div>
        <p v-if="selectedHidden" class="tracking-selection-note" role="status">当前选择被筛选条件隐藏，未自动切换记录。</p>
      </PanelSection>

      <aside class="tracking-inspector" aria-labelledby="tracking-inspector-heading">
        <TrackingInspector v-if="selectedItem" :tracking-id="selectedItem.tracking_id" />
        <template v-else>
          <h2 id="tracking-inspector-heading">检查器</h2>
          <EmptyState message="选择一条追番记录查看安全检查器。" />
        </template>
      </aside>
    </section>
  </section>
</template>

<style scoped>
.tracking-overview { display: grid; gap: var(--space-5); }
.tracking-lede { margin: 0; color: var(--color-text-muted); }
.tracking-status-overview { display: grid; gap: var(--space-3); }
.tracking-status-overview h2, .tracking-inspector h2 { margin: 0; font-size: 1.05rem; }
.tracking-status-cards { display: grid; grid-template-columns: repeat(5, minmax(0, 1fr)); gap: var(--space-3); }
.tracking-status-card { display: grid; gap: .35rem; text-align: left; padding: var(--space-3); border: 1px solid var(--color-border); border-radius: var(--radius-md); background: var(--color-surface); color: var(--color-text); cursor: pointer; }
.tracking-status-card:hover, .tracking-status-card:focus-visible, .tracking-status-card.is-selected { border-color: var(--color-primary); box-shadow: 0 0 0 2px color-mix(in srgb, var(--color-primary) 18%, transparent); }
.tracking-status-card strong { font-size: 1.35rem; }
.tracking-status-total, .tracking-count { margin: 0; color: var(--color-text-muted); }
.tracking-workspace { display: grid; grid-template-columns: minmax(0, 1.6fr) minmax(17rem, 1fr); gap: var(--space-5); align-items: start; }
.tracking-list-panel { min-width: 0; }
.tracking-filters { display: grid; grid-template-columns: auto minmax(10rem, 1fr) auto minmax(8rem, .7fr) auto; gap: .65rem; align-items: center; margin-bottom: var(--space-4); }
.tracking-filters label { font-size: .85rem; font-weight: 600; }
.tracking-list { display: grid; gap: .55rem; }
.tracking-list-item { display: grid; grid-template-columns: .35rem minmax(0, 1fr) auto; gap: .8rem; align-items: center; width: 100%; padding: .85rem .9rem; border: 1px solid var(--color-border); border-radius: var(--radius-md); background: var(--color-surface); color: var(--color-text); text-align: left; cursor: pointer; }
.tracking-list-item:hover, .tracking-list-item:focus-visible, .tracking-list-item.is-selected { border-color: var(--color-primary); background: var(--color-surface-subtle); }
.tracking-list-item.is-selected .tracking-list-indicator { background: var(--color-primary); }
.tracking-list-indicator { align-self: stretch; min-height: 2rem; border-radius: 99px; background: var(--color-border); }
.tracking-list-copy, .tracking-list-meta { display: grid; gap: .25rem; min-width: 0; }
.tracking-list-copy strong { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.tracking-list-copy span, .tracking-list-meta small { color: var(--color-text-muted); }
.tracking-list-meta { text-align: right; white-space: nowrap; }
.tracking-list-state { min-height: 8rem; }
.tracking-selection-note { margin: var(--space-3) 0 0; color: var(--color-text-muted); }
.tracking-inspector { position: sticky; top: var(--space-4); display: grid; gap: var(--space-3); min-height: 15rem; padding: var(--space-4); border: 1px solid var(--color-border); border-radius: var(--radius-md); background: var(--color-surface); }
.tracking-inspector-placeholder { display: grid; gap: .5rem; padding: var(--space-4); border: 1px dashed var(--color-border); border-radius: var(--radius-md); }
.tracking-inspector-placeholder h3, .tracking-inspector-placeholder p { margin: 0; }
@media (max-width: 1280px) { .tracking-workspace { grid-template-columns: minmax(0, 1.35fr) minmax(16rem, 1fr); } }
@media (max-width: 800px) {
  .tracking-status-cards { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .tracking-workspace { grid-template-columns: 1fr; }
  .tracking-inspector { position: static; }
  .tracking-filters { grid-template-columns: 1fr; }
  .tracking-filters label { margin-top: .25rem; }
  .tracking-list-meta { white-space: normal; }
}
</style>
