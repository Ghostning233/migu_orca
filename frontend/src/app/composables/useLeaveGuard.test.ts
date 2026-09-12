import { mount } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'
import { createMemoryHistory, createRouter } from 'vue-router'

import { useLeaveGuard } from '@/app/composables/useLeaveGuard'

describe('useLeaveGuard', () => {
  it('blocks beforeunload only while the feature reports unsafe work', async () => {
    let guarded = true
    const router = createRouter({
      history: createMemoryHistory(),
      routes: [{ path: '/add', component: { template: '<p>add</p>' } }],
    })
    await router.push('/add')
    await router.isReady()
    const wrapper = mount({
      setup() {
        useLeaveGuard({ shouldGuard: () => guarded, confirm: vi.fn(), cleanup: vi.fn() })
        return () => null
      },
    }, { global: { plugins: [router] } })

    const event = new Event('beforeunload', { cancelable: true }) as BeforeUnloadEvent
    Object.defineProperty(event, 'returnValue', { writable: true, value: undefined })
    window.dispatchEvent(event)
    expect(event.defaultPrevented).toBe(true)

    guarded = false
    const safeEvent = new Event('beforeunload', { cancelable: true }) as BeforeUnloadEvent
    Object.defineProperty(safeEvent, 'returnValue', { writable: true, value: undefined })
    window.dispatchEvent(safeEvent)
    expect(safeEvent.defaultPrevented).toBe(false)
    wrapper.unmount()
  })

  it('confirms router navigation and cleans up only after approval', async () => {
    const confirm = vi.fn().mockResolvedValueOnce(false).mockResolvedValueOnce(true)
    const cleanup = vi.fn()
    const router = createRouter({
      history: createMemoryHistory(),
      routes: [
        { path: '/add', component: { template: '<p>add</p>' } },
        { path: '/plans', component: { template: '<p>plans</p>' } },
      ],
    })
    await router.push('/add')
    await router.isReady()
    const wrapper = mount({
      setup() {
        useLeaveGuard({ shouldGuard: () => true, confirm, cleanup })
        return () => null
      },
    }, { global: { plugins: [router] } })
    const cancelled = await router.push('/plans')
    expect(cancelled).toMatchObject({ type: 4 })
    expect(cleanup).not.toHaveBeenCalled()
    expect(router.currentRoute.value.path).toBe('/add')

    await router.push('/plans')
    expect(cleanup).toHaveBeenCalledTimes(1)
    wrapper.unmount()
  })
})
