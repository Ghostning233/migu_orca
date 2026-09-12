<script setup lang="ts">
/** SafeInfoDialog (US-297): the only consumer of getRequestSafeInfo. */
import { nextTick, onBeforeUnmount, ref, watch } from 'vue'

import { api } from '@/api/client'
import type { operations } from '@/api/generated/api'
import { useFocusTrap } from '@/app/composables/useFocusTrap'
import ErrorState from '@/components/feedback/ErrorState.vue'
import LoadingState from '@/components/feedback/LoadingState.vue'
import { storageQuery } from '@/features/requests/requestStorage'
import { statusLabel } from '@/features/requests/requestsList'

type SafeInfoResult = NonNullable<
  operations['getRequestSafeInfo']['responses']['200']['content']['application/json']['result']
>
type SafeInfo = SafeInfoResult['safe_info']

const props = defineProps<{
  open: boolean
  requestId: string
}>()

const emit = defineEmits<{
  (event: 'close'): void
}>()

const backdrop = ref<HTMLElement | null>(null)
const safeInfo = ref<SafeInfo | null>(null)
const loading = ref(false)
const failed = ref(false)
let requestSequence = 0

const { activate, deactivate } = useFocusTrap(backdrop, () => emit('close'))

function safeLabel(value: string | null | undefined): string {
  return value && value.trim() ? value : '未设置'
}

async function load(): Promise<void> {
  const sequence = ++requestSequence
  if (!props.open || !props.requestId) return
  loading.value = true
  failed.value = false
  safeInfo.value = null
  try {
    const result = await api.get<SafeInfoResult>('/api/v1/requests/{request_id}/safe-info', {
      path: { request_id: props.requestId },
      query: storageQuery(),
    })
    if (sequence !== requestSequence || !props.open) return
    safeInfo.value = result.safe_info
  } catch {
    if (sequence !== requestSequence || !props.open) return
    failed.value = true
  } finally {
    if (sequence === requestSequence) loading.value = false
  }
}

function retry(): void {
  void load()
}

function close(): void {
  ++requestSequence
  deactivate()
  emit('close')
}

watch(
  () => [props.open, props.requestId] as const,
  async ([open]) => {
    if (!open) {
      ++requestSequence
      deactivate()
      return
    }
    void load()
    await nextTick()
    if (props.open) activate()
  },
  { immediate: true },
)

function historyStatus(value: string | null): string {
  return value ? statusLabel(value) : '未设置'
}

function safeAbError(value: string | null | undefined): string {
  return value ? '提交失败（详细原因已隐藏）' : '未设置'
}

onBeforeUnmount(() => {
  ++requestSequence
  deactivate()
})
</script>

