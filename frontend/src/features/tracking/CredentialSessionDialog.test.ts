import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { api } from '@/api/client'
import CredentialSessionDialog from './CredentialSessionDialog.vue'

vi.mock('@/api/client', () => ({ api: { post: vi.fn() } }))
const apiPost = vi.mocked(api.post)

function capabilities(overrides: Record<string, unknown> = {}) {
  return {
    probe_status: 'VERIFIED', version: '3.1.18', adapter: 'legacy_3_1',
    subscription_list: 'SUPPORTED', subscription_detail: 'SUPPORTED', subscription_submit: 'SUPPORTED',
    subscription_modify: 'SUPPORTED', subscription_enable: 'SUPPORTED', subscription_disable: 'SUPPORTED',
    subscription_delete: 'SUPPORTED', rss_list: 'SUPPORTED', rss_modify: 'SUPPORTED',
    rss_enable: 'SUPPORTED', rss_disable: 'SUPPORTED', rss_delete: 'SUPPORTED', rss_refresh: 'SUPPORTED',
    external_verify: 'SUPPORTED', checked_at: null, safe_message: null, ...overrides,
  }
}

describe('CredentialSessionDialog (US-307)', () => {
  beforeEach(() => apiPost.mockReset())

  it('defaults to password and probes only the generated capability endpoint', async () => {
    apiPost.mockResolvedValue(capabilities() as never)
    const wrapper = mount(CredentialSessionDialog, { props: { open: true }, global: { stubs: { Teleport: true } } })
    await wrapper.find('#tracking-ab-base-url').setValue('https://ab.invalid')
    await wrapper.find('#tracking-ab-username').setValue('user')
    await wrapper.find('#tracking-ab-password').setValue('secret')
    await wrapper.find('#tracking-ab-probe').trigger('click')
    await flushPromises()
    expect(apiPost).toHaveBeenCalledTimes(1)
    expect(apiPost).toHaveBeenCalledWith('/api/v1/autobangumi/capabilities', {
      body: { ab_config: {
        auth_mode: 'password', base_url: 'https://ab.invalid', username: 'user', password: 'secret', fallback_enabled: false,
      } },
    })
    expect(wrapper.text()).toContain('3.1.18')
    expect(wrapper.text()).not.toContain('https://ab.invalid')
  })

  it('validates missing credentials without issuing a request and clears on cancel', async () => {
    const wrapper = mount(CredentialSessionDialog, { props: { open: true }, global: { stubs: { Teleport: true } } })
    await wrapper.find('#tracking-ab-base-url').setValue('https://ab.invalid')
    await wrapper.find('#tracking-ab-username').setValue('user')
    await wrapper.find('#tracking-ab-probe').trigger('click')
    await flushPromises()
    expect(apiPost).not.toHaveBeenCalled()
    expect(wrapper.text()).toContain('请填写用户名和密码')
    expect((wrapper.find('#tracking-ab-password').element as HTMLInputElement).value).toBe('')
    await wrapper.findAll('.credential-dialog-actions button')[0]!.trigger('click')
    expect((wrapper.find('#tracking-ab-password').element as HTMLInputElement).value).toBe('')
    expect(wrapper.emitted('update:open')?.at(-1)).toEqual([false])
    expect(wrapper.text()).not.toContain('private endpoint')
  })

  it('switching to API token resets password fields and reports capability downgrade', async () => {
    const wrapper = mount(CredentialSessionDialog, { props: { open: true }, global: { stubs: { Teleport: true } } })
    await wrapper.find('#tracking-ab-password').setValue('secret')
    await wrapper.find('#tracking-ab-auth-mode').setValue('api_token')
    expect(wrapper.find('#tracking-ab-password').exists()).toBe(false)
    await wrapper.find('#tracking-ab-base-url').setValue('https://ab.invalid')
    await wrapper.find('#tracking-ab-token').setValue('token')
    apiPost.mockResolvedValue(capabilities({ subscription_submit: 'UNSUPPORTED', subscription_modify: 'UNKNOWN' }) as never)
    await wrapper.find('#tracking-ab-probe').trigger('click')
    await flushPromises()
    expect(wrapper.text()).toContain('提交能力：UNSUPPORTED')
    expect(wrapper.text()).not.toContain('secret')
  })
})
