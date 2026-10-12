/**
 * 审核资格（#167）：单番与批量共用的唯一判定与文案源。
 *
 * 纯函数：无 Vue 响应式、无 IO、无 store。调用方装配「客户端事实」与两项「服务端事实」
 * （选中字幕组、有效资源名），模块只回答 `confirmable` 与阻断判据码；中文文案由本模块
 * 唯一提供，各面不再各写一份。
 *
 * 两层结构（#160 冻结的约束，保留不合并）：
 *
 *   - **弱闸**：`useBatchReviewJourney.batchItemCanConfirm`——相位为 `draft`、有草案身份、
 *     没有未应用编辑。它是 `begin_save` 的入口自保，语义不变。
 *   - **强闸**：本模块——在弱闸判据之上再加会话有效性、重算/编辑在途、修改失败、
 *     保存/恢复在途、字幕组与有效资源等服务端事实。
 *
 *   因此**强闸为真必然蕴含弱闸为真**：弱闸判据是强闸判据的子集。新增判据只能加在强闸
 *   这一侧；`reviewEligibility.test.ts` 有一条遍历事实空间的断言钉住这条关系。
 *
 * 展示顺序：两个页面历史上把同一条文案放在不同位置（判据集合完全一致，只是句子里的
 * 先后不同），顺序表作为 `SINGLE_REVIEW_DISPLAY_ORDER` / `BATCH_REVIEW_DISPLAY_ORDER`
 * 导出并单测钉住；`reviewBlockerMessages()` 按给定顺序翻译，避免「归一」顺手改掉
 * 用户可见的句子顺序。本票唯一的内容变化是词表裁定的两条版本文案合并为一条
 * （`draft_version`），因此批量侧的原因条数会从 2 变 1。
 */

/** 资格判据码：稳定的语义标识，供各面按自己的展示序取用。 */
export type ReviewBlockerCode =
  | 'draft_not_reviewable'
  | 'draft_version'
  | 'draft_invalid'
  | 'phase_not_review'
  | 'saving'
  | 'save_unverified'
  | 'recalculating'
  | 'pending_edit_filter'
  | 'pending_edit_folder'
  | 'pending_edit'
  | 'edit_failed'
  | 'subtitle_group'
  | 'no_resources'
  | 'weak_gate'

/** 判据码 → 唯一中文文案（用户可见；#167 词表裁定后的口径）。 */
export const REVIEW_BLOCKER_MESSAGES: Readonly<Record<ReviewBlockerCode, string>> = {
  draft_not_reviewable: '需先生成可审核草案',
  draft_version: '订阅草案版本不可用',
  draft_invalid: '订阅草案已失效',
  phase_not_review: '当前订阅方案已进入确认恢复流程',
  saving: '正在保存并确认',
  save_unverified: '保存结果待核验',
  recalculating: '正在重新计算订阅方案',
  pending_edit_filter: '有尚未应用的编辑，正在等待过滤规则自动更新',
  pending_edit_folder: '有尚未应用的编辑，等待提交目录名',
  pending_edit: '有尚未应用的编辑',
  edit_failed: '存在未恢复的字段修改失败',
  subtitle_group: '请选择有效字幕组',
  no_resources: '没有有效资源',
  weak_gate: '当前订阅方案不可确认',
}

/**
 * 调用方装配的事实集合。缺省即「该判据不成立」；**各面只装配自己那份**，
 * 不得因为归一而丢掉任何一面现有的判据。
 */
export interface ReviewEligibilityFacts {
  /** 服务端条目可审核（可展开且带公开 Request）。批量侧传；单番侧缺省 true。 */
  readonly reviewableDraft?: boolean
  readonly draftId?: string | null
  readonly draftRevision?: number | null
  /** 草案会话存在（批量：条目有会话事实）；`false` 等价于草案已失效。 */
  readonly sessionPresent?: boolean
  readonly draftInvalid?: boolean
  /** 单番：journey 相位是否仍在 review。 */
  readonly phaseInReview?: boolean
  /** 单番：正在保存并确认。 */
  readonly saving?: boolean
  /** 批量：条目处于保存/恢复在途或响应未知。 */
  readonly saveUnverified?: boolean
  readonly recalculating?: boolean
  readonly schedulerWaiting?: boolean
  readonly schedulerFolderPending?: boolean
  /** 未应用编辑（批量把调度器 groupPending 并入这一项）。 */
  readonly pendingEdit?: boolean
  readonly editFailed?: boolean
  /** 单番：弱闸（`journey.canConfirm()`）。 */
  readonly weakConfirmable?: boolean
  /** 服务端事实之一：草案选中的字幕组。 */
  readonly selectedSubtitleGroup?: string | null
  /** 服务端事实之二：有效资源名（只判「有没有一个非空值」，不推算集数）。 */
  readonly effectiveSeedNames?: readonly unknown[]
}

