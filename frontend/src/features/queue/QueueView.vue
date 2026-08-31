<script setup lang="ts">
// 提交队列 route (US-206).
//
// Migrated from the legacy `/index` pre-submission queue panel onto the shared
// primitives and the generated OpenAPI client:
//
//   - reads the queue via `GET /api/v1/batches/{batch_id}/queue` (the public
//     batch_id comes from the URL query, so a refresh restores the queue; the
//     batch workbench pushes batch_id into the URL after a parse),
//   - renders each queue item's public status/summary and offers the correct
//     per-status action: FAILED/RETRYABLE → 重试, SUBMITTING /
//     RESULT_PERSIST_FAILED → 恢复 (auto-recover first, then explicit
//     succeeded/failed manual verification through the shared ConfirmDialog),
//   - a single Auto Bangumi credential form (auth mode + endpoint +
//     password/token + fallback + explicit confirm) is used for submit, retry
//     and recover; AB credentials live only in component memory
//     (useSensitiveFields) and one POST body, and are cleared on success,
//     cancel, auth-mode switch and unmount — never persisted.
//
// Security boundary: queue items are the public sanitized DTO only; server
// `error_message` values are never rendered (fixed Chinese copy only); the
// relative storage profile is the only query value; endpoint/token/password
// never enter URL, browser storage, history, logs or traces.
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'

import { useNotificationStore } from '@/app/stores/notification'
import { useSensitiveFields } from '@/app/composables/useSensitiveFields'
import ConfirmDialog from '@/components/feedback/ConfirmDialog.vue'
import EmptyState from '@/components/feedback/EmptyState.vue'
import ErrorState from '@/components/feedback/ErrorState.vue'
import LoadingState from '@/components/feedback/LoadingState.vue'
import StatusAlert from '@/components/feedback/StatusAlert.vue'
import BaseButton from '@/components/forms/BaseButton.vue'
import BaseInput from '@/components/forms/BaseInput.vue'
import BaseSelect from '@/components/forms/BaseSelect.vue'
import CheckboxRow from '@/components/forms/CheckboxRow.vue'
import FormField from '@/components/layout/FormField.vue'
import PanelSection from '@/components/layout/PanelSection.vue'

import {
  batchSubmitNotification,
  batchSubmitSummaryMessage,
  buildAbConfig,
  loadQueue as fetchQueue,
  queueItemCanRecover,
  queueItemCanRetry,
  queueItemSummary,
  queueStatusClass,
  queueStatusLabel,
  recoverNeedsManualMessage,
  recoverOutcomeNeedsManual,
  recoverQueueItem as apiRecoverQueueItem,
  retryQueueItem as apiRetryQueueItem,
  submitQueue as apiSubmitQueue,
  validateAbConfig,
  type BatchSubmitResult,
  type QueueItem,
} from '@/features/queue/queueWorkbench'
import { storageQuery } from '@/features/requests/requestStorage'

const route = useRoute()
const notification = useNotificationStore()
const confirmDialog = ref<InstanceType<typeof ConfirmDialog> | null>(null)

// Queue state. The batch_id is a public identifier read from the URL query so
// a refresh restores the queue (the batch workbench pushes it after a parse).
const batchId = ref('')
const items = ref<QueueItem[]>([])
const loading = ref(false)
const loadFailed = ref(false)

// Action state (submit / retry / recover share one in-flight flag and one
// result area, mirroring the legacy setBatchQueueInFlight).
const actionInFlight = ref(false)
const actionStatus = ref<{ kind: 'success' | 'error' | 'info' | 'empty'; message: string }>({
  kind: 'empty',
  message: '尚未提交 Auto Bangumi。',
})

// Auto Bangumi request-scoped credentials (component memory only).
const ab = useSensitiveFields({
  baseUrl: { label: '服务地址', required: true },
  username: { label: '用户名' },
  password: { label: '密码' },
  token: { label: 'API Token' },
})
const abAuthMode = ref<'password' | 'api_token'>('password')
const abFallbackEnabled = ref(false)
const abConfirm = ref(false)

const abBaseUrl = computed({
  get: () => ab.get('baseUrl'),
  set: (value: string) => ab.set('baseUrl', value),
})
const abUsername = computed({
  get: () => ab.get('username'),
  set: (value: string) => ab.set('username', value),
})
const abPassword = computed({
  get: () => ab.get('password'),
  set: (value: string) => ab.set('password', value),
})
const abToken = computed({
  get: () => ab.get('token'),
  set: (value: string) => ab.set('token', value),
})

const countText = computed(() => `队列中 ${items.value.length} 项`)

function switchAbAuthMode(): void {
  // Switching auth mode clears every credential (never persisted).
  ab.reset()
}

function credentials(): { username: string; password: string; token: string } {
  return {
    username: ab.get('username'),
    password: ab.get('password'),
    token: ab.get('token'),
  }
}

