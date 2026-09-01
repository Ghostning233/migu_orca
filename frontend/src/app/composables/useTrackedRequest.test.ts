import { createPinia, setActivePinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { trackedApi } from '@/app/composables/useTrackedRequest'
import { useLoadingStore } from '@/app/stores/loading'

// US-199: tracked requests drive the global loading indicator. The transport
// itself is unit-tested in src/api/client.test.ts; here we assert the
// begin/end lifecycle around a request.

const fetchMock = vi.fn()

beforeEach(() => {
  setActivePinia(createPinia())
  fetchMock.mockReset()
  vi.stubGlobal('fetch', fetchMock)
})

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('trackedApi (US-199)', () => {
  it('shows the global loading state while a request is in flight', async () => {
    let resolveFetch!: (value: Response) => void
    fetchMock.mockImplementation(
      () =>
        new Promise<Response>((resolve) => {
          resolveFetch = resolve
        }),
    )

    const loading = useLoadingStore()
    expect(loading.isLoading).toBe(false)

    const pending = trackedApi.get('/api/v1/requests')
    await Promise.resolve()
    expect(loading.isLoading).toBe(true)

    resolveFetch(new Response(JSON.stringify({ ok: true, result: {} }), {
      status: 200,
      headers: { 'Content-Type': 'application/json' },
    }))
    await pending
    expect(loading.isLoading).toBe(false)
  })

  it('clears the loading state on failure', async () => {
    fetchMock.mockRejectedValue(new TypeError('Failed to fetch'))

    const loading = useLoadingStore()
    await expect(trackedApi.get('/api/v1/requests')).rejects.toMatchObject({
      type: 'network_error',
    })
    expect(loading.isLoading).toBe(false)
  })
})
