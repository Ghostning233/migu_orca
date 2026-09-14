import { beforeEach, describe, expect, it, vi } from 'vitest'

import { api } from '@/api/client'
import { useConnectionStatus } from '@/app/stores/connectionStatus'

vi.mock('@/api/client', () => ({
  api: { get: vi.fn() },
}))

const apiGet = vi.mocked(api.get)

describe('Stage 39 global connection status invalidation', () => {
  beforeEach(() => {
    apiGet.mockReset()
  })

  it('reloads the safe summary after configuration invalidation', async () => {
    const first = {
      configured: true,
      credential_present: true,
      connection_ref: 'old-ref',
      configuration_revision: 1,
      connection_status: 'CONFIGURED',
    }
    const latest = {
      configured: true,
      credential_present: true,
      connection_ref: 'new-ref',
      configuration_revision: 2,
      connection_status: 'VERIFIED',
    }
    apiGet.mockResolvedValueOnce(first as never).mockResolvedValueOnce(latest as never)

    const status = useConnectionStatus()
    await status.loadSummary()
    expect(status.summary.value?.connection_ref).toBe('old-ref')

    status.invalidate()
    // Saving/deleting a profile invalidates the in-memory cache and must
    // immediately converge to the newest server-owned safe summary.
    await vi.waitFor(() => expect(status.summary.value?.connection_ref).toBe('new-ref'))
    expect(apiGet.mock.calls.filter(([path]) => path === '/api/v1/settings/autobangumi')).toHaveLength(2)
  })

  it('clears the old badge and reads the current profile after switching profiles', async () => {
    localStorage.setItem('miguOrca.web.storageDir', 'profile-a')
    apiGet.mockResolvedValueOnce({ items: [{ status: 'PENDING_SUBMIT' }] } as never)
    const status = useConnectionStatus()
    await status.loadPending()
    expect(status.pendingCount.value).toBe(1)

    localStorage.setItem('miguOrca.web.storageDir', 'profile-b')
    apiGet.mockResolvedValueOnce({ items: [{ status: 'SUBMIT_FAILED' }, { status: 'DONE' }] } as never)
    await status.loadPending()
    expect(apiGet).toHaveBeenLastCalledWith('/api/v1/tracking/items', {
      query: { storage_dir: 'profile-b', sort: 'updated_at' },
    })
    expect(status.pendingCount.value).toBe(1)
  })

  it('does not show a fabricated zero when the list request fails', async () => {
    apiGet.mockRejectedValueOnce(new Error('upstream unavailable'))
    const status = useConnectionStatus()
    await status.loadPending()
    expect(status.pendingCount.value).toBeNull()
  })

  it('refreshes the current profile pending badge together with the summary', async () => {
    localStorage.setItem('miguOrca.web.storageDir', 'profile-b')
    apiGet.mockImplementation(async (path) => path === '/api/v1/settings/autobangumi'
      ? { configured: true, credential_present: true, connection_ref: 'new-ref', configuration_revision: 2, connection_status: 'VERIFIED' } as never
      : { items: [{ status: 'PENDING_SUBMIT' }, { status: 'SUBMIT_FAILED' }, { status: 'DONE' }] } as never)
    const status = useConnectionStatus()
    status.invalidate()
    await vi.waitFor(() => expect(status.summary.value?.connection_ref).toBe('new-ref'))
    await vi.waitFor(() => expect(status.pendingCount.value).toBe(2))
    expect(apiGet).toHaveBeenCalledWith('/api/v1/tracking/items', { query: { storage_dir: 'profile-b', sort: 'updated_at' } })
  })
})
