/**
 * Draft edit scheduling (US-344 / WP-41-C).
 *
 * The server owns the draft. This composable owns only *when* an edit is
 * turned into a `preview-modify` call on top of `useDraftSession`:
 *
 *   - `selected_subtitle_group` is authoritative as soon as it is picked, so it
 *     is sent immediately;
 *   - `must_contain` / `must_not_contain` / `use_regex` / `case_sensitive` are
 *     one filter rule and are debounced for 1.5s from the last input;
 *   - `expected_folder_name` never affects resource filtering and is never sent
 *     on its own; only an explicit flush ("保存修改") submits it, together with
 *     any filter input whose debounce window has not expired yet.
 *
 * `useDraftSession` still owns the compare-and-swap: exactly one request may
 * hold the current `base_revision`. Intent arriving while a request is in
 * flight is kept as the latest desired value and sent after that request
 * settles, never as a second CAS reusing the same revision. The scheduler never
 * sends a full Request snapshot and never persists anything.
 */
import { computed, ref, watch, type ComputedRef, type Ref } from 'vue'

import type { DraftModifyResult, DraftPatch, DraftSession } from '@/app/composables/useDraftSession'
import { collectPreviewEditPatch, previewEditStateFrom, type PreviewEditState } from '@/features/workbench/candidateSearch'

/** The filter rule is one unit: 1.5s after the last input or toggle. */
export const DRAFT_FILTER_DEBOUNCE_MS = 1500

export interface DraftEditSchedulerOptions {
  session: DraftSession
  /** Relative storage profile; resolved at send time, never cached. */
  storageDir?: () => string | null
  debounceMs?: number
  /** Called just before an automatic or flushed CAS leaves the browser. */
  onSending?: () => void
  onApplied?: (result: DraftModifyResult) => void
  onInvalid?: () => void
  onFailed?: () => void
}

export interface DraftEditScheduler {
  /** Subtitle group the user picked that the server has not confirmed yet. */
  pendingGroup: Ref<string | null>
  /** Filter rule the user typed that the server has not confirmed yet. */
  pendingFilter: Ref<PreviewEditState | null>
  /** Folder name the user typed; only an explicit flush submits it. */
  pendingFolder: Ref<string | null>
  /** A filter debounce window is open. */
  waiting: Ref<boolean>
  /** An intent is waiting for the in-flight request to settle. */
  queued: Ref<boolean>
  groupPending: ComputedRef<boolean>
  filterPending: ComputedRef<boolean>
  folderPending: ComputedRef<boolean>
  /** Any edit still has to reach the server (waiting, queued or in flight). */
  hasPendingIntent: ComputedRef<boolean>
  /** "保存修改" has something to submit right now and no request is in flight. */
  canFlush: ComputedRef<boolean>
  setSubtitleGroup: (value: string) => void
  setFilter: (state: PreviewEditState) => void
  setFolderName: (value: string) => void
  /** Submit the pending filter and folder immediately (保存修改). */
  flush: () => Promise<void>
  /** Retry after a recoverable failure, without losing the unapplied intent. */
  retry: () => Promise<void>
  /** Return to the last server-consistent result and drop local intent. */
  restore: () => void
  /** Cancel the debounce window without sending (item switch, leave). */
  cancelTimer: () => void
  /** Drop every local intent without touching the session. */
  dropPending: () => void
  dispose: () => void
}

const EMPTY_STATE: PreviewEditState = {
  selectedSubtitleGroup: '',
  mustContain: '',
  mustNotContain: '',
  useRegex: false,
  caseSensitive: false,
  expectedFolderName: '',
}

/** Which not-yet-due parts a single CAS may submit. */
interface PumpScope {
  filter: boolean
  folder: boolean
}

