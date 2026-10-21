import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'

import TrackingSubmissionModeDialog from './TrackingSubmissionModeDialog.vue'

/**
 * Issue #98: the submission-mode choice is one operation-level decision.
 *
 * These lock the dialog contract the Chromium journeys rely on: a stable title,
 * the fixed button order, focus starting on 取消, and every action disabled once
 * a mode has been chosen so no second submission can start.
 *
 * Issue #234 (D9): the dialog also has to carry the approved primary/secondary
 * hierarchy (持续追番 primary, 下载现有资源 outlined) and state *when* to pick
 * which mode. The primary colour is a hierarchy hint only: opening the dialog
 * preselects nothing and sends nothing.
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
    const body = wrapper.find('.tracking-mode-body').text()
    expect(body).toContain('不建立持续追番订阅')
    expect(body).toContain('建立受控外部订阅')
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

describe('TrackingSubmissionModeDialog (issue #234 D9)', () => {
  it('renders 持续追番 as the primary action and 下载现有资源 as the outlined one', () => {
    const wrapper = mountDialog()

    const cancel = wrapper.find('#tracking-mode-cancel')
    const download = wrapper.find('#tracking-mode-download')
    const continueTracking = wrapper.find('#tracking-mode-continue')

    // AC 1: the approved design has one dark primary action, not two.
    expect(continueTracking.classes()).toContain('primary-button')
    expect(continueTracking.classes()).not.toContain('secondary-button')
    expect(download.classes()).toContain('secondary-button')
    expect(download.classes()).not.toContain('primary-button')
    // 取消 keeps the secondary treatment it already had, and the fixed order.
    expect(cancel.classes()).toContain('secondary-button')
    expect(wrapper.findAll('.confirm-dialog-actions button').map((b) => b.text())).toEqual([
      '取消', '下载现有资源', '持续追番',
    ])
    wrapper.unmount()
  })

  it('writes when to pick which mode into the visible copy', () => {
    const wrapper = mountDialog()

    const body = wrapper.find('.tracking-mode-body')
    const options = body.findAll('.tracking-mode-option')
    expect(options).toHaveLength(2)

    const download = options[0]!
    const continueTracking = options[1]!
    expect(download.find('.tracking-mode-option-title').text()).toBe('下载现有资源')
    expect(download.text()).toContain('加入下载一次')
    expect(download.text()).toContain('不建立持续追番订阅')
    expect(download.text()).toContain('后续新资源不会自动下载')
    expect(continueTracking.find('.tracking-mode-option-title').text()).toBe('持续追番')
    expect(continueTracking.text()).toContain('建立受控外部订阅')
    expect(continueTracking.text()).toContain('后续新资源持续自动下载')

    // AC 2: the copy states the choice itself, not just the two effects.
    expect(body.text()).toContain('现在只想把已符合方案的资源加入下载')
    expect(body.text()).toContain('想让后续新资源持续自动下载')
    // The unchanged scope promise of #98 and the no-write-on-open promise.
    expect(body.text()).toContain('都只作用于本次提交，不会改变本地方案')
    expect(body.text()).toContain('打开这个弹窗不会提交任何内容')

    // The concise description stays the range sentence, not the whole option
    // list: the dialog must not read as a preselected form.
    const dialog = wrapper.find('[role="alertdialog"]')
    expect(dialog.attributes('aria-describedby')).toBe(
      wrapper.find('.confirm-dialog-message').attributes('id'),
    )
    wrapper.unmount()
  })

  it('does not preselect a mode, submit, or block a choice on open', () => {
    const wrapper = mountDialog()

    // The primary colour is hierarchy only: nothing is chosen, nothing is sent.
    expect(wrapper.emitted('choose')).toBeUndefined()
    expect(wrapper.emitted('cancel')).toBeUndefined()
    for (const id of ['#tracking-mode-download', '#tracking-mode-continue']) {
      expect(wrapper.find(id).attributes('disabled')).toBeUndefined()
      expect(wrapper.find(id).attributes('aria-pressed')).toBeUndefined()
      expect(wrapper.find(id).attributes('aria-checked')).toBeUndefined()
    }
    wrapper.unmount()
  })

  it('keeps the in-progress labels and the existing disable semantics', () => {
    const continuing = mountDialog({ pendingMode: 'CONTINUE_TRACKING' })
    expect(continuing.find('#tracking-mode-continue').text()).toBe('持续追番…')
    expect(continuing.find('#tracking-mode-download').text()).toBe('下载现有资源')
    expect(continuing.find('#tracking-mode-continue').attributes('aria-busy')).toBe('true')
    // `aria-busy` stays rendered as an explicit false on the idle action.
    expect(continuing.find('#tracking-mode-download').attributes('aria-busy')).toBe('false')
    continuing.unmount()

    const downloading = mountDialog({ pendingMode: 'DOWNLOAD_EXISTING' })
    expect(downloading.find('#tracking-mode-download').text()).toBe('下载现有资源…')
    expect(downloading.find('#tracking-mode-continue').text()).toBe('持续追番')
    expect(downloading.find('#tracking-mode-download').attributes('aria-busy')).toBe('true')
    downloading.unmount()

    const busy = mountDialog({ busy: true })
    for (const id of ['#tracking-mode-download', '#tracking-mode-continue']) {
      expect(busy.find(id).attributes('disabled')).toBeDefined()
      expect(busy.find(id).attributes('aria-busy')).toBe('false')
    }
    expect(busy.find('#tracking-mode-cancel').attributes('disabled')).toBeUndefined()
    busy.unmount()
  })

  it('refuses both mode choices while the page is busy', async () => {
    const wrapper = mountDialog({ busy: true })

    await wrapper.find('#tracking-mode-download').trigger('click')
    await wrapper.find('#tracking-mode-continue').trigger('click')
    expect(wrapper.emitted('choose')).toBeUndefined()
    wrapper.unmount()
  })

  it('cancels on Escape and keeps the write out of Escape while it is in flight', async () => {
    const wrapper = mountDialog()
    await wrapper.vm.$nextTick()

    // AC 3: Escape before the choice sends nothing at all.
    document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }))
    expect(wrapper.emitted('cancel')).toHaveLength(1)
    expect(wrapper.emitted('choose')).toBeUndefined()

    // AC 4 of #98: once the external write has started, Escape cannot undo it.
    await wrapper.setProps({ pendingMode: 'CONTINUE_TRACKING' })
    document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }))
    expect(wrapper.emitted('cancel')).toHaveLength(1)
    wrapper.unmount()
  })

  it('cancels on a backdrop click and keeps the actions trapped', async () => {
    const wrapper = mountDialog()
    await wrapper.vm.$nextTick()

    // The scrim behaves like the shared ConfirmDialog scrim.
    await wrapper.find('.confirm-dialog-backdrop').trigger('click')
    expect(wrapper.emitted('cancel')).toHaveLength(1)
    expect(wrapper.emitted('choose')).toBeUndefined()

    // AC 3: Tab wraps from the last action to 取消 and Shift+Tab back again.
    ;(document.getElementById('tracking-mode-continue') as HTMLButtonElement).focus()
    document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Tab' }))
    expect(document.activeElement?.id).toBe('tracking-mode-cancel')
    document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Tab', shiftKey: true }))
    expect(document.activeElement?.id).toBe('tracking-mode-continue')

    wrapper.unmount()
  })

  it('reuses the same title, action order and copy for the batch entry', () => {
    const batch = mountDialog({ batchCount: 2 })

    expect(batch.find('.confirm-dialog-title').text()).toBe('选择提交方式')
    // The batch path adds only the count line on top of the shared copy.
    expect(batch.find('.tracking-mode-dialog').text()).toContain('所选 2 条追番方案')
    expect(
      batch.findAll('.tracking-mode-option .tracking-mode-option-title').map((entry) => entry.text()),
    ).toEqual(['下载现有资源', '持续追番'])
    expect(batch.findAll('.tracking-mode-option')[1]!.text()).toContain('后续新资源持续自动下载')
    expect(batch.findAll('.confirm-dialog-actions button').map((b) => b.text())).toEqual([
      '取消', '下载现有资源', '持续追番',
    ])
    batch.unmount()
  })
})
