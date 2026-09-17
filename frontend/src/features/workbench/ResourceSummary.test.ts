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

  it('nests the in-group resources one level under their subtitle group', () => {
    const wrapper = mount(ResourceSummary, {
      props: {
        selectedGroupName: '喵萌奶茶屋',
        effectiveSeeds: ['[喵萌] 芙莉莲 01.mkv'],
        completeGroups: [
          { subtitleGroup: '喵萌奶茶屋', seedNames: ['[喵萌] 芙莉莲 01.mkv'] },
          { subtitleGroup: '桜都字幕组', seedNames: ['[桜都] 芙莉莲 01.mkv'] },
        ],
        excludedSeeds: [],
      },
    })

    // F4/US-345: 字幕组是一级条目，组内资源是二级（嵌套在组内 details 里）。
    const groups = wrapper.findAll('.complete-seed-groups > .subgroup-seed-group')
    expect(groups).toHaveLength(2)
    expect(groups[0]!.find('summary').text()).toContain('喵萌奶茶屋')
    expect(groups[0]!.find('summary').text()).toContain('(1)')
    expect(groups[0]!.findAll('.seed-list > li')).toHaveLength(1)
    expect(groups[0]!.find('.seed-list').text()).toContain('[喵萌] 芙莉莲 01.mkv')
    // 组内资源不是完整种子列表的直接子项，因此不会与一级条目并列。
    expect(wrapper.find('.complete-seed-groups > .seed-list').exists()).toBe(false)
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

  it('does not render absolute filesystem paths', () => {
    const wrapper = mount(ResourceSummary, {
      props: {
        selectedGroupName: '字幕组',
        effectiveSeeds: ['/home/ghostning/.migu_orca/storage/secret.mkv'],
        completeGroups: [],
        excludedSeeds: [],
      },
    })

    expect(wrapper.text()).not.toContain('/home/ghostning/')
    expect(wrapper.text()).toContain('[已隐藏本地路径]')
  })
})