export interface ReviewEligibility {
  readonly confirmable: boolean
  /** 判据码，按下面的规范序；各面渲染时可按自己的展示序重排。 */
  readonly blockers: readonly ReviewBlockerCode[]
}

/**
 * 规范判定顺序：直接取文案表的键序（单测与「兜底追加」用），
 * 不另外维护一份清单，避免出现第三份近重复的顺序表。
 */
export const REVIEW_BLOCKER_CANONICAL_ORDER: readonly ReviewBlockerCode[] =
  Object.keys(REVIEW_BLOCKER_MESSAGES) as ReviewBlockerCode[]

/**
 * 两个页面**历史上**的展示序（改前逐位一致，本票只换文案来源、不动句子顺序）。
 * 放在模块里是为了可单测：`reviewEligibility.test.ts` 按序断言，新增判据若忘了
 * 加进任一序，`reviewBlockerMessages()` 仍会把它追加显示（fail visible）。
 */
export const SINGLE_REVIEW_DISPLAY_ORDER: readonly ReviewBlockerCode[] = [
  'saving',
  'draft_invalid',
  'phase_not_review',
  'recalculating',
  'pending_edit_filter',
  'pending_edit_folder',
  'pending_edit',
  'edit_failed',
  'subtitle_group',
  'no_resources',
  'draft_version',
  'weak_gate',
]

export const BATCH_REVIEW_DISPLAY_ORDER: readonly ReviewBlockerCode[] = [
  'draft_not_reviewable',
  'draft_version',
  'draft_invalid',
  'pending_edit_filter',
  'pending_edit_folder',
  'pending_edit',
  'recalculating',
  'edit_failed',
  'save_unverified',
  'subtitle_group',
  'no_resources',
]

/**
 * 空值口径（本票唯一的收紧点，需规格方确认）：统一采用批量侧更严格的口径——
 * 字符串去空白后非空、版本号为正整数。单番侧原先只判 `null`/长度，因此
 * 纯空白字幕组、全空白资源名、版本 `0`/负数/小数由「放行」变为「阻断」；
 * 这三类都不在服务端契约可达范围内（`draft_revision` 自 1 单调递增、
 * 字幕组来自 RSS 源列表、资源名来自已过滤清单），但按 AC「不得收紧」需明示。
 */
function hasTrimmedText(value: string | null | undefined): boolean {
  return typeof value === 'string' && value.trim().length > 0
}

function hasUsableRevision(value: number | null | undefined): boolean {
  // 与批量侧既有判据一致：`0`、负数、小数、字符串、null 一律不可用。
  return typeof value === 'number' && Number.isInteger(value) && value > 0
}

/** 单条判据求值：返回该组合下命中的全部判据码。 */
export function evaluateReviewEligibility(facts: ReviewEligibilityFacts): ReviewEligibility {
  const blockers: ReviewBlockerCode[] = []
  if (facts.reviewableDraft === false) blockers.push('draft_not_reviewable')
  if (!hasTrimmedText(facts.draftId) || !hasUsableRevision(facts.draftRevision)) blockers.push('draft_version')
  if (facts.sessionPresent === false || facts.draftInvalid === true) blockers.push('draft_invalid')
  if (facts.phaseInReview === false) blockers.push('phase_not_review')
  if (facts.saving === true) blockers.push('saving')
  if (facts.saveUnverified === true) blockers.push('save_unverified')
  if (facts.recalculating === true) blockers.push('recalculating')
  if (facts.schedulerWaiting === true) blockers.push('pending_edit_filter')
  else if (facts.schedulerFolderPending === true) blockers.push('pending_edit_folder')
  else if (facts.pendingEdit === true) blockers.push('pending_edit')
  if (facts.editFailed === true) blockers.push('edit_failed')
  if (!hasTrimmedText(facts.selectedSubtitleGroup)) blockers.push('subtitle_group')
  if (!(facts.effectiveSeedNames ?? []).some((name) => hasTrimmedText(name as string))) blockers.push('no_resources')
  if (facts.weakConfirmable === false) blockers.push('weak_gate')
  return { confirmable: blockers.length === 0, blockers }
}

/**
 * 按调用方的展示序把判据码翻译成唯一文案。
 *
 * `order` 里没列的判据码会按规范序追加在末尾——新增判据仍会显示（fail visible），
 * 而不是被某个页面的旧顺序表悄悄吞掉。
 */
export function reviewBlockerMessages(
  blockers: readonly ReviewBlockerCode[],
  order: readonly ReviewBlockerCode[],
): string[] {
  const present = new Set(blockers)
  const ordered = [
    ...order.filter((code) => present.has(code)),
    ...REVIEW_BLOCKER_CANONICAL_ORDER.filter((code) => present.has(code) && !order.includes(code)),
  ]
  return ordered.map((code) => REVIEW_BLOCKER_MESSAGES[code])
}
