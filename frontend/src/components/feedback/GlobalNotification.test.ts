import { mount } from '@vue/test-utils'
import { createPinia, type Pinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { useNotificationStore, type NotificationKind } from '@/app/stores/notification'
import GlobalNotification from '@/components/feedback/GlobalNotification.vue'

// A kind outside the typed union can still arrive from untyped callers.
const UNKNOWN_KIND = 'warning' as unknown as NotificationKind

function mountToast() {
  const pinia: Pinia = createPinia()
  const wrapper = mount(GlobalNotification, {
    attachTo: document.body,
    global: { plugins: [pinia] },
  })
  return { wrapper, store: useNotificationStore(pinia) }
}

describe('GlobalNotification toast (US-199 / US-346)', () => {
  beforeEach(() => {
    vi.useFakeTimers()
  })

  afterEach(() => {
    vi.clearAllTimers()
    vi.useRealTimers()
    document.body.innerHTML = ''
  })

  it('renders nothing while no message is current', () => {
    const { wrapper } = mountToast()
    expect(wrapper.find('.global-notification').exists()).toBe(false)
  })

  it('announces success and info politely as an atomic status', async () => {
    const { wrapper, store } = mountToast()

    store.success('保存成功', '订阅方案已保存。')
    await wrapper.vm.$nextTick()

    const region = wrapper.find('.global-notification')
    expect(region.attributes('role')).toBe('status')
    expect(region.attributes('aria-live')).toBe('polite')
    expect(region.attributes('aria-atomic')).toBe('true')
    expect(region.classes()).toContain('global-notification-success')
    expect(region.text()).toContain('保存成功')
    expect(region.text()).toContain('订阅方案已保存。')

    store.info('未找到候选合集')
    await wrapper.vm.$nextTick()
    expect(wrapper.find('.global-notification').attributes('aria-live')).toBe('polite')
  })

  it('announces errors assertively as an atomic alert', async () => {
    const { wrapper, store } = mountToast()

    store.error('请求失败', '网络请求失败，请检查网络后重试。')
    await wrapper.vm.$nextTick()

    const region = wrapper.find('.global-notification')
    expect(region.attributes('role')).toBe('alert')
    expect(region.attributes('aria-live')).toBe('assertive')
    expect(region.attributes('aria-atomic')).toBe('true')
    expect(region.classes()).toContain('global-notification-error')
  })

  it('fails closed to an assertive alert for an unrecognised kind', async () => {
    const { wrapper, store } = mountToast()

    store.show(UNKNOWN_KIND, '未定义类型')
    await wrapper.vm.$nextTick()

    const region = wrapper.find('.global-notification')
    expect(region.attributes('role')).toBe('alert')
    expect(region.attributes('aria-live')).toBe('assertive')
  })

  it('exposes a Chinese, keyboard reachable close control', async () => {
    const { wrapper, store } = mountToast()
    store.error('请求失败')
    await wrapper.vm.$nextTick()

    const close = wrapper.find('.global-notification-close')
    expect(close.element.tagName).toBe('BUTTON')
    expect(close.attributes('type')).toBe('button')
    expect(close.attributes('tabindex')).toBeUndefined()
    expect(close.text()).toBe('关闭')

    await close.trigger('click')
    expect(store.current).toBeNull()
    expect(wrapper.find('.global-notification').exists()).toBe(false)
  })

  it('never enters the tab order or moves focus when it appears or expires', async () => {
    const { wrapper, store } = mountToast()

    const field = document.createElement('input')
    document.body.append(field)
    field.focus()
    expect(document.activeElement).toBe(field)

    store.success('保存成功')
    await wrapper.vm.$nextTick()
    expect(document.activeElement).toBe(field)
    // The live region itself is not focusable — only its close button is.
    expect(wrapper.find('.global-notification').attributes('tabindex')).toBeUndefined()

    vi.advanceTimersByTime(10_000)
    await wrapper.vm.$nextTick()
    expect(wrapper.find('.global-notification').exists()).toBe(false)
    expect(document.activeElement).toBe(field)
  })

  it('takes the pending auto-close timer down with it on unmount', async () => {
    const { wrapper, store } = mountToast()
    store.error('请求失败')
    await wrapper.vm.$nextTick()
    expect(vi.getTimerCount()).toBe(1)

    wrapper.unmount()
    expect(store.current).toBeNull()
    expect(vi.getTimerCount()).toBe(0)
  })
})
