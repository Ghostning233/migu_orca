import { flushPromises } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { api } from '@/api/client'
import { useDraftSession } from '@/app/composables/useDraftSession'
import {
  DRAFT_FILTER_DEBOUNCE_MS,
  useDraftEditScheduler,
} from '@/features/workbench/draftEditScheduler'
import { previewEditStateFrom, type PreviewEditState } from '@/features/workbench/candidateSearch'
import type { RequestSnapshot } from '@/features/requests/requestDetail'

// US-344 (WP-41-C): the edit scheduler is the only place that decides *when*
// a server-authoritative preview-modify leaves the browser. Subtitle groups go
// out immediately, filter rules are debounced for 1.5s from the last input,
// and the folder name is never auto-sent.

vi.mock('@/api/client', () => ({
  api: {
    get: vi.fn(),
    post: vi.fn(),
    put: vi.fn(),
    patch: vi.fn(),
    delete: vi.fn(),
    poster: vi.fn(),
  },
  toApiError: (error: unknown) =>
    error && typeof error === 'object' && 'type' in error
      ? (error as { type: string; message: string; details?: Record<string, unknown> })
      : { type: 'request_error', message: '请求失败，请重试' },
  isApiError: () => false,
  apiRequest: vi.fn(),
}))

const apiPost = vi.mocked(api.post)

function draftSnapshot(overrides: Record<string, unknown> = {}): RequestSnapshot {
  const base = {
    request_id: null,
    status: 'PENDING_CONFIRM',
    input: { raw_title: '葬送的芙莉莲' },
    source_info: {
      matched_bangumi: { title: '葬送的芙莉莲' },
      rss_sources: [
        { subtitle_group: '喵萌奶茶屋', valid_seed_names: ['01.mkv'], seed_names: ['01.mkv'] },
        { subtitle_group: '桜都字幕组', valid_seed_names: ['01.mkv'], seed_names: ['01.mkv'] },
      ],
    },
    confirmable_config: {
      selected_subtitle_group: '喵萌奶茶屋',
      selected_rss_url: null,
      filter_rule: { must_contain: '', must_not_contain: '', use_regex: false, case_sensitive: false },
      effective_seed_names: ['01.mkv'],
      expected_folder_name: '葬送的芙莉莲',
      warnings: [],
    },
    ab_submit_result: null,
    created_at: '2026-09-17T00:00:00+00:00',
    updated_at: '2026-09-17T00:00:00+00:00',
    user_action: null,
  }
  const merged = { ...base, ...overrides }
  if (overrides.confirmable_config) {
    merged.confirmable_config = { ...base.confirmable_config, ...(overrides.confirmable_config as object) }
  }
  return merged as unknown as RequestSnapshot
}

function modifyResult(snapshot: RequestSnapshot, revision: number, draftId = 'draft-opaque') {
  return { request: snapshot, summary: {}, draft_id: draftId, draft_revision: revision } as never
}

function formState(overrides: Partial<PreviewEditState> = {}): PreviewEditState {
  return {
    selectedSubtitleGroup: '喵萌奶茶屋',
    mustContain: '',
    mustNotContain: '',
    useRegex: false,
    caseSensitive: false,
    expectedFolderName: '葬送的芙莉莲',
    ...overrides,
  }
}

function modifyCalls() {
  return apiPost.mock.calls.filter(([path]) => path === '/api/v1/requests/preview-modify')
}

function bodyOf(index: number) {
  return modifyCalls()[index]?.[1]?.body as Record<string, unknown> | undefined
}

function build(overrides: { request?: RequestSnapshot; draftRevision?: number } = {}) {
  const session = useDraftSession({
    request: overrides.request ?? draftSnapshot(),
    draftId: 'draft-opaque',
    draftRevision: overrides.draftRevision ?? 1,
  })
  const applied: unknown[] = []
  const invalidated = vi.fn()
  const failed = vi.fn()
  const scheduler = useDraftEditScheduler({
    session,
    storageDir: () => null,
    onApplied: (result) => applied.push(result),
    onInvalid: invalidated,
    onFailed: failed,
  })
  return { session, scheduler, applied, invalidated, failed }
}