export function useDraftEditScheduler(options: DraftEditSchedulerOptions): DraftEditScheduler {
  const { session } = options
  const debounceMs = options.debounceMs ?? DRAFT_FILTER_DEBOUNCE_MS

  const pendingGroup = ref<string | null>(null)
  const pendingFilter = ref<PreviewEditState | null>(null)
  const pendingFolder = ref<string | null>(null)
  const waiting = ref(false)
  const queued = ref(false)

  let timer: ReturnType<typeof setTimeout> | null = null
  let disposed = false
  // Which not-yet-due intent the next CAS is allowed to carry. A subtitle
  // change must never smuggle a filter rule that is still inside its debounce
  // window; only an expired window or an explicit flush may submit one.
  let queuedScope: PumpScope = { filter: false, folder: false }

  function serverState(): PreviewEditState {
    const snapshot = session.request.value
    return snapshot ? previewEditStateFrom(snapshot) : EMPTY_STATE
  }

  function groupIsUnsent(): boolean {
    const value = pendingGroup.value
    return value !== null && value !== serverState().selectedSubtitleGroup
  }

  function filterIsUnsent(): boolean {
    const value = pendingFilter.value
    if (!value) return false
    return Object.keys(collectPreviewEditPatch(serverState(), value)).some((key) => key === 'filter_rule')
  }

  function folderIsUnsent(): boolean {
    const value = pendingFolder.value
    return value !== null && value !== serverState().expectedFolderName
  }

  const groupPending = computed(groupIsUnsent)
  const filterPending = computed(filterIsUnsent)
  const folderPending = computed(folderIsUnsent)
  const hasPendingIntent = computed(
    () => waiting.value || queued.value || session.applying.value || groupPending.value || filterPending.value || folderPending.value,
  )
  const canFlush = computed(
    () => !session.applying.value && !session.invalid.value && (groupPending.value || filterPending.value || folderPending.value),
  )

  function cancelTimer(): void {
    if (timer !== null) {
      clearTimeout(timer)
      timer = null
    }
    waiting.value = false
  }

  function dropPending(): void {
    pendingGroup.value = null
    pendingFilter.value = null
    pendingFolder.value = null
    queued.value = false
    queuedScope = { filter: false, folder: false }
  }

  /** Build the patch for the still-unsent intent the scope allows. */
  function buildPatch(scope: PumpScope): DraftPatch | null {
    const base = serverState()
    const filter = scope.filter ? pendingFilter.value : null
    const desired: PreviewEditState = {
      selectedSubtitleGroup: pendingGroup.value ?? base.selectedSubtitleGroup,
      mustContain: filter?.mustContain ?? base.mustContain,
      mustNotContain: filter?.mustNotContain ?? base.mustNotContain,
      useRegex: filter?.useRegex ?? base.useRegex,
      caseSensitive: filter?.caseSensitive ?? base.caseSensitive,
      expectedFolderName: scope.folder ? pendingFolder.value ?? base.expectedFolderName : base.expectedFolderName,
    }
    const patch = collectPreviewEditPatch(base, desired)
    return Object.keys(patch).length ? patch : null
  }

  /** Clear the slots the server has just confirmed; newer intent survives. */
  function reconcile(): void {
    const base = serverState()
    if (pendingGroup.value !== null && pendingGroup.value === base.selectedSubtitleGroup) pendingGroup.value = null
    const filter = pendingFilter.value
    if (
      filter &&
      filter.mustContain === base.mustContain &&
      filter.mustNotContain === base.mustNotContain &&
      filter.useRegex === base.useRegex &&
      filter.caseSensitive === base.caseSensitive
    ) {
      pendingFilter.value = null
    }
    if (pendingFolder.value !== null && pendingFolder.value === base.expectedFolderName) pendingFolder.value = null
  }

  async function pump(scope: PumpScope): Promise<void> {
    if (disposed || session.invalid.value) return
    if (session.applying.value) {
      // A CAS already owns the current revision: keep only the latest intent.
      queued.value = true
      queuedScope = { filter: queuedScope.filter || scope.filter, folder: queuedScope.folder || scope.folder }
      return
    }
    const patch = buildPatch(scope)
    if (!patch) {
      queued.value = false
      queuedScope = { filter: false, folder: false }
      return
    }
    options.onSending?.()
    const result = await session.apply(patch, options.storageDir ? options.storageDir() : undefined)
    if (disposed) return
    if (!result) {
      queued.value = false
      queuedScope = { filter: false, folder: false }
      if (session.invalid.value) {
        dropPending()
        cancelTimer()
        options.onInvalid?.()
      } else {
        // Keep the intent so the host can offer retry or restore.
        options.onFailed?.()
      }
      return
    }
    reconcile()
    options.onApplied?.(result)
    if (queued.value) {
      const nextScope = queuedScope
      queued.value = false
      queuedScope = { filter: false, folder: false }
      void pump(nextScope)
    }
  }

  function startTimer(): void {
    if (timer !== null) clearTimeout(timer)
    waiting.value = true
    timer = setTimeout(() => {
      timer = null
      waiting.value = false
      void pump({ filter: true, folder: false })
    }, debounceMs)
  }

  const stopInvalidWatch = watch(
    () => session.invalid.value,
    (invalid) => {
      if (!invalid) return
      cancelTimer()
      dropPending()
    },
    { immediate: false },
  )

  function setSubtitleGroup(value: string): void {
    if (disposed) return
    pendingGroup.value = value
    // Immediate, and strictly the subtitle group: a filter rule still inside
    // its debounce window must not ride along.
    void pump({ filter: false, folder: false })
  }

  function setFilter(state: PreviewEditState): void {
    if (disposed) return
    pendingFilter.value = {
      selectedSubtitleGroup: state.selectedSubtitleGroup,
      mustContain: state.mustContain,
      mustNotContain: state.mustNotContain,
      useRegex: state.useRegex,
      caseSensitive: state.caseSensitive,
      expectedFolderName: state.expectedFolderName,
    }
    startTimer()
  }

  function setFolderName(value: string): void {
    if (disposed) return
    // Deliberately no send and no timer: only an explicit flush submits it.
    pendingFolder.value = value
  }

  async function flush(): Promise<void> {
    cancelTimer()
    await pump({ filter: true, folder: true })
  }

  async function retry(): Promise<void> {
    if (disposed || session.invalid.value) return
    cancelTimer()
    await pump({ filter: true, folder: true })
  }

  function restore(): void {
    cancelTimer()
    dropPending()
    session.reset()
  }

  function dispose(): void {
    disposed = true
    cancelTimer()
    dropPending()
    stopInvalidWatch()
  }

  return {
    pendingGroup,
    pendingFilter,
    pendingFolder,
    waiting,
    queued,
    groupPending,
    filterPending,
    folderPending,
    hasPendingIntent,
    canFlush,
    setSubtitleGroup,
    setFilter,
    setFolderName,
    flush,
    retry,
    restore,
    cancelTimer,
    dropPending,
    dispose,
  }
}
