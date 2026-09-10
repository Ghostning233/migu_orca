/**
 * Server-authoritative draft session (US-266).
 *
 * This composable is the shared in-memory boundary for an unsaved Request.
 * It owns the last successful public snapshot and the opaque capability that
 * identifies it on the next preview-modify call. Neither is persisted. Save
 * and confirm endpoints deliberately do not belong here; compatibility hosts
 * keep those flows outside the shared review core.
 */
import { computed, ref, type Ref } from 'vue'

import { api, toApiError, type ApiError } from '@/api/client'
import type { operations } from '@/api/generated/api'

type CreateRequestResult = NonNullable<
  operations['createRequest']['responses']['200']['content']['application/json']['result']
>
type PreviewModifyBody = NonNullable<operations['previewModifyRequest']['requestBody']>['content']['application/json']
type PreviewModifyResult = NonNullable<
  operations['previewModifyRequest']['responses']['200']['content']['application/json']['result']
>

/** Public snapshot type from the generated create-request contract. */
export type DraftSnapshot = CreateRequestResult['request']
/** Preview-modify patch type from the generated contract. */
export type DraftPatch = PreviewModifyBody['patch']
export type DraftModifyResult = PreviewModifyResult

export interface DraftSessionOptions {
  request: DraftSnapshot
  draftId: string
  draftRevision?: number
}

export interface DraftSession {
  request: Ref<DraftSnapshot | null>
  draftId: Ref<string | null>
  draftRevision: Ref<number | null>
  dirty: Ref<boolean>
  applying: Ref<boolean>
  error: Ref<ApiError | null>
  requestSequence: Ref<number>
  invalid: Ref<boolean>
  canRetry: Readonly<Ref<boolean>>
  setDirty: (dirty: boolean) => void
  apply: (patch: DraftPatch, storageDir?: string) => Promise<DraftModifyResult | null>
  retry: () => Promise<DraftModifyResult | null>
  reset: () => void
  invalidate: () => void
}

const INVALID_DRAFT_ERRORS = new Set([
  'draft_revision_conflict',
  'draft_expired',
  'draft_evicted',
  'draft_replayed',
])

/**
 * Create a component-local draft session. Calling this outside a component is
 * also supported, which keeps the state machine straightforward to unit test.
 */
export function useDraftSession(options: DraftSessionOptions): DraftSession {
  const request = ref<DraftSnapshot | null>(options.request)
  const draftId = ref<string | null>(options.draftId)
  const draftRevision = ref<number | null>(options.draftRevision ?? 1)
  const dirty = ref(false)
  const applying = ref(false)
  const error = ref<ApiError | null>(null)
  const requestSequence = ref(0)
  const invalid = ref(false)
  const retryable = ref(false)

  // The last attempted patch is request-scoped memory, used only by retry.
  let lastPatch: DraftPatch | null = null
  let lastStorageDir: string | undefined

  const canRetry = computed(() => retryable.value && !invalid.value && !applying.value)

  function setDirty(value: boolean): void {
    if (!invalid.value) dirty.value = value
  }

  function invalidate(): void {
    // Bump the sequence before clearing state so an in-flight response cannot
    // resurrect an expired or replayed capability.
    requestSequence.value += 1
    request.value = null
    draftId.value = null
    draftRevision.value = null
    dirty.value = false
    applying.value = false
    invalid.value = true
    retryable.value = false
    error.value = null
    lastPatch = null
    lastStorageDir = undefined
  }

  async function apply(patch: DraftPatch, storageDir?: string): Promise<DraftModifyResult | null> {
    // A second request cannot safely reuse the current base_revision. Reject
    // it while the first request owns the session instead of issuing two CAS
    // writes with the same revision.
    if (applying.value || invalid.value || !draftId.value || draftRevision.value === null) return null

    const sequence = ++requestSequence.value
    lastPatch = patch
    lastStorageDir = storageDir
    dirty.value = true
    error.value = null
    applying.value = true
    try {
      const body: PreviewModifyBody = {
        draft_id: draftId.value,
        base_revision: draftRevision.value,
        patch,
        ...(storageDir === undefined ? {} : { storage_dir: storageDir }),
      }
      const result = await api.post<DraftModifyResult>('/api/v1/requests/preview-modify', { body })

      // Only the newest started request may commit. This makes an older
      // response harmless even if the transport resolves requests out of order.
      if (sequence !== requestSequence.value || invalid.value) return null
      if (result.request) request.value = result.request
      if (result.draft_id) draftId.value = result.draft_id
      if (typeof result.draft_revision === 'number') draftRevision.value = result.draft_revision
      dirty.value = false
      error.value = null
      retryable.value = false
      lastPatch = null
      lastStorageDir = undefined
      return result
    } catch (cause) {
      if (sequence !== requestSequence.value || invalid.value) return null
      const safeError = toApiError(cause)
      if (INVALID_DRAFT_ERRORS.has(safeError.type)) {
        invalidate()
      } else {
        // Keep the last successful snapshot and the uncommitted form intent so
        // the host can offer retry or reset without losing the user's edits.
        error.value = safeError
        retryable.value = true
      }
      return null
    } finally {
      if (sequence === requestSequence.value) applying.value = false
    }
  }

  function reset(): void {
    // Reset means recover the editing surface to the last consistent result;
    // it does not regenerate or silently replay an invalid draft. While a
    // preview-modify owns the revision lock, reset is deliberately a no-op:
    // cancelling the local lock would let another apply reuse its base.
    if (invalid.value || applying.value) return
    requestSequence.value += 1
    dirty.value = false
    applying.value = false
    error.value = null
    retryable.value = false
    lastPatch = null
    lastStorageDir = undefined
  }

  function retry(): Promise<DraftModifyResult | null> {
    if (!lastPatch || invalid.value) return Promise.resolve(null)
    return apply(lastPatch, lastStorageDir)
  }

  return {
    request,
    draftId,
    draftRevision,
    dirty,
    applying,
    error,
    requestSequence,
    invalid,
    canRetry,
    setDirty,
    apply,
    retry,
    reset,
    invalidate,
  }
}
