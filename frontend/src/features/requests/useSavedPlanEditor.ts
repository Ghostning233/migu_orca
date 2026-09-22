/**
 * Shared "edit a saved local plan" session (issue #90).
 *
 * A saved plan is edited with the shared draft editor core, and every save is a
 * revision-authoritative server call: the browser sends only the patch, re-reads
 * the authoritative snapshot and never treats its own copy as the source of
 * truth. A write whose result cannot be confirmed locks the editor until the
 * user explicitly re-checks it — it is never blindly resent.
 *
 * The host owns rendering, the request snapshot and how a committed snapshot is
 * applied to its own view; this composable owns only the session semantics, so
 * the "我的追番" detail and any other host behave identically.
 */
import { ref, type Ref } from 'vue'

import { api, toApiError } from '@/api/client'
import type { operations } from '@/api/generated/api'
import type { RequestDetailResult } from '@/features/requests/requestDetail'
import type { PreviewPatch } from '@/features/workbench/candidateSearch'

type ModifyResult = NonNullable<
  operations['modifyRequest']['responses']['200']['content']['application/json']['result']
>
type ModifyRequestBodyContract = NonNullable<
  operations['modifyRequest']['requestBody']['content']['application/json']
>
type ModifyRequestBody = Omit<ModifyRequestBodyContract, 'patch'> & { patch: PreviewPatch }

export type SavedPlanFetch =
  | { result: RequestDetailResult; error: null }
  | { result: null; error: ReturnType<typeof toApiError> }

export interface SavedPlanEditorOptions {
  /** The saved plan this session edits. */
  requestId: () => string
  /** Re-read the authoritative snapshot (never a cached client copy). */
  fetchSnapshot: () => Promise<SavedPlanFetch>
  /** Apply a confirmed snapshot to the host's own view. */
  commitSnapshot: (snapshot: RequestDetailResult) => void
  /** Called after a save is confirmed and committed. */
  onApplied?: (snapshot: RequestDetailResult) => void
  /** Relative storage profile query, exactly as every other request uses it. */
  storageQuery: () => Record<string, string | undefined>
  /** Host notification for a confirmed save. */
  onSuccess?: () => void
}

export interface SavedPlanEditorSession {
  readonly formOpen: Ref<boolean>
  readonly error: Ref<string>
  readonly resultUnknown: Ref<boolean>
  readonly inFlight: Ref<boolean>
  toggle: () => void
  submit: (patch: PreviewPatch) => void
  retry: () => Promise<void>
  recover: () => Promise<void>
  /** Test/host hook: forget a locked intent after a host-side reset. */
  reset: () => void
}

/** True when a patch is visible in the authoritative snapshot. */
export function savedPlanPatchApplied(
  patch: PreviewPatch,
  snapshot: RequestDetailResult,
): boolean {
  const config = snapshot.request?.confirmable_config
  if (!config) return false
  if (patch.selected_subtitle_group !== undefined
    && patch.selected_subtitle_group !== config.selected_subtitle_group) return false
  if (patch.expected_folder_name !== undefined
    && patch.expected_folder_name !== config.expected_folder_name) return false
  if (patch.filter_rule) {
    const rule = config.filter_rule
    if (!rule) return false
    for (const key of ['must_contain', 'must_not_contain', 'use_regex', 'case_sensitive'] as const) {
      if (patch.filter_rule[key] !== undefined && patch.filter_rule[key] !== rule[key]) return false
    }
  }
  return true
}

/** True when a transport failure leaves the write's outcome genuinely unknown. */
export function isUncertainSavedPlanWrite(error: unknown): boolean {
  const apiError = toApiError(error)
  const raw = error && typeof error === 'object' ? error as {
    status?: unknown
    network?: unknown
    cancelled?: unknown
    nonJson?: unknown
  } : {}
  return apiError.network || apiError.cancelled || apiError.nonJson
    || apiError.status >= 500
    || raw.network === true || raw.cancelled === true || raw.nonJson === true
    || (typeof raw.status === 'number' && raw.status >= 500)
    || apiError.type === 'network_error' || apiError.type === 'request_cancelled'
    || apiError.type === 'server_error' || apiError.type === 'upstream_timeout'
    || apiError.type === 'upstream_unavailable'
}

