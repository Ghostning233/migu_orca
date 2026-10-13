/**
 * 保存确认结果 → 服务端条目行的展示投影（#160 AC1 / #164 / #195）。
 *
 * 「服务端快照」与「客户端生命周期」是两个概念：条目行的 `status` 既有服务端
 * 词汇（FOUND / EMPTY / FAILED），也有生命周期词汇（CONFIRMED /
 * SAVED_PENDING_* / RESPONSE_UNKNOWN）。视图只装配事实与执行副作用，**这一层
 * 是唯一决定生命周期词汇的地方**，因此同一条结局不会在组件里再写一遍。
 *
 * #195：本模块是 `items[].status` 的**唯一写点**；客户端相位
 * （`useBatchReviewJourney` 的 `BatchItemPhase`）是生命周期权威，两者消费同一份
 * 错误类型判定（`batchSaveErrorIsReplayed` / `batchSaveErrorInvalidatesDraft`）。
 * 映射表（错误类型 × 相位前提 → 展示状态 / 恢复动作）钉在
 * `batchDisplayStateMapping.test.ts`。
 *
 * 这些函数是纯数据变换：不发请求、不读响应式状态、不决定焦点与文案。
 */
import type { BatchSaveResultItem } from '@/app/composables/useBatchReviewJourney'
import {
  batchSaveConfirmRecoveryAllowed,
  batchSaveConfirmSucceeded,
  batchSaveErrorInvalidatesDraft,
  batchSaveErrorIsReplayed,
  BATCH_STATUS_LOCATE_PENDING,
  type BatchItem,
} from '@/features/workbench/batchWorkbench'

/** 一次保存确认给单个条目带来的生命周期结局。 */
export type BatchOutcomeKind =
  | 'succeeded'
  | 'locate_pending'
  | 'confirm_pending'
  | 'draft_invalidated'
  | 'draft_retryable'

export interface BatchOutcomeProjection {
  readonly row: BatchItem
  readonly kind: BatchOutcomeKind
  /** 该结局是否让本地草案资源失效（交给模块的唯一失效命令）。 */
  readonly invalidatesResources: boolean
  /** 该结局是否撤销条目的勾选意图。 */
  readonly clearsSelection: boolean
}

/**
 * 一条保存确认结果 → 展示行 + 要执行的副作用标记。
 *
 * 分支顺序与原实现逐条一致：成功 → 草案已被保存（重放）→ 允许恢复确认 →
 * 草案失效 → 其余可重试失败。
 */
/** 草案已被保存、等待定位的冻结行（两个入口共用）。 */
function locatePendingRow(row: BatchItem): BatchItem {
  return {
    ...row,
    status: BATCH_STATUS_LOCATE_PENDING,
    preview_request: null,
    draft_id: null,
    draft_revision: null,
    request_id: null,
  }
}

/**
 * 草案已失效：回到真实合集选择（有候选 FOUND，否则 EMPTY）。
 *
 * #195：保存结果里的 `draft_invalidated` 与视图的会话失效（`onDraftExpired`）
 * 共用这一个投影，视图不再手写同一组字段。
 */
export function projectDraftInvalidated(row: BatchItem): BatchItem {
  return {
    ...row,
    status: (row.candidates?.length ?? 0) > 0 ? 'FOUND' : 'EMPTY',
    preview_request: null,
    draft_id: null,
    draft_revision: null,
  }
}

export function projectSaveConfirmOutcome(
  row: BatchItem,
  resultItem: BatchSaveResultItem,
): BatchOutcomeProjection {
  if (batchSaveConfirmSucceeded(resultItem)) {
    return {
      kind: 'succeeded',
      row: {
        ...row,
        status: 'CONFIRMED',
        draft_id: null,
        draft_revision: null,
        request_id: resultItem.request_id,
        tracking_id: resultItem.tracking_id,
      },
      invalidatesResources: true,
      clearsSelection: true,
    }
  }
  if (batchSaveErrorIsReplayed(resultItem.error_type)) {
    // Issue 130：草案已经被保存；冻结该条目等待核验，不提供重新生成或新键重试。
    return {
      kind: 'locate_pending',
      row: locatePendingRow(row),
      invalidatesResources: true,
      clearsSelection: true,
    }
  }
  if (batchSaveConfirmRecoveryAllowed(resultItem)) {
    return {
      kind: 'confirm_pending',
      row: {
        ...row,
        status: 'SAVED_PENDING_CONFIRM',
        draft_id: null,
        draft_revision: null,
        request_id: resultItem.request_id,
      },
      invalidatesResources: true,
      clearsSelection: false,
    }
  }
  if (batchSaveErrorInvalidatesDraft(resultItem.error_type)) {
    return {
      kind: 'draft_invalidated',
      row: projectDraftInvalidated(row),
      invalidatesResources: true,
      clearsSelection: true,
    }
  }
  return {
    kind: 'draft_retryable',
    row: { ...row, status: 'DRAFT' },
    invalidatesResources: false,
    clearsSelection: false,
  }
}

/** 确定失败（整批路径）：安全错误类型决定回到哪一种可处理状态。 */
export function projectDeterministicSaveFailure(row: BatchItem, safeType: string): BatchItem {
  if (batchSaveErrorIsReplayed(safeType)) {
    // Issue 130：单条重试撞上已保存草案：同样冻结为待定位，不引导重复保存。
    return locatePendingRow(row)
  }
  if (batchSaveErrorInvalidatesDraft(safeType)) return projectDraftInvalidated(row)
  return { ...row, status: 'DRAFT' }
}

/** 响应未知：条目冻结为待核验。 */
export function projectResponseUnknown(row: BatchItem): BatchItem {
  return { ...row, status: 'RESPONSE_UNKNOWN' }
}

/** 由用户所选合集生成了草案。 */
export function projectDraftGenerated(
  row: BatchItem,
  changes: Pick<BatchItem, 'preview_request' | 'draft_id' | 'draft_revision'>,
): BatchItem {
  return {
    ...row,
    status: 'DRAFT',
    preview_request: changes.preview_request,
    draft_id: changes.draft_id,
    draft_revision: changes.draft_revision,
  }
}

/** 只读回查定位到真实追番记录。 */
export function projectTrackingLocated(row: BatchItem, trackingId: string): BatchItem {
  return { ...row, status: 'CONFIRMED', tracking_id: trackingId }
}

/** 确认成功：从此只允许重试定位。 */
export function projectAcceptSucceeded(row: BatchItem, requestId: string): BatchItem {
  return { ...row, status: 'CONFIRMED', request_id: requestId, tracking_id: null }
}

/** 方案已保存但确认未完成：冻结为待确认，等用户显式重试。 */
export function projectSavedConfirmPending(row: BatchItem, requestId: string): BatchItem {
  return {
    ...row,
    status: 'SAVED_PENDING_CONFIRM',
    draft_id: null,
    draft_revision: null,
    request_id: requestId,
  }
}

/** 重新定位仍未命中：从待核验退回「已保存待确认」。 */
export function projectTrackingNotFound(row: BatchItem): BatchItem {
  return { ...row, status: 'SAVED_PENDING_CONFIRM' }
}
