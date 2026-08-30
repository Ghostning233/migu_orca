<script setup lang="ts">
// RequestDetailPanel (US-203).
//
// The detail panel for a saved Request, migrated from the legacy
// `renderDetailPayload` (app.js). Renders Overview / Source / Filter / Seeds /
// Audit sections and the status-dependent management actions:
//
// - PENDING_CONFIRM → 确认 (accept) / 取消 (cancel) / 修改 (modify),
// - ACCEPTED       → 去 Settings 提交 Auto Bangumi / 修改 / 删除 (delete),
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
import { computed, onMounted, ref, watch } from 'vue'

import { api } from '@/api/client'
import type { operations } from '@/api/generated/api'
import { useNotificationStore } from '@/app/stores/notification'
import ConfirmDialog from '@/components/feedback/ConfirmDialog.vue'
import ErrorState from '@/components/feedback/ErrorState.vue'
import LoadingState from '@/components/feedback/LoadingState.vue'
import BaseButton from '@/components/forms/BaseButton.vue'
import BaseInput from '@/components/forms/BaseInput.vue'
import BaseSelect from '@/components/forms/BaseSelect.vue'
import BaseTextarea from '@/components/forms/BaseTextarea.vue'
import CheckboxRow from '@/components/forms/CheckboxRow.vue'
import PanelSection from '@/components/layout/PanelSection.vue'
import FormField from '@/components/layout/FormField.vue'

import {
  actionLabel,
  completeSeedGroups,
  displayValue,
  effectiveSeeds,
  excludedSeeds,
  scrubConfig,
  totalCompleteSeedCount,
  type RequestDetailResult,
  type RequestSnapshot,
} from '@/features/requests/requestDetail'
import { statusLabel as detailStatusLabel } from '@/features/requests/requestsList'
import { storageQuery } from '@/features/requests/requestStorage'

type ActionResult = NonNullable<
  operations['acceptRequest']['responses']['200']['content']['application/json']['result']
>

const props = defineProps<{
  requestId: string
}>()

const emit = defineEmits<{
  (e: 'changed'): void
  (e: 'deleted', requestId: string): void
}>()

const notification = useNotificationStore()
const confirmDialog = ref<InstanceType<typeof ConfirmDialog> | null>(null)

const loading = ref(false)
const loadFailed = ref(false)
const detail = ref<RequestDetailResult | null>(null)
const actionInFlight = ref(false)

// Inline form visibility (legacy hidden toggles).
const cancelFormOpen = ref(false)
const modifyFormOpen = ref(false)

// Modify form state (initialized from the snapshot when the panel loads).
const modifyGroup = ref('')
const modifyMustContain = ref('')
const modifyMustNotContain = ref('')
const modifyUseRegex = ref(false)
const modifyCaseSensitive = ref(false)
const modifyFolderName = ref('')
// Explicit "clear this field" flags (legacy appendClearControl behavior).
const modifyClearMustContain = ref(false)
const modifyClearMustNotContain = ref(false)
const modifyClearFolderName = ref(false)
const modifyError = ref('')

const cancelReason = ref('')

const request = computed<RequestSnapshot | null>(() => detail.value?.request ?? null)
const isAccepted = computed(() => request.value?.status === 'ACCEPTED')
const isPending = computed(() => request.value?.status === 'PENDING_CONFIRM')
const isCancelled = computed(() => request.value?.status === 'CANCELLED')

const groupOptions = computed(() => {
  const sources = request.value?.source_info?.rss_sources ?? []
  return sources.map((source) => ({
    value: source.subtitle_group ?? '',
    label: source.subtitle_group ?? '未知字幕组',
  }))
})

const effective = computed(() => (request.value ? effectiveSeeds(request.value) : []))
const excluded = computed(() => (request.value ? excludedSeeds(request.value) : []))
const completeGroups = computed(() => (request.value ? completeSeedGroups(request.value) : []))
const completeTotal = computed(() => (request.value ? totalCompleteSeedCount(request.value) : 0))

const selectedGroupName = computed(
  () => request.value?.confirmable_config?.selected_subtitle_group ?? '未选择字幕组',
)

