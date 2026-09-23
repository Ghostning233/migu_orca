import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'

import TrackingSubmissionModeDialog from './TrackingSubmissionModeDialog.vue'

/**
 * Issue #98: the submission-mode choice is one operation-level decision.
 *
 * These lock the dialog contract the Chromium journeys rely on: a stable title,
 * the fixed button order, focus starting on 取消, and every action disabled once
 * a mode has been chosen so no second submission can start.
 */
function mountDialog(props: Record<string, unknown> = {}) {
  return mount(TrackingSubmissionModeDialog, {
    props: { open: true, ...props },
    attachTo: document.body,
    // The dialog teleports to <body>; stub it so the wrapper still owns the DOM.
    global: { stubs: { teleport: true } },
  })
}

describe('TrackingSubmissionModeDialog (issue #98)', () => {
  it('explains both external effects with the fixed button order', () => {
    const wrapper = mountDialog()

    expect(wrapper.find('.confirm-dialog-title').text()).toBe('选择提交方式')
    const body = wrapper.find('.confirm-dialog-message').text()
    expect(body).toContain('不建立持续检查的 RSS 订阅')
    expect(body).toContain('持续检查并下载后续资源')
    expect(body).toContain('不会改变本地方案')
    expect(wrapper.findAll('.confirm-dialog-actions button').map((b) => b.text())).toEqual([
      '取消', '下载现有资源', '持续追番',
    ])
    wrapper.unmount()
  })

  it('starts focus on 取消 so Enter can never submit', async () => {
    const wrapper = mountDialog()
    await wrapper.vm.$nextTick()

    expect(document.activeElement?.id).toBe('tracking-mode-cancel')
    wrapper.unmount()
  })

  it('emits the chosen mode once and locks every action afterwards', async () => {
    const wrapper = mountDialog()

    await wrapper.find('#tracking-mode-download').trigger('click')
    expect(wrapper.emitted('choose')).toEqual([['DOWNLOAD_EXISTING']])

    await wrapper.setProps({ pendingMode: 'DOWNLOAD_EXISTING' })
    await wrapper.find('#tracking-mode-continue').trigger('click')
    expect(wrapper.emitted('choose')).toEqual([['DOWNLOAD_EXISTING']])
    for (const id of ['#tracking-mode-cancel', '#tracking-mode-download', '#tracking-mode-continue']) {
      expect(wrapper.find(id).attributes('disabled')).toBeDefined()
    }
    await wrapper.find('#tracking-mode-cancel').trigger('click')
    expect(wrapper.emitted('cancel')).toBeUndefined()
    wrapper.unmount()
  })

  it('cancels only before a mode has been chosen', async () => {
    const wrapper = mountDialog()

    await wrapper.find('#tracking-mode-cancel').trigger('click')
    expect(wrapper.emitted('cancel')).toHaveLength(1)
    expect(wrapper.emitted('choose')).toBeUndefined()
    wrapper.unmount()
  })
})