function queuePayload(): Record<string, unknown> {
  const config = buildAbConfig(abAuthMode.value, ab.get('baseUrl').trim(), abFallbackEnabled.value, credentials())
  return {
    storage_dir: storageQuery().storage_dir ?? null,
    ab_config: config,
    confirm: true,
  }
}

async function refreshQueue(): Promise<void> {
  if (!batchId.value) {
    items.value = []
    loadFailed.value = false
    return
  }
  loading.value = true
  loadFailed.value = false
  try {
    const result = await fetchQueue(batchId.value, storageQuery())
    items.value = result.queue?.items ?? []
  } catch (error) {
    items.value = []
    loadFailed.value = true
    actionStatus.value = { kind: 'error', message: '队列读取失败。请稍后重试。' }
    notification.error('队列读取失败', '请稍后重试。')
    void error
  } finally {
    loading.value = false
  }
}

function applyResult(result: BatchSubmitResult): void {
  // Only the public, sanitized queue is trusted back into the view; the
  // request-scoped AB config was already cleared by the caller on success.
  items.value = result.queue?.items ?? []
}

function showOutcome(result: BatchSubmitResult): void {
  const summary = result.summary ?? {}
  actionStatus.value = { kind: 'success', message: batchSubmitSummaryMessage(summary) }
  const notif = batchSubmitNotification(summary)
  notification.show(notif.kind, notif.title, notif.message)
}

/** Validate the shared AB credential form (fixed Chinese copy only). */
function abValidationError(): string | null {
  return validateAbConfig(abAuthMode.value, ab.get('baseUrl'), credentials())
}

async function submitBatchQueue(): Promise<void> {
  if (!batchId.value) {
    actionStatus.value = { kind: 'error', message: '缺少批次标识，无法提交队列。' }
    return
  }
  const validation = abValidationError()
  if (validation) {
    actionStatus.value = { kind: 'error', message: validation }
    return
  }
  if (!abConfirm.value) {
    actionStatus.value = { kind: 'error', message: '请勾选确认后再提交到 Auto Bangumi。' }
    return
  }

  actionInFlight.value = true
  actionStatus.value = { kind: 'info', message: '正在提交队列到 Auto Bangumi...' }
  try {
    const result = await apiSubmitQueue(batchId.value, queuePayload())
    ab.clearAll()
    abConfirm.value = false
    applyResult(result)
    showOutcome(result)
  } catch (error) {
    // HTTP-level failure preserves the sensitive inputs for retry (legacy
    // parity); only fixed Chinese copy is shown, never the server error.
    void error
    actionStatus.value = {
      kind: 'error',
      message: 'Auto Bangumi 批量提交失败。请检查配置与订阅方案状态后重试。',
    }
    notification.error('批量提交失败', '请检查配置与订阅方案状态后重试。')
  } finally {
    actionInFlight.value = false
  }
}

async function retryItem(item: QueueItem): Promise<void> {
  if (!batchId.value) {
    actionStatus.value = { kind: 'error', message: '缺少批次标识，无法重试。' }
    return
  }
  const validation = abValidationError()
  if (validation) {
    actionStatus.value = { kind: 'error', message: validation }
    return
  }
  if (!abConfirm.value) {
    actionStatus.value = { kind: 'error', message: '请勾选确认后再提交到 Auto Bangumi。' }
    return
  }

  actionInFlight.value = true
  actionStatus.value = { kind: 'info', message: '正在重试到 Auto Bangumi...' }
  try {
    const result = await apiRetryQueueItem(batchId.value, item.request_id ?? '', queuePayload())
    ab.clearAll()
    abConfirm.value = false
    applyResult(result)
    showOutcome(result)
  } catch (error) {
    void error
    actionStatus.value = {
      kind: 'error',
      message: 'Auto Bangumi 单项重试失败。请检查配置与订阅方案状态后重试。',
    }
    notification.error('单项重试失败', '请检查配置与订阅方案状态后重试。')
  } finally {
    actionInFlight.value = false
  }
}

