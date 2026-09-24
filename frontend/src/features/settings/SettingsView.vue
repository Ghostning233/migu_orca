<script setup lang="ts">
// Settings (US-201).
//
// Migrated from the legacy `/settings` page onto the shared primitives
// (PanelSection/FormField/BaseInput/BaseTextarea/BaseSelect/CheckboxRow,
// ConfirmDialog/StatusAlert, useSensitiveFields). Four panels:
//
//   1. Storage 偏好 — non-sensitive browser preferences (storage profile)
//      stored ONLY in localStorage, sanitized to
//      a server-root-relative profile (US-193).
//   2. 偏好默认值 — non-sensitive preference defaults read/saved through
//      `/api/v1/preferences` (defaults when absent).
//   3. Auto Bangumi deployment settings — credentials live only in component
//      memory (useSensitiveFields) and are cleared on success/cancel/unmount.
//   4. Auto Bangumi deployment settings. Credentials live only in memory and
//      are cleared on success/cancel/unmount.
//
// Security boundary: endpoint/username/password/token/base_url values are
// component-local reactive memory only (useSensitiveFields); they are never
// written to store, URL, localStorage/sessionStorage, logs or traces. The
// AB submit context (request_id) is read from the URL query but the
// credentials themselves never go into the URL.
import { computed, onMounted, ref, watch } from 'vue'

import { api, isApiError, toApiError } from '@/api/client'
import type { operations } from '@/api/generated/api'
import { useNotificationStore } from '@/app/stores/notification'
import { refreshConnectionStatus } from '@/app/stores/connectionStatus'
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
import {
  AUTO_BANGUMI_SERVICE_ROOT_HELP,
  validateAutoBangumiServiceRoot,
} from '@/features/autobangumi/serviceRoot'

import { DEFAULT_PREFERENCES, listToText, textToList, type UserPreferences } from './preferences'
import {
  clearStoragePreferences,
  loadStoragePreferences,
  sanitizeStorageProfile,
  saveStoragePreferences,
  type StoragePreferences,
} from './storagePreferences'

const notification = useNotificationStore()

// ---------------------------------------------------------------------------
// 1. Storage 偏好 (localStorage)
// ---------------------------------------------------------------------------

const storageForm = ref<StoragePreferences>({ storageDir: '' })
const storageStatus = ref<{ kind: 'success' | 'error' | 'info' | 'empty'; message: string }>({
  kind: 'empty',
  message: '尚未读取浏览器偏好。',
})

function restoreStoragePreferences(): void {
  storageForm.value = loadStoragePreferences()
  const text = storageForm.value.storageDir
    ? `数据档案 ${storageForm.value.storageDir}`
    : '服务器默认数据档案'
  storageStatus.value = { kind: 'empty', message: `已读取浏览器选择。当前浏览器使用${text}。` }
}

function persistStoragePreferences(): void {
  const previousDir = loadStoragePreferences().storageDir
  const rawDir = storageForm.value.storageDir
  const safeDir = sanitizeStorageProfile(rawDir)
  saveStoragePreferences({ storageDir: safeDir })
  refreshConnectionStatus()
  storageForm.value.storageDir = safeDir
  const migrationNote =
    safeDir !== rawDir.trim() && rawDir.trim() !== ''
      ? '（已忽略不安全的数据档案，改用服务器默认根目录）'
      : ''
  // Issue 117：切换档案只改变当前浏览器选用的 profile，不迁移任何历史数据。
  const switchNote =
    safeDir !== previousDir
      ? '切换数据档案不会移动原有数据；可切回原档案查看。'
      : ''
  storageStatus.value = {
    kind: 'success',
    message: `数据档案已保存。${switchNote}${migrationNote}`,
  }
}

