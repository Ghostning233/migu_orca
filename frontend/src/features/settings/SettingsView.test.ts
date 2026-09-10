import { mount } from '@vue/test-utils'
import { createPinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createMemoryHistory, createRouter } from 'vue-router'
import { nextTick } from 'vue'

import { api } from '@/api/client'
import SettingsView from '@/features/settings/SettingsView.vue'

// US-201: Settings migration. These tests cover the four panels against the
// shared transport (mocked) and the shared primitives:
//  1. Storage 偏好 — localStorage only, sanitized relative profile,
//  2. 偏好默认值 — GET/POST /api/v1/preferences + reset-with-confirm,
//  3. qBittorrent — request-scoped connection test with confirm + clear,
//  4. Auto Bangumi — connection test + submit-ab with request_id from the URL.
//
// Sensitive values (endpoint/username/password/token) must never appear in
// localStorage, sessionStorage or the rendered DOM after success/cancel.

vi.mock('@/api/client', () => ({
  api: {
    get: vi.fn(),
    post: vi.fn(),
    put: vi.fn(),
    patch: vi.fn(),
    delete: vi.fn(),
    poster: vi.fn(),
  },
  toApiError: (error: unknown) =>
    error && typeof error === 'object' && 'type' in error
      ? (error as { type: string; message: string })
      : { type: 'request_error', message: '请求失败，请重试' },
  isApiError: () => false,
  apiRequest: vi.fn(),
}))

const apiGet = vi.mocked(api.get)
const apiPost = vi.mocked(api.post)

const DEFAULT_PREFERENCES = {
  version: 1,
  subtitle_groups: { preferred: [], excluded: [], fallback: 'next_preferred' },
  filter_defaults: { must_contain: '', must_not_contain: '', use_regex: false, case_sensitive: false },
  naming: { strategy: 'official_title_season', template: '{title}' },
  search: { reuse_explicit_corrections: true },
}

const SAVED_PREFERENCES = {
  version: 1,
  subtitle_groups: { preferred: ['喵萌'], excluded: ['Loli'], fallback: 'none' },
  filter_defaults: { must_contain: '1080p', must_not_contain: '合集版', use_regex: true, case_sensitive: true },
  naming: { strategy: 'raw_title', template: '[{title}]' },
  search: { reuse_explicit_corrections: false },
}

async function mountSettings(query: Record<string, string> = {}) {
  const router = createRouter({
    history: createMemoryHistory('/app/'),
    routes: [
      {
        path: '/settings',
        name: 'settings',
        component: SettingsView,
      },
      // The AB panel's "返回订阅方案详情" link targets the requests list where
      // the detail panel lives (US-203); keep the test router table in sync
      // with the real one to avoid "No match found".
      {
        path: '/plans',
        name: 'plans',
        component: { template: '<p>requests</p>' },
      },
    ],
  })
  await router.push({ path: '/settings', query })
  await router.isReady()

  const wrapper = mount(SettingsView, {
    attachTo: document.body,
    global: {
      plugins: [createPinia(), router],
      stubs: { teleport: true },
    },
  })
  await nextTick()
  await nextTick()
  return { wrapper, router }
}

