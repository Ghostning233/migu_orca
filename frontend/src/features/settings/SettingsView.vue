<script setup lang="ts">
// Settings (US-201).
//
// Migrated from the legacy `/settings` page onto the shared primitives
// (PanelSection/FormField/BaseInput/BaseTextarea/BaseSelect/CheckboxRow,
// ConfirmDialog/StatusAlert, useSensitiveFields). Four panels:
//
//   1. Storage 偏好 — non-sensitive browser preferences (storage profile +
//      default-save) stored ONLY in localStorage (legacy keys), sanitized to
//      a server-root-relative profile (US-193).
//   2. 偏好默认值 — non-sensitive preference defaults read/saved through
//      `/api/v1/preferences` (defaults when absent).
//   3. qBittorrent — explicit request-scoped connection test; credentials
//      live only in component memory (useSensitiveFields) and are cleared on
//      success/cancel/unmount, never persisted.
//   4. Auto Bangumi — request-scoped connection test + submit context
//      (request_id from the URL query). Credentials live only in memory and
//      are cleared on success/cancel/unmount.
//
// Security boundary: endpoint/username/password/token/base_url values are
// component-local reactive memory only (useSensitiveFields); they are never
// written to store, URL, localStorage/sessionStorage, logs or traces. The
// AB submit context (request_id) is read from the URL query but the
// credentials themselves never go into the URL.
import { computed, onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'

import { api } from '@/api/client'
import { useNotificationStore } from '@/app/stores/notification'
import { useSensitiveFields } from '@/app/composables/useSensitiveFields'
import ConfirmDialog from '@/components/feedback/ConfirmDialog.vue'
import StatusAlert from '@/components/feedback/StatusAlert.vue'
import BaseButton from '@/components/forms/BaseButton.vue'
import BaseInput from '@/components/forms/BaseInput.vue'
import BaseSelect from '@/components/forms/BaseSelect.vue'
import BaseTextarea from '@/components/forms/BaseTextarea.vue'
import CheckboxRow from '@/components/forms/CheckboxRow.vue'
import FormField from '@/components/layout/FormField.vue'
import PanelSection from '@/components/layout/PanelSection.vue'

import { DEFAULT_PREFERENCES, listToText, textToList, type UserPreferences } from './preferences'
import {
  clearStoragePreferences,
  loadStoragePreferences,
  sanitizeStorageProfile,
  saveStoragePreferences,
  type StoragePreferences,
} from './storagePreferences'

const route = useRoute()
const notification = useNotificationStore()

// ---------------------------------------------------------------------------
// 1. Storage 偏好 (localStorage)
// ---------------------------------------------------------------------------

const storageForm = ref<StoragePreferences>({ storageDir: '', saveRequest: true })
const storageStatus = ref<{ kind: 'success' | 'error' | 'info' | 'empty'; message: string }>({
  kind: 'empty',
  message: '尚未读取浏览器偏好。',
})

function restoreStoragePreferences(): void {
  storageForm.value = loadStoragePreferences()
  const text = storageForm.value.storageDir
    ? `storage profile：${storageForm.value.storageDir}`
    : '默认服务器 storage 根目录'
  const saveText = storageForm.value.saveRequest ? '默认保存订阅方案 JSON' : '默认只生成预览'
  storageStatus.value = { kind: 'empty', message: `已读取浏览器偏好。当前使用${text}；${saveText}。可在 Settings 修改。` }
}

function persistStoragePreferences(): void {
  const rawDir = storageForm.value.storageDir
  const safeDir = sanitizeStorageProfile(rawDir)
  const saveRequest = Boolean(storageForm.value.saveRequest)
  saveStoragePreferences({ storageDir: safeDir, saveRequest })
  storageForm.value.storageDir = safeDir
  const migrationNote =
    safeDir !== rawDir.trim() && rawDir.trim() !== ''
      ? '（已忽略不安全的 storage profile，改用服务器默认根目录）'
      : ''
  storageStatus.value = { kind: 'success', message: `偏好已保存。${migrationNote}` }
}

function clearStorage(): void {
  clearStoragePreferences()
  storageForm.value = { storageDir: '', saveRequest: true }
  storageStatus.value = {
    kind: 'info',
    message: '偏好已清除；订阅方案工作台将使用服务器默认 storage 根目录并保存订阅方案 JSON。',
  }
}

// The workbench reads the storage profile from localStorage; this getter keeps
// the (non-sensitive) relative profile available to feature requests.
function currentStorageDir(): string {
  return sanitizeStorageProfile(storageForm.value.storageDir)
}

// ---------------------------------------------------------------------------
// 2. 偏好默认值 (/api/v1/preferences)
// ---------------------------------------------------------------------------

const preferenceForm = ref<UserPreferences>(structuredClone(DEFAULT_PREFERENCES))
// Last successfully loaded/saved preference set. On a failed save we restore
// these values so a rejected sensitive/illegal input never stays in the form
// (same behavior as the legacy page: renderPreferenceSettings(currentPreferenceValues)).
let lastGoodPreferences: UserPreferences = structuredClone(DEFAULT_PREFERENCES)
const preferenceStatus = ref<{ kind: 'success' | 'error' | 'info' | 'empty'; message: string }>({
  kind: 'empty',
  message: '尚未读取偏好默认值。',
})
const preferenceLoading = ref(false)

const preferredText = computed({
  get: () => listToText(preferenceForm.value.subtitle_groups.preferred),
  set: (value: string) => {
    preferenceForm.value.subtitle_groups.preferred = textToList(value)
  },
})
const excludedText = computed({
  get: () => listToText(preferenceForm.value.subtitle_groups.excluded),
  set: (value: string) => {
    preferenceForm.value.subtitle_groups.excluded = textToList(value)
  },
})

function renderPreferences(preferences: UserPreferences): void {
  preferenceForm.value = structuredClone(preferences)
  lastGoodPreferences = structuredClone(preferences)
}

function restoreLastGoodPreferences(): void {
  preferenceForm.value = structuredClone(lastGoodPreferences)
}

function buildPreferencePayload(): { preferences: UserPreferences } {
  return {
    preferences: {
      version: 1,
      subtitle_groups: {
        preferred: textToList(preferredText.value),
        excluded: textToList(excludedText.value),
        fallback: preferenceForm.value.subtitle_groups.fallback,
      },
      filter_defaults: {
        must_contain: preferenceForm.value.filter_defaults.must_contain.trim(),
        must_not_contain: preferenceForm.value.filter_defaults.must_not_contain.trim(),
        use_regex: preferenceForm.value.filter_defaults.use_regex,
        case_sensitive: preferenceForm.value.filter_defaults.case_sensitive,
      },
      naming: {
        strategy: preferenceForm.value.naming.strategy,
        template: preferenceForm.value.naming.template.trim(),
      },
      search: {
        reuse_explicit_corrections: preferenceForm.value.search.reuse_explicit_corrections,
      },
    },
  }
}

function preferenceQuery(): { storage_dir?: string } {
  const dir = currentStorageDir()
  return dir ? { storage_dir: dir } : {}
}

async function loadPreferences(): Promise<void> {
  preferenceLoading.value = true
  preferenceStatus.value = { kind: 'info', message: '正在读取偏好默认值...' }
  try {
    const preferences = await api.get<UserPreferences>('/api/v1/preferences', { query: preferenceQuery() })
    renderPreferences(preferences)
    preferenceStatus.value = { kind: 'empty', message: '已读取偏好默认值。' }
  } catch (error) {
    void error
    restoreLastGoodPreferences()
    preferenceStatus.value = { kind: 'error', message: '读取偏好默认值失败。请检查存储目录后重试。' }
  } finally {
    preferenceLoading.value = false
  }
}

async function savePreferences(): Promise<void> {
  preferenceLoading.value = true
  preferenceStatus.value = { kind: 'info', message: '正在保存偏好默认值...' }
  try {
    const preferences = await api.post<UserPreferences>('/api/v1/preferences', {
      query: preferenceQuery(),
      body: buildPreferencePayload(),
    })
    renderPreferences(preferences)
    preferenceStatus.value = { kind: 'success', message: '偏好默认值已保存。' }
    notification.success('偏好默认值已保存', '后续批量订阅草案将使用这些默认值。')
  } catch (error) {
    // 回退到上次已成功加载/保存的偏好，保证被拒绝的敏感输入不会残留在表单中。
    void error
    restoreLastGoodPreferences()
    preferenceStatus.value = { kind: 'error', message: '保存偏好默认值失败。请修正后重试。' }
    notification.error('保存偏好默认值失败', '请修正后重试。')
  } finally {
    preferenceLoading.value = false
  }
}

async function resetPreferences(): Promise<void> {
  const confirmed = await confirmDialog.value?.confirm({
    title: '恢复默认偏好',
    message: '确认恢复所有偏好为默认值？此操作不会清除订阅方案、批量提交队列或 Auto Bangumi 结果存储。',
    confirmLabel: '恢复默认',
    danger: true,
  })
  if (!confirmed) return

  preferenceLoading.value = true
  preferenceStatus.value = { kind: 'info', message: '正在恢复默认偏好...' }
  try {
    const preferences = await api.post<UserPreferences>('/api/v1/preferences', {
      query: preferenceQuery(),
      body: { preferences: {} },
    })
    renderPreferences(preferences)
    preferenceStatus.value = { kind: 'success', message: '已恢复默认偏好。' }
    notification.success('已恢复默认偏好', '偏好默认值已清空，订阅方案与队列不受影响。')
  } catch (error) {
    void error
    restoreLastGoodPreferences()
    preferenceStatus.value = { kind: 'error', message: '恢复默认偏好失败。请重试。' }
    notification.error('恢复默认偏好失败', '请重试。')
  } finally {
    preferenceLoading.value = false
  }
}

// ---------------------------------------------------------------------------
// 3. qBittorrent connection test
// ---------------------------------------------------------------------------

const qbittorrent = useSensitiveFields({
  endpoint: { label: 'endpoint', required: true },
  username: { label: 'username', required: true },
  password: { label: 'password', required: true },
})
const qbittorrentTimeout = ref(10)
const qbittorrentVerifyTls = ref(true)
const qbittorrentLoading = ref(false)
const qbittorrentStatus = ref<{ kind: 'success' | 'error' | 'info' | 'empty'; message: string }>({
  kind: 'empty',
  message: '尚未测试 qBittorrent 连接。',
})

const qbittorrentEndpoint = computed({
  get: () => qbittorrent.get('endpoint'),
  set: (value: string) => qbittorrent.set('endpoint', value),
})
const qbittorrentUsername = computed({
  get: () => qbittorrent.get('username'),
  set: (value: string) => qbittorrent.set('username', value),
})
const qbittorrentPassword = computed({
  get: () => qbittorrent.get('password'),
  set: (value: string) => qbittorrent.set('password', value),
})

async function testQbittorrentConnection(): Promise<void> {
  const missing = qbittorrent.firstMissing()
  if (missing) {
    qbittorrentStatus.value = { kind: 'error', message: `测试 qBittorrent 前必须填写 ${missing}。` }
    return
  }
  const timeout = Number(qbittorrentTimeout.value)
  if (!Number.isFinite(timeout) || timeout <= 0) {
    qbittorrentStatus.value = { kind: 'error', message: '测试 qBittorrent 前 timeout_seconds 必须为正数。' }
    return
  }
  const confirmed = await confirmDialog.value?.confirm({
    title: '测试 qBittorrent 连接',
    message: '确认使用当前 qBittorrent 配置测试连接？',
    confirmLabel: '测试连接',
  })
  if (!confirmed) return

  qbittorrentLoading.value = true
  qbittorrentStatus.value = { kind: 'info', message: '正在测试 qBittorrent 连接...' }
  try {
    const result = await api.post<{ status: string; reachable: boolean; version: string }>(
      '/api/v1/qbittorrent/test-connection',
      {
        body: {
          qbittorrent_config: {
            endpoint: qbittorrent.get('endpoint'),
            username: qbittorrent.get('username'),
            password: qbittorrent.get('password'),
            timeout_seconds: timeout,
            verify_tls: qbittorrentVerifyTls.value,
          },
        },
      },
    )
    qbittorrentStatus.value = {
      kind: 'success',
      message: `status: ${result.status}；reachable: ${result.reachable}；version: ${result.version}`,
    }
    qbittorrent.clearAll()
  } catch (error) {
    // 只显示固定中文反馈，绝不把服务端原始错误（可能含 endpoint/凭据）渲染出来。
    void error
    qbittorrentStatus.value = {
      kind: 'error',
      message: 'qBittorrent 连接测试失败。请检查配置后重试。',
    }
  } finally {
    qbittorrentLoading.value = false
  }
}

// ---------------------------------------------------------------------------
// 4. Auto Bangumi connection test + submit context
// ---------------------------------------------------------------------------

const ab = useSensitiveFields({
  baseUrl: { label: '服务地址', required: true },
  username: { label: '用户名' },
  password: { label: '密码' },
  token: { label: 'API Token' },
})
const abAuthMode = ref<'password' | 'api_token'>('password')
const abFallbackEnabled = ref(false)
const abLoading = ref(false)
const abStatus = ref<{ kind: 'success' | 'error' | 'info' | 'empty'; message: string }>({
  kind: 'empty',
  message: '可先测试 Auto Bangumi 连接；从已确认订阅方案详情进入后，可提交订阅方案。认证信息不会持久化。',
})

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

const requestId = computed(() => {
  const value = route.query.request_id
  return typeof value === 'string' ? value.trim() : ''
})
const hasRequestContext = computed(() => requestId.value.length > 0)

function buildAbConfig(): Record<string, string | boolean> {
  const base: Record<string, string | boolean> = {
    auth_mode: abAuthMode.value,
    base_url: ab.get('baseUrl'),
    fallback_enabled: abFallbackEnabled.value,
  }
  if (abAuthMode.value === 'api_token') {
    base.token = ab.get('token')
  } else {
    base.username = ab.get('username')
    base.password = ab.get('password')
  }
  return base
}

function abValidate(): string | null {
  if (!ab.get('baseUrl')) return '请填写服务地址。'
  if (abAuthMode.value === 'api_token') {
    if (!ab.get('token')) return '请填写 API Token。'
  } else {
    if (!ab.get('username')) return '请填写用户名。'
    if (!ab.get('password')) return '请填写密码。'
  }
  return null
}

function switchAbAuthMode(): void {
  ab.reset()
}

async function testAbConnection(): Promise<void> {
  const validation = abValidate()
  if (validation) {
    abStatus.value = { kind: 'error', message: validation }
    return
  }
  abLoading.value = true
  abStatus.value = { kind: 'info', message: '正在测试 Auto Bangumi 连接...' }
  try {
    const result = await api.post<{
      reachable: boolean
      authenticated: boolean
      version: string
      auth_mode: string
      adapter: string
      submit_supported: boolean
    }>('/api/v1/autobangumi/test-connection', {
      body: { ab_config: buildAbConfig() },
    })
    abStatus.value = {
      kind: 'success',
      message: `连接成功；版本：${result.version}；认证方式：${result.auth_mode}`,
    }
    ab.clearAll()
  } catch (error) {
    // 只显示固定中文反馈，绝不把服务端原始错误（可能含凭据）渲染出来。
    void error
    abStatus.value = {
      kind: 'error',
      message: 'Auto Bangumi 连接测试失败。请检查配置后重试。',
    }
  } finally {
    abLoading.value = false
  }
}

async function submitAb(): Promise<void> {
  if (!requestId.value) {
    abStatus.value = { kind: 'error', message: '缺少 request_id，无法提交 Auto Bangumi。' }
    return
  }
  const validation = abValidate()
  if (validation) {
    abStatus.value = { kind: 'error', message: validation }
    return
  }
  const confirmed = await confirmDialog.value?.confirm({
    title: '提交 Auto Bangumi',
    message: '确认提交此订阅方案到 Auto Bangumi？',
    confirmLabel: '确认提交',
    danger: true,
  })
  if (!confirmed) return

  abLoading.value = true
  abStatus.value = { kind: 'info', message: '正在提交 Auto Bangumi...' }
  try {
    const result = await api.post<{
      ab_submit_result: {
        success: boolean
        ab_subscription_id: string | null
        ab_response: Record<string, unknown>
        fallback_config: Record<string, unknown> | null
        error: Record<string, unknown> | null
      }
    }>('/api/v1/requests/{request_id}/submit-ab', {
      path: { request_id: requestId.value },
      query: preferenceQuery(),
      body: { ab_config: buildAbConfig() },
    })
    const submitResult = result.ab_submit_result
    const subscriptionId = submitResult.ab_subscription_id
      ? `；ab_subscription_id: ${submitResult.ab_subscription_id}`
      : ''
    abStatus.value = {
      kind: 'success',
      message: `Auto Bangumi 提交成功；request_id: ${requestId.value}${subscriptionId}`,
    }
    notification.success('Auto Bangumi 提交成功', `订阅方案 ${requestId.value}`)
    ab.clearAll()
  } catch (error) {
    // 只显示固定中文反馈，绝不把服务端原始错误（可能含凭据）渲染出来。
    void error
    abStatus.value = {
      kind: 'error',
      message: 'Auto Bangumi 提交失败。请检查配置与订阅方案状态后重试。',
    }
    notification.error('Auto Bangumi 提交失败', '请检查配置与订阅方案状态后重试。')
  } finally {
    abLoading.value = false
  }
}

const confirmDialog = ref<InstanceType<typeof ConfirmDialog> | null>(null)

onMounted(() => {
  restoreStoragePreferences()
  void loadPreferences()
})
</script>

<template>
  <div class="settings-view">
    <h2 id="settings-heading" class="settings-title">Settings</h2>
    <p class="field-help">
      配置与连接测试集中在 Settings；敏感外部系统配置保持显式输入，不写入浏览器存储、URL 或本地订阅方案 JSON。
    </p>

    <!-- 1. Storage 偏好 -->
    <PanelSection title="Storage 偏好">
      <form id="storage-preferences-form" class="settings-form" @submit.prevent="persistStoragePreferences">
        <p class="field-help">
          非敏感浏览器偏好；仅写入当前浏览器 localStorage，不保存外部系统配置或凭据。
        </p>

        <FormField
          label="默认 storage profile"
          inputId="settings-storage-dir"
          help="留空时订阅方案工作台使用服务器默认 storage 根目录。只能填写服务器允许根目录下的相对目录名（profile），不能填写绝对路径；不安全的旧值会自动回退到默认根目录。"
        >
          <BaseInput
            id="settings-storage-dir"
            v-model="storageForm.storageDir"
            name="storage_dir"
            type="text"
            placeholder="例如 backups（相对服务器 storage 根目录）"
            autocomplete="off"
          />
        </FormField>

        <CheckboxRow
          id="settings-save-request"
          v-model:checked="storageForm.saveRequest"
          label="默认保存订阅方案"
          help="开启后订阅方案工作台默认写入订阅方案 JSON；关闭时只生成预览。"
        />

        <StatusAlert :kind="storageStatus.kind" :message="storageStatus.message" />

        <div class="settings-actions">
          <BaseButton id="storage-preferences-save" type="submit" variant="primary">保存偏好</BaseButton>
          <BaseButton id="storage-preferences-clear" variant="danger" @click="clearStorage">清除偏好</BaseButton>
        </div>
      </form>
    </PanelSection>

    <!-- 2. 偏好默认值 -->
    <PanelSection title="偏好默认值">
      <form id="preference-settings-form" class="settings-form" @submit.prevent="savePreferences">
        <p class="field-help">
          这些偏好只保存非敏感用户选择，用于为批量订阅草案提供默认值。不会保存 endpoint、token、cookie、
          Authorization 头或任何原始外部响应。
        </p>

        <FormField
          label="偏好字幕组（每行一个）"
          inputId="preference-preferred-groups"
          help="批量草案会优先使用这些字幕组；留空时不偏好任何字幕组。"
        >
          <BaseTextarea
            id="preference-preferred-groups"
            v-model="preferredText"
            name="preferred_groups"
            placeholder="喵萌"
          />
        </FormField>

        <FormField
          label="排除字幕组（每行一个）"
          inputId="preference-excluded-groups"
          help="这些字幕组不会被批量草案选择；同一字幕组不能同时出现在偏好与排除列表。"
        >
          <BaseTextarea
            id="preference-excluded-groups"
            v-model="excludedText"
            name="excluded_groups"
            placeholder="Loli"
          />
        </FormField>

        <FormField
          label="无偏好命中时的回退"
          inputId="preference-fallback"
          help="偏好字幕组都没有有效种子时，是否继续尝试下一个偏好字幕组。"
        >
          <BaseSelect
            id="preference-fallback"
            v-model="preferenceForm.subtitle_groups.fallback"
            label="无偏好命中时的回退"
            :options="[
              { value: 'next_preferred', label: '依次使用下一个偏好字幕组' },
              { value: 'none', label: '不自动回退' },
            ]"
          />
        </FormField>

        <FormField label="默认包含规则" inputId="preference-filter-must-contain">
          <BaseInput
            id="preference-filter-must-contain"
            v-model="preferenceForm.filter_defaults.must_contain"
            name="must_contain"
            type="text"
            placeholder="1080p"
            autocomplete="off"
          />
        </FormField>

        <FormField label="默认排除规则" inputId="preference-filter-must-not-contain">
          <BaseInput
            id="preference-filter-must-not-contain"
            v-model="preferenceForm.filter_defaults.must_not_contain"
            name="must_not_contain"
            type="text"
            placeholder="合集版"
            autocomplete="off"
          />
        </FormField>

        <CheckboxRow
          id="preference-filter-use-regex"
          v-model:checked="preferenceForm.filter_defaults.use_regex"
          label="默认使用正则"
        />
        <CheckboxRow
          id="preference-filter-case-sensitive"
          v-model:checked="preferenceForm.filter_defaults.case_sensitive"
          label="默认大小写敏感"
        />
        <p class="field-help">作为批量草案的默认筛选规则；默认按字面文本匹配且不区分大小写。</p>

        <FormField
          label="命名策略"
          inputId="preference-naming-strategy"
          help="只生成文件夹名默认值，仍可在单卡修改流程中覆盖。"
        >
          <BaseSelect
            id="preference-naming-strategy"
            v-model="preferenceForm.naming.strategy"
            label="命名策略"
            :options="[
              { value: 'official_title_season', label: '官方标题 + 季数' },
              { value: 'official_title', label: '官方标题' },
              { value: 'raw_title', label: '原始标题' },
            ]"
          />
        </FormField>

        <FormField label="命名模板" inputId="preference-naming-template">
          <BaseInput
            id="preference-naming-template"
            v-model="preferenceForm.naming.template"
            name="naming_template"
            type="text"
            placeholder="{title}"
            autocomplete="off"
          />
        </FormField>

        <CheckboxRow
          id="preference-search-reuse-corrections"
          v-model:checked="preferenceForm.search.reuse_explicit_corrections"
          label="复用已保存的搜索词修正"
        />

        <StatusAlert :kind="preferenceStatus.kind" :message="preferenceStatus.message" />

        <div class="settings-actions">
          <BaseButton id="preference-settings-save" type="submit" variant="primary" :loading="preferenceLoading">
            保存偏好默认值
          </BaseButton>
          <BaseButton id="preference-settings-reset" variant="danger" :disabled="preferenceLoading" @click="resetPreferences">
            恢复默认
          </BaseButton>
        </div>
      </form>
    </PanelSection>

    <!-- 3. qBittorrent -->
    <PanelSection title="qBittorrent">
      <form id="settings-qbittorrent-test-form" class="settings-form" @submit.prevent="testQbittorrentConnection">
        <p class="field-help">
          配置仅用于本次连接测试；endpoint、username 和 password 不写入浏览器存储、URL 或订阅方案 JSON。
        </p>

        <FormField label="endpoint" inputId="settings-qbittorrent-endpoint">
          <BaseInput
            id="settings-qbittorrent-endpoint"
            v-model="qbittorrentEndpoint"
            name="qbittorrent_endpoint"
            type="text"
            placeholder="qBittorrent Web UI endpoint"
            autocomplete="off"
          />
        </FormField>

        <FormField label="username" inputId="settings-qbittorrent-username">
          <BaseInput
            id="settings-qbittorrent-username"
            v-model="qbittorrentUsername"
            name="qbittorrent_username"
            type="text"
            autocomplete="off"
          />
        </FormField>

        <FormField label="password" inputId="settings-qbittorrent-password">
          <BaseInput
            id="settings-qbittorrent-password"
            v-model="qbittorrentPassword"
            name="qbittorrent_password"
            type="password"
            autocomplete="off"
          />
        </FormField>

        <FormField label="timeout_seconds" inputId="settings-qbittorrent-timeout-seconds">
          <BaseInput
            id="settings-qbittorrent-timeout-seconds"
            v-model="qbittorrentTimeout"
            name="qbittorrent_timeout_seconds"
            type="number"
            min="0.1"
            step="0.1"
          />
        </FormField>

        <CheckboxRow
          id="settings-qbittorrent-verify-tls"
          v-model:checked="qbittorrentVerifyTls"
          label="verify_tls"
        />
        <p class="field-help">提交前需要确认；成功后只显示 status、reachable 和 version，并清空敏感输入。</p>

        <StatusAlert :kind="qbittorrentStatus.kind" :message="qbittorrentStatus.message" />

        <div class="settings-actions">
          <BaseButton id="settings-qbittorrent-test-submit" type="submit" variant="primary" :loading="qbittorrentLoading">
            测试 qBittorrent 连接
          </BaseButton>
        </div>
      </form>
    </PanelSection>

    <!-- 4. Auto Bangumi -->
    <PanelSection title="Auto Bangumi">
      <div id="settings-ab-context" class="settings-ab-context">
        <p v-if="hasRequestContext" class="field-help">
          当前 request_id：<code id="settings-ab-request-id">{{ requestId }}</code>。仅已确认订阅方案可提交。
        </p>
        <p v-else class="field-help">
          可先测试 Auto Bangumi 连接；从已确认订阅方案详情进入后，可提交订阅方案。认证信息不会持久化。
        </p>
      </div>

      <form id="settings-ab-submit-form" class="settings-form" @submit.prevent="submitAb">
        <p class="field-help">
          服务地址和认证信息只用于本次请求，不写入浏览器存储、URL 或订阅方案 JSON。
        </p>

        <FormField label="认证方式" inputId="settings-ab-auth-mode">
          <BaseSelect
            id="settings-ab-auth-mode"
            v-model="abAuthMode"
            label="认证方式"
            :options="[
              { value: 'password', label: '账号密码' },
              { value: 'api_token', label: 'API Token' },
            ]"
            @change="switchAbAuthMode"
          />
        </FormField>

        <FormField label="服务地址" inputId="settings-ab-endpoint">
          <BaseInput
            id="settings-ab-endpoint"
            v-model="abBaseUrl"
            name="ab_base_url"
            type="url"
            autocomplete="off"
            placeholder="例如：局域网 Auto Bangumi 服务根地址"
          />
        </FormField>

        <template v-if="abAuthMode === 'password'">
          <FormField label="用户名" inputId="settings-ab-username">
            <BaseInput
              id="settings-ab-username"
              v-model="abUsername"
              name="ab_username"
              type="text"
              autocomplete="username"
            />
          </FormField>
          <FormField label="密码" inputId="settings-ab-password">
            <BaseInput
              id="settings-ab-password"
              v-model="abPassword"
              name="ab_password"
              type="password"
              autocomplete="current-password"
            />
          </FormField>
        </template>
        <template v-else>
          <FormField label="API Token" inputId="settings-ab-token">
            <BaseInput
              id="settings-ab-token"
              v-model="abToken"
              name="ab_token"
              type="password"
              autocomplete="off"
              placeholder="Auto Bangumi Token"
            />
          </FormField>
        </template>

        <CheckboxRow
          id="settings-ab-fallback-enabled"
          v-model:checked="abFallbackEnabled"
          label="提交时启用备用兼容选项"
        />
        <p class="field-help">
          默认使用账号密码；API Token 模式仅兼容只读连接探测。提交前需要确认；成功后清空认证信息。
        </p>

        <StatusAlert :kind="abStatus.kind" :message="abStatus.message" />

        <div class="settings-actions">
          <BaseButton id="settings-ab-test-submit" :disabled="abLoading" @click="testAbConnection">
            测试连接
          </BaseButton>
          <BaseButton id="settings-ab-submit" type="submit" variant="primary" :loading="abLoading">
            提交 Auto Bangumi
          </BaseButton>
          <RouterLink
            v-if="hasRequestContext"
            id="settings-ab-return-link"
            class="base-button secondary-button"
            :to="{ path: '/workbench', query: { request_id: requestId } }"
          >
            返回订阅方案详情
          </RouterLink>
        </div>
      </form>
    </PanelSection>

    <ConfirmDialog ref="confirmDialog" />
  </div>
</template>

<style scoped>
.settings-view {
  display: grid;
  gap: 1.25rem;
}

.settings-title {
  margin: 0;
  font-size: 1.25rem;
}

.settings-form {
  display: grid;
  gap: 0.75rem;
  max-width: 640px;
}

.settings-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 0.5rem;
  margin-top: 0.25rem;
}

.settings-ab-context {
  margin-bottom: 0.5rem;
}

.settings-ab-context code {
  font-weight: 600;
}
</style>
