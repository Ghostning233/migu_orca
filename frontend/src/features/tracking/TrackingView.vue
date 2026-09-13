<script setup lang="ts">
/** Formal tracking overview (US-305). The first management screen is read-only. */
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import { api } from '@/api/client'
import type { operations } from '@/api/generated/api'
import EmptyState from '@/components/feedback/EmptyState.vue'
import ErrorState from '@/components/feedback/ErrorState.vue'
import LoadingState from '@/components/feedback/LoadingState.vue'
import ConfirmDialog from '@/components/feedback/ConfirmDialog.vue'
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
import CredentialSessionDialog from './CredentialSessionDialog.vue'

type ListResult = NonNullable<
  operations['listTrackingItems']['responses']['200']['content']['application/json']['result']
>
type ProbeBody = NonNullable<
  operations['probeAutoBangumiCapabilities']['requestBody']['content']['application/json']
>
type CapabilityResult = NonNullable<
  operations['probeAutoBangumiCapabilities']['responses']['200']['content']['application/json']['result']
>
type SyncBody = NonNullable<
  operations['syncTrackingItems']['requestBody']['content']['application/json']
>
type SyncResult = NonNullable<
  operations['syncTrackingItems']['responses']['200']['content']['application/json']['result']
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
const credentialDialogOpen = ref(false)
const credentialDialog = ref<InstanceType<typeof CredentialSessionDialog> | null>(null)
const sessionConfig = ref<ProbeBody['ab_config'] | null>(null)
const sessionCapabilities = ref<CapabilityResult | null>(null)
const syncLoading = ref(false)
const syncMessage = ref('')
const syncSummary = ref<SyncResult['summary'] | null>(null)
const confirmDialog = ref<InstanceType<typeof ConfirmDialog> | null>(null)
const detailRevision = ref(0)
let dataSequence = 0
let syncSequence = 0

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
  if (syncLoading.value) {
    syncSequence += 1
    syncLoading.value = false
  }
  const sequence = ++dataSequence
  loading.value = true
  failed.value = false
  try {
    const result = await api.get<ListResult>('/api/v1/tracking/items', {
      query: { ...storageQuery(), sort: 'updated_at' },
    })
    if (sequence !== dataSequence) return
    const previous = selectedTrackingId.value
    items.value = result?.items ?? []
    syncSelection(true)
    if (selectedTrackingId.value && selectedTrackingId.value !== previous) await focusSelection()
  } catch (error) {
    if (sequence !== dataSequence) return
    failed.value = true
    void error
  } finally {
    if (sequence === dataSequence) {
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

function onConnected(value: { config: ProbeBody['ab_config']; capabilities: CapabilityResult }): void {
  sessionConfig.value = value.config
  sessionCapabilities.value = value.capabilities
  credentialDialogOpen.value = false
}

function clearConnection(): void {
  credentialDialog.value?.clearSession()
  sessionConfig.value = null
  sessionCapabilities.value = null
  dataSequence += 1
  syncSequence += 1
  syncLoading.value = false
  syncMessage.value = ''
  syncSummary.value = null
}

const capabilityFields: Array<keyof CapabilityResult> = [
  'subscription_list', 'subscription_detail', 'subscription_submit', 'subscription_modify',
  'subscription_enable', 'subscription_disable', 'subscription_delete', 'rss_list', 'rss_modify',
  'rss_enable', 'rss_disable', 'rss_delete', 'rss_refresh', 'external_verify',
]

function hasUnknownCapability(capabilities: CapabilityResult): boolean {
  return capabilities.probe_status !== 'VERIFIED'
    || capabilityFields.some((field) => capabilities[field] === 'UNKNOWN')
}

async function syncTracking(): Promise<void> {
  if (syncLoading.value || !sessionConfig.value || !sessionCapabilities.value) return
  const confirmed = await confirmDialog.value?.confirm({
    title: '同步 Auto Bangumi',
    message: '将使用本页面已探测的连接读取外部追番并更新本地安全摘要，是否继续？',
    confirmLabel: '确认同步',
    cancelLabel: '取消',
  })
  if (!confirmed || !sessionConfig.value || !sessionCapabilities.value) return
  const sequence = ++syncSequence
  const dataRevision = ++dataSequence
  loading.value = false
  syncLoading.value = true
  syncMessage.value = ''
  try {
    const body: SyncBody = { ab_config: sessionConfig.value, confirm: true }
    const result = await api.post<SyncResult>('/api/v1/tracking/sync', { body })
    if (sequence !== syncSequence || dataRevision !== dataSequence) return
    syncSummary.value = result.summary
    const degraded = result.sync_status !== 'COMPLETE' || hasUnknownCapability(result.capabilities)
    if (!degraded && result.items) {
      items.value = result.items
      detailRevision.value += 1
      syncSelection(true)
      syncMessage.value = `同步完成：检查 ${result.summary.checked} 条，新增 ${result.summary.created} 条，更新 ${result.summary.updated} 条。`
    } else {
      syncMessage.value = result.sync_status === 'PARTIAL'
        ? '同步部分完成，已保留原有本地列表；可重连或再次同步。'
        : '同步未完成，已保留原有本地列表；可重连、重探测或再次同步。'
    }
    sessionCapabilities.value = result.capabilities
  } catch (error) {
    if (sequence !== syncSequence || dataRevision !== dataSequence) return
    syncMessage.value = '同步 Auto Bangumi 失败，已保留原有本地列表；可重连或再次同步。'
    void error
  } finally {
    if (sequence === syncSequence && dataRevision === dataSequence) syncLoading.value = false
  }
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
        <BaseButton id="tracking-connect" variant="secondary" @click="credentialDialogOpen = true">连接 Auto Bangumi</BaseButton>
        <BaseButton v-if="sessionCapabilities" id="tracking-sync" variant="secondary" :loading="syncLoading" :disabled="syncLoading" @click="syncTracking">同步 Auto Bangumi</BaseButton>
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
        <TrackingInspector v-if="selectedItem" :key="`${selectedItem.tracking_id}:${detailRevision}`" :tracking-id="selectedItem.tracking_id" />
        <template v-else>
          <h2 id="tracking-inspector-heading">检查器</h2>
          <EmptyState message="选择一条追番记录查看安全检查器。" />
        </template>
      </aside>
    </section>
    <p v-if="sessionCapabilities" class="tracking-connection-status" role="status">
      当前页面已连接 Auto Bangumi（{{ sessionCapabilities.probe_status }}），仅在用户明确操作时使用。
      <button type="button" class="tracking-clear-connection" @click="clearConnection">清除连接</button>
    </p>
    <p v-if="syncMessage" id="tracking-sync-status" class="tracking-sync-status" role="status">{{ syncMessage }}</p>
    <p v-if="syncSummary" class="tracking-sync-summary" role="status">本次安全同步摘要：检查 {{ syncSummary.checked }}，新增 {{ syncSummary.created }}，更新 {{ syncSummary.updated }}，未变化 {{ syncSummary.unchanged }}。</p>
    <CredentialSessionDialog ref="credentialDialog" v-model:open="credentialDialogOpen" @connected="onConnected" />
    <ConfirmDialog ref="confirmDialog" />
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
.tracking-connection-status { margin: 0; color: var(--color-text-muted); }
.tracking-clear-connection { margin-left: .5rem; color: var(--color-primary); text-decoration: underline; }
.tracking-sync-status, .tracking-sync-summary { margin: 0; color: var(--color-text-muted); }
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