<template>
  <Teleport to="body">
    <div v-if="open" ref="backdrop" class="safe-info-backdrop" @click.self="close">
      <section
        class="safe-info-dialog"
        role="dialog"
        aria-modal="true"
        aria-labelledby="safe-info-title"
      >
        <header class="safe-info-header">
          <div>
            <p class="safe-info-kicker">只读安全摘要</p>
            <h2 id="safe-info-title">全部信息</h2>
          </div>
          <button type="button" class="safe-info-close" aria-label="关闭全部信息" @click="close">关闭</button>
        </header>

        <div v-if="loading" class="safe-info-state"><LoadingState message="正在加载方案安全信息..." /></div>
        <ErrorState
          v-else-if="failed"
          title="全部信息加载失败"
          message="暂时无法读取方案安全信息，请稍后重试。"
          retry-label="重试"
          @retry="retry"
        />
        <div v-else-if="!safeInfo" class="safe-info-empty" role="status">暂无可展示的方案安全信息。</div>
        <div v-else class="safe-info-content">
          <section class="safe-info-section" aria-labelledby="safe-info-basic-heading">
            <h3 id="safe-info-basic-heading">标题与合集</h3>
            <dl class="safe-info-grid">
              <div><dt>原始标题</dt><dd>{{ safeLabel(safeInfo.raw_title) }}</dd></div>
              <div><dt>标题</dt><dd>{{ safeLabel(safeInfo.title) }}</dd></div>
              <div><dt>别名</dt><dd>{{ safeInfo.aliases?.length ? safeInfo.aliases.join('、') : '无' }}</dd></div>
              <div><dt>季度</dt><dd>{{ safeInfo.season ? `第 ${safeInfo.season} 季` : '未设置' }}</dd></div>
              <div><dt>季度原文</dt><dd>{{ safeLabel(safeInfo.season_raw) }}</dd></div>
              <div><dt>季度证据</dt><dd>{{ safeLabel(safeInfo.season_evidence) }}</dd></div>
              <div><dt>MiKan 合集</dt><dd>{{ safeLabel(safeInfo.mikan_collection?.title) }}</dd></div>
              <div><dt>公开编号</dt><dd>{{ safeLabel(safeInfo.mikan_collection?.bangumi_id) }}</dd></div>
              <div><dt>Request 状态</dt><dd>{{ statusLabel(safeInfo.status) }}</dd></div>
            </dl>
          </section>

          <section class="safe-info-section" aria-labelledby="safe-info-config-heading">
            <h3 id="safe-info-config-heading">字幕组与过滤</h3>
            <dl class="safe-info-grid">
              <div><dt>已选字幕组</dt><dd>{{ safeLabel(safeInfo.selected_subtitle_group) }}</dd></div>
              <div><dt>安全目录名</dt><dd>{{ safeLabel(safeInfo.folder_name) }}</dd></div>
              <div><dt>存储 profile</dt><dd>{{ safeLabel(safeInfo.storage_profile) }}</dd></div>
              <div><dt>包含规则</dt><dd>{{ safeLabel(safeInfo.filter_rule?.must_contain) }}</dd></div>
              <div><dt>排除规则</dt><dd>{{ safeLabel(safeInfo.filter_rule?.must_not_contain) }}</dd></div>
              <div><dt>匹配模式</dt><dd>{{ safeInfo.filter_rule?.use_regex ? '正则' : '普通文本' }}</dd></div>
              <div><dt>大小写</dt><dd>{{ safeInfo.filter_rule?.case_sensitive ? '区分大小写' : '不区分大小写' }}</dd></div>
            </dl>
            <ul v-if="safeInfo.subtitle_groups?.length" class="safe-info-list">
              <li v-for="group in safeInfo.subtitle_groups" :key="`${group.subtitle_group}-${group.total_resource_count}`">
                {{ safeLabel(group.subtitle_group) }}：资源 {{ group.total_resource_count }}，有效 {{ group.valid_resource_count }}，排除 {{ group.invalid_resource_count }}
                <span v-if="group.warnings?.length">（提示：{{ group.warnings.join('；') }}）</span>
              </li>
            </ul>
          </section>

          <section class="safe-info-section" aria-labelledby="safe-info-resource-heading">
            <h3 id="safe-info-resource-heading">资源摘要</h3>
            <dl class="safe-info-grid">
              <div><dt>有效资源</dt><dd>{{ safeInfo.resources?.valid_resource_count ?? 0 }}</dd></div>
              <div><dt>排除资源</dt><dd>{{ safeInfo.resources?.invalid_resource_count ?? 0 }}</dd></div>
              <div><dt>完整资源</dt><dd>{{ safeInfo.resources?.complete_resource_count ?? 0 }}</dd></div>
              <div><dt>资源字幕组</dt><dd>{{ safeLabel(safeInfo.resources?.selected_subtitle_group) }}</dd></div>
              <div><dt>总集数</dt><dd>{{ safeInfo.total_episodes ?? '待获取' }}</dd></div>
              <div><dt>已更新集数</dt><dd>待开发</dd></div>
            </dl>
            <p class="safe-info-subheading">有效文件名摘要</p>
            <ul v-if="safeInfo.resources?.valid_file_names?.length" class="safe-info-list">
              <li v-for="name in safeInfo.resources.valid_file_names" :key="name">{{ name }}</li>
            </ul>
            <p v-else class="safe-info-muted">无有效文件名摘要。</p>
            <p class="safe-info-subheading">排除文件名摘要</p>
            <ul v-if="safeInfo.resources?.excluded_file_names?.length" class="safe-info-list">
              <li v-for="file in safeInfo.resources.excluded_file_names" :key="`${file.name}-${file.reason}`">{{ file.name }}：{{ file.reason }}</li>
            </ul>
            <p v-else class="safe-info-muted">无排除文件名摘要。</p>
          </section>

          <section class="safe-info-section" aria-labelledby="safe-info-history-heading">
            <h3 id="safe-info-history-heading">历史与安全状态</h3>
            <ul v-if="safeInfo.history_summary?.length" class="safe-info-list">
              <li v-for="(event, index) in safeInfo.history_summary" :key="`${event.timestamp}-${index}`">
                {{ safeLabel(event.action) }}：{{ historyStatus(event.previous_status) }} → {{ historyStatus(event.next_status) }}（{{ safeLabel(event.timestamp) }}）
              </li>
            </ul>
            <p v-else class="safe-info-muted">暂无历史摘要。</p>
            <p class="safe-info-ab" role="status">
              Auto Bangumi：{{ safeInfo.ab_status?.submitted ? (safeInfo.ab_status.success === true ? '已提交且成功' : safeInfo.ab_status.success === false ? '已提交但未成功' : '已提交，结果未知') : '未提交' }}
              <span v-if="safeInfo.ab_status?.submitted && safeInfo.ab_status.success === false">（{{ safeAbError(safeInfo.ab_status.error_type) }}）</span>
            </p>
          </section>
        </div>
      </section>
    </div>
  </Teleport>
