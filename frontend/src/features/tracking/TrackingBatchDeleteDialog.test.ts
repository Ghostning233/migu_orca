import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'

import TrackingBatchDeleteDialog from './TrackingBatchDeleteDialog.vue'

/**
 * Issue #223: the batch delete confirmation is one explicit scope choice.
 *
 * These lock the safe defaults the page relies on: local-only unless the user
 * ticks the box, 取消 as the default focus (so Enter alone never deletes), the
 * affected count and the pre-check skips with their reasons, and a disabled
 * external scope when no saved connection exists.
 */
function mountDialog(props: Record<string, unknown> = {}) {
  return mount(TrackingBatchDeleteDialog, {
    props: { open: true, count: 2, externalAvailable: true, ...props },
    attachTo: document.body,
    // The dialog teleports to <body>; stub it so the wrapper still owns the DOM.
    global: { stubs: { teleport: true } },
  })
}

describe('TrackingBatchDeleteDialog (issue #223)', () => {
  it('defaults to the local-only scope and states what that means', () => {
    const wrapper = mountDialog()

    expect(wrapper.find('.confirm-dialog-title').text()).toBe('删除追番方案')
    expect(wrapper.find('.confirm-dialog-message').text()).toContain('2 条')
    expect(wrapper.find('#tracking-batch-delete-external').attributes('checked')).toBeUndefined()
    expect(wrapper.text()).toContain('Auto Bangumi 中的订阅会继续运行，MiGuOrca 不再管理它们')
    // No deletion has happened and nothing is sent by opening the dialog.
    expect(wrapper.emitted('confirm')).toBeUndefined()
    wrapper.unmount()
  })

  it('starts focus on 取消 so Enter can never delete', async () => {
    const wrapper = mountDialog()
    await wrapper.vm.$nextTick()

    expect(document.activeElement?.id).toBe('tracking-batch-delete-cancel')
    wrapper.unmount()
  })

  it('sends the chosen scope: local by default, external only when ticked', async () => {
    const local = mountDialog()
    await local.find('#tracking-batch-delete-confirm').trigger('click')
    expect(local.emitted('confirm')).toEqual([[false]])
    local.unmount()

    const external = mountDialog()
    await external.find('#tracking-batch-delete-external').setValue(true)
    expect(external.text()).toContain('先删除这 2 条在 Auto Bangumi 中的受控外部订阅')
    expect(external.text()).toContain('外部删除失败或结果未知的条目会完整保留')
    await external.find('#tracking-batch-delete-confirm').trigger('click')
    expect(external.emitted('confirm')).toEqual([[true]])
    external.unmount()
  })

  it('lists the pre-check skips with their reasons and never sends them', () => {
    const wrapper = mountDialog({
      count: 1,
      skipped: [
        { trackingId: 'trk_a', title: '番 A', reason: '结果待确认，需要逐条处理' },
        { trackingId: 'trk_b', title: '番 B', reason: '正在处理中，需等待当前操作完成' },
      ],
    })

    const skipped = wrapper.find('.tracking-batch-delete-skipped')
    expect(skipped.text()).toContain('另有 2 条将被跳过')
    expect(skipped.text()).toContain('番 A：结果待确认，需要逐条处理')
    expect(skipped.text()).toContain('番 B：正在处理中，需等待当前操作完成')
    // The count is only the entries that will actually be deleted.
    expect(wrapper.find('.confirm-dialog-message').text()).toContain('1 条')
    wrapper.unmount()
  })

  it('refuses the external scope without a saved connection', async () => {
    const wrapper = mountDialog({ externalAvailable: false })

    expect(wrapper.find('#tracking-batch-delete-external').attributes('disabled')).toBeDefined()
    expect(wrapper.text()).toContain('缺少已保存连接时只能删除本地记录')
    await wrapper.find('#tracking-batch-delete-confirm').trigger('click')
    expect(wrapper.emitted('confirm')).toEqual([[false]])
    wrapper.unmount()
  })

  it('ignores confirm and cancel while the batch is already in flight', async () => {
    const wrapper = mountDialog({ busy: true })

    expect(wrapper.find('#tracking-batch-delete-confirm').attributes('disabled')).toBeDefined()
    expect(wrapper.find('#tracking-batch-delete-confirm').text()).toBe('正在删除…')
    await wrapper.find('#tracking-batch-delete-confirm').trigger('click')
    await wrapper.find('#tracking-batch-delete-cancel').trigger('click')
    expect(wrapper.emitted('confirm')).toBeUndefined()
    expect(wrapper.emitted('cancel')).toBeUndefined()
    wrapper.unmount()
  })

  it('cancels with 取消 and Escape without deleting', async () => {
    const wrapper = mountDialog()
    await wrapper.find('#tracking-batch-delete-cancel').trigger('click')
    expect(wrapper.emitted('cancel')).toHaveLength(1)
    expect(wrapper.emitted('confirm')).toBeUndefined()

    document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }))
    expect(wrapper.emitted('cancel')).toHaveLength(2)
    expect(wrapper.emitted('confirm')).toBeUndefined()
    wrapper.unmount()
  })

  it('resets the scope to local-only on every opening', async () => {
    const wrapper = mountDialog()
    await wrapper.find('#tracking-batch-delete-external').setValue(true)
    await wrapper.setProps({ open: false })
    await wrapper.setProps({ open: true })
    await wrapper.vm.$nextTick()

    expect(wrapper.find('#tracking-batch-delete-external').attributes('checked')).toBeUndefined()
    wrapper.unmount()
  })
})
