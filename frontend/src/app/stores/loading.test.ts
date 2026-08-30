import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it } from 'vitest'

import { useLoadingStore } from '@/app/stores/loading'

describe('loading store (US-199)', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
  })

  it('tracks in-flight requests with a counter', () => {
    const store = useLoadingStore()
    expect(store.isLoading).toBe(false)

    store.begin()
    expect(store.isLoading).toBe(true)

    store.begin()
    store.end()
    expect(store.isLoading).toBe(true)

    store.end()
    expect(store.isLoading).toBe(false)
  })

  it('never goes negative', () => {
    const store = useLoadingStore()
    store.end()
    expect(store.inFlight).toBe(0)
    expect(store.isLoading).toBe(false)
  })
})
