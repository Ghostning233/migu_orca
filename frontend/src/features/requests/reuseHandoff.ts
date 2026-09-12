/**
 * One-shot, in-memory handoff for the local "复制再用" journey (US-300).
 *
 * This module deliberately stores no Request identity, snapshot, URL, resource
 * data, history, tracking state, capability or idempotency key. A refresh (or
 * a new document) naturally drops the module state.
 */
import type { operations } from '@/api/generated/api'

export type SafeInfo = NonNullable<
  operations['getRequestSafeInfo']['responses']['200']['content']['application/json']['result']
>['safe_info']

export interface ReuseHandoff {
  readonly title: string
  readonly mikanBangumiId: string
  readonly suggestion: ReuseSuggestion
}

export interface ReuseSuggestion {
  readonly selectedSubtitleGroup: string
  readonly filterRule: {
    readonly mustContain: string
    readonly mustNotContain: string
    readonly useRegex: boolean
    readonly caseSensitive: boolean
  }
  readonly expectedFolderName: string
}

let pending: ReuseHandoff | null = null

function text(value: string | null | undefined): string {
  return typeof value === 'string' ? value.trim() : ''
}

/** Build only the public, user-editable fields allowed in a reuse handoff. */
export function buildReuseHandoff(safeInfo: SafeInfo): ReuseHandoff | null {
  const title = text(safeInfo.title) || text(safeInfo.raw_title)
  const mikanBangumiId = text(safeInfo.mikan_collection?.bangumi_id)
  if (!title || !mikanBangumiId || !/^[A-Za-z0-9][A-Za-z0-9_.-]*$/.test(mikanBangumiId)) {
    return null
  }
  const filter = safeInfo.filter_rule
  return {
    title,
    mikanBangumiId,
    suggestion: {
      selectedSubtitleGroup: text(safeInfo.selected_subtitle_group),
      filterRule: {
        mustContain: text(filter?.must_contain),
        mustNotContain: text(filter?.must_not_contain),
        useRegex: filter?.use_regex === true,
        caseSensitive: filter?.case_sensitive === true,
      },
      expectedFolderName: text(safeInfo.folder_name),
    },
  }
}

/** Replace any previous handoff; it is consumed at most once. */
export function publishReuseHandoff(handoff: ReuseHandoff): void {
  pending = handoff
}

/** Consume and immediately clear the pending handoff. */
export function consumeReuseHandoff(): ReuseHandoff | null {
  const handoff = pending
  pending = null
  return handoff
}

/** Test-only cleanup; this remains memory-only and never touches browser storage. */
export function clearReuseHandoff(): void {
  pending = null
}