describe('SettingsView storage panel (US-201)', () => {
  beforeEach(() => {
    localStorage.clear()
    sessionStorage.clear()
    apiGet.mockReset()
    apiPost.mockReset()
    apiGet.mockResolvedValue(DEFAULT_PREFERENCES)
  })

  it('loads storage preferences from localStorage on mount', async () => {
    localStorage.setItem('miguOrca.web.storageDir', 'backups')
    localStorage.setItem('miguOrca.web.saveRequest', 'false')
    const { wrapper } = await mountSettings()
    await nextTick()

    const dir = wrapper.find<HTMLInputElement>('#settings-storage-dir')
    expect(dir.element.value).toBe('backups')
    // CheckboxRow renders the id on both the wrapper div and the native input;
    // assert on the input itself.
    expect(wrapper.find<HTMLInputElement>('input#settings-save-request').element.checked).toBe(false)
  })

  it('persists only the sanitized relative profile', async () => {
    const { wrapper } = await mountSettings()
    await nextTick()

    const dir = wrapper.find('#settings-storage-dir')
    await dir.setValue('/etc/passwd')
    await wrapper.find('#storage-preferences-save').trigger('submit')
    await nextTick()

    // The unsafe value is dropped; storage falls back to the server root.
    expect(localStorage.getItem('miguOrca.web.storageDir')).toBeNull()
    expect(wrapper.find('#storage-preferences-form .status-alert').text()).toContain('偏好已保存')
    expect(wrapper.find('#storage-preferences-form .status-alert').text()).toContain('已忽略不安全的 storage profile')
  })

  it('clears both localStorage keys via 清除偏好', async () => {
    localStorage.setItem('miguOrca.web.storageDir', 'backups')
    const { wrapper } = await mountSettings()
    await nextTick()

    await wrapper.find('#storage-preferences-clear').trigger('click')
    await nextTick()

    expect(localStorage.getItem('miguOrca.web.storageDir')).toBeNull()
    expect(localStorage.getItem('miguOrca.web.saveRequest')).toBeNull()
    expect(wrapper.find('#storage-preferences-form .status-alert').text()).toContain('偏好已清除')
  })
})

describe('SettingsView preferences panel (US-201)', () => {
  beforeEach(() => {
    localStorage.clear()
    sessionStorage.clear()
    apiGet.mockReset()
    apiPost.mockReset()
    apiGet.mockResolvedValue(DEFAULT_PREFERENCES)
  })

  it('loads preferences from GET /api/v1/preferences on mount', async () => {
    apiGet.mockResolvedValue(SAVED_PREFERENCES)
    const { wrapper } = await mountSettings()
    await nextTick()
    await nextTick()

    expect(apiGet).toHaveBeenCalledWith('/api/v1/preferences', { query: {} })
    const preferred = wrapper.find<HTMLTextAreaElement>('#preference-preferred-groups')
    expect(preferred.element.value).toBe('喵萌')
    expect(wrapper.find<HTMLSelectElement>('#preference-fallback').element.value).toBe('none')
    expect(wrapper.find<HTMLInputElement>('input#preference-filter-use-regex').element.checked).toBe(true)
    expect(wrapper.find<HTMLInputElement>('#preference-naming-template').element.value).toBe('[{title}]')
    expect(wrapper.find<HTMLInputElement>('input#preference-search-reuse-corrections').element.checked).toBe(false)
    expect(wrapper.find('#preference-settings-form .status-alert').text()).toContain('已读取偏好默认值')
  })

  it('posts the normalized payload and shows success', async () => {
    apiPost.mockResolvedValue(DEFAULT_PREFERENCES)
    const { wrapper } = await mountSettings()
    await nextTick()

    await wrapper.find('#preference-preferred-groups').setValue('喵萌\n\n   \nLoli')
    await wrapper.find('#preference-filter-must-contain').setValue('1080p')
    await wrapper.find('#preference-settings-save').trigger('submit')
    await nextTick()
    await nextTick()

    const body = apiPost.mock.calls[0]?.[1]?.body as { preferences: unknown }
    expect(apiPost).toHaveBeenCalledWith('/api/v1/preferences', expect.anything())
    expect((body as { preferences: { subtitle_groups: { preferred: string[] } } }).preferences.subtitle_groups.preferred)
      .toEqual(['喵萌', 'Loli'])
    expect(wrapper.find('#preference-settings-form .status-alert').text()).toContain('偏好默认值已保存')
  })

  it('reset requires confirmation and posts empty preferences', async () => {
    apiPost.mockResolvedValue(DEFAULT_PREFERENCES)
    const { wrapper } = await mountSettings()
    await nextTick()

    await wrapper.find('#preference-settings-reset').trigger('click')
    await nextTick()
    // ConfirmDialog is open with the danger variant.
    const dialog = wrapper.find('.confirm-dialog')
    expect(dialog.exists()).toBe(true)
    expect(dialog.text()).toContain('恢复默认偏好')
    await dialog.find('.danger-button').trigger('click')
    await nextTick()
    await nextTick()

    expect(apiPost).toHaveBeenCalledWith('/api/v1/preferences', {
      query: {},
      body: { preferences: {} },
    })
    expect(wrapper.find('#preference-settings-form .status-alert').text()).toContain('已恢复默认偏好')
  })

  it('cancelled reset keeps the form unchanged', async () => {
    apiPost.mockResolvedValue(DEFAULT_PREFERENCES)
    const { wrapper } = await mountSettings()
    await nextTick()

    await wrapper.find('#preference-preferred-groups').setValue('喵萌')
    await wrapper.find('#preference-settings-reset').trigger('click')
    await nextTick()
    await wrapper.find('.confirm-dialog .secondary-button').trigger('click')
    await nextTick()

    expect(apiPost).not.toHaveBeenCalledWith('/api/v1/preferences', { body: { preferences: {} } })
    expect(wrapper.find<HTMLTextAreaElement>('#preference-preferred-groups').element.value).toBe('喵萌')
  })

  it('renders a safe Chinese error on API failure', async () => {
    apiGet.mockRejectedValue({
      type: 'request_error',
      message: '保存偏好默认值失败。请修正后重试。',
    })
    const { wrapper } = await mountSettings()
    await nextTick()
    await nextTick()

    expect(wrapper.find('#preference-settings-form .status-alert').text()).toContain('读取偏好默认值失败')
  })

  it('restores last-known-good values when a save is rejected', async () => {
    apiGet.mockResolvedValue(SAVED_PREFERENCES)
    apiPost.mockRejectedValue({
      type: 'validation_error',
      message: 'subtitle_groups.preferred 包含不允许的敏感内容',
    })
    const { wrapper } = await mountSettings()
    await nextTick()
    await nextTick()

    // Form was loaded with SAVED_PREFERENCES (喵萌 preferred).
    expect(wrapper.find<HTMLTextAreaElement>('#preference-preferred-groups').element.value).toBe('喵萌')

    // Enter a sensitive value and attempt to save; the server rejects it.
    await wrapper.find('#preference-preferred-groups').setValue('https://mikan.example/Home/Search')
    await wrapper.find('#preference-settings-save').trigger('submit')
    await nextTick()
    await nextTick()

    // The rejected sensitive input is cleared by restoring the last good set.
    expect(wrapper.find<HTMLTextAreaElement>('#preference-preferred-groups').element.value).toBe('喵萌')
    const alertText = wrapper.find('#preference-settings-form .status-alert').text()
    expect(alertText).toContain('保存偏好默认值失败')
    // The raw server error_message never appears in the DOM.
    expect(alertText).not.toContain('mikan.example')
    expect(alertText).not.toContain('敏感内容')
  })
})

