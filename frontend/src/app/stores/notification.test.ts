import { createPinia, setActivePinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import {
  NOTIFICATION_AUTO_CLOSE_MS,
  useNotificationStore,
  type NotificationKind,
} from '@/app/stores/notification'

// A kind outside the typed union can still arrive from untyped callers.
const UNKNOWN_KIND = 'warning' as unknown as NotificationKind

describe('notification store (US-199 / US-346)', () => {
  beforeEach(() => {
    vi.useFakeTimers()
    setActivePinia(createPinia())
  })

  afterEach(() => {
    vi.clearAllTimers()
    vi.useRealTimers()
  })

  it('keeps success and info for 10 seconds and error for 20 seconds', () => {
    expect(NOTIFICATION_AUTO_CLOSE_MS).toEqual({
      success: 10_000,
      info: 10_000,
      error: 20_000,
    })

    const store = useNotificationStore()

    store.success('保存成功')
    vi.advanceTimersByTime(9_999)
    expect(store.current?.title).toBe('保存成功')
    vi.advanceTimersByTime(1)
    expect(store.current).toBeNull()

    store.info('未找到候选合集')
    vi.advanceTimersByTime(10_000)
    expect(store.current).toBeNull()

    store.error('请求失败')
    vi.advanceTimersByTime(19_999)
    expect(store.current?.title).toBe('请求失败')
    vi.advanceTimersByTime(1)
    expect(store.current).toBeNull()
  })

  it('gives every message a unique id', () => {
    const store = useNotificationStore()
    store.success('第一条')
    const firstId = store.current?.id
    store.success('第二条')
    expect(store.current?.id).not.toBe(firstId)
  })

  it('drops the message and its timer immediately on manual close', () => {
    const store = useNotificationStore()
    store.error('请求失败')
    expect(vi.getTimerCount()).toBe(1)

    store.clear()
    expect(store.current).toBeNull()
    expect(vi.getTimerCount()).toBe(0)

    vi.advanceTimersByTime(60_000)
    expect(store.current).toBeNull()
  })

  it('lets a replacement keep its own deadline and leaves no extra timer', () => {
    const store = useNotificationStore()
    store.success('第一条')
    vi.advanceTimersByTime(5_000)

    store.error('第二条')
    expect(vi.getTimerCount()).toBe(1)

    // Past the replaced message's own 10s deadline: the old timer must not
    // expire the message that replaced it.
    vi.advanceTimersByTime(10_000)
    expect(store.current?.title).toBe('第二条')
    expect(store.current?.kind).toBe('error')

    // The replacement keeps its full 20s budget measured from its own start.
    vi.advanceTimersByTime(9_999)
    expect(store.current?.title).toBe('第二条')
    vi.advanceTimersByTime(1)
    expect(store.current).toBeNull()
    expect(vi.getTimerCount()).toBe(0)
  })

  it('survives repeated replacements without a stale timer closing the survivor', () => {
    const store = useNotificationStore()

    store.success('A')
    vi.advanceTimersByTime(3_000)
    store.success('B')
    vi.advanceTimersByTime(3_000)
    store.success('C')

    expect(vi.getTimerCount()).toBe(1)

    // Both A and B have passed their original deadlines by now, while C keeps
    // its own (10s measured from its own start).
    vi.advanceTimersByTime(9_000)
    expect(store.current?.title).toBe('C')
    expect(vi.getTimerCount()).toBe(1)

    vi.advanceTimersByTime(1_000)
    expect(store.current).toBeNull()
    expect(vi.getTimerCount()).toBe(0)
  })

  it('does not let a cleared message expire the next one', () => {
    const store = useNotificationStore()
    store.success('A')
    store.clear()
    vi.advanceTimersByTime(1_000)

    store.error('B')
    // Past A's original 10s deadline, B is still up and keeps its own 20s.
    vi.advanceTimersByTime(10_000)
    expect(store.current?.title).toBe('B')

    vi.advanceTimersByTime(9_999)
    expect(store.current?.title).toBe('B')

    vi.advanceTimersByTime(1)
    expect(store.current).toBeNull()
  })

  it('never schedules an auto-close for an unrecognised kind', () => {
    const store = useNotificationStore()
    store.show(UNKNOWN_KIND, '未定义类型')

    expect(store.current?.title).toBe('未定义类型')
    expect(vi.getTimerCount()).toBe(0)

    vi.advanceTimersByTime(120_000)
    expect(store.current?.title).toBe('未定义类型')

    store.clear()
    expect(store.current).toBeNull()
  })
})