async function loadDetail(): Promise<void> {
  if (!props.requestId) return
  loading.value = true
  loadFailed.value = false
  try {
    const result = await api.get<RequestDetailResult>('/api/v1/requests/{request_id}', {
      path: { request_id: props.requestId },
      query: storageQuery(),
    })
    detail.value = result
    resetModifyForm()
    cancelFormOpen.value = false
    modifyFormOpen.value = false
    cancelReason.value = ''
  } catch (error) {
    void error
    detail.value = null
    loadFailed.value = true
    notification.error('订阅方案详情加载失败', '请确认 request_id 是否存在。')
  } finally {
    loading.value = false
  }
}

function resetModifyForm(): void {
  const snapshot = request.value
  modifyGroup.value = snapshot?.confirmable_config?.selected_subtitle_group ?? ''
  modifyMustContain.value = snapshot?.confirmable_config?.filter_rule?.must_contain ?? ''
  modifyMustNotContain.value = snapshot?.confirmable_config?.filter_rule?.must_not_contain ?? ''
  modifyUseRegex.value = snapshot?.confirmable_config?.filter_rule?.use_regex === true
  modifyCaseSensitive.value = snapshot?.confirmable_config?.filter_rule?.case_sensitive === true
  modifyFolderName.value = snapshot?.confirmable_config?.expected_folder_name ?? ''
  modifyClearMustContain.value = false
  modifyClearMustNotContain.value = false
  modifyClearFolderName.value = false
  modifyError.value = ''
}

function copyRequestId(): void {
  const id = props.requestId
  if (!id) return
  navigator.clipboard
    .writeText(id)
    .then(() => notification.success('已复制 request_id', id))
    .catch(() => notification.error('复制失败', '无法访问剪贴板，请手动选择复制。'))
}

async function confirmAccept(): Promise<void> {
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
  cancelFormOpen.value = !cancelFormOpen.value
}

function toggleModifyForm(): void {
  modifyFormOpen.value = !modifyFormOpen.value
  if (modifyFormOpen.value) {
    resetModifyForm()
  }
}

async function confirmCancel(): Promise<void> {
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

interface FilterRulePatch {
  must_contain?: string
  must_not_contain?: string
  use_regex?: boolean
  case_sensitive?: boolean
}

interface ModifyPatch {
  selected_subtitle_group?: string
  filter_rule?: FilterRulePatch
  expected_folder_name?: string
}

/** Structural view of the snapshot config the modify form edits. */
interface ModifyConfig {
  selected_subtitle_group: string
  filter_rule: {
    must_contain: string
    must_not_contain: string
    use_regex: boolean
    case_sensitive: boolean
  }
  expected_folder_name: string
}

function currentModifyConfig(): ModifyConfig {
  const config = request.value?.confirmable_config
  return {
    selected_subtitle_group: config?.selected_subtitle_group ?? '',
    filter_rule: {
      must_contain: config?.filter_rule?.must_contain ?? '',
      must_not_contain: config?.filter_rule?.must_not_contain ?? '',
      use_regex: config?.filter_rule?.use_regex === true,
      case_sensitive: config?.filter_rule?.case_sensitive === true,
    },
    expected_folder_name: config?.expected_folder_name ?? '',
  }
}

function buildModifyPatch(): ModifyPatch | null {
  const snapshot = request.value
  if (!snapshot) return null
  const config = currentModifyConfig()
  const originalGroup = config.selected_subtitle_group
  const originalMustContain = config.filter_rule.must_contain
  const originalMustNotContain = config.filter_rule.must_not_contain
  const originalUseRegex = config.filter_rule.use_regex
  const originalCaseSensitive = config.filter_rule.case_sensitive
  const originalFolderName = config.expected_folder_name

  const patch: ModifyPatch = {}
  if (modifyGroup.value !== originalGroup) {
    patch.selected_subtitle_group = modifyGroup.value
  }

  const mcChanged = modifyClearMustContain.value || modifyMustContain.value.trim() !== originalMustContain
  const mncChanged = modifyClearMustNotContain.value || modifyMustNotContain.value.trim() !== originalMustNotContain
  const filterChanged =
    mcChanged ||
    mncChanged ||
    modifyUseRegex.value !== originalUseRegex ||
    modifyCaseSensitive.value !== originalCaseSensitive
  if (filterChanged) {
    patch.filter_rule = {}
    if (mcChanged) {
      patch.filter_rule.must_contain = modifyClearMustContain.value ? '' : modifyMustContain.value.trim()
    }
    if (mncChanged) {
      patch.filter_rule.must_not_contain = modifyClearMustNotContain.value ? '' : modifyMustNotContain.value.trim()
    }
    patch.filter_rule.use_regex = modifyUseRegex.value
    patch.filter_rule.case_sensitive = modifyCaseSensitive.value
  }

  const fnChanged = modifyClearFolderName.value || modifyFolderName.value.trim() !== originalFolderName
  if (fnChanged) {
    patch.expected_folder_name = modifyClearFolderName.value ? '' : modifyFolderName.value.trim()
  }

  if (!Object.keys(patch).length) {
    return {}
  }
  return patch
}

async function submitModify(): Promise<void> {
  const patch = buildModifyPatch()
  if (!patch || !Object.keys(patch).length) {
    modifyError.value = '请至少修改或清空一个字段。'
    return
  }
  modifyError.value = ''
  await performAction('modify', { patch })
}

async function confirmDelete(): Promise<void> {
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
    notification.success('删除成功', `已删除订阅方案 ${props.requestId}`)
    emit('deleted', props.requestId)
  } catch (error) {
    void error
    notification.error('删除失败', '删除订阅方案失败，请稍后重试。')
  } finally {
    actionInFlight.value = false
  }
}

