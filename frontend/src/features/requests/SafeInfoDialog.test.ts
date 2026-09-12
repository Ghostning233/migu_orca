import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { api } from '@/api/client'
import SafeInfoDialog from '@/features/requests/SafeInfoDialog.vue'

vi.mock('@/api/client', () => ({ api: { get: vi.fn() } }))

const apiGet = vi.mocked(api.get)

function safeInfo(title = '葬送的芙莉莲') {
  return {
    request_id: 'request-safe-1',
    status: 'ACCEPTED',
    raw_title: title,
    title,
    aliases: ['别名'],
    season: 1,
    season_raw: 'S1',
    season_evidence: '用户确认',
    mikan_collection: { title: '真实合集', bangumi_id: '123' },
    subtitle_groups: [{ subtitle_group: '字幕组', total_resource_count: 2, valid_resource_count: 1, invalid_resource_count: 1, warnings: ['缺少季度信息'] }],
    selected_subtitle_group: '字幕组',
    filter_rule: { must_contain: '1080p', must_not_contain: 'SP', use_regex: false, case_sensitive: false },
    resources: {
      selected_subtitle_group: '字幕组', valid_resource_count: 1, invalid_resource_count: 1, complete_resource_count: 2,
      valid_file_names: ['episode-01.mkv'], excluded_file_names: [{ name: 'episode-SP.mkv', reason: '排除' }],
    },
    folder_name: '葬送的芙莉莲',
    storage_profile: 'storage',
    total_episodes: null,
    updated_episode: null,
    updated_episode_status: 'NOT_IMPLEMENTED',
    history_summary: [{ action: 'ACCEPT', previous_status: 'PENDING_CONFIRM', next_status: 'ACCEPTED', timestamp: '2026-09-01' }],
    ab_status: { submitted: false, success: null, ab_subscription_id: null, error_type: null },
  }
}

describe('SafeInfoDialog (US-297)', () => {
  beforeEach(() => apiGet.mockReset())

  it('loads only generated safe-info and renders the complete safe whitelist', async () => {
    apiGet.mockResolvedValue({ safe_info: safeInfo() } as never)
    const trigger = document.createElement('button')
    document.body.append(trigger)
    trigger.focus()
    const wrapper = mount(SafeInfoDialog, {
      attachTo: document.body,
      props: { open: true, requestId: 'request-safe-1' },
    })
    await flushPromises()
    expect(apiGet).toHaveBeenCalledWith('/api/v1/requests/{request_id}/safe-info', {
      path: { request_id: 'request-safe-1' },
      query: {},
    })
    expect(document.body.textContent).toContain('真实合集')
    expect(document.body.textContent).toContain('episode-01.mkv')
    expect(document.body.textContent).toContain('季度原文')
    expect(document.body.textContent).toContain('S1')
    expect(document.body.textContent).toContain('缺少季度信息')
    expect(document.body.textContent).toContain('资源字幕组')
    expect(document.body.textContent).toContain('已更新集数')
    expect(document.body.textContent).toContain('待开发')
    expect(document.body.textContent).not.toContain('https://')
    ;(document.querySelector('.safe-info-close') as HTMLButtonElement).click()
    await flushPromises()
    expect(wrapper.emitted('close')).toBeTruthy()
  })

  it('renders submitted AB success, failure, and unknown as separate safe states', async () => {
    apiGet.mockResolvedValue({ safe_info: {
      ...safeInfo(),
      ab_status: { submitted: true, success: null, ab_subscription_id: null, error_type: null },
    } } as never)
    const wrapper = mount(SafeInfoDialog, { attachTo: document.body, props: { open: true, requestId: 'request-safe-1' } })
    await flushPromises()
    expect(document.body.textContent).toContain('已提交，结果未知')
    expect(document.body.textContent).not.toContain('未成功')

    await wrapper.setProps({ open: false })
    apiGet.mockResolvedValue({ safe_info: {
      ...safeInfo(),
      ab_status: { submitted: true, success: false, ab_subscription_id: 'public-sub-1', error_type: 'upstream_error' },
    } } as never)
    await wrapper.setProps({ open: true })
    await flushPromises()
    expect(document.body.textContent).toContain('已提交但未成功')
    expect(document.body.textContent).toContain('提交失败（详细原因已隐藏）')
    expect(document.body.textContent).not.toContain('upstream_error')
  })

  it('deactivates the focus trap on unmount', async () => {
    apiGet.mockResolvedValue({ safe_info: safeInfo() } as never)
    const wrapper = mount(SafeInfoDialog, { attachTo: document.body, props: { open: true, requestId: 'request-safe-1' } })
    await flushPromises()
    const removeSpy = vi.spyOn(document, 'removeEventListener')
    wrapper.unmount()
    expect(removeSpy).toHaveBeenCalledWith('keydown', expect.any(Function))
    removeSpy.mockRestore()
  })

  it('shows a fixed error with retry and discards stale responses after close', async () => {
    let resolveRequest!: (value: unknown) => void
    apiGet.mockReturnValue(new Promise((resolve) => { resolveRequest = resolve }) as never)
    const wrapper = mount(SafeInfoDialog, { attachTo: document.body, props: { open: true, requestId: 'request-safe-1' } })
    await wrapper.setProps({ open: false })
    resolveRequest({ safe_info: safeInfo('旧响应') })
    await flushPromises()
    expect(document.body.textContent).not.toContain('旧响应')

    apiGet.mockRejectedValueOnce(new Error('sensitive raw response'))
    await wrapper.setProps({ open: true })
    await flushPromises()
    expect(document.body.textContent).toContain('全部信息加载失败')
    expect(document.body.textContent).not.toContain('sensitive raw response')
  })
})
