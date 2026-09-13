import { mount } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import { nextTick } from 'vue'

import ConfirmDialog from '@/components/feedback/ConfirmDialog.vue'

function mountDialog() {
  return mount(ConfirmDialog, {
    attachTo: document.body,
    global: {
      stubs: { teleport: true },
    },
  })
}

describe('ConfirmDialog (US-200)', () => {
  let wrapper: ReturnType<typeof mountDialog>

  beforeEach(() => {
    document.body.innerHTML = ''
  })

  afterEach(() => {
    wrapper?.unmount()
  })

  it('is closed by default and resolves false when confirmed without state', async () => {
    wrapper = mountDialog()
    expect(wrapper.find('.confirm-dialog').exists()).toBe(false)

    // Calling confirm without options should still produce a boolean result.
    const promise = wrapper.vm.confirm({
      title: '确认操作',
      message: '此操作不可恢复。',
    })
    await new Promise((r) => requestAnimationFrame(r))
    expect(wrapper.find('.confirm-dialog').exists()).toBe(true)
    wrapper.find('.primary-button').trigger('click')
    await expect(promise).resolves.toBe(true)
  })

  it('opens with title/message and confirms via the primary action', async () => {
    wrapper = mountDialog()
    const promise = wrapper.vm.confirm({
      title: '确认删除',
      message: '此订阅方案删除后不可恢复。',
    })
    await new Promise((r) => requestAnimationFrame(r))

    expect(wrapper.find('.confirm-dialog').exists()).toBe(true)
    expect(wrapper.find('.confirm-dialog-title').text()).toBe('确认删除')
    expect(wrapper.find('.confirm-dialog-message').text()).toBe('此订阅方案删除后不可恢复。')
    expect(wrapper.find('.confirm-dialog').attributes('role')).toBe('alertdialog')
    expect(wrapper.find('.confirm-dialog').attributes('aria-modal')).toBe('true')
    expect(wrapper.find('.confirm-dialog').attributes('aria-describedby')).toBeTruthy()

    wrapper.find('.primary-button').trigger('click')
    await expect(promise).resolves.toBe(true)
    expect(wrapper.find('.confirm-dialog').exists()).toBe(false)
  })

  it('cancels via the secondary action', async () => {
    wrapper = mountDialog()
    const promise = wrapper.vm.confirm({
      title: '确认操作',
      message: '正文',
    })
    await new Promise((r) => requestAnimationFrame(r))

    wrapper.find('.secondary-button').trigger('click')
    await expect(promise).resolves.toBe(false)
    expect(wrapper.find('.confirm-dialog').exists()).toBe(false)
  })

  it('renders a danger variant with custom labels', async () => {
    wrapper = mountDialog()
    const promise = wrapper.vm.confirm({
      title: '确认取消',
      message: '取消后无法恢复。',
      confirmLabel: '仍然取消',
      cancelLabel: '返回',
      danger: true,
    })
    await new Promise((r) => requestAnimationFrame(r))

    expect(wrapper.find('.confirm-dialog').classes()).toContain('confirm-dialog-danger')
    expect(wrapper.find('.danger-button').text()).toBe('仍然取消')
    expect(wrapper.find('.secondary-button').text()).toBe('返回')

    wrapper.find('.danger-button').trigger('click')
    await expect(promise).resolves.toBe(true)
  })

  it('closes on Escape and resolves false', async () => {
    wrapper = mountDialog()
    const promise = wrapper.vm.confirm({
      title: '确认操作',
      message: '正文',
    })
    await new Promise((r) => requestAnimationFrame(r))

    document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }))
    await expect(promise).resolves.toBe(false)
    expect(wrapper.find('.confirm-dialog').exists()).toBe(false)
  })

  it('closes on backdrop click and resolves false', async () => {
    wrapper = mountDialog()
    const promise = wrapper.vm.confirm({
      title: '确认操作',
      message: '正文',
    })
    await new Promise((r) => requestAnimationFrame(r))

    wrapper.find('.confirm-dialog-backdrop').trigger('click')
    await expect(promise).resolves.toBe(false)
    expect(wrapper.find('.confirm-dialog').exists()).toBe(false)
  })

  it('restores focus to the previously focused element on close', async () => {
    wrapper = mountDialog()
    const trigger = document.createElement('button')
    trigger.id = 'trigger'
    document.body.appendChild(trigger)
    trigger.focus()

    const promise = wrapper.vm.confirm({
      title: '确认操作',
      message: '正文',
    })
    await new Promise((r) => requestAnimationFrame(r))

    // Focus moved inside the dialog.
    expect(document.activeElement?.closest('.confirm-dialog')).toBeTruthy()

    wrapper.find('.primary-button').trigger('click')
    await expect(promise).resolves.toBe(true)
    await new Promise((r) => requestAnimationFrame(r))
    expect(document.activeElement?.id).toBe('trigger')
  })

  it('traps Tab within the dialog', async () => {
    wrapper = mountDialog()
    const promise = wrapper.vm.confirm({
      title: '确认操作',
      message: '正文',
    })
    await new Promise((r) => requestAnimationFrame(r))

    // Simulate Tab on the last button: focus wraps to the first button.
    const buttons = wrapper.findAll('.confirm-dialog button')
    const first = buttons[0]?.element as HTMLButtonElement
    const last = buttons[buttons.length - 1]?.element as HTMLButtonElement
    last.focus()

    last.dispatchEvent(new KeyboardEvent('keydown', { key: 'Tab', bubbles: true }))
    await new Promise((r) => requestAnimationFrame(r))
    expect(document.activeElement).toBe(first)

    // Shift+Tab from the first button wraps to the last.
    first.dispatchEvent(
      new KeyboardEvent('keydown', { key: 'Tab', shiftKey: true, bubbles: true }),
    )
    await new Promise((r) => requestAnimationFrame(r))
    expect(document.activeElement).toBe(last)

    // Close and resolve the pending promise so the test ends cleanly.
    wrapper.find('.secondary-button').trigger('click')
    await expect(promise).resolves.toBe(false)
  })

  it('activates focus and inert siblings after Vue nextTick', async () => {
    // Keep Teleport real here so inert is observable on the page siblings.
    wrapper = mount(ConfirmDialog, { attachTo: document.body })
    const background = document.createElement('button')
    background.id = 'background'
    document.body.appendChild(background)
    background.focus()

    const pending = wrapper.vm.confirm({ title: '确认操作', message: '正文' })
    await nextTick()
    await nextTick()

    const cancel = document.querySelector<HTMLElement>('.confirm-dialog .secondary-button')
    expect(cancel).toBe(document.activeElement)
    expect(document.querySelector('[inert]')).toBeTruthy()
    cancel?.click()
    await expect(pending).resolves.toBe(false)
    expect(document.querySelector('[inert]')).toBeNull()
  })

  it('invalidates a replaced or unmounted dialog before its activation tick', async () => {
    wrapper = mountDialog()
    const first = wrapper.vm.confirm({ title: '第一步', message: '正文' })
    const second = wrapper.vm.confirm({ title: '第二步', message: '正文' })
    await expect(first).resolves.toBe(false)
    wrapper.unmount()
    await expect(second).resolves.toBe(false)
    await nextTick()

    expect(document.querySelector('.confirm-dialog')).toBeNull()
    expect(Array.from(document.body.children).some((node) => node.hasAttribute('inert'))).toBe(false)
  })
})
