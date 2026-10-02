import { describe, expect, it } from 'vitest'

import {
  decideWheelIntent,
  resolveScreenRest,
  screenGeometryIsStable,
  SCREEN_EDGE_EPSILON,
} from '@/app/composables/useAddAnimeScreenScroll'

/**
 * Issue #140/#141/#143：两屏切屏的纯决策边界。
 *
 * 首屏顶部 = 0，工作台顶部 = 780（1440×900 下 100vh − 顶栏 72 − 上下内边距 48）。
 */
const HERO_TOP = 0
const WORKBENCH_TOP = 780

function decision(overrides: Partial<Parameters<typeof decideWheelIntent>[0]> = {}) {
  return decideWheelIntent({
    scrollY: HERO_TOP,
    firstTop: HERO_TOP,
    secondTop: WORKBENCH_TOP,
    deltaY: 120,
    gestureConsumedContent: false,
    locked: false,
    insideInnerScroll: false,
    ...overrides,
  })
}

describe('decideWheelIntent', () => {
  it('从首屏向下滚动一次就完整切到工作台', () => {
    expect(decision({ scrollY: 0, deltaY: 120 })).toBe('second')
    // 即使是很小的向下手势也整屏切换，不停在两屏之间。
    expect(decision({ scrollY: 0, deltaY: 4 })).toBe('second')
  })

  it('首屏之外不抢滚动：工作台内容中间保持原生滚动', () => {
    expect(decision({ scrollY: 1200, deltaY: 120 })).toBe('native')
    expect(decision({ scrollY: 1200, deltaY: -120 })).toBe('native')
  })

  it('长工作台滚到顶部时，同一次手势先停住', () => {
    expect(
      decision({ scrollY: WORKBENCH_TOP, deltaY: -120, gestureConsumedContent: true }),
    ).toBe('hold')
  })

  it('下一次向上手势才完整回到首屏', () => {
    expect(
      decision({ scrollY: WORKBENCH_TOP, deltaY: -120, gestureConsumedContent: false }),
    ).toBe('first')
  })

  it('已经在首屏顶部时向上滚动不再切屏', () => {
    expect(decision({ scrollY: 0, deltaY: -120 })).toBe('native')
  })

  it('批量左右栏内部滚动永不切屏', () => {
    expect(decision({ scrollY: 0, deltaY: 400, insideInnerScroll: true })).toBe('native')
    expect(
      decision({ scrollY: WORKBENCH_TOP, deltaY: -400, insideInnerScroll: true }),
    ).toBe('native')
  })

  it('切屏动画期间吞掉滚轮，避免与动画争夺位置', () => {
    expect(decision({ scrollY: 0, deltaY: 120, locked: true })).toBe('hold')
    expect(decision({ scrollY: WORKBENCH_TOP, deltaY: -120, locked: true })).toBe('hold')
  })

  it('没有工作台屏（加载/失败/无候选）时不动滚动', () => {
    expect(decision({ scrollY: 0, deltaY: 120, secondTop: null })).toBe('native')
    expect(decision({ scrollY: 0, deltaY: -120, secondTop: null })).toBe('native')
  })

  it('忽略零增量与触控板亚像素抖动', () => {
    expect(decision({ scrollY: 0, deltaY: 0 })).toBe('native')
    expect(decision({ scrollY: 0, deltaY: 0.4 })).toBe('native')
  })
})

describe('resolveScreenRest', () => {
  it('落在两屏之间的停顿收敛到最近一屏', () => {
    expect(resolveScreenRest(120, HERO_TOP, WORKBENCH_TOP)).toBe('first')
    expect(resolveScreenRest(WORKBENCH_TOP / 2 - 1, HERO_TOP, WORKBENCH_TOP)).toBe('first')
    expect(resolveScreenRest(WORKBENCH_TOP / 2 + 1, HERO_TOP, WORKBENCH_TOP)).toBe('second')
    expect(resolveScreenRest(700, HERO_TOP, WORKBENCH_TOP)).toBe('second')
  })

  it('已经在某一屏上时不干预', () => {
    expect(resolveScreenRest(0, HERO_TOP, WORKBENCH_TOP)).toBeNull()
    expect(resolveScreenRest(SCREEN_EDGE_EPSILON, HERO_TOP, WORKBENCH_TOP)).toBeNull()
    expect(resolveScreenRest(WORKBENCH_TOP, HERO_TOP, WORKBENCH_TOP)).toBeNull()
    // 长工作台内部（超过一屏）保持原位，不被拉回顶部。
    expect(resolveScreenRest(WORKBENCH_TOP + 600, HERO_TOP, WORKBENCH_TOP)).toBeNull()
  })

  it('没有工作台屏时不做收敛', () => {
    expect(resolveScreenRest(120, HERO_TOP, null)).toBeNull()
  })
})

describe('screenGeometryIsStable', () => {
  it('要求文档 top 与高度同时稳定，而不是只看高度', () => {
    expect(screenGeometryIsStable({ top: 780, height: 780 }, { top: 780, height: 780 })).toBe(true)
    // 第一屏进度条收尾：第二屏高度不变、文档 top 变了 —— 这不是稳定布局。
    expect(screenGeometryIsStable({ top: 780, height: 780 }, { top: 620, height: 780 })).toBe(false)
    // 高度本身在变（图片/字体撑开）同样不算稳定。
    expect(screenGeometryIsStable({ top: 780, height: 780 }, { top: 780, height: 820 })).toBe(false)
    // 还没有测量到第二屏时不算稳定。
    expect(screenGeometryIsStable(null, { top: 780, height: 780 })).toBe(false)
    expect(screenGeometryIsStable({ top: 780, height: 780 }, null)).toBe(false)
    // 亚像素抖动在容差内仍然算稳定。
    expect(screenGeometryIsStable({ top: 780, height: 780 }, { top: 780.4, height: 780.4 })).toBe(true)
  })
})
