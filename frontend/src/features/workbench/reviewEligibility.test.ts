import { describe, expect, it } from 'vitest'

import { batchItemCanConfirm, type BatchReviewItem } from '@/app/composables/useBatchReviewJourney'
import {
  BATCH_REVIEW_DISPLAY_ORDER,
  REVIEW_BLOCKER_CANONICAL_ORDER,
  SINGLE_REVIEW_DISPLAY_ORDER,
  REVIEW_BLOCKER_MESSAGES,
  evaluateReviewEligibility,
  reviewBlockerMessages,
  type ReviewBlockerCode,
  type ReviewEligibilityFacts,
} from './reviewEligibility'

/** 全部判据都成立的事实：confirmable。 */
const ELIGIBLE: ReviewEligibilityFacts = {
  reviewableDraft: true,
  draftId: 'draft-1',
  draftRevision: 2,
  sessionPresent: true,
  draftInvalid: false,
  phaseInReview: true,
  saving: false,
  saveUnverified: false,
  recalculating: false,
  schedulerWaiting: false,
  schedulerFolderPending: false,
  pendingEdit: false,
  editFailed: false,
  weakConfirmable: true,
  selectedSubtitleGroup: '喵萌奶茶屋',
  effectiveSeedNames: ['史莱姆 S4 01 [1080p]'],
}

/** 逐条判据 → 期望命中的判据码（#167 「逐条映射表」的单测形态）。 */
const CRITERIA: ReadonlyArray<readonly [string, Partial<ReviewEligibilityFacts>, ReviewBlockerCode]> = [
  ['服务端条目不可审核', { reviewableDraft: false }, 'draft_not_reviewable'],
  ['草案身份缺失', { draftId: null }, 'draft_version'],
  ['草案身份为空白', { draftId: '   ' }, 'draft_version'],
  ['草案版本不可用（null）', { draftRevision: null }, 'draft_version'],
  ['草案版本不可用（0）', { draftRevision: 0 }, 'draft_version'],
  ['草案版本不可用（小数）', { draftRevision: 1.5 }, 'draft_version'],
  ['会话不存在', { sessionPresent: false }, 'draft_invalid'],
  ['草案已失效', { draftInvalid: true }, 'draft_invalid'],
  ['相位已进入确认恢复流程', { phaseInReview: false }, 'phase_not_review'],
  ['正在保存并确认', { saving: true }, 'saving'],
  ['保存结果待核验', { saveUnverified: true }, 'save_unverified'],
  ['正在重新计算订阅方案', { recalculating: true }, 'recalculating'],
  ['等待过滤规则自动更新', { schedulerWaiting: true }, 'pending_edit_filter'],
  ['等待提交目录名', { schedulerFolderPending: true }, 'pending_edit_folder'],
  ['有尚未应用的编辑', { pendingEdit: true }, 'pending_edit'],
  ['存在未恢复的字段修改失败', { editFailed: true }, 'edit_failed'],
  ['字幕组缺失', { selectedSubtitleGroup: null }, 'subtitle_group'],
  ['字幕组为空白', { selectedSubtitleGroup: '  ' }, 'subtitle_group'],
  ['没有有效资源', { effectiveSeedNames: [] }, 'no_resources'],
  ['有效资源全为空白', { effectiveSeedNames: ['', '  '] }, 'no_resources'],
  ['弱闸未通过', { weakConfirmable: false }, 'weak_gate'],
]

