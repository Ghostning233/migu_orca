import { flushPromises } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { api, toApiError } from '@/api/client'

import { useSavedPlanEditor, type SavedPlanFetch } from './useSavedPlanEditor'

vi.mock('@/api/client', () => ({
  api: { get: vi.fn(), post: vi.fn() },
  toApiError: (error: unknown) =>
    typeof error === 'object' && error !== null
      ? { type: 'unexpected_error', status: 0, network: false, cancelled: false, nonJson: false, ...(error as object) }
      : { type: 'unexpected_error', status: 0, network: false, cancelled: false, nonJson: false },
}))
const apiPost = vi.mocked(api.post)

function snapshot(overrides: Record<string, unknown> = {}) {
  return {
    request: {
      request_id: 'request-1',
      status: 'ACCEPTED',
      confirmable_config: {
        selected_subtitle_group: '喵萌奶茶屋',
        expected_folder_name: '芙莉莲',
        filter_rule: {
          must_contain: '', must_not_contain: '', use_regex: false, case_sensitive: false,
        },
      },
      ...overrides,
    },
  } as never
}

function session(fetches: SavedPlanFetch[], overrides: Record<string, unknown> = {}) {
  const commitSnapshot = vi.fn()
  const onApplied = vi.fn()
  const queue = [...fetches]
  const editor = useSavedPlanEditor({
    requestId: () => 'request-1',
    fetchSnapshot: async () => queue.shift() ?? { result: null, error: toApiError(new Error('empty')) },
    commitSnapshot,
    onApplied,
    storageQuery: () => ({ storage_dir: 'storage' }),
    ...overrides,
  })
  return { editor, commitSnapshot, onApplied, queued: queue }
}

describe('shared saved-plan editor session (issue #90)', () => {
  beforeEach(() => { apiPost.mockReset() })

  it('refuses an empty patch without sending anything', () => {
    const { editor } = session([{ result: snapshot(), error: null }])

    editor.submit({})

    expect(editor.error.value).toContain('请至少修改或清空一个字段')
    expect(apiPost).not.toHaveBeenCalled()
  })

  it('sends only the patch and commits the authoritative snapshot', async () => {
    const applied = snapshot({ confirmable_config: {
      selected_subtitle_group: '喵萌奶茶屋',
      expected_folder_name: '新目录',
      filter_rule: { must_contain: '', must_not_contain: '', use_regex: false, case_sensitive: false },
    } })
    const { editor, commitSnapshot, onApplied } = session([{ result: applied, error: null }])
    apiPost.mockResolvedValue({} as never)

    editor.submit({ expected_folder_name: '新目录' })
    await flushPromises()

    expect(apiPost).toHaveBeenCalledTimes(1)
    const [path, request] = apiPost.mock.calls[0] as [string, { path: { request_id: string }; body: unknown; query: unknown }]
    expect(path).toBe('/api/v1/requests/{request_id}/modify')
    expect(request.path).toEqual({ request_id: 'request-1' })
    expect(request.body).toEqual({ patch: { expected_folder_name: '新目录' }, storage_dir: 'storage' })
    expect(commitSnapshot).toHaveBeenCalledWith(applied)
    expect(onApplied).toHaveBeenCalledTimes(1)
    expect(editor.formOpen.value).toBe(false)
  })

  it('reports an unapplied change instead of claiming success', async () => {
    const { editor, commitSnapshot } = session([{ result: snapshot(), error: null }])
    apiPost.mockResolvedValue({} as never)

    editor.submit({ expected_folder_name: '新目录' })
    await flushPromises()

    expect(commitSnapshot).not.toHaveBeenCalled()
    expect(editor.error.value).toBe('修改未生效，请重试。')
    expect(editor.resultUnknown.value).toBe(false)
  })

  it('locks the editor on an unconfirmed write and never resends blindly', async () => {
    const { editor } = session([{ result: null, error: toApiError(new Error('boom')) }])
    apiPost.mockRejectedValue({ network: true })

    editor.submit({ expected_folder_name: '新目录' })
    await flushPromises()

    expect(editor.resultUnknown.value).toBe(true)
    expect(editor.error.value).toBe('结果暂无法确认，请重新确认结果。')

    // A second submit is refused while the intent is unresolved.
    editor.submit({ expected_folder_name: '另一个目录' })
    await flushPromises()
    expect(apiPost).toHaveBeenCalledTimes(1)
  })

  it('resolves a locked write by read-back only', async () => {
    const applied = snapshot({ confirmable_config: {
      selected_subtitle_group: '喵萌奶茶屋',
      expected_folder_name: '新目录',
      filter_rule: { must_contain: '', must_not_contain: '', use_regex: false, case_sensitive: false },
    } })
    const { editor, commitSnapshot, onApplied } = session([
      { result: null, error: toApiError(new Error('boom')) },
      { result: applied, error: null },
    ])
    apiPost.mockRejectedValue({ network: true })

    editor.submit({ expected_folder_name: '新目录' })
    await flushPromises()
    expect(editor.resultUnknown.value).toBe(true)

    await editor.retry()

    // The read-back proved it applied: no second write was sent.
    expect(apiPost).toHaveBeenCalledTimes(1)
    expect(commitSnapshot).toHaveBeenCalledWith(applied)
    expect(onApplied).toHaveBeenCalledTimes(1)
    expect(editor.resultUnknown.value).toBe(false)
  })

  it('releases the lock when the read-back proves nothing was written', async () => {
    const { editor } = session([
      { result: null, error: toApiError(new Error('boom')) },
      { result: snapshot(), error: null },
    ])
    apiPost.mockRejectedValue({ network: true })

    editor.submit({ expected_folder_name: '新目录' })
    await flushPromises()
    await editor.retry()

    expect(editor.resultUnknown.value).toBe(false)
    expect(editor.error.value).toBe('修改未生效，请重试。')
  })
})