</template>

<style scoped>
.safe-info-backdrop { position: fixed; inset: 0; z-index: var(--z-overlay); display: flex; align-items: center; justify-content: center; padding: var(--space-4); background: var(--color-feedback-scrim); }
.safe-info-dialog { width: min(58rem, 100%); max-height: min(90vh, 54rem); overflow: auto; background: var(--color-surface-raised); color: var(--color-text); border: 1px solid var(--color-border-subtle); border-radius: var(--radius-lg); box-shadow: var(--shadow-dialog); padding: var(--space-5); }
.safe-info-header { display: flex; justify-content: space-between; gap: var(--space-3); align-items: start; border-bottom: 1px solid var(--color-border); padding-bottom: var(--space-3); }
.safe-info-kicker { margin: 0; color: var(--color-text-muted); font-size: 0.85rem; }
.safe-info-header h2 { margin: 0.25rem 0 0; }
.safe-info-close { border: 1px solid var(--color-border); border-radius: var(--radius-sm); background: transparent; color: inherit; padding: 0.4rem 0.75rem; cursor: pointer; }
.safe-info-content { display: grid; gap: var(--space-5); padding-top: var(--space-4); }
.safe-info-section { display: grid; gap: var(--space-2); }
.safe-info-section h3 { margin: 0; font-size: var(--font-size-md); }
.safe-info-grid { display: grid; grid-template-columns: max-content minmax(0, 1fr); gap: 0.4rem 1rem; margin: 0; }
.safe-info-grid div { display: contents; }
.safe-info-grid dt { color: var(--color-text-muted); font-weight: 600; }
.safe-info-grid dd { margin: 0; overflow-wrap: anywhere; }
.safe-info-list { margin: 0; padding-left: 1.25rem; display: grid; gap: 0.25rem; overflow-wrap: anywhere; }
.safe-info-subheading { margin: 0.4rem 0 0; font-weight: 600; }
.safe-info-muted { margin: 0; color: var(--color-text-muted); }
.safe-info-state { min-height: 8rem; padding-top: var(--space-4); }
.safe-info-empty { padding: var(--space-5) 0; color: var(--color-text-muted); }
.safe-info-ab { margin: 0; font-weight: 600; }
@media (max-width: 640px) { .safe-info-grid { grid-template-columns: 1fr; gap: 0.15rem; } .safe-info-grid dd { margin-bottom: 0.35rem; } }
@media (prefers-reduced-motion: reduce) { .safe-info-dialog { scroll-behavior: auto; } }
</style>
