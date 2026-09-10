import { beforeEach, describe, expect, it, vi } from 'vitest'

import { api } from '@/api/client'
import { useDraftSession, type DraftSnapshot } from '@/app/composables/useDraftSession'

vi.mock('@/api/client', async (importOriginal) => {
  const original = await importOriginal<typeof import('@/api/client')>()
  return { ...original, api: { post: vi.fn() } }
})

const snapshot = {} as DraftSnapshot

describe('useDraftSession (US-266)', () => {
  beforeEach(() => vi.mocked(api.post).mockReset())

  it('atomically replaces the snapshot and revision after a successful modify', async () => {
    vi.mocked(api.post).mockResolvedValue({ request: { ...snapshot, status: 'changed' }, draft_id: 'next', draft_revision: 2 })
    const session = useDraftSession({ request: snapshot, draftId: 'opaque', draftRevision: 1 })

    await session.apply({} as never)

    expect(session.request.value).toEqual({ ...snapshot, status: 'changed' })
    expect(session.draftId.value).toBe('next')
    expect(session.draftRevision.value).toBe(2)
    expect(session.dirty.value).toBe(false)
    expect(session.canRetry.value).toBe(false)
  })

  it('rejects a second apply while the first request owns the revision', async () => {
    let resolveFirst!: (value: unknown) => void
    vi.mocked(api.post).mockReturnValueOnce(new Promise((resolve) => { resolveFirst = resolve }))
    const session = useDraftSession({ request: snapshot, draftId: 'opaque', draftRevision: 1 })

    const first = session.apply({} as never)
    const second = await session.apply({} as never)
    expect(second).toBeNull()
    expect(api.post).toHaveBeenCalledTimes(1)
    resolveFirst({ request: { ...snapshot, status: 'old' }, draft_id: 'opaque', draft_revision: 2 })
    await first

    expect(session.request.value?.status).toBe('old')
    expect(session.draftRevision.value).toBe(2)
  })

  it('clears applying when an in-flight request is invalidated or reset', async () => {
    let resolve!: (value: unknown) => void
    vi.mocked(api.post).mockReturnValueOnce(new Promise((done) => { resolve = done }))
    const invalidated = useDraftSession({ request: snapshot, draftId: 'opaque' })
    const pendingInvalidation = invalidated.apply({} as never)
    expect(invalidated.applying.value).toBe(true)
    invalidated.invalidate()
    expect(invalidated.applying.value).toBe(false)
    expect(invalidated.canRetry.value).toBe(false)
    resolve({ request: snapshot, draft_id: 'opaque', draft_revision: 2 })
    await pendingInvalidation
    expect(invalidated.applying.value).toBe(false)

    let resolveReset!: (value: unknown) => void
    vi.mocked(api.post).mockReturnValueOnce(new Promise((done) => { resolveReset = done }))
    const reset = useDraftSession({ request: snapshot, draftId: 'opaque' })
    const pendingReset = reset.apply({} as never)
    expect(reset.applying.value).toBe(true)
    reset.reset()
    expect(reset.applying.value).toBe(false)
    expect(reset.canRetry.value).toBe(false)
    resolveReset({ request: snapshot, draft_id: 'opaque', draft_revision: 2 })
    await pendingReset
    expect(reset.applying.value).toBe(false)
  })

  it('invalidates the capability for draft conflicts and preserves ordinary failures', async () => {
    vi.mocked(api.post).mockRejectedValueOnce({ type: 'draft_expired', message: 'unsafe', status: 409 })
    const expired = useDraftSession({ request: snapshot, draftId: 'opaque' })
    await expired.apply({} as never)
    expect(expired.invalid.value).toBe(true)
    expect(expired.draftId.value).toBeNull()
    expect(expired.request.value).toBeNull()

    vi.mocked(api.post).mockRejectedValueOnce({
      type: 'network_error',
      message: '网络请求失败，请检查网络后重试',
      status: 0,
      details: null,
      cancelled: false,
      network: true,
      nonJson: false,
      httpError: false,
    })
    const failed = useDraftSession({ request: snapshot, draftId: 'opaque' })
    await failed.apply({} as never)
    expect(failed.request.value).toEqual(snapshot)
    expect(failed.draftId.value).toBe('opaque')
    expect(failed.dirty.value).toBe(true)
    expect(failed.error.value?.message).toBe('网络请求失败，请检查网络后重试')
    expect(failed.canRetry.value).toBe(true)

    failed.reset()
    expect(failed.canRetry.value).toBe(false)
  })

})