function clearStorage(): void {
  clearStoragePreferences()
  refreshConnectionStatus()
  storageForm.value = { storageDir: '' }
  storageStatus.value = {
    kind: 'info',
    message: '已清除选择；当前浏览器将使用服务器默认数据档案，原有数据不会被移动。',
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
// 3. Auto Bangumi saved deployment connection
// ---------------------------------------------------------------------------

const ab = useSensitiveFields({
  baseUrl: { label: '服务地址', required: true },
  username: { label: '用户名' },
  password: { label: '密码' },
  token: { label: 'API Token' },
})
const abAuthMode = ref<'password' | 'api_token'>('password')
const abProtocol = ref<'http' | 'https'>('http')
const abHost = ref('')
const abPort = ref('')
const abLocked = ref(false)
const verifiedDraft = ref<string | null>(null)
const abLoading = ref(false)
const abStatus = ref<{ kind: 'success' | 'error' | 'info' | 'empty'; message: string }>({
  kind: 'empty',
  message: '已保存连接只显示安全摘要；秘密不会回显。',
})
type ConnectionSummary = NonNullable<operations['getAutoBangumiConnection']['responses']['200']['content']['application/json']['result']>
type SaveConnectionBody = NonNullable<operations['saveAutoBangumiConnection']['requestBody']['content']['application/json']>
type TestConnectionBody = NonNullable<operations['testAutoBangumiConnection']['requestBody']['content']['application/json']>
type TestConnectionResult = NonNullable<operations['testAutoBangumiConnection']['responses']['200']['content']['application/json']['result']>
const savedConnection = ref<ConnectionSummary | null>(null)
const draftGeneration = ref(0)
const verifiedGeneration = ref<number | null>(null)

const abBaseUrl = computed({
  get: () => `${abProtocol.value}://${abHost.value}${abPort.value ? `:${abPort.value}` : ''}`,
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

function buildAbConfig(): Record<string, string> {
  const serviceRoot = validateAutoBangumiServiceRoot(abBaseUrl.value)
  const base: Record<string, string | boolean> = {
    auth_mode: abAuthMode.value,
    base_url: serviceRoot.value ?? abBaseUrl.value.trim(),
  }
  if (abAuthMode.value === 'api_token') {
    base.token = ab.get('token')
  } else {
    base.username = ab.get('username')
    base.password = ab.get('password')
  }
  return base as Record<string, string>
}

function abValidate(): string | null {
  if (!abHost.value.trim()) return '请填写主机或 IP。'
  if (abHost.value.includes(':') || /[/?#@\\\s]/.test(abHost.value)) return '主机或 IP 不能包含端口或路径。'
  if (abPort.value && (!/^\d+$/.test(abPort.value) || Number(abPort.value) < 1 || Number(abPort.value) > 65535)) return '端口必须是 1–65535。'
  const serviceRoot = validateAutoBangumiServiceRoot(abBaseUrl.value)
  if (!serviceRoot.value) return serviceRoot.message ?? '请填写合法的 Auto Bangumi 服务根地址。'
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
function invalidateAbDraft(): void {
  draftGeneration.value += 1
  verifiedDraft.value = null
  verifiedGeneration.value = null
}

watch(
  () => [abProtocol.value, abHost.value, abPort.value, abAuthMode.value, abUsername.value, abPassword.value, abToken.value],
  () => {
    draftGeneration.value += 1
    verifiedDraft.value = null
    verifiedGeneration.value = null
  },
  { flush: 'sync' },
)

async function testAbConnection(): Promise<void> {
  const validation = abValidate()
  if (validation) {
    abStatus.value = { kind: 'error', message: validation }
    return
  }
  abLoading.value = true
  abStatus.value = { kind: 'info', message: '正在测试 Auto Bangumi 连接...' }
  try {
    const config = buildAbConfig() as TestConnectionBody['config']
    const requestGeneration = draftGeneration.value
    const requestSnapshot = JSON.stringify(config)
    const result = await api.post<TestConnectionResult>('/api/v1/settings/autobangumi/test', { body: { config } })
    if (!result.success) throw new Error('probe failed')
    if (requestGeneration !== draftGeneration.value || requestSnapshot !== JSON.stringify(buildAbConfig())) {
      abStatus.value = { kind: 'info', message: '连接草稿已变化，测试结果已失效；请重新测试。' }
      return
    }
    verifiedDraft.value = JSON.stringify(config)
    verifiedGeneration.value = draftGeneration.value
    abStatus.value = { kind: 'success', message: '连接测试成功。当前草稿已验证，可以保存。' }
  } catch (error) {
    if (typeof error === 'object' && error !== null && 'status' in error && error.status === 409) {
      await loadSavedConnection()
      abStatus.value = { kind: 'error', message: '配置已变化，已重新读取摘要；请重新确认后再保存。' }
      return
    }
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
async function saveAbConnection(): Promise<void> {
  const validation = abValidate()
  const config = buildAbConfig()
  if (validation) { abStatus.value = { kind: 'error', message: validation }; return }
  if (verifiedGeneration.value !== draftGeneration.value || verifiedDraft.value !== JSON.stringify(config)) { abStatus.value = { kind: 'error', message: '请先测试当前连接草稿；修改任一字段后需重新测试。' }; return }
  abLoading.value = true
  try {
    const body: SaveConnectionBody = { confirm: true, expected_configuration_revision: savedConnection.value?.configuration_revision ?? 0, config: config as SaveConnectionBody['config'] }
    savedConnection.value = await api.put<ConnectionSummary>('/api/v1/settings/autobangumi', { body })
    abLocked.value = true
    verifiedDraft.value = null
    verifiedGeneration.value = null
    ab.clearAll()
    abHost.value = ''
    abPort.value = ''
    refreshConnectionStatus()
    abStatus.value = { kind: 'success', message: 'Auto Bangumi 连接已保存。' }
  } catch (error) {
    const safeError = toApiError(error)
    if (isApiError(error) && safeError.status === 409) {
      await loadSavedConnection()
      abStatus.value = { kind: 'error', message: '配置已变化，已重新读取摘要；请重新确认后再保存。' }
      return
    }
    abStatus.value = { kind: 'error', message: 'Auto Bangumi 连接保存失败，请重试。' }
    notification.error('Auto Bangumi 连接保存失败', '请检查配置后重试。')
  } finally { abLoading.value = false }
}
function editAbConnection(): void { abLocked.value = false; ab.clearAll(); verifiedDraft.value = null; verifiedGeneration.value = null; abStatus.value = { kind: 'info', message: '请重新填写连接信息并测试。' } }
async function loadSavedConnection(): Promise<void> { try { savedConnection.value = await api.get<ConnectionSummary>('/api/v1/settings/autobangumi'); abLocked.value = Boolean(savedConnection.value?.configured) } catch { savedConnection.value = null } }
async function deleteSavedConnection(): Promise<void> { const ok = await confirmDialog.value?.confirm({ title: '清除 Auto Bangumi 连接', message: '确认清除已保存连接？不会影响本地方案或媒体。', confirmLabel: '清除', danger: true }); if (!ok || !savedConnection.value) return; try { savedConnection.value = await api.delete<ConnectionSummary>('/api/v1/settings/autobangumi', { body: { confirm: true, expected_configuration_revision: savedConnection.value.configuration_revision } }); abStatus.value = { kind: 'success', message: '已清除 Auto Bangumi 连接。' }; refreshConnectionStatus() } catch { abStatus.value = { kind: 'error', message: '清除失败，请重新读取后重试。' } } }

const confirmDialog = ref<InstanceType<typeof ConfirmDialog> | null>(null)

onMounted(() => {
  restoreStoragePreferences()
  void loadPreferences()
  void loadSavedConnection()
})
</script>

<template>
  <div class="settings-view">
    <h2 id="settings-heading" class="settings-title">设置</h2>
    <p class="field-help">
      配置与连接测试集中在 Settings；敏感外部系统配置保持显式输入，不写入浏览器存储、URL 或本地订阅方案 JSON。
    </p>

    <!-- 1. 默认偏好（字幕组 / 过滤规则 / 命名方式） -->
    <PanelSection title="默认偏好">
      <form id="preference-settings-form" class="settings-form" @submit.prevent="savePreferences">
        <p class="field-help">
          设置新建番剧时的默认选项；只保存非敏感用户选择，不会保存 endpoint、token、cookie、
          Authorization 头或任何原始外部响应。
        </p>

        <h3 class="settings-group-title">字幕组</h3>
        <p class="field-help">设置偏好的字幕组及排除规则。</p>

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

        <h3 class="settings-group-title">过滤规则</h3>
        <p class="field-help">新建方案时的默认包含与排除规则。</p>

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

        <h3 class="settings-group-title">命名方式</h3>
        <p class="field-help">新建方案时的默认目录命名方式。</p>

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
        <p class="field-help">搜索词修正只影响批量搜索的默认解析，不改变过滤规则或命名方式。</p>

        <StatusAlert :kind="preferenceStatus.kind" :message="preferenceStatus.message" />

        <div class="settings-actions">
          <BaseButton id="preference-settings-save" type="submit" variant="primary" :loading="preferenceLoading">
            保存默认偏好
          </BaseButton>
          <BaseButton id="preference-settings-reset" variant="danger" :disabled="preferenceLoading" @click="resetPreferences">
            恢复默认
          </BaseButton>
        </div>
      </form>
    </PanelSection>

    <!-- 2. MiGuOrca 本地数据（当前浏览器选用的业务数据档案） -->
    <PanelSection title="MiGuOrca 本地数据">
      <form id="storage-preferences-form" class="settings-form" @submit.prevent="persistStoragePreferences">
        <p class="field-help">
          这里的数据档案是当前浏览器选用的 MiGuOrca 业务数据 profile（方案、追番记录等），
          不是下载媒体的位置。选择只写入当前浏览器 localStorage，不保存外部系统配置或凭据。
        </p>

        <FormField
          label="当前浏览器使用的数据档案"
          inputId="settings-storage-dir"
          help="留空时使用服务器默认的数据 profile。只能填写服务器允许根目录下的相对目录名（profile），不能填写绝对路径；切换数据档案不会移动原有数据，可切回原档案查看。不安全的旧值会自动回退到默认根目录。"
        >
          <BaseInput
            id="settings-storage-dir"
            v-model="storageForm.storageDir"
            name="storage_dir"
            type="text"
            placeholder="例如 backups（相对服务器数据根目录）"
            autocomplete="off"
          />
        </FormField>

        <StatusAlert :kind="storageStatus.kind" :message="storageStatus.message" />

        <div class="settings-actions">
          <BaseButton id="storage-preferences-save" type="submit" variant="primary">保存数据档案</BaseButton>
          <BaseButton id="storage-preferences-clear" variant="danger" @click="clearStorage">清除选择</BaseButton>
        </div>
      </form>
    </PanelSection>

    <!-- 3. Auto Bangumi 连接 -->
    <PanelSection title="Auto Bangumi 连接">
      <div id="settings-ab-context" class="settings-ab-context">
        <p class="field-help">已保存连接：{{ savedConnection?.credential_present ? '已配置' : '未配置' }}；配置版本 {{ savedConnection?.configuration_revision ?? 0 }}。</p>
      </div>

      <form id="settings-ab-save-form" class="settings-form" @submit.prevent="saveAbConnection">
        <p class="field-help">连接测试只做当前草稿的瞬时只读探测，不保存配置；保存成功后表单锁定且不回显秘密。</p>

        <FormField label="认证方式" inputId="settings-ab-auth-mode">
          <BaseSelect
            id="settings-ab-auth-mode"
            v-model="abAuthMode"
            label="认证方式"
            :options="[
              { value: 'password', label: '账号密码' },
              { value: 'api_token', label: 'API Token' },
            ]"
            :disabled="abLocked"
            @update:model-value="invalidateAbDraft"
            @input="invalidateAbDraft"
            @change="switchAbAuthMode"
          />
        </FormField>

        <FormField label="协议" inputId="settings-ab-protocol">
          <BaseSelect id="settings-ab-protocol" v-model="abProtocol" label="协议" :disabled="abLocked" :options="[{ value: 'http', label: 'HTTP' }, { value: 'https', label: 'HTTPS' }]" @update:model-value="invalidateAbDraft" />
        </FormField>
        <FormField label="主机或 IP" inputId="settings-ab-endpoint">
          <BaseInput
            id="settings-ab-endpoint"
            v-model="abHost"
            name="ab_host"
            type="text"
            autocomplete="off"
            :disabled="abLocked"
            @update:model-value="invalidateAbDraft"
            placeholder="例如：192.168.1.20"
          />
          <p class="field-help">{{ AUTO_BANGUMI_SERVICE_ROOT_HELP }}主机字段不得包含端口。</p>
        </FormField>
        <FormField label="端口（可选）" inputId="settings-ab-port">
          <BaseInput id="settings-ab-port" v-model="abPort" name="ab_port" type="text" inputmode="numeric" autocomplete="off" placeholder="HTTP 80 / HTTPS 443" :disabled="abLocked" @update:model-value="invalidateAbDraft" @input="invalidateAbDraft" />
        </FormField>

        <template v-if="abAuthMode === 'password'">
          <FormField label="用户名" inputId="settings-ab-username">
            <BaseInput
              id="settings-ab-username"
              v-model="abUsername"
              name="ab_username"
              type="text"
              autocomplete="username"
              :disabled="abLocked"
              @update:model-value="invalidateAbDraft"
              @input="invalidateAbDraft"
            />
          </FormField>
          <FormField label="密码" inputId="settings-ab-password">
            <BaseInput
              id="settings-ab-password"
              v-model="abPassword"
              name="ab_password"
              type="password"
              autocomplete="current-password"
              :disabled="abLocked"
              @update:model-value="invalidateAbDraft"
              @input="invalidateAbDraft"
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
              :disabled="abLocked"
              @update:model-value="invalidateAbDraft"
              @input="invalidateAbDraft"
            />
          </FormField>
        </template>

        <p class="field-help">
          默认使用账号密码；API Token 模式仅兼容只读连接探测。
        </p>

        <StatusAlert :kind="abStatus.kind" :message="abStatus.message" />

        <div class="settings-actions">
          <BaseButton v-if="!abLocked" id="settings-ab-test" type="button" variant="secondary" :loading="abLoading" @click="testAbConnection">测试连接</BaseButton>
          <BaseButton v-if="!abLocked" id="settings-ab-save" type="submit" variant="primary" :disabled="abLoading || !verifiedDraft" :loading="abLoading">保存连接</BaseButton>
          <BaseButton v-else id="settings-ab-edit" type="button" @click="editAbConnection">修改连接</BaseButton>
          <BaseButton id="settings-ab-delete" type="button" variant="danger" :disabled="abLoading || !savedConnection?.credential_present" @click="deleteSavedConnection">清除连接</BaseButton>
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

/* Issue 117：默认偏好按字幕组 / 过滤规则 / 命名方式分段。 */
.settings-group-title {
  margin: var(--space-4) 0 0;
  font-size: var(--font-size-lg);
  font-weight: var(--font-weight-semibold);
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