describe('SettingsView qBittorrent panel (US-201)', () => {
  beforeEach(() => {
    localStorage.clear()
    sessionStorage.clear()
    apiGet.mockReset()
    apiPost.mockReset()
    apiGet.mockResolvedValue(DEFAULT_PREFERENCES)
  })

  it('validates required fields before calling the API', async () => {
    const { wrapper } = await mountSettings()
    await nextTick()

    await wrapper.find('#settings-qbittorrent-test-submit').trigger('submit')
    await nextTick()

    expect(apiPost).not.toHaveBeenCalledWith('/api/v1/qbittorrent/test-connection', expect.anything())
    expect(wrapper.find('#settings-qbittorrent-test-form .status-alert').text()).toContain('测试 qBittorrent 前必须填写')
  })

  it('requires confirmation, posts request-scoped config and clears fields on success', async () => {
    apiPost.mockResolvedValue({ status: 'ok', reachable: true, version: '4.6.5' })
    const { wrapper } = await mountSettings()
    await nextTick()

    await wrapper.find('#settings-qbittorrent-endpoint').setValue('http://private-qbt.local')
    await wrapper.find('#settings-qbittorrent-username').setValue('private-user')
    await wrapper.find('#settings-qbittorrent-password').setValue('private-password')
    await wrapper.find('#settings-qbittorrent-test-submit').trigger('submit')
    await nextTick()

    const dialog = wrapper.find('.confirm-dialog')
    expect(dialog.exists()).toBe(true)
    expect(dialog.text()).toContain('测试 qBittorrent 连接')
    await dialog.find('.primary-button').trigger('click')
    await nextTick()
    await nextTick()

    const call = apiPost.mock.calls.find(([path]) => path === '/api/v1/qbittorrent/test-connection')
    expect(call).toBeTruthy()
    expect(call?.[1]?.body).toEqual({
      qbittorrent_config: {
        endpoint: 'http://private-qbt.local',
        username: 'private-user',
        password: 'private-password',
        timeout_seconds: 10,
        verify_tls: true,
      },
    })
    const alertText = wrapper.find('#settings-qbittorrent-test-form .status-alert').text()
    expect(alertText).toContain('status: ok')
    expect(alertText).toContain('version: 4.6.5')
    // Credentials are cleared from component memory and never persist.
    expect(wrapper.find<HTMLInputElement>('#settings-qbittorrent-endpoint').element.value).toBe('')
    expect(wrapper.find<HTMLInputElement>('#settings-qbittorrent-password').element.value).toBe('')
    expect(localStorage.length).toBe(0)
    expect(sessionStorage.length).toBe(0)
  })

  it('cancelled confirmation blocks the API call and preserves fields', async () => {
    const { wrapper } = await mountSettings()
    await nextTick()

    await wrapper.find('#settings-qbittorrent-endpoint').setValue('http://private-qbt.local')
    await wrapper.find('#settings-qbittorrent-username').setValue('user')
    await wrapper.find('#settings-qbittorrent-password').setValue('pw')
    await wrapper.find('#settings-qbittorrent-test-submit').trigger('submit')
    await nextTick()

    await wrapper.find('.confirm-dialog .secondary-button').trigger('click')
    await nextTick()

    expect(apiPost).not.toHaveBeenCalledWith('/api/v1/qbittorrent/test-connection', expect.anything())
    expect(wrapper.find<HTMLInputElement>('#settings-qbittorrent-endpoint').element.value).toBe('http://private-qbt.local')
  })

  it('failure shows only a fixed Chinese message (never the raw server error)', async () => {
    apiPost.mockRejectedValue({
      type: 'qbittorrent_timeout',
      message: 'qBittorrent HTTP 请求超时 from http://private-qbt.local private-user private-password secret-session',
      status: 400,
    })
    const { wrapper } = await mountSettings()
    await nextTick()

    await wrapper.find('#settings-qbittorrent-endpoint').setValue('http://private-qbt.local')
    await wrapper.find('#settings-qbittorrent-username').setValue('private-user')
    await wrapper.find('#settings-qbittorrent-password').setValue('private-password')
    await wrapper.find('#settings-qbittorrent-test-submit').trigger('submit')
    await nextTick()

    await wrapper.find('.confirm-dialog .primary-button').trigger('click')
    await nextTick()
    await nextTick()

    const alertText = wrapper.find('#settings-qbittorrent-test-form .status-alert').text()
    expect(alertText).toContain('qBittorrent 连接测试失败')
    // Raw error message (may contain endpoint/credentials) never reaches the DOM.
    expect(alertText).not.toContain('private-qbt')
    expect(alertText).not.toContain('private-user')
    expect(alertText).not.toContain('private-password')
    expect(alertText).not.toContain('secret-session')
    expect(alertText).not.toContain('http://')
  })
})

