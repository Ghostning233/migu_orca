/**
 * #195：批量审核「显示状态」映射表的 characterization 断言。
 *
 * 冻结结论：**机制取自选项 a 的相位扩展，权威口径取自选项 b**。
 *
 * - **生命周期相位**（选项 a 的机制）：`useBatchReviewJourney` 的 `BatchItemPhase`
 *   **新增 `saved_pending_locate`**，由错误类型判定一次
 *   （`batchSaveErrorIsReplayed` / `batchSaveErrorInvalidatesDraft`）。
 * - **展示状态**（选项 b 的口径）：`batchItemProjection` 是**批量路径内**
 *   `items[].status` 的唯一写点；展示词汇（token / 中文文案 / 语气 / 下一步 /
 *   恢复动作）在 `batchWorkbench` 的批量路径内只定义一次。
 * - 相位只保留生命周期，不再并行表达展示状态：`draft_replayed` 不再伪装成
 *   `candidates` / `blocked`（与「已保存，待定位」互相矛盾的旧行为）。
 * - **范围限定**：以上「唯一」均限定在**批量路径内**。单番路径
 *   （`SingleAnimeReviewPanel.vue`、`useSingleAnimeJourney.ts`、`useDraftSession.ts`）
 *   仍各自内联同一份错误类型分类，且 `SingleAnimeReviewPanel.vue` 把
 *   `draft_replayed` 判为「草案失效→重新选合集」，与批量路径的「已保存，待定位」
 *   相反；单番收口不在 #195 范围内。
 *
 * 映射表（错误类型 × 前提 → 展示状态 / 相位 / 恢复动作 / 芯片 / 语气 / 需处理）：
 *
 * | 保存结果 / 错误类型 | 前提 | 现展示状态 | 现相位 | 目标展示状态 | 目标相位 | 恢复动作 | 差异 |
 * | --- | --- | --- | --- | --- | --- | --- | --- |
 * | CONFIRMED | 有/无候选 | CONFIRMED | confirmed | CONFIRMED | confirmed | NONE（已定位） | 无 |
 * | save_confirm_failed + request_id | 有/无候选 | SAVED_PENDING_CONFIRM | saved_pending_confirm | 同 | 同 | RETRY_CONFIRM | 无 |
 * | draft_replayed | 有候选 | SAVED_PENDING_LOCATE | candidates | SAVED_PENDING_LOCATE | **saved_pending_locate** | LOCATE_SAVED | 相位不再暗示「重新选合集」 |
 * | draft_replayed | 无候选 | SAVED_PENDING_LOCATE | blocked | SAVED_PENDING_LOCATE | **saved_pending_locate** | LOCATE_SAVED | 同上 |
 * | draft_expired / draft_evicted / draft_revision_conflict | 有候选 | FOUND | candidates | 同 | 同 | REGENERATE_DRAFT | 无 |
 * | draft_expired / draft_evicted / draft_revision_conflict | 无候选 | EMPTY | blocked | 同 | 同 | REGENERATE_DRAFT | 无 |
 * | draft_reserved / idempotency_conflict / 未知类型 | 有/无候选 | DRAFT | draft | 同 | 同 | RETRY_SAVE | 无 |
 * | 响应未知（网络/非 JSON/5xx） | 有/无候选 | RESPONSE_UNKNOWN | response_unknown | 同 | 同 | VERIFY_RESULT | 无 |
 *
 * 用户可见结果零变化：`draft_replayed` 在两种前提下都是同一条冻结展示状态
 * （不受候选是否存在影响），芯片、语气、下一步与恢复动作逐字保持。
 */
import { describe, expect, it } from 'vitest'