describe('useDraftEditScheduler (US-344)', () => {
  beforeEach(() => {
    apiPost.mockReset()
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  it('sends the subtitle group immediately and never adds the folder name', async () => {
    const { scheduler, session } = build()
    scheduler.setFolderName('自定义目录')
    apiPost.mockResolvedValueOnce(modifyResult(
      draftSnapshot({ confirmable_config: { selected_subtitle_group: '桜都字幕组' } }),
      2,
    ))

    scheduler.setSubtitleGroup('桜都字幕组')
    await flushPromises()

    expect(modifyCalls()).toHaveLength(1)
    expect(bodyOf(0)).toMatchObject({
      draft_id: 'draft-opaque',
      base_revision: 1,
      patch: { selected_subtitle_group: '桜都字幕组' },
      storage_dir: null,
    })
    // The folder edit stays manual even after a successful automatic send.
    expect(bodyOf(0)?.patch).not.toHaveProperty('expected_folder_name')
    expect(scheduler.folderPending.value).toBe(true)
    expect(session.draftRevision.value).toBe(2)
  })

  it('never piggybacks a not-yet-due filter rule on an immediate subtitle change', async () => {
    const { scheduler } = build()
    apiPost.mockResolvedValueOnce(modifyResult(
      draftSnapshot({ confirmable_config: { selected_subtitle_group: '桜都字幕组' } }),
      2,
    ))

    // The filter was typed a moment ago and its window has not expired yet.
    scheduler.setFilter(formState({ mustNotContain: 'V2' }))
    scheduler.setSubtitleGroup('桜都字幕组')
    await flushPromises()

    expect(modifyCalls()).toHaveLength(1)
    expect(bodyOf(0)?.patch).toEqual({ selected_subtitle_group: '桜都字幕组' })
    // The filter intent survives, still waiting for its own window.
    expect(scheduler.waiting.value).toBe(true)
    expect(scheduler.filterPending.value).toBe(true)
  })

  it('debounces the filter rule for 1.5s from the last input', async () => {
    vi.useFakeTimers()
    const { scheduler } = build()
    apiPost.mockResolvedValue(modifyResult(
      draftSnapshot({ confirmable_config: { filter_rule: { must_contain: '', must_not_contain: 'V2', use_regex: false, case_sensitive: false } } }),
      2,
    ))

    scheduler.setFilter(formState({ mustNotContain: 'V1' }))
    expect(scheduler.waiting.value).toBe(true)
    await vi.advanceTimersByTimeAsync(DRAFT_FILTER_DEBOUNCE_MS - 100)
    scheduler.setFilter(formState({ mustNotContain: 'V2' }))
    await vi.advanceTimersByTimeAsync(DRAFT_FILTER_DEBOUNCE_MS - 100)

    // The window restarted with the second keystroke: nothing has been sent.
    expect(modifyCalls()).toHaveLength(0)

    await vi.advanceTimersByTimeAsync(200)
    expect(modifyCalls()).toHaveLength(1)
    expect(bodyOf(0)).toMatchObject({
      base_revision: 1,
      patch: { filter_rule: { must_not_contain: 'V2', use_regex: false, case_sensitive: false } },
    })
    expect(scheduler.filterPending.value).toBe(false)
    expect(scheduler.waiting.value).toBe(false)
  })

  it('flushes a pending filter together with the folder name on demand', async () => {
    vi.useFakeTimers()
    const { scheduler } = build()
    apiPost.mockResolvedValue(modifyResult(
      draftSnapshot({ confirmable_config: { filter_rule: { must_contain: '', must_not_contain: 'V2', use_regex: false, case_sensitive: false }, expected_folder_name: '自定义目录' } }),
      2,
    ))

    scheduler.setFilter(formState({ mustNotContain: 'V2' }))
    scheduler.setFolderName('自定义目录')
    expect(scheduler.canFlush.value).toBe(true)

    await scheduler.flush()
    await vi.advanceTimersByTimeAsync(DRAFT_FILTER_DEBOUNCE_MS * 2)

    expect(modifyCalls()).toHaveLength(1)
    expect(bodyOf(0)).toMatchObject({
      base_revision: 1,
      patch: {
        filter_rule: { must_not_contain: 'V2', use_regex: false, case_sensitive: false },
        expected_folder_name: '自定义目录',
      },
    })
    expect(scheduler.waiting.value).toBe(false)
    expect(scheduler.hasPendingIntent.value).toBe(false)
    expect(scheduler.canFlush.value).toBe(false)
  })

  it('never sends the folder name on its own', async () => {
    vi.useFakeTimers()
    const { scheduler } = build()

    scheduler.setFolderName('自定义目录')
    await vi.advanceTimersByTimeAsync(DRAFT_FILTER_DEBOUNCE_MS * 4)

    expect(modifyCalls()).toHaveLength(0)
    expect(scheduler.folderPending.value).toBe(true)
    expect(scheduler.hasPendingIntent.value).toBe(true)
  })

  it('queues intent typed during a flight and only sends the latest one', async () => {
    let release!: (value: unknown) => void
    const held = new Promise((resolve) => { release = resolve })
    const { scheduler, session } = build()
    apiPost.mockReturnValueOnce(held as never)

    scheduler.setSubtitleGroup('桜都字幕组')
    await flushPromises()
    expect(modifyCalls()).toHaveLength(1)
    expect(session.applying.value).toBe(true)

    // Three more intents arrive while the first request owns the revision;
    // only the latest one survives.
    scheduler.setSubtitleGroup('喵萌奶茶屋')
    scheduler.setSubtitleGroup('桜都字幕组')
    scheduler.setSubtitleGroup('喵萌奶茶屋')
    await flushPromises()
    expect(modifyCalls()).toHaveLength(1)

    apiPost.mockResolvedValueOnce(modifyResult(
      draftSnapshot({ confirmable_config: { selected_subtitle_group: '桜都字幕组' } }),
      2,
    ))
    release(modifyResult(draftSnapshot({ confirmable_config: { selected_subtitle_group: '桜都字幕组' } }), 2))
    await flushPromises()

    expect(modifyCalls()).toHaveLength(2)
    // No revision was reused: the queued send uses the revision the first
    // response returned, and carries only the still-latest intent.
    expect(bodyOf(1)).toMatchObject({ base_revision: 2, draft_id: 'draft-opaque' })
    expect(bodyOf(1)?.patch).toEqual({ selected_subtitle_group: '喵萌奶茶屋' })
    for (const call of modifyCalls()) {
      expect(call[1]?.body).not.toHaveProperty('request')
    }
  })

  it('commits the returned snapshot and revision atomically', async () => {
    const { scheduler, session, applied } = build()
    const next = draftSnapshot({
      confirmable_config: { selected_subtitle_group: '桜都字幕组', effective_seed_names: [] },
    })
    apiPost.mockResolvedValueOnce(modifyResult(next, 3))

    scheduler.setSubtitleGroup('桜都字幕组')
    await flushPromises()

    expect(applied).toHaveLength(1)
    expect(session.request.value).toEqual(next)
    expect(session.draftRevision.value).toBe(3)
    expect(session.draftId.value).toBe('draft-opaque')
    expect(session.dirty.value).toBe(false)
    expect(scheduler.groupPending.value).toBe(false)
    expect(scheduler.pendingGroup.value).toBeNull()
  })

  it('keeps the last server-consistent result and retries the unapplied intent', async () => {
    const { scheduler, session, failed } = build()
    apiPost.mockRejectedValueOnce({ type: 'network_error', message: '原始网络错误' })

    scheduler.setSubtitleGroup('桜都字幕组')
    await flushPromises()

    expect(session.request.value?.confirmable_config?.selected_subtitle_group).toBe('喵萌奶茶屋')
    expect(session.error.value?.type).toBe('network_error')
    expect(scheduler.pendingGroup.value).toBe('桜都字幕组')
    expect(scheduler.groupPending.value).toBe(true)
    expect(scheduler.hasPendingIntent.value).toBe(true)
    expect(failed).toHaveBeenCalled()

    apiPost.mockResolvedValueOnce(modifyResult(
      draftSnapshot({ confirmable_config: { selected_subtitle_group: '桜都字幕组' } }),
      2,
    ))
    await scheduler.retry()
    await flushPromises()

    expect(session.request.value?.confirmable_config?.selected_subtitle_group).toBe('桜都字幕组')
    expect(session.error.value).toBeNull()
    expect(scheduler.hasPendingIntent.value).toBe(false)
  })

  it('restores the last consistent result and drops the unapplied intent', async () => {
    const { scheduler, session } = build()
    apiPost.mockRejectedValueOnce({ type: 'network_error', message: '原始网络错误' })

    scheduler.setSubtitleGroup('桜都字幕组')
    await flushPromises()
    expect(session.error.value).not.toBeNull()

    scheduler.restore()

    expect(scheduler.pendingGroup.value).toBeNull()
    expect(scheduler.hasPendingIntent.value).toBe(false)
    expect(session.error.value).toBeNull()
    expect(session.draftRevision.value).toBe(1)
  })

  it('stops sending and reports invalidation when the draft capability is gone', async () => {
    const { scheduler, session, invalidated } = build()
    apiPost.mockRejectedValueOnce({
      type: 'draft_revision_conflict',
      message: '草案已被更新',
      details: { details: { field: 'base_revision', current_revision: 2 } },
    })

    scheduler.setSubtitleGroup('桜都字幕组')
    await flushPromises()

    expect(session.invalid.value).toBe(true)
    expect(invalidated).toHaveBeenCalledTimes(1)
    expect(scheduler.pendingGroup.value).toBeNull()
    expect(scheduler.hasPendingIntent.value).toBe(false)

    scheduler.setSubtitleGroup('喵萌奶茶屋')
    await flushPromises()
    expect(modifyCalls()).toHaveLength(1)
  })

  it('cancels a debounced filter without sending it', async () => {
    vi.useFakeTimers()
    const { scheduler } = build()

    scheduler.setFilter(formState({ mustNotContain: 'V2' }))
    scheduler.cancelTimer()
    await vi.advanceTimersByTimeAsync(DRAFT_FILTER_DEBOUNCE_MS * 2)

    expect(modifyCalls()).toHaveLength(0)
    expect(scheduler.waiting.value).toBe(false)

    scheduler.dropPending()
    expect(scheduler.hasPendingIntent.value).toBe(false)
  })

  it('never reuses an in-flight revision for intent typed during the flight', async () => {
    let release!: (value: unknown) => void
    const held = new Promise((resolve) => { release = resolve })
    const { scheduler } = build()
    apiPost.mockReturnValueOnce(held as never)

    scheduler.setFilter(formState({ mustNotContain: 'V2' }))
    // The CAS is held, so the flush promise only settles once it is released.
    void scheduler.flush()
    await flushPromises()
    expect(modifyCalls()).toHaveLength(1)

    // 保存并确认 is disabled while the CAS owns the revision, so nothing may
    // sneak a second send with base_revision 1.
    scheduler.setSubtitleGroup('桜都字幕组')
    await flushPromises()
    expect(modifyCalls()).toHaveLength(1)

    apiPost.mockResolvedValueOnce(modifyResult(draftSnapshot(), 2))
    release(modifyResult(draftSnapshot(), 2))
    await flushPromises()
    expect(bodyOf(1)).toMatchObject({ base_revision: 2 })
  })
})

describe('previewEditStateFrom', () => {
  it('projects the server snapshot onto the editor form state', () => {
    expect(previewEditStateFrom(draftSnapshot())).toEqual({
      selectedSubtitleGroup: '喵萌奶茶屋',
      mustContain: '',
      mustNotContain: '',
      useRegex: false,
      caseSensitive: false,
      expectedFolderName: '葬送的芙莉莲',
    })
    expect(previewEditStateFrom(draftSnapshot({
      confirmable_config: { selected_subtitle_group: '', filter_rule: { must_contain: '1080p', must_not_contain: '', use_regex: true, case_sensitive: true }, expected_folder_name: '' },
    }))).toEqual({
      selectedSubtitleGroup: '',
      mustContain: '1080p',
      mustNotContain: '',
      useRegex: true,
      caseSensitive: true,
      expectedFolderName: '',
    })
  })
})