async function recoverItem(item: QueueItem): Promise<void> {
  if (!batchId.value) {
    actionStatus.value = { kind: 'error', message: '缺少批次标识，无法恢复。' }
    return
  }

  actionInFlight.value = true
  actionStatus.value = { kind: 'info', message: '正在恢复队列项目...' }
  try {
    // Auto-recover first (only meaningful for SUBMITTING with a persisted AB
    // result); when the server cannot decide it returns `needs_manual` and
    // the user explicitly verifies Auto Bangumi (succeeded / failed).
    let result = await apiRecoverQueueItem(batchId.value, item.request_id ?? '', 'auto', false, storageQuery())
    let outcome = result.items?.[0]
    if (recoverOutcomeNeedsManual(outcome)) {
      const created =
        (await confirmDialog.value?.confirm({
          title: '恢复队列项目',
          message: `${recoverNeedsManualMessage(item.status)}。请前往 Auto Bangumi 核对后选择：已创建订阅则标记为提交成功，未创建则标记为失败（可重试）。`,
          confirmLabel: '已创建订阅',
          cancelLabel: '未创建订阅',
        })) ?? false
      result = await apiRecoverQueueItem(
        batchId.value,
        item.request_id ?? '',
        created ? 'succeeded' : 'failed',
        true,
        storageQuery(),
      )
      outcome = result.items?.[0]
    }
    void outcome
    applyResult(result)
    showOutcome(result)
  } catch (error) {
    void error
    actionStatus.value = { kind: 'error', message: '队列项目恢复失败。请核对 Auto Bangumi 状态后重试。' }
    notification.error('恢复失败', '请核对 Auto Bangumi 状态后重试。')
  } finally {
    actionInFlight.value = false
  }
}

onMounted(() => {
  const fromQuery = typeof route.query.batch_id === 'string' ? route.query.batch_id : ''
  batchId.value = fromQuery
  if (fromQuery) {
    void refreshQueue()
  }
})

// Reflect URL batch_id changes (nav away/back, workbench push) onto the view.
watch(
  () => route.query.batch_id,
  (value) => {
    batchId.value = typeof value === 'string' ? value : ''
    if (batchId.value) {
      void refreshQueue()
    } else {
      items.value = []
      loadFailed.value = false
      actionStatus.value = { kind: 'empty', message: '尚未提交 Auto Bangumi。' }
    }
  },
)
</script>

<template>
  <PanelSection title="提交前队列" class="queue-panel">
    <template #actions>
      <BaseButton
        id="batch-queue-refresh"
        aria-label="刷新提交前队列"
        :disabled="!batchId"
        :loading="loading"
        @click="refreshQueue"
      >
        刷新
      </BaseButton>
    </template>

    <p id="batch-queue-context" class="field-help">
      接受后的批量卡片进入提交前队列；在此显式配置 Auto Bangumi 并顺序提交。队列只保留公开字段与脱敏结果摘要。
    </p>
    <p id="batch-queue-count" class="request-list-count" aria-live="polite">
      {{ countText }}
    </p>

    <div
      id="batch-queue-list"
      class="queue-list-container"
      aria-live="polite"
      aria-relevant="additions text"
    >
      <LoadingState v-if="loading && !items.length" message="正在读取提交前队列..." />
      <ErrorState
        v-else-if="loadFailed"
        title="队列读取失败"
        message="无法读取提交前队列。请稍后重试。"
        retry-label="重试"
        @retry="refreshQueue"
      />
      <EmptyState
        v-else-if="!items.length"
        message="暂无队列项目。接受批量卡片后，此处会显示提交前队列。"
      />
      <div v-else class="batch-queue-grid" role="list" aria-label="提交前队列项目">
        <article
          v-for="item in items"
          :key="item.item_id ?? item.request_id ?? ''"
          class="batch-queue-item"
          :data-item-id="item.item_id ?? ''"
          role="listitem"
        >
          <div class="batch-queue-item-status-row">
            <span
              class="batch-status batch-queue-status"
              :class="`batch-queue-status-${queueStatusClass(item.status)}`"
            >
              {{ queueStatusLabel(item.status) }}
            </span>
            <BaseButton
              v-if="queueItemCanRetry(item.status)"
              class="batch-queue-item-retry"
              :disabled="actionInFlight"
              :data-request-id="item.request_id ?? ''"
              @click="retryItem(item)"
            >
              重试
            </BaseButton>
            <BaseButton
              v-if="queueItemCanRecover(item.status)"
              class="batch-queue-item-recover"
              :disabled="actionInFlight"
              :data-request-id="item.request_id ?? ''"
              @click="recoverItem(item)"
            >
              恢复
            </BaseButton>
          </div>
          <strong class="batch-queue-item-title">{{ item.title ?? '未命名订阅方案' }}</strong>
          <div class="batch-queue-item-meta">
            尝试次数：{{ item.attempts ?? 0 }}；更新于：{{ item.updated_at ?? '未记录' }}
          </div>
          <div class="batch-queue-item-summary">{{ queueItemSummary(item) }}</div>
        </article>
      </div>
    </div>

    <form
      v-if="items.length"
      id="batch-queue-submit-form"
      class="queue-submit-form"
      @submit.prevent="submitBatchQueue"
    >
      <h3 class="queue-form-heading">提交到 Auto Bangumi</h3>
      <p class="field-help">
        服务地址和认证信息只用于本次请求，不写入浏览器存储、URL、history 或队列 JSON；提交成功后清空。已提交成功的项目会跳过重复提交。
      </p>

      <FormField label="认证方式" inputId="batch-queue-ab-auth-mode">
        <BaseSelect
          id="batch-queue-ab-auth-mode"
          v-model="abAuthMode"
          label="认证方式"
          :options="[
            { value: 'password', label: '账号密码' },
            { value: 'api_token', label: 'API Token' },
          ]"
          :disabled="actionInFlight"
          @change="switchAbAuthMode"
        />
      </FormField>

      <FormField label="服务地址" inputId="batch-queue-ab-endpoint">
        <BaseInput
          id="batch-queue-ab-endpoint"
          v-model="abBaseUrl"
          name="ab_base_url"
          type="url"
          autocomplete="off"
          placeholder="例如：局域网 Auto Bangumi 服务根地址"
          :disabled="actionInFlight"
        />
      </FormField>

      <template v-if="abAuthMode === 'password'">
        <FormField label="用户名" inputId="batch-queue-ab-username">
          <BaseInput
            id="batch-queue-ab-username"
            v-model="abUsername"
            name="ab_username"
            type="text"
            autocomplete="username"
            :disabled="actionInFlight"
          />
        </FormField>
        <FormField label="密码" inputId="batch-queue-ab-password">
          <BaseInput
            id="batch-queue-ab-password"
            v-model="abPassword"
            name="ab_password"
            type="password"
            autocomplete="current-password"
            :disabled="actionInFlight"
          />
        </FormField>
      </template>
      <template v-else>
        <FormField label="API Token" inputId="batch-queue-ab-token">
          <BaseInput
            id="batch-queue-ab-token"
            v-model="abToken"
            name="ab_token"
            type="password"
            autocomplete="off"
            placeholder="Auto Bangumi Token"
            :disabled="actionInFlight"
          />
        </FormField>
      </template>

      <CheckboxRow
        id="batch-queue-ab-fallback-enabled"
        v-model:checked="abFallbackEnabled"
        label="提交时启用备用兼容选项"
        :disabled="actionInFlight"
      />
      <CheckboxRow
        id="batch-queue-ab-confirm"
        v-model:checked="abConfirm"
        label="我已确认将这些订阅方案提交到 Auto Bangumi"
        help="提交前需要勾选确认；失败时保留输入便于重试，成功后清空认证信息。"
        :disabled="actionInFlight"
      />

      <StatusAlert :kind="actionStatus.kind" :message="actionStatus.message" />

      <div class="notification-actions">
        <BaseButton
          id="batch-queue-submit-button"
          type="submit"
          variant="primary"
          :loading="actionInFlight"
        >
          提交队列
        </BaseButton>
      </div>
    </form>

    <ConfirmDialog ref="confirmDialog" />
  </PanelSection>