import {
  batchSaveErrorInvalidatesDraft,
  batchSaveErrorIsReplayed,
  createBatchReviewState,
  reduceBatchReview,
  type BatchItemPhase,
  type BatchParseItem,
  type BatchReviewState,
  type BatchSaveResultItem,
  type ParseBatchTitlesResult,
} from '@/app/composables/useBatchReviewJourney'
import {
  batchCardNextStep,
  batchItemNeedsProcessing,
  batchSaveRecoveryAction,
  BATCH_STATUS_LOCATE_PENDING,
  batchStatusLabel,
  batchStatusTone,
  type BatchItem,
  type BatchSaveRecoveryAction,
} from '@/features/workbench/batchWorkbench'
import {
  projectDeterministicSaveFailure,
  projectResponseUnknown,
  projectSaveConfirmOutcome,
} from '@/features/workbench/batchItemProjection'

/** 一条保存结果对应的展示行前提。 */
function row(withCandidates: boolean): BatchItem {
  return {
    item_id: 'item-1',
    raw_title: '萌王S4',
    status: 'DRAFT',
    candidates: withCandidates ? [{ bangumi_id: '42' }] : [],
    preview_request: { request_id: 'req-1' },
    draft_id: 'draft-1',
    draft_revision: 1,
    request_id: null,
    tracking_id: null,
  } as unknown as BatchItem
}

function parsedItem(withCandidates: boolean): BatchParseItem {
  return {
    item_id: 'item-1',
    raw_title: '萌王S4',
    status: 'DRAFT',
    candidates: withCandidates ? [{ bangumi_id: '42' }] : [],
    preview_request: { request_id: 'req-1' },
    draft_id: 'draft-1',
    draft_revision: 1,
  } as unknown as BatchParseItem
}

/** 解析 → 开始保存 的公共前缀。 */
function stateAfterBeginSave(withCandidates: boolean): BatchReviewState {
  const result = {
    batch_id: 'batch-1',
    raw_input: '萌王S4',
    items: [parsedItem(withCandidates)],
  } as ParseBatchTitlesResult
  const state = reduceBatchReview(createBatchReviewState(), { type: 'parse_succeeded', result })
  return reduceBatchReview(state, { type: 'begin_save', itemIds: ['item-1'] })
}

/** 成功路径的状态：解析 → 开始保存 → 收到 CONFIRMED 结果。 */
function stateAfterSaveSucceeded(withCandidates: boolean): BatchReviewState {
  return reduceBatchReview(stateAfterBeginSave(withCandidates), {
    type: 'save_succeeded',
    itemId: 'item-1',
    result: {
      item_id: 'item-1',
      outcome: 'CONFIRMED',
      request_id: 'req-1',
      status: 'CONFIRMED',
      error_type: null,
      error_message: null,
      tracking_id: 'tracking-1',
      tracking_ready: true,
    } as unknown as BatchSaveResultItem,
  })
}

/** 成功路径的相位：真实 reducer 驱动，而不是与本表字面量自比。 */
function phaseAfterSaveSucceeded(withCandidates: boolean): BatchItemPhase {
  return stateAfterSaveSucceeded(withCandidates).items['item-1']!.phase
}

/** 保存失败后的完整状态，供相位之外的断言（例如勾选意图）复用。 */
function stateAfterSaveFailed(
  withCandidates: boolean,
  error: Record<string, unknown>,
  options: { frozenBefore?: boolean } = {},
): BatchReviewState {
  let state = stateAfterBeginSave(withCandidates)
  // 冻结前提：上一次保存响应未知（条目已被保存过或状态未知），本次是同键重放。
  if (options.frozenBefore) {
    state = reduceBatchReview(state, { type: 'save_response_unknown', itemIds: ['item-1'] })
  }
  return reduceBatchReview(state, { type: 'save_failed', itemId: 'item-1', error })
}

/** 同一相位判定入口：解析 → 开始保存 →（可选）先落入冻结态 → 收到这条保存失败。 */
function phaseAfterSaveFailed(
  withCandidates: boolean,
  error: Record<string, unknown>,
  options: { frozenBefore?: boolean } = {},
): BatchItemPhase {
  return stateAfterSaveFailed(withCandidates, error, options).items['item-1']!.phase
}