type ModifyCheck =
  | { state: 'applied' | 'not_applied'; snapshot: RequestDetailResult }
  | { state: 'unknown' }

export function useSavedPlanEditor(options: SavedPlanEditorOptions): SavedPlanEditorSession {
  const formOpen = ref(false)
  const error = ref('')
  const resultUnknown = ref(false)
  const inFlight = ref(false)
  let lastPatch: PreviewPatch | null = null

  function reset(): void {
    formOpen.value = false
    error.value = ''
    resultUnknown.value = false
    lastPatch = null
  }

  function toggle(): void {
    if (inFlight.value || resultUnknown.value) return
    formOpen.value = !formOpen.value
    if (formOpen.value) error.value = ''
  }

  function submit(patch: PreviewPatch): void {
    if (resultUnknown.value || inFlight.value) return
    if (!Object.keys(patch).length) {
      error.value = '请至少修改或清空一个字段。'
      return
    }
    error.value = ''
    resultUnknown.value = false
    lastPatch = patch
    void perform(patch)
  }

  async function recheck(patch: PreviewPatch): Promise<ModifyCheck> {
    const fetched = await options.fetchSnapshot()
    if (!fetched.result) return { state: 'unknown' }
    return {
      state: savedPlanPatchApplied(patch, fetched.result) ? 'applied' : 'not_applied',
      snapshot: fetched.result,
    }
  }

  function commitSuccess(snapshot: RequestDetailResult): void {
    options.commitSnapshot(snapshot)
    resultUnknown.value = false
    formOpen.value = false
    lastPatch = null
    options.onSuccess?.()
    options.onApplied?.(snapshot)
  }

  async function recover(): Promise<void> {
    if (inFlight.value) return
    inFlight.value = true
    try {
      const fetched = await options.fetchSnapshot()
      if (fetched.result) {
        options.commitSnapshot(fetched.result)
        error.value = ''
        resultUnknown.value = false
      } else {
        error.value = '结果暂无法确认，请重新确认结果。'
        resultUnknown.value = true
      }
    } finally {
      inFlight.value = false
    }
  }

  async function perform(patch: PreviewPatch): Promise<void> {
    inFlight.value = true
    error.value = ''
    try {
      const body: ModifyRequestBody = { patch, storage_dir: options.storageQuery().storage_dir ?? null }
      await api.post<ModifyResult>('/api/v1/requests/{request_id}/modify', {
        path: { request_id: options.requestId() },
        query: options.storageQuery(),
        body,
      })
      const fetched = await options.fetchSnapshot()
      if (!fetched.result) {
        error.value = '结果暂无法确认，请重新确认结果。'
        resultUnknown.value = true
        return
      }
      if (!savedPlanPatchApplied(patch, fetched.result)) {
        resultUnknown.value = false
        error.value = '修改未生效，请重试。'
        return
      }
      commitSuccess(fetched.result)
    } catch (failure) {
      if (isUncertainSavedPlanWrite(failure)) {
        const checked = await recheck(patch)
        if (checked.state === 'applied') commitSuccess(checked.snapshot)
        else if (checked.state === 'not_applied') {
          resultUnknown.value = false
          error.value = '修改未生效，请重试。'
        } else {
          resultUnknown.value = true
          error.value = '结果暂无法确认，请重新确认结果。'
        }
      } else {
        resultUnknown.value = false
        error.value = '修改失败，请稍后重试。'
      }
    } finally {
      inFlight.value = false
    }
  }

  async function retry(): Promise<void> {
    if (inFlight.value) return
    const patch = lastPatch
    if (!patch) return
    if (resultUnknown.value) {
      inFlight.value = true
      try {
        const checked = await recheck(patch)
        if (checked.state === 'applied') commitSuccess(checked.snapshot)
        else if (checked.state === 'not_applied') {
          resultUnknown.value = false
          error.value = '修改未生效，请重试。'
        } else {
          error.value = '结果暂无法确认，请重新确认结果。'
        }
      } finally {
        inFlight.value = false
      }
      return
    }
    void perform(patch)
  }

  return { formOpen, error, resultUnknown, inFlight, toggle, submit, retry, recover, reset }
}