</template>

<style scoped>
.queue-list-container {
  display: grid;
  gap: 0.75rem;
}

.batch-queue-grid {
  display: grid;
  gap: 0.6rem;
  margin: 0;
  padding: 0;
}

.batch-queue-item {
  background: var(--color-bg);
  border: 1px solid var(--color-border);
  border-radius: 6px;
  display: grid;
  gap: 0.3rem;
  min-width: 0;
  padding: 0.7rem 0.8rem;
}

.batch-queue-item-status-row {
  align-items: center;
  display: flex;
  flex-wrap: wrap;
  gap: 0.5rem;
}

.batch-queue-status {
  border-radius: 4px;
  font-size: 0.78rem;
  font-weight: 600;
  padding: 0.15rem 0.5rem;
}

.batch-queue-status-ready {
  background: #eef2f7;
  border: 1px solid #cdd8e4;
  color: #3b5570;
}

.batch-queue-status-submitting {
  background: #eef4fd;
  border: 1px solid #c2d6f0;
  color: #1f4e8c;
}

.batch-queue-status-succeeded {
  background: #e7f4e9;
  border: 1px solid #abd3b6;
  color: #1f5f34;
}

.batch-queue-status-failed {
  background: #fdf1f0;
  border: 1px solid #e8c2bd;
  color: #8d2f20;
}

.batch-queue-status-retryable {
  background: #fdf6e8;
  border: 1px solid #e8d39a;
  color: #7a5600;
}

.batch-queue-status-result-persist-failed {
  background: #f6ecfd;
  border: 1px solid #dcc3ee;
  color: #5b2f7a;
}

.batch-queue-item-title {
  overflow-wrap: anywhere;
}

.batch-queue-item-meta,
.batch-queue-item-summary {
  color: var(--color-text-muted);
  font-size: 0.84rem;
  overflow-wrap: anywhere;
}

.queue-submit-form {
  display: grid;
  gap: 0.75rem;
  max-width: 640px;
  margin-top: 1rem;
}

.queue-form-heading {
  margin: 0;
  font-size: 1rem;
}

.notification-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 0.5rem;
}
</style>