interface MappingRow {
  name: string
  withCandidates: boolean
  errorType: string | null
  outcome: 'CONFIRMED' | 'FAILED'
  requestId: string | null
  status: string
  phase: BatchItemPhase
  recovery: BatchSaveRecoveryAction
  chip: string
  tone: string
  needsProcessing: boolean
}

const ROWS: MappingRow[] = [
  {
    name: 'CONFIRMED（保存成功，已定位追番记录）',
    withCandidates: false,
    errorType: null,
    outcome: 'CONFIRMED',
    requestId: 'req-1',
    status: 'CONFIRMED',
    phase: 'confirmed',
    recovery: 'NONE',
    chip: '已确认待提交',
    tone: 'success',
    needsProcessing: false,
  },
  {
    name: 'save_confirm_failed（已保存、确认未完成）',
    withCandidates: true,
    errorType: 'save_confirm_failed',
    outcome: 'FAILED',
    requestId: 'req-saved',
    status: 'SAVED_PENDING_CONFIRM',
    phase: 'saved_pending_confirm',
    recovery: 'RETRY_CONFIRM',
    chip: '已保存待确认',
    tone: 'attention',
    needsProcessing: true,
  },
  {
    name: 'draft_replayed —— 有候选',
    withCandidates: true,
    errorType: 'draft_replayed',
    outcome: 'FAILED',
    requestId: null,
    status: BATCH_STATUS_LOCATE_PENDING,
    phase: 'saved_pending_locate',
    recovery: 'LOCATE_SAVED',
    chip: '已保存，待定位',
    tone: 'attention',
    needsProcessing: true,
  },
  {
    name: 'draft_replayed —— 无候选（同一冻结展示状态）',
    withCandidates: false,
    errorType: 'draft_replayed',
    outcome: 'FAILED',
    requestId: null,
    status: BATCH_STATUS_LOCATE_PENDING,
    phase: 'saved_pending_locate',
    recovery: 'LOCATE_SAVED',
    chip: '已保存，待定位',
    tone: 'attention',
    needsProcessing: true,
  },
  {
    name: 'draft_expired —— 有候选',
    withCandidates: true,
    errorType: 'draft_expired',
    outcome: 'FAILED',
    requestId: null,
    status: 'FOUND',
    phase: 'candidates',
    recovery: 'REGENERATE_DRAFT',
    chip: '找到候选',
    tone: 'attention',
    needsProcessing: true,
  },
  {
    name: 'draft_expired —— 无候选',
    withCandidates: false,
    errorType: 'draft_expired',
    outcome: 'FAILED',
    requestId: null,
    status: 'EMPTY',
    phase: 'blocked',
    recovery: 'REGENERATE_DRAFT',
    chip: '未找到候选',
    tone: 'attention',
    needsProcessing: true,
  },
  {
    name: 'draft_evicted —— 有候选',
    withCandidates: true,
    errorType: 'draft_evicted',
    outcome: 'FAILED',
    requestId: null,
    status: 'FOUND',
    phase: 'candidates',
    recovery: 'REGENERATE_DRAFT',
    chip: '找到候选',
    tone: 'attention',
    needsProcessing: true,
  },
  {
    name: 'draft_revision_conflict —— 无候选',
    withCandidates: false,
    errorType: 'draft_revision_conflict',
    outcome: 'FAILED',
    requestId: null,
    status: 'EMPTY',
    phase: 'blocked',
    recovery: 'REGENERATE_DRAFT',
    chip: '未找到候选',
    tone: 'attention',
    needsProcessing: true,
  },
  {
    name: 'draft_reserved —— 稍后重试保存',
    withCandidates: false,
    errorType: 'draft_reserved',
    outcome: 'FAILED',
    requestId: null,
    status: 'DRAFT',
    phase: 'draft',
    recovery: 'RETRY_SAVE',
    chip: '草案',
    tone: 'attention',
    needsProcessing: true,
  },
  {
    name: 'idempotency_conflict —— 稍后重试保存',
    withCandidates: false,
    errorType: 'idempotency_conflict',
    outcome: 'FAILED',
    requestId: null,
    status: 'DRAFT',
    phase: 'draft',
    recovery: 'RETRY_SAVE',
    chip: '草案',
    tone: 'attention',
    needsProcessing: true,
  },
  {
    name: '未知错误类型 fail closed 为普通可重试失败',
    withCandidates: false,
    errorType: 'unexpected_error',
    outcome: 'FAILED',
    requestId: null,
    status: 'DRAFT',
    phase: 'draft',
    recovery: 'RETRY_SAVE',
    chip: '草案',
    tone: 'attention',
    needsProcessing: true,
  },
]

