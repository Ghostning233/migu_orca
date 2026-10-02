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

/**
 * 组件把「提示条环境」（documentElement/body 的内联样式与 scrollRestoration）保存在
 * 模块级变量里，文件内各用例因此共享同一份状态。挂载再卸载一次会走完整的
 * `restoreToastEnvironment()`，把上一用例遗留的环境真正复位，避免用例互相污染。
 */
function resetSharedToastEnvironment(): void {
  mount(GlobalNotification, { attachTo: document.body, global: { plugins: [createPinia()] } }).unmount()
  vi.clearAllTimers()
  document.documentElement.style.scrollBehavior = ''
  document.documentElement.style.overflowAnchor = ''
  document.body.style.overflowAnchor = ''
  history.scrollRestoration = 'auto'
}

describe('GlobalNotification toast (US-199 / US-346)', () => {
  beforeEach(() => {
    vi.useFakeTimers()
    resetSharedToastEnvironment()
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

  /** 推进一帧，让排队的退场恢复回调执行。 */
  async function flushRestoreFrame(): Promise<void> {
    vi.advanceTimersByTime(50)
    await Promise.resolve()
  }

  it('keeps the new toast protected when it replaces one whose restore frame is still queued', async () => {
    // 已确认竞态：旧提示清除后排队的 rAF 在新提示出现后才执行，旧回调会恢复样式并
    // 清空共享的 toast 环境，让新提示失去滚动保护。
    const { wrapper, store } = mountToast()
    store.success('第一条', '正在处理。')
    await wrapper.vm.$nextTick()
    expect(document.documentElement.style.scrollBehavior).toBe('auto')
    expect(history.scrollRestoration).toBe('manual')

    // 退场排队一帧；同一帧内立刻出现新通知。
    store.clear()
    store.info('第二条', '新的提示。')
    await wrapper.vm.$nextTick()
    await flushRestoreFrame()

    // 旧恢复回调必须失效：新提示的滚动保护仍在。
    expect(document.documentElement.style.scrollBehavior).toBe('auto')
    expect(history.scrollRestoration).toBe('manual')
    expect(wrapper.find('.global-notification').text()).toContain('第二条')

    // 新提示正常关闭后才恢复原样式与滚动环境。
    store.clear()
    await wrapper.vm.$nextTick()
    await flushRestoreFrame()
    expect(document.documentElement.style.scrollBehavior).toBe('')
    expect(history.scrollRestoration).toBe('auto')
  })

  it('restores the environment once when several toasts are replaced in the same frame', async () => {
    const { wrapper, store } = mountToast()
    store.success('第一条')
    await wrapper.vm.$nextTick()
    store.clear()
    store.info('第二条')
    await wrapper.vm.$nextTick()
    store.clear()
    store.error('第三条')
    await wrapper.vm.$nextTick()
    await flushRestoreFrame()

    // 前两次退场的回调都已过期，第三条仍在保护中。
    expect(document.documentElement.style.scrollBehavior).toBe('auto')

    store.clear()
    await wrapper.vm.$nextTick()
    await flushRestoreFrame()
    expect(document.documentElement.style.scrollBehavior).toBe('')
    expect(history.scrollRestoration).toBe('auto')
  })
})
