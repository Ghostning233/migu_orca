import { describe, expect, it } from 'vitest'

import {
  EPISODE_PLACEHOLDER,
  episodeCountText,
  episodeProgressText,
  hasTrustedEpisodeCount,
} from './episodeCount'

/**
 * #165：集数占位只留一份投影。
 *
 * 判定统一为 `Number.isInteger(total) && total > 0`：`0`、负数、小数、字符串、
 * `null`/`undefined` 全部视为不可得，显示「未开发」；有可信数值时显示不变。
 */
describe('episodeCount', () => {
  it('keeps the trusted-value rendering unchanged', () => {
    expect(episodeCountText(28)).toBe('28 集')
    expect(episodeCountText(1)).toBe('1 集')
    expect(episodeProgressText(28)).toBe('总集数：28 集')
  })

  it('treats non-positive and fractional numbers as unavailable', () => {
    expect(episodeCountText(0)).toBe(EPISODE_PLACEHOLDER)
    expect(episodeCountText(-3)).toBe(EPISODE_PLACEHOLDER)
    expect(episodeCountText(1.5)).toBe(EPISODE_PLACEHOLDER)
    expect(episodeCountText(Number.NaN)).toBe(EPISODE_PLACEHOLDER)
    expect(episodeCountText(Number.POSITIVE_INFINITY)).toBe(EPISODE_PLACEHOLDER)
  })

  it('never coerces strings, null or undefined into a trusted count', () => {
    expect(episodeCountText('28' as never)).toBe(EPISODE_PLACEHOLDER)
    expect(episodeCountText('invalid' as never)).toBe(EPISODE_PLACEHOLDER)
    expect(episodeCountText(null)).toBe(EPISODE_PLACEHOLDER)
    expect(episodeCountText(undefined)).toBe(EPISODE_PLACEHOLDER)
    expect(episodeProgressText(null)).toBe(`总集数：${EPISODE_PLACEHOLDER}`)
    expect(episodeProgressText('invalid' as never)).toBe(`总集数：${EPISODE_PLACEHOLDER}`)
  })

  it('exposes the judgement for surfaces that render the raw number', () => {
    expect(hasTrustedEpisodeCount(28)).toBe(true)
    expect(hasTrustedEpisodeCount(0)).toBe(false)
    expect(hasTrustedEpisodeCount(1.5)).toBe(false)
    expect(hasTrustedEpisodeCount(null)).toBe(false)
    expect(hasTrustedEpisodeCount('28' as never)).toBe(false)
  })

  it('uses one placeholder constant, not a per-surface literal', () => {
    expect(EPISODE_PLACEHOLDER).toBe('未开发')
    expect(episodeProgressText(undefined)).toBe('总集数：未开发')
  })
})