async function performAction(action: 'accept' | 'cancel' | 'modify', body: Record<string, unknown>): Promise<void> {
  actionInFlight.value = true
  try {
    const result = await api.post<ActionResult>(`/api/v1/requests/{request_id}/${action}`, {
      path: { request_id: props.requestId },
      query: storageQuery(),
      body: { ...body, storage_dir: storageQuery().storage_dir ?? null },
    })
    const titles: Record<string, string> = {
      accept: '确认成功',
      cancel: '取消成功',
      modify: '修改成功',
    }
    notification.success(titles[action] ?? '操作成功', `订阅方案 ${props.requestId}`)
    // Update the in-memory snapshot with the server-authoritative result so
    // the panel reflects the new status immediately, then refresh the list.
    if (result?.request) {
      detail.value = { ...(detail.value as RequestDetailResult), request: result.request }
    }
    cancelFormOpen.value = false
    modifyFormOpen.value = false
    emit('changed')
    void loadDetail()
  } catch (error) {
    void error
    const messages: Record<string, string> = {
      accept: '确认失败，请稍后重试。',
      cancel: '取消失败，请稍后重试。',
      modify: '修改失败，请稍后重试。',
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

// Legacy `appendClearControl`: checking a "clear" box clears and disables the
// paired input so the patch sends an explicit empty value.
watch(modifyClearMustContain, (clear) => {
  if (clear) modifyMustContain.value = ''
})
watch(modifyClearMustNotContain, (clear) => {
  if (clear) modifyMustNotContain.value = ''
})
watch(modifyClearFolderName, (clear) => {
  if (clear) modifyFolderName.value = ''
})
</script>
<template>
  <PanelSection v-if="!loading && !loadFailed && detail" title="订阅方案详情" class="request-detail-panel">
    <template #actions>
      <button
        type="button"
        class="copy-request-id secondary-button"
        aria-label="复制 request_id"
        @click="copyRequestId"
      >
        复制 request_id
      </button>
    </template>

    <div id="request-detail-container" class="request-detail" aria-live="polite" aria-relevant="additions text">
      <h3 class="request-detail-title">{{ detail.request?.input?.raw_title || detail.request?.source_info?.matched_bangumi?.title || '订阅方案' }}</h3>

      <!-- ── actions ─────────────────────────────────────────────── -->
      <div class="detail-actions" aria-label="订阅方案操作">
        <template v-if="isPending">
          <BaseButton id="detail-accept-button" variant="primary" :loading="actionInFlight" @click="confirmAccept">
            确认
          </BaseButton>
          <BaseButton id="detail-cancel-toggle" :disabled="actionInFlight" @click="toggleCancelForm">
            取消
          </BaseButton>
          <BaseButton id="detail-modify-toggle" :disabled="actionInFlight" @click="toggleModifyForm">
            修改
          </BaseButton>
        </template>

        <template v-else-if="isAccepted">
          <p class="field-help">
            此订阅方案已{{ detailStatusLabel(request?.status) }}，可提交到 Auto Bangumi。
          </p>
          <RouterLink
            id="detail-ab-submit-entry"
            class="base-button secondary-button"
            :to="{ path: '/settings', query: { request_id: props.requestId, ab: '1' } }"
          >
            去 Settings 提交 Auto Bangumi
          </RouterLink>
          <BaseButton id="detail-accepted-modify-toggle" :disabled="actionInFlight" @click="toggleModifyForm">
            修改
          </BaseButton>
          <BaseButton id="detail-delete-button" variant="danger" :disabled="actionInFlight" @click="confirmDelete">
            删除
          </BaseButton>
        </template>

        <template v-else-if="isCancelled">
          <p class="field-help">此订阅方案已{{ detailStatusLabel(request?.status) }}，不可操作。</p>
        </template>
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
          <BaseButton id="detail-cancel-submit" type="submit" variant="danger" :loading="actionInFlight">
            提交取消
          </BaseButton>
          <BaseButton type="button" :disabled="actionInFlight" @click="cancelFormOpen = false">
            收起
          </BaseButton>
        </div>
      </form>

      <!-- ── inline modify form ──────────────────────────────────── -->
      <form
        v-if="modifyFormOpen"
        id="detail-modify-form"
        class="detail-inline-form"
        @submit.prevent="submitModify"
      >
        <h4 class="detail-form-heading">修改订阅方案</h4>

        <FormField label="字幕组" inputId="modify-subtitle-group">
          <BaseSelect
            id="modify-subtitle-group"
            v-model="modifyGroup"
            label="字幕组"
            :options="groupOptions"
          />
        </FormField>

        <FormField label="包含规则" inputId="modify-must-contain">
          <BaseInput
            id="modify-must-contain"
            v-model="modifyMustContain"
            type="text"
            placeholder="如 1080p（默认按字面匹配）"
            :disabled="modifyClearMustContain"
          />
        </FormField>
        <CheckboxRow
          id="modify-clear-must-contain"
          v-model:checked="modifyClearMustContain"
          label="清空包含规则"
        />

        <FormField label="排除规则" inputId="modify-must-not-contain">
          <BaseInput
            id="modify-must-not-contain"
            v-model="modifyMustNotContain"
            type="text"
            placeholder="如 [v2]（默认按字面匹配）"
            :disabled="modifyClearMustNotContain"
          />
        </FormField>
        <CheckboxRow
          id="modify-clear-must-not-contain"
          v-model:checked="modifyClearMustNotContain"
          label="清空排除规则"
        />

        <div class="filter-options">
          <CheckboxRow id="modify-filter-use-regex" v-model:checked="modifyUseRegex" label="使用正则" />
          <CheckboxRow
            id="modify-filter-case-sensitive"
            v-model:checked="modifyCaseSensitive"
            label="大小写敏感"
          />
        </div>
        <p class="field-help" id="modify-filter-help">
          默认按字面文本匹配且不区分大小写；勾选「使用正则」后按正则匹配，勾选「大小写敏感」后区分大小写。
        </p>

        <FormField label="folder_name" inputId="modify-folder-name">
          <BaseInput
            id="modify-folder-name"
            v-model="modifyFolderName"
            type="text"
            placeholder="期望存储目录名"
            :disabled="modifyClearFolderName"
          />
        </FormField>
        <CheckboxRow id="modify-clear-folder-name" v-model:checked="modifyClearFolderName" label="清空 folder_name" />

        <p v-if="modifyError" id="detail-modify-error" class="field-error" role="alert">
          {{ modifyError }}
        </p>

        <div class="detail-form-actions">
          <BaseButton id="detail-modify-submit" type="submit" variant="primary" :loading="actionInFlight">
            提交修改
          </BaseButton>
          <BaseButton type="button" :disabled="actionInFlight" @click="modifyFormOpen = false">
            取消
          </BaseButton>
        </div>
      </form>

      <!-- ── Overview ────────────────────────────────────────────── -->
      <section class="detail-section overview-section" aria-label="Overview">
        <h4 class="detail-section-heading">Overview</h4>
        <dl class="detail-grid">
          <div class="detail-row"><dt>request_id</dt><dd>{{ displayValue(request?.request_id) }}</dd></div>
          <div class="detail-row"><dt>状态</dt><dd>{{ detailStatusLabel(request?.status) }}</dd></div>
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
            <p class="muted-text">{{ String(detail.history.error.error_message ?? '状态历史不可用。') }}</p>
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
            <p class="muted-text">{{ String(detail.ab_result.error.error_message ?? '提交结果不可用。') }}</p>
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