describe('reviewEligibility', () => {
  it('accepts the fully-jointed fact set', () => {
    expect(evaluateReviewEligibility(ELIGIBLE)).toEqual({ confirmable: true, blockers: [] })
  })

  it.each(CRITERIA)('%s → %s', (_label, override, expected) => {
    const result = evaluateReviewEligibility({ ...ELIGIBLE, ...override })
    expect(result.confirmable).toBe(false)
    expect(result.blockers).toContain(expected)
  })

  it('keeps the canonical order and reports every hit in one pass', () => {
    const result = evaluateReviewEligibility({
      ...ELIGIBLE,
      reviewableDraft: false,
      draftId: '',
      phaseInReview: false,
      saving: true,
      saveUnverified: true,
      recalculating: true,
      schedulerWaiting: true,
      editFailed: true,
      selectedSubtitleGroup: '',
      effectiveSeedNames: [],
      weakConfirmable: false,
    })
    expect(result.blockers).toEqual([
      'draft_not_reviewable',
      'draft_version',
      'phase_not_review',
      'saving',
      'save_unverified',
      'recalculating',
      'pending_edit_filter',
      'edit_failed',
      'subtitle_group',
      'no_resources',
      'weak_gate',
    ])
  })

  it('treats the scheduler pending flags as one three-step ladder', () => {
    const waiting = evaluateReviewEligibility({ ...ELIGIBLE, schedulerWaiting: true, schedulerFolderPending: true, pendingEdit: true })
    expect(waiting.blockers).toEqual(['pending_edit_filter'])
    const folder = evaluateReviewEligibility({ ...ELIGIBLE, schedulerFolderPending: true, pendingEdit: true })
    expect(folder.blockers).toEqual(['pending_edit_folder'])
    const dirty = evaluateReviewEligibility({ ...ELIGIBLE, pendingEdit: true })
    expect(dirty.blockers).toEqual(['pending_edit'])
  })

  it('has one message per code and no legacy wording left', () => {
    for (const code of REVIEW_BLOCKER_CANONICAL_ORDER) {
      expect(REVIEW_BLOCKER_MESSAGES[code]).toBeTruthy()
    }
    const messages = Object.values(REVIEW_BLOCKER_MESSAGES).join('|')
    for (const legacy of ['正在重新计算资源', '尚未选择字幕组', '修改失败，请重试或恢复最后一致值', '草案能力无效', '草案版本无效']) {
      expect(messages).not.toContain(legacy)
    }
  })

  it('renders in the caller display order and never drops a code', () => {
    const blockers: ReviewBlockerCode[] = ['no_resources', 'saving', 'draft_invalid']
    expect(reviewBlockerMessages(blockers, ['saving', 'draft_invalid'])).toEqual([
      REVIEW_BLOCKER_MESSAGES.saving,
      REVIEW_BLOCKER_MESSAGES.draft_invalid,
      REVIEW_BLOCKER_MESSAGES.no_resources,
    ])
  })

  it('两个页面的展示序都被单测钉住，且不遗漏判据码', () => {
    expect(SINGLE_REVIEW_DISPLAY_ORDER).toEqual([
      'saving', 'draft_invalid', 'phase_not_review', 'recalculating',
      'pending_edit_filter', 'pending_edit_folder', 'pending_edit',
      'edit_failed', 'subtitle_group', 'no_resources', 'draft_version', 'weak_gate',
    ])
    expect(BATCH_REVIEW_DISPLAY_ORDER).toEqual([
      'draft_not_reviewable', 'draft_version', 'draft_invalid',
      'pending_edit_filter', 'pending_edit_folder', 'pending_edit',
      'recalculating', 'edit_failed', 'save_unverified', 'subtitle_group', 'no_resources',
    ])
    // 每条判据至少要出现在一个展示序里（否则只能靠兜底追加显示）。
    for (const code of REVIEW_BLOCKER_CANONICAL_ORDER) {
      expect(SINGLE_REVIEW_DISPLAY_ORDER.includes(code) || BATCH_REVIEW_DISPLAY_ORDER.includes(code)).toBe(true)
    }
  })

  it('弱闸 ⊂ 强闸：强闸为真时 journey 的弱闸必然放行', () => {
    // 用真正的弱闸 `batchItemCanConfirm`（不是本地重述判据）遍历事实空间：
    // 只要强闸 confirmable，弱闸就必须为真。
    const weakItem = (facts: ReviewEligibilityFacts): BatchReviewItem => ({
      itemId: 'item-1',
      inputIndex: 0,
      reviewIndex: 0,
      rawTitle: '萌王S4',
      source: null,
      phase: 'draft',
      selected: false,
      draftId: facts.draftId ?? null,
      draftRevision: facts.draftRevision ?? null,
      dirty: facts.pendingEdit === true,
      idempotencyKey: null,
      requestId: null,
      trackingId: null,
      result: null,
      error: null,
    })
    let confirmableCases = 0
    for (const hasIdentity of [true, false]) {
      for (const isDirty of [true, false]) {
        for (const isInvalid of [true, false]) {
          for (const seeds of [0, 1]) {
            const facts: ReviewEligibilityFacts = {
              ...ELIGIBLE,
              draftId: hasIdentity ? 'draft-1' : null,
              draftRevision: hasIdentity ? 1 : null,
              pendingEdit: isDirty,
              draftInvalid: isInvalid,
              effectiveSeedNames: seeds ? ['x'] : [],
            }
            if (!evaluateReviewEligibility(facts).confirmable) continue
            confirmableCases += 1
            expect(batchItemCanConfirm(weakItem(facts))).toBe(true)
          }
        }
      }
    }
    expect(confirmableCases).toBeGreaterThan(0)
  })
})
