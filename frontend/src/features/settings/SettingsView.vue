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

import { api } from '@/api/client'
import type { operations } from '@/api/generated/api'
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
    ? `storage profile：${storageForm.value.storageDir}`
    : '默认服务器 storage 根目录'
  storageStatus.value = { kind: 'empty', message: `已读取浏览器偏好。当前使用${text}。` }
}

function persistStoragePreferences(): void {
  const rawDir = storageForm.value.storageDir
  const safeDir = sanitizeStorageProfile(rawDir)
  saveStoragePreferences({ storageDir: safeDir })
  storageForm.value.storageDir = safeDir
  const migrationNote =
    safeDir !== rawDir.trim() && rawDir.trim() !== ''
      ? '（已忽略不安全的 storage profile，改用服务器默认根目录）'
      : ''
  storageStatus.value = { kind: 'success', message: `偏好已保存。${migrationNote}` }
}

function clearStorage(): void {
  clearStoragePreferences()
  storageForm.value = { storageDir: '' }
  storageStatus.value = {
    kind: 'info',
    message: '偏好已清除；订阅方案工作台将使用服务器默认 storage 根目录。',
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
const abFallbackEnabled = ref(false)
const abLoading = ref(false)
const abStatus = ref<{ kind: 'success' | 'error' | 'info' | 'empty'; message: string }>({
  kind: 'empty',
  message: '已保存连接只显示安全摘要；秘密不会回显。',
})
type ConnectionSummary = NonNullable<operations['getAutoBangumiConnection']['responses']['200']['content']['application/json']['result']>
type SaveConnectionBody = NonNullable<operations['saveAutoBangumiConnection']['requestBody']['content']['application/json']>
type ProbeResult = NonNullable<operations['probeSavedAutoBangumiCapabilities']['responses']['200']['content']['application/json']['result']>
const savedConnection = ref<ConnectionSummary | null>(null)

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

function buildAbConfig(): Record<string, string | boolean> {
  const serviceRoot = validateAutoBangumiServiceRoot(ab.get('baseUrl'))
  const base: Record<string, string | boolean> = {
    auth_mode: abAuthMode.value,
    base_url: serviceRoot.value ?? ab.get('baseUrl').trim(),
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
  const serviceRoot = validateAutoBangumiServiceRoot(ab.get('baseUrl'))
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

async function testAbConnection(): Promise<void> {
  const validation = abValidate()
  if (validation) {
    abStatus.value = { kind: 'error', message: validation }
    return
  }
  abLoading.value = true
  abStatus.value = { kind: 'info', message: '正在测试 Auto Bangumi 连接...' }
  try {
    const body: SaveConnectionBody = { confirm: true, expected_configuration_revision: savedConnection.value?.configuration_revision ?? 0, config: buildAbConfig() as SaveConnectionBody['config'] }
    const result = await api.put<ConnectionSummary>('/api/v1/settings/autobangumi', { body })
    savedConnection.value = result
    abStatus.value = { kind: 'success', message: 'Auto Bangumi 连接已保存。请点击“测试已保存连接”进行显式探测。' }
    ab.clearAll()
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
async function loadSavedConnection(): Promise<void> { try { savedConnection.value = await api.get<ConnectionSummary>('/api/v1/settings/autobangumi') } catch { savedConnection.value = null } }
async function probeSavedConnection(): Promise<void> { if (!savedConnection.value?.connection_ref) return; abLoading.value = true; try { const result = await api.post<ProbeResult>('/api/v1/settings/autobangumi/probe', { body: { connection_ref: savedConnection.value.connection_ref, configuration_revision: savedConnection.value.configuration_revision } }); abStatus.value = { kind: 'success', message: `连接探测结果：${result.probe_status}` } } catch { abStatus.value = { kind: 'error', message: '连接探测失败；已保存配置未删除。' } } finally { abLoading.value = false } }
async function deleteSavedConnection(): Promise<void> { const ok = await confirmDialog.value?.confirm({ title: '清除 Auto Bangumi 连接', message: '确认清除已保存连接？不会影响本地方案或媒体。', confirmLabel: '清除', danger: true }); if (!ok || !savedConnection.value) return; try { savedConnection.value = await api.delete<ConnectionSummary>('/api/v1/settings/autobangumi', { body: { confirm: true, expected_configuration_revision: savedConnection.value.configuration_revision } }); abStatus.value = { kind: 'success', message: '已清除 Auto Bangumi 连接。' } } catch { abStatus.value = { kind: 'error', message: '清除失败，请重新读取后重试。' } } }

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

    <!-- 3. Auto Bangumi -->
    <PanelSection title="Auto Bangumi">
      <div id="settings-ab-context" class="settings-ab-context">
        <p class="field-help">已保存连接：{{ savedConnection?.credential_present ? '已配置' : '未配置' }}；配置版本 {{ savedConnection?.configuration_revision ?? 0 }}。</p>
      </div>

      <form id="settings-ab-save-form" class="settings-form" @submit.prevent="testAbConnection">
        <p class="field-help">保存与探测分离；秘密仅提交到服务端保存配置接口，永不回显。</p>

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
            type="text"
            inputmode="url"
            autocomplete="off"
            placeholder="例如：192.168.1.20:7890"
          />
          <p class="field-help">{{ AUTO_BANGUMI_SERVICE_ROOT_HELP }}</p>
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
          <BaseButton id="settings-ab-save" type="submit" variant="primary" :loading="abLoading">保存连接</BaseButton>
          <BaseButton id="settings-ab-probe" type="button" :disabled="abLoading || !savedConnection?.connection_ref" @click="probeSavedConnection">测试已保存连接</BaseButton>
          <BaseButton id="settings-ab-delete" type="button" variant="danger" :disabled="abLoading || !savedConnection?.credential_present" @click="deleteSavedConnection">清除连接</BaseButton>
        </div>
      </form>
    </PanelSection>

    <PanelSection title="高级诊断">
      <details id="settings-advanced-diagnostics">
        <summary>显示安全诊断信息</summary>
        <p class="field-help">仅显示当前客户端支持的安全能力说明；不会显示地址、外部 ID、原始响应或日志。</p>
        <dl class="settings-diagnostics">
          <dt>客户端版本</dt><dd>MiGuOrca 桌面工作台</dd>
          <dt>连接能力</dt><dd>仅在用户显式探测后更新；已配置不代表持续在线。</dd>
        </dl>
      </details>
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
