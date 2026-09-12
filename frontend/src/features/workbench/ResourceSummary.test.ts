import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'

import ResourceSummary from '@/features/workbench/ResourceSummary.vue'

describe('ResourceSummary', () => {
  it('renders helper projections and the fixed unavailable updated-episode state', () => {
    const wrapper = mount(ResourceSummary, {
      props: {
        selectedGroupName: '喵萌奶茶屋',
        effectiveSeeds: ['[喵萌] 芙莉莲 01.mkv'],
        completeGroups: [
          { subtitleGroup: '喵萌奶茶屋', seedNames: ['[喵萌] 芙莉莲 01.mkv', '[喵萌] 芙莉莲 SP.mkv'] },
        ],
        excludedSeeds: [{ name: '[喵萌] 芙莉莲 SP.mkv', reason: '命中排除规则：SP' }],
      },
    })

    expect(wrapper.text()).toContain('有效资源数1')
    expect(wrapper.text()).toContain('完整资源数2')
    expect(wrapper.text()).toContain('排除资源数1')
    expect(wrapper.text()).toContain('已更新集数待开发 / 不可用')
    expect(wrapper.text()).toContain('命中排除规则：SP')
  })

  it('does not render URL or magnet-like seed values', () => {
    const wrapper = mount(ResourceSummary, {
      props: {
        selectedGroupName: '字幕组',
        effectiveSeeds: ['https://example.invalid/rss.xml', 'magnet:?xt=urn:btih:secret'],
        completeGroups: [],
        excludedSeeds: [],
      },
    })

    expect(wrapper.text()).not.toContain('example.invalid')
    expect(wrapper.text()).not.toContain('magnet:?')
    expect(wrapper.text()).toContain('[已隐藏资源地址]')
  })
})
