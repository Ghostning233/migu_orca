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
  })

  it('ignores an older response when requests resolve out of order', async () => {
    let resolveFirst!: (value: unknown) => void
    let resolveSecond!: (value: unknown) => void
    vi.mocked(api.post)
      .mockReturnValueOnce(new Promise((resolve) => { resolveFirst = resolve }))
      .mockReturnValueOnce(new Promise((resolve) => { resolveSecond = resolve }))
    const session = useDraftSession({ request: snapshot, draftId: 'opaque', draftRevision: 1 })

    const first = session.apply({} as never)
    const second = session.apply({} as never)
    resolveFirst({ request: { ...snapshot, status: 'old' }, draft_id: 'opaque', draft_revision: 2 })
    resolveSecond({ request: { ...snapshot, status: 'new' }, draft_id: 'opaque', draft_revision: 3 })
    await Promise.all([first, second])

    expect(session.request.value?.status).toBe('new')
    expect(session.draftRevision.value).toBe(3)
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
  })
})
