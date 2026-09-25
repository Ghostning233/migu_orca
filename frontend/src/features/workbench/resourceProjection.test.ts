import { describe, expect, it } from 'vitest'

import {
  resourcePreview,
  safeResourceReason,
  safeResourceTitle,
} from '@/features/workbench/resourceProjection'

/** #151：默认层与明细弹窗共用的资源安全投影。 */
describe('resource projection (#151)', () => {
  it('keeps ordinary seed titles and reasons readable', () => {
    expect(safeResourceTitle('星海旅途 S01E01 1080p WEB-DL x264.mkv')).toBe('星海旅途 S01E01 1080p WEB-DL x264.mkv')
    expect(safeResourceReason('命中排除规则：[v2]')).toBe('命中排除规则：[v2]')
  })

  it('hides URL-like values, magnets and absolute local paths without echoing them', () => {
    expect(safeResourceTitle('magnet:?xt=urn:btih:deadbeef')).toBe('[已隐藏资源地址]')
    expect(safeResourceTitle('https://mikan.example/rss/1')).toBe('[已隐藏资源地址]')
    expect(safeResourceTitle('/data/media/anime/01.mkv')).toBe('[已隐藏本地路径]')
    expect(safeResourceTitle('C:\\media\\01.mkv')).toBe('[已隐藏本地路径]')
    expect(safeResourceTitle('\\\\server\\share\\01.mkv')).toBe('[已隐藏本地路径]')
    expect(safeResourceReason('magnet:?xt=urn:btih:deadbeef')).toBe('[已隐藏资源地址]')
    expect(safeResourceReason('/srv/library/01.mkv')).toBe('[已隐藏本地路径]')
  })

  it('previews only a few safe samples and never invents extra values', () => {
    const seeds = ['01.mkv', '02.mkv', '03.mkv']
    expect(resourcePreview(seeds)).toEqual(['01.mkv', '02.mkv'])
    expect(resourcePreview(seeds, 1)).toEqual(['01.mkv'])
    expect(resourcePreview([])).toEqual([])
    expect(resourcePreview(['magnet:?xt=urn:btih:deadbeef', '02.mkv'])).toEqual(['[已隐藏资源地址]', '02.mkv'])
    expect(resourcePreview(['01.mkv'], -3)).toEqual([])
  })
})
