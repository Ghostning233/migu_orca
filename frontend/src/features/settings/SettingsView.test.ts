import { flushPromises, mount } from '@vue/test-utils'
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

const { refreshGlobalStatus } = vi.hoisted(() => ({ refreshGlobalStatus: vi.fn() }))
vi.mock('@/app/stores/connectionStatus', () => ({
  useConnectionStatus: () => ({ invalidate: refreshGlobalStatus }),
  refreshConnectionStatus: refreshGlobalStatus,
}))

const apiGet = vi.mocked(api.get)
const apiPost = vi.mocked(api.post)
const apiPut = vi.mocked(api.put)
const apiDelete = vi.mocked(api.delete)

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
    apiPut.mockReset()
    apiDelete.mockReset()
    apiPut.mockReset()
    apiDelete.mockReset()
    apiGet.mockResolvedValue(DEFAULT_PREFERENCES)
  })

  it('loads storage preferences from localStorage on mount', async () => {
    localStorage.setItem('miguOrca.web.storageDir', 'backups')
    localStorage.setItem('miguOrca.web.saveRequest', 'false')
    const { wrapper } = await mountSettings()
    await nextTick()

    const dir = wrapper.find<HTMLInputElement>('#settings-storage-dir')
    expect(dir.element.value).toBe('backups')
    expect(localStorage.getItem('miguOrca.web.saveRequest')).toBeNull()
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

describe('Stage 39 saved connection conflict flow', () => {
  it('rereads the safe summary after 409 and does not auto-resubmit secrets', async () => {
    apiGet.mockImplementation(async (path) => {
      if (path === '/api/v1/settings/autobangumi') return {
        configured: true, credential_present: true, connection_ref: 'ref-1',
        configuration_revision: 2, connection_status: 'CONFIGURED',
      } as never
      return DEFAULT_PREFERENCES as never
    })
    apiPut.mockRejectedValue({ status: 409, type: 'configuration_conflict', message: '冲突' })
    const { wrapper } = await mountSettings()
    await nextTick()
    await wrapper.find('#settings-ab-endpoint').setValue('https://ab.invalid')
    await wrapper.find('#settings-ab-username').setValue('user')
    await wrapper.find('#settings-ab-password').setValue('secret')
    await wrapper.find('#settings-ab-save-form').trigger('submit')
    await flushPromises()
    expect(apiGet.mock.calls.filter(([path]) => path === '/api/v1/settings/autobangumi')).toHaveLength(3)
    expect(apiPut).toHaveBeenCalledTimes(1)
    expect(wrapper.find<HTMLInputElement>('#settings-ab-password').element.value).toBe('secret')
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

describe('Stage 39 global status refresh events', () => {
  beforeEach(() => {
    apiGet.mockReset()
    apiPost.mockReset()
    apiPut.mockReset()
    apiDelete.mockReset()
  })

  it('refreshes global status after saved connection probe', async () => {
    refreshGlobalStatus.mockReset()
    apiGet.mockImplementation(async (path) => path === '/api/v1/settings/autobangumi'
      ? { configured: true, credential_present: true, connection_ref: 'ref-1', configuration_revision: 2, connection_status: 'CONFIGURED' } as never
      : DEFAULT_PREFERENCES as never)
    apiPost.mockResolvedValue({ probe_status: 'VERIFIED' } as never)
    const { wrapper } = await mountSettings()
    await wrapper.find('#settings-ab-probe').trigger('click')
    await flushPromises()
    expect(refreshGlobalStatus).toHaveBeenCalled()
  })

  it.each(['#settings-ab-save', '#settings-ab-delete'])('refreshes global status after %s', async (button) => {
    refreshGlobalStatus.mockReset()
    apiGet.mockImplementation(async (path) => path === '/api/v1/settings/autobangumi'
      ? { configured: true, credential_present: true, connection_ref: 'ref-1', configuration_revision: 2, connection_status: 'CONFIGURED' } as never
      : DEFAULT_PREFERENCES as never)
    const { wrapper } = await mountSettings()
    if (button.endsWith('save')) {
      await wrapper.find('#settings-ab-endpoint').setValue('https://ab.invalid')
      await wrapper.find('#settings-ab-username').setValue('u')
      await wrapper.find('#settings-ab-password').setValue('p')
    }
    await wrapper.find(button).trigger('click')
    if (button.endsWith('delete')) await wrapper.find('.confirm-dialog .danger-button').trigger('click')
    expect(refreshGlobalStatus).toHaveBeenCalled()
  })
})

describe('SettingsView saved Auto Bangumi connection flow', () => {
  beforeEach(() => {
    localStorage.clear()
    sessionStorage.clear()
    apiGet.mockReset()
    apiPost.mockReset()
    apiPut.mockReset()
    apiDelete.mockReset()
    apiGet.mockResolvedValue(DEFAULT_PREFERENCES)
  })

  it('saves a connection through the generated saved operation and clears inputs', async () => {
    apiPut.mockResolvedValue({ configured: true, credential_present: true, connection_ref: 'ref-1', configuration_revision: 2, connection_status: 'CONFIGURED' } as never)
    const { wrapper } = await mountSettings()
    await nextTick()

    await wrapper.find('#settings-ab-endpoint').setValue('192.168.1.20:7890')
    await wrapper.find('#settings-ab-username').setValue('browser-user')
    await wrapper.find('#settings-ab-password').setValue('browser-secret-password')
    await wrapper.find('#settings-ab-save-form').trigger('submit')
    await nextTick()
    await nextTick()

    expect(apiPut).toHaveBeenCalledWith('/api/v1/settings/autobangumi', expect.objectContaining({ body: expect.objectContaining({ confirm: true, config: expect.objectContaining({ base_url: 'http://192.168.1.20:7890' }) }) }))
    expect(wrapper.text()).not.toContain('browser-secret-password')
    expect(wrapper.find('#settings-ab-save-form .status-alert').text()).toContain('已保存')
    expect(wrapper.find<HTMLInputElement>('#settings-ab-endpoint').element.value).toBe('')
    expect(wrapper.find<HTMLInputElement>('#settings-ab-password').element.value).toBe('')
    expect(localStorage.length).toBe(0)
    expect(sessionStorage.length).toBe(0)
  })

  it('probes only an already saved ref and revision', async () => {
    apiPost.mockResolvedValue({ ...SAVED_PREFERENCES, probe_status: 'VERIFIED', version: '3.1.18' } as never)
    apiGet.mockImplementation(async (path) => path === '/api/v1/settings/autobangumi'
      ? { configured: true, credential_present: true, connection_ref: 'ref-1', configuration_revision: 2, connection_status: 'CONFIGURED' } as never
      : DEFAULT_PREFERENCES as never)
    const { wrapper } = await mountSettings()
    await nextTick()

    await wrapper.find('#settings-ab-probe').trigger('click')
    await flushPromises()
    expect(apiPost).toHaveBeenCalledWith('/api/v1/settings/autobangumi/probe', { body: { connection_ref: 'ref-1', configuration_revision: 2 } })
  })

  it('canceling clear leaves the saved connection untouched and performs no delete', async () => {
    apiGet.mockImplementation(async (path) => path === '/api/v1/settings/autobangumi'
      ? { configured: true, credential_present: true, connection_ref: 'ref-1', configuration_revision: 2, connection_status: 'CONFIGURED' } as never
      : DEFAULT_PREFERENCES as never)
    const { wrapper } = await mountSettings()
    await nextTick()
    await wrapper.find('#settings-ab-delete').trigger('click')
    expect(wrapper.find('.confirm-dialog').exists()).toBe(true)
    await wrapper.find('.confirm-dialog .secondary-button').trigger('click')
    expect(apiDelete).not.toHaveBeenCalled()
  })
})