describe('SettingsView Auto Bangumi panel (US-201)', () => {
  beforeEach(() => {
    localStorage.clear()
    sessionStorage.clear()
    apiGet.mockReset()
    apiPost.mockReset()
    apiGet.mockResolvedValue(DEFAULT_PREFERENCES)
  })

  it('test-connection sends password-mode config and clears credentials on success', async () => {
    apiPost.mockResolvedValue({
      reachable: true,
      authenticated: true,
      version: '3.1.18',
      auth_mode: '账号密码',
      adapter: 'legacy_3_1',
      submit_supported: true,
    })
    const { wrapper } = await mountSettings()
    await nextTick()

    await wrapper.find('#settings-ab-endpoint').setValue('http://ab.example.invalid')
    await wrapper.find('#settings-ab-username').setValue('browser-user')
    await wrapper.find('#settings-ab-password').setValue('browser-secret-password')
    await wrapper.find('#settings-ab-test-submit').trigger('click')
    await nextTick()
    await nextTick()

    const call = apiPost.mock.calls.find(([path]) => path === '/api/v1/autobangumi/test-connection')
    expect(call).toBeTruthy()
    expect(call?.[1]?.body).toEqual({
      ab_config: {
        auth_mode: 'password',
        base_url: 'http://ab.example.invalid',
        username: 'browser-user',
        password: 'browser-secret-password',
        fallback_enabled: false,
      },
    })
    expect(wrapper.find('#settings-ab-submit-form .status-alert').text()).toContain('连接成功')
    expect(wrapper.find<HTMLInputElement>('#settings-ab-endpoint').element.value).toBe('')
    expect(wrapper.find<HTMLInputElement>('#settings-ab-password').element.value).toBe('')
    expect(localStorage.length).toBe(0)
    expect(sessionStorage.length).toBe(0)
  })

  it('submit-ab uses request_id from the URL query and confirms first', async () => {
    apiPost.mockResolvedValue({
      request: { request_id: 'req-ab-1', status: 'ACCEPTED' },
      summary: {},
      ab_submit_result: {
        success: true,
        ab_subscription_id: 'sub-1',
        ab_response: { id: 'sub-1' },
        fallback_config: null,
        error: null,
      },
    })
    const { wrapper } = await mountSettings({ request_id: 'req-ab-1' })
    await nextTick()

    expect(wrapper.find('#settings-ab-request-id').text()).toBe('req-ab-1')
    await wrapper.find('#settings-ab-endpoint').setValue('http://ab.example.invalid')
    await wrapper.find('#settings-ab-username').setValue('browser-user')
    await wrapper.find('#settings-ab-password').setValue('browser-secret-password')
    await wrapper.find('#settings-ab-submit').trigger('submit')
    await nextTick()

    const dialog = wrapper.find('.confirm-dialog')
    expect(dialog.exists()).toBe(true)
    expect(dialog.text()).toContain('提交 Auto Bangumi')
    await dialog.find('.danger-button').trigger('click')
    await nextTick()
    await nextTick()

    const call = apiPost.mock.calls.find(([path]) => path === '/api/v1/requests/{request_id}/submit-ab')
    expect(call).toBeTruthy()
    expect(call?.[1]).toMatchObject({
      path: { request_id: 'req-ab-1' },
      query: {},
      body: {
        ab_config: {
          auth_mode: 'password',
          base_url: 'http://ab.example.invalid',
          username: 'browser-user',
          password: 'browser-secret-password',
          fallback_enabled: false,
        },
      },
    })
    expect(wrapper.find('#settings-ab-submit-form .status-alert').text()).toContain('Auto Bangumi 提交成功')
    expect(wrapper.find<HTMLInputElement>('#settings-ab-endpoint').element.value).toBe('')
    expect(wrapper.find<HTMLInputElement>('#settings-ab-password').element.value).toBe('')
    expect(localStorage.length).toBe(0)
  })

  it('submit-ab without request_id shows a Chinese error without calling the API', async () => {
    const { wrapper } = await mountSettings()
    await nextTick()

    await wrapper.find('#settings-ab-submit').trigger('submit')
    await nextTick()

    expect(wrapper.find('#settings-ab-submit-form .status-alert').text()).toContain('缺少 request_id')
    expect(apiPost).not.toHaveBeenCalledWith('/api/v1/requests/{request_id}/submit-ab', expect.anything())
  })

  it('switching auth mode clears the sensitive fields (API Token mode)', async () => {
    const { wrapper } = await mountSettings()
    await nextTick()

    await wrapper.find('#settings-ab-endpoint').setValue('http://ab.example.invalid')
    await wrapper.find('#settings-ab-username').setValue('user')
    await wrapper.find('#settings-ab-password').setValue('pw')
    // Switch to API Token mode.
    await wrapper.find('#settings-ab-auth-mode').setValue('api_token')
    await wrapper.find('#settings-ab-auth-mode').trigger('change')
    await nextTick()

    expect(wrapper.find<HTMLInputElement>('#settings-ab-username').exists()).toBe(false)
    expect(wrapper.find<HTMLInputElement>('#settings-ab-token').exists()).toBe(true)
    // Old password-mode credentials were cleared by the mode switch.
    expect(wrapper.find<HTMLInputElement>('#settings-ab-endpoint').element.value).toBe('')
  })
})
