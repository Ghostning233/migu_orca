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
    expect(wrapper.text()).toContain('已更新集数未开发')
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

  it('shows at most three effective titles by default and expands the rest on demand', async () => {
    const wrapper = mount(ResourceSummary, {
      props: {
        selectedGroupName: '字幕组',
        effectiveSeeds: ['01.mkv', '02.mkv', '03.mkv', '04.mkv'],
        completeGroups: [],
        excludedSeeds: [],
      },
    })

    const effective = wrapper.find('.effective-seed-group')
    expect(effective.findAll(':scope > .seed-list > li')).toHaveLength(3)
    expect(effective.findAll(':scope > .seed-list > li').map((item) => item.text())).not.toContain('04.mkv')
    await effective.find('.effective-seed-more summary').trigger('click')
    expect(effective.find('.effective-seed-more').text()).toContain('04.mkv')
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

  // 已确认缺陷：地址嵌在说明文字里时，前缀匹配的投影会把它原样渲染出来。
  it('does not render addresses or paths embedded inside reason text', () => {
    const wrapper = mount(ResourceSummary, {
      props: {
        selectedGroupName: '字幕组',
        effectiveSeeds: ['资源位于 /srv/private/file.mkv'],
        completeGroups: [
          {
            subtitleGroup: '字幕组',
            seedNames: ['[字幕组] 番剧 - 01 [1080p][CHS].mkv', '缓存 C:\\private\\file.mkv'],
          },
        ],
        excludedSeeds: [
          { name: '番剧 - 01 720p.mkv', reason: '命中规则：https://example.invalid/private.xml' },
          { name: '番剧 - 02.mkv', reason: '排除原因：magnet:?xt=urn:btih:deadbeef' },
        ],
      },
    })

    const text = wrapper.text()
    expect(text).not.toContain('example.invalid')
    expect(text).not.toContain('magnet:?')
    expect(text).not.toContain('/srv/private')
    expect(text).not.toContain('C:\\private')
    expect(text).toContain('[已隐藏资源地址]')
    expect(text).toContain('[已隐藏本地路径]')
    // 正常种子标题仍然可读。
    expect(text).toContain('[字幕组] 番剧 - 01 [1080p][CHS].mkv')
  })

  // 已确认缺陷：单段 POSIX 绝对路径（无第二层目录、无扩展名）此前会原样渲染。
  it('does not render single-segment absolute paths in text or attributes', () => {
    const canary = 'CANARY-summary-single-4b7c'
    const wrapper = mount(ResourceSummary, {
      props: {
        selectedGroupName: '字幕组',
        effectiveSeeds: ['/private', `缓存目录：/${canary}`, '正常资源 01.mkv'],
        completeGroups: [
          { subtitleGroup: '字幕组', seedNames: ['临时目录 /tmp', '根目录=/home'] },
        ],
        excludedSeeds: [
          { name: '/data', reason: '排除原因：/srv' },
          { name: '番剧 - 02.mkv', reason: `缓存目录：/${canary}` },
        ],
      },
    })

    const html = wrapper.html()
    const text = wrapper.text()
    for (const surface of [text, html]) {
      expect(surface).not.toContain('/private')
      expect(surface).not.toContain('/tmp')
      expect(surface).not.toContain('/home')
      expect(surface).not.toContain('/srv')
      expect(surface).not.toContain('/data')
      expect(surface).not.toContain(canary)
    }
    // 危险值整体替换为固定占位，正常标题仍然可读。
    expect(text).toContain('[已隐藏本地路径]')
    expect(text).toContain('正常资源 01.mkv')
    expect(text).toContain('番剧 - 02.mkv')
  })

  // 闭合分隔符与「字段语义 + 有限连接词」是两条真实的安全绕过形态。
  it('hides paths after closing delimiters and keyword connectors', () => {
    const canary = 'CANARY-summary-bypass-c15e'
    const wrapper = mount(ResourceSummary, {
      props: {
        selectedGroupName: '字幕组',
        effectiveSeeds: [
          `说明）/private/${canary}`,
          `路径】/srv/${canary}`,
          `缓存目录为/srv/${canary}`,
          `资源在/tmp/${canary}`,
        ],
        completeGroups: [
          {
            subtitleGroup: '字幕组',
            seedNames: [
              `文件路径是/home/${canary}`,
              `存储位置为/var/${canary}`,
              '孤独/摇滚！- 01.mkv',
            ],
          },
        ],
        excludedSeeds: [
          { name: `说明]/data/${canary}`, reason: `说明』/opt/${canary}` },
        ],
      },
    })

    const text = wrapper.text()
    for (const surface of [text, wrapper.html()]) {
      expect(surface).not.toContain(canary)
      expect(surface).not.toContain('/private')
      expect(surface).not.toContain('/srv')
      expect(surface).not.toContain('/tmp')
      expect(surface).not.toContain('/home')
      expect(surface).not.toContain('/var')
      expect(surface).not.toContain('/data')
      expect(surface).not.toContain('/opt')
    }
    expect(text).toContain('[已隐藏本地路径]')
    // 普通标题中的 CJK 斜杠必须原样保留（完整清单里的日语标题另有专测）。
    expect(text).toContain('孤独/摇滚！- 01.mkv')
  })

  // 连字符是常见的「说明 + 取值」分隔符（安全绕过）；而普通 CJK 标题里的斜杠必须保留
  // （误伤）。两者一起锁住，避免用「任意 CJK + 斜杠即路径」的旧规则换绿灯。
  it('hides hyphen-separated paths while keeping CJK slash titles readable', () => {
    const canary = 'CANARY-summary-hyphen-6d21'
    const wrapper = mount(ResourceSummary, {
      props: {
        selectedGroupName: '字幕组',
        effectiveSeeds: [
          `缓存目录-/srv/${canary}`,
          `说明-/tmp/${canary}`,
          '孤独/摇滚！- 01.mkv',
        ],
        completeGroups: [
          { subtitleGroup: '字幕组', seedNames: ['鬼滅の刃/遊郭編 - 01 [1080p].mkv'] },
        ],
        excludedSeeds: [
          { name: `/private/${canary}`, reason: `说明-/mnt/${canary}` },
        ],
      },
    })

    const text = wrapper.text()
    for (const surface of [text, wrapper.html()]) {
      expect(surface).not.toContain(canary)
      expect(surface).not.toContain('/srv')
      expect(surface).not.toContain('/tmp')
      expect(surface).not.toContain('/mnt')
      expect(surface).not.toContain('/private')
    }
    expect(text).toContain('[已隐藏本地路径]')
    // 普通标题中的 CJK 斜杠必须原样保留。
    expect(text).toContain('孤独/摇滚！- 01.mkv')
    expect(text).toContain('鬼滅の刃/遊郭編 - 01 [1080p].mkv')
  })
})