describe('#195 展示状态映射表', () => {
  it.each(ROWS)('$name', (row_) => {
    const resultItem = {
      item_id: 'item-1',
      outcome: row_.outcome,
      request_id: row_.requestId,
      status: row_.outcome === 'CONFIRMED' ? 'CONFIRMED' : null,
      error_type: row_.errorType,
      error_message: null,
      tracking_id: row_.outcome === 'CONFIRMED' ? 'tracking-1' : null,
      tracking_ready: row_.outcome === 'CONFIRMED',
    } as unknown as Parameters<typeof projectSaveConfirmOutcome>[1]

    // 展示状态：投影是唯一写点。
    const projection = projectSaveConfirmOutcome(row(row_.withCandidates), resultItem)
    expect(projection.row.status).toBe(row_.status)
    expect(batchStatusLabel(projection.row.status)).toBe(row_.chip)
    expect(batchStatusTone(projection.row.status)).toBe(row_.tone)
    expect(batchItemNeedsProcessing(projection.row, false)).toBe(row_.needsProcessing)

    // 恢复动作：展示状态 + 最近一次失败类型。
    expect(batchSaveRecoveryAction({
      status: projection.row.status,
      errorType: row_.errorType,
      trackingLocated: row_.outcome === 'CONFIRMED',
    })).toBe(row_.recovery)

    // 生命周期相位：同一错误类型的唯一判定。
    if (row_.outcome === 'CONFIRMED') {
      // 成功路径同样走真实 reducer（save_succeeded），不再与本表字面量自比。
      expect(phaseAfterSaveSucceeded(row_.withCandidates)).toBe(row_.phase)
      return
    }
    expect(phaseAfterSaveFailed(row_.withCandidates, {
      error_type: row_.errorType,
      outcome: row_.outcome,
      request_id: row_.requestId,
    })).toBe(row_.phase)
  })

  it('draft_replayed 的错误类型判定只有一个定义，且两种前提都不落到 candidates/blocked', () => {
    // 单一判定：生命周期层导出、展示投影与相位共用。
    expect(batchSaveErrorIsReplayed('draft_replayed')).toBe(true)
    expect(batchSaveErrorInvalidatesDraft('draft_replayed')).toBe(false)
    for (const withCandidates of [true, false]) {
      const phase = phaseAfterSaveFailed(withCandidates, {
        error_type: 'draft_replayed',
        outcome: 'FAILED',
        request_id: null,
      })
      expect(phase).toBe('saved_pending_locate')
      expect(phase).not.toBe('candidates')
      expect(phase).not.toBe('blocked')
    }
  })

  it('draft_replayed 在单条重试路径上得到同一对（展示状态, 相位）', () => {
    // 视图单条重试：先 failSaveItem（相位），再按 safeType 投影展示行。
    const displayed = projectDeterministicSaveFailure(row(true), 'draft_replayed')
    expect(displayed.status).toBe(BATCH_STATUS_LOCATE_PENDING)
    expect(batchStatusLabel(displayed.status)).toBe('已保存，待定位')
    expect(batchSaveRecoveryAction({ status: displayed.status, errorType: 'draft_replayed' })).toBe('LOCATE_SAVED')
    expect(phaseAfterSaveFailed(true, {
      error_type: 'draft_replayed',
      outcome: 'FAILED',
      request_id: null,
    })).toBe('saved_pending_locate')
  })

  it('draft_replayed 在「已保存」与「未保存」两种前提下都收敛到同一对（展示状态, 相位）', () => {
    // 「未保存」前提：本次保存直接撞上已保存草案。
    // 「已保存」前提：上一次保存响应未知（条目可能已被保存），本次是冻结的同键重放。
    const replayError = { error_type: 'draft_replayed', outcome: 'FAILED', request_id: null }
    for (const frozenBefore of [false, true]) {
      const phase = phaseAfterSaveFailed(true, replayError, { frozenBefore })
      expect(phase).toBe('saved_pending_locate')
      const displayed = projectSaveConfirmOutcome(row(true), {
        item_id: 'item-1',
        outcome: 'FAILED',
        request_id: null,
        status: null,
        error_type: 'draft_replayed',
        error_message: null,
        tracking_id: null,
        tracking_ready: null,
      } as unknown as Parameters<typeof projectSaveConfirmOutcome>[1])
      expect(displayed.row.status).toBe(BATCH_STATUS_LOCATE_PENDING)
      expect(batchStatusLabel(displayed.row.status)).toBe('已保存，待定位')
      expect(batchSaveRecoveryAction({
        status: displayed.row.status,
        errorType: 'draft_replayed',
      })).toBe('LOCATE_SAVED')
    }
  })

  it('响应未知的展示状态与相位成对收敛', () => {
    const displayed = projectResponseUnknown(row(true))
    expect(displayed.status).toBe('RESPONSE_UNKNOWN')
    expect(batchSaveRecoveryAction({ status: displayed.status, errorType: null })).toBe('VERIFY_RESULT')
    expect(batchCardNextStep({
      status: displayed.status,
      hasCandidates: false,
      hasDraft: false,
      blocker: null,
      resultUnknown: true,
      savedPendingConfirm: false,
      trackingLocated: false,
      generating: false,
    })).toContain('核验本条结果')
  })

  it('已保存待定位的下一步文案与候选无关，且不引导重新生成草案', () => {
    const displayed = projectDeterministicSaveFailure(row(false), 'draft_replayed')
    const step = batchCardNextStep({
      status: displayed.status,
      hasCandidates: true,
      hasDraft: false,
      blocker: null,
      resultUnknown: false,
      savedPendingConfirm: false,
      trackingLocated: false,
      generating: false,
    })
    expect(step).toContain('确认状态尚未定位')
    // 明确禁止重新生成（而不是给出「重新生成草案」入口）。
    expect(step).toContain('不要重新生成草案')
    expect(step).toContain('请勿重新添加同一部')
  })

  it('终态相位拒绝新的勾选意图：saved_pending_locate 拒绝、candidates 仍允许', () => {
    // #195 在 set_selected 里把 saved_pending_locate 加入终态清单：它必须与
    // saved_pending_confirm / blocked / confirmed 一样拒绝新的勾选意图；
    // 同时用 candidates 作对照，证明终态清单没有扩大到正常可确认的条目。
    const locate = stateAfterSaveFailed(true, {
      error_type: 'draft_replayed',
      outcome: 'FAILED',
      request_id: null,
    })
    expect(locate.items['item-1']!.phase).toBe('saved_pending_locate')
    expect(reduceBatchReview(locate, { type: 'set_selected', itemId: 'item-1', selected: true })
      .items['item-1']!.selected).toBe(false)

    const candidates = stateAfterSaveFailed(true, {
      error_type: 'draft_expired',
      outcome: 'FAILED',
      request_id: null,
    })
    expect(candidates.items['item-1']!.phase).toBe('candidates')
    expect(reduceBatchReview(candidates, { type: 'set_selected', itemId: 'item-1', selected: true })
      .items['item-1']!.selected).toBe(true)
  })
})

/**
 * 全部 `BatchItemPhase` 与展示状态的对照（不只是保存失败结局）。
 *
 * `Record<BatchItemPhase, …>` 让类型系统强制这张表覆盖每一个相位：将来新增相位
 * 必须先在这里写出「展示状态 + 恢复动作」，不能悄悄漏掉。
 */
interface PhaseRow {
  /** 该相位下条目行持有的展示状态（服务端词汇镜像）。 */
  status: string
  /** 该相位下视图记住的最近一次保存失败类型（若有）。 */
  errorType: string | null
  /** 该相位默认给出的恢复动作。 */
  recovery: BatchSaveRecoveryAction
  /** 该相位下条目是否还需要用户处理。 */
  needsProcessing: boolean
  note: string
}

const PHASE_ROWS: Record<BatchItemPhase, PhaseRow> = {
  parsing: { status: '', errorType: null, recovery: 'NONE', needsProcessing: true, note: '整批解析在途，条目卡尚未进入审核面' },
  blocked: { status: 'EMPTY', errorType: null, recovery: 'NONE', needsProcessing: true, note: '没有可确认内容；未知原因 fail closed 为 NONE' },
  candidates: { status: 'FOUND', errorType: null, recovery: 'NONE', needsProcessing: true, note: '在右栏选择真实 MiKan 合集' },
  draft: { status: 'DRAFT', errorType: null, recovery: 'NONE', needsProcessing: true, note: '可保存；仅在记住普通失败类型时给 RETRY_SAVE' },
  applying: { status: 'DRAFT', errorType: null, recovery: 'NONE', needsProcessing: true, note: '草案修改在途，入口禁用' },
  apply_failed: { status: 'DRAFT', errorType: null, recovery: 'NONE', needsProcessing: true, note: '右栏重试修改，不新增保存入口' },
  saving: { status: 'DRAFT', errorType: null, recovery: 'NONE', needsProcessing: true, note: '保存确认在途，冻结现场' },
  confirmed: { status: 'CONFIRMED', errorType: null, recovery: 'VERIFY_RESULT', needsProcessing: false, note: '未定位到追番记录时只允许重试定位' },
  saved_pending_confirm: { status: 'SAVED_PENDING_CONFIRM', errorType: 'save_confirm_failed', recovery: 'RETRY_CONFIRM', needsProcessing: true, note: '只允许重试确认，不重复保存' },
  saved_pending_locate: { status: BATCH_STATUS_LOCATE_PENDING, errorType: 'draft_replayed', recovery: 'LOCATE_SAVED', needsProcessing: true, note: '草案已保存待定位；没有任何重复保存入口' },
  response_unknown: { status: 'RESPONSE_UNKNOWN', errorType: null, recovery: 'VERIFY_RESULT', needsProcessing: true, note: '核验冻结请求的结果' },
}

describe('#195 全相位展示状态对照', () => {
  it.each(Object.entries(PHASE_ROWS))('%s 相位的展示状态与恢复动作', (phase, expected) => {
    const item = row(false)
    // 相位不决定展示状态（选项 b）：条目行保留自己的镜像，恢复动作只读它。
    if (expected.status) item.status = expected.status
    expect(batchSaveRecoveryAction({
      status: item.status,
      errorType: expected.errorType,
      trackingLocated: false,
    })).toBe(expected.recovery)
    expect(batchItemNeedsProcessing(item, false)).toBe(expected.needsProcessing)
    if (phase === 'saved_pending_locate') {
      // 唯一一处展示词汇定义，避免再次散落。
      expect(item.status).toBe('SAVED_PENDING_LOCATE')
      expect(batchStatusLabel(item.status)).toBe('已保存，待定位')
      expect(batchSaveErrorIsReplayed(expected.errorType)).toBe(true)
    }
  })
})
