import { enableAutoUnmount, mount } from '@vue/test-utils'
import { afterEach, describe, expect, it } from 'vitest'
import { defineComponent, h, nextTick, ref } from 'vue'

import ResourceDetailDialog from '@/features/workbench/ResourceDetailDialog.vue'

// #151：资源明细双页签弹窗——页签、长列表、焦点恢复、滚动位置与安全投影。
enableAutoUnmount(afterEach)

function mountDialog(options: {
  effective?: string[]
  excluded?: Array<{ name: string; reason: string }>
  group?: string
} = {}) {
  const effective = options.effective ?? ['星海旅途 S01E01 1080p WEB-DL x264.mkv']
  const excluded = options.excluded ?? [{ name: '星海旅途 S01E03 [v2].mkv', reason: '命中排除规则：[v2]' }]
  const dialog = ref<InstanceType<typeof ResourceDetailDialog> | null>(null)
  const wrapper = mount(
    defineComponent({
      setup() {
        return () =>
          h('div', [
            h(
              'button',
              { id: 'open-resources', onClick: () => dialog.value?.open('effective') },
              '查看完整资源列表',
            ),
            h(ResourceDetailDialog, {
              ref: dialog,
              effectiveSeeds: effective,
              excludedSeeds: excluded,
              selectedGroupName: options.group ?? '星海字幕组',
            }),
          ])
      },
    }),
    { attachTo: document.body },
  )
  return { wrapper, dialog }
}

describe('ResourceDetailDialog (#151)', () => {
  it('opens on the effective tab and switches to the excluded tab with reasons', async () => {
    const { wrapper } = mountDialog()
    await wrapper.find('#open-resources').trigger('click')
    await nextTick()

    const effectiveTab = document.querySelector<HTMLElement>('#resource-detail-tab-effective')
    const excludedTab = document.querySelector<HTMLElement>('#resource-detail-tab-excluded')
    expect(effectiveTab?.getAttribute('aria-selected')).toBe('true')
    expect(effectiveTab?.textContent).toContain('有效资源（1）')
    expect(excludedTab?.textContent).toContain('已排除（1）')
    expect(document.querySelector('#resource-detail-panel-effective')?.textContent)
      .toContain('星海旅途 S01E01 1080p WEB-DL x264.mkv')
    expect(document.querySelector('#resource-detail-count')?.textContent).toContain('共 1 条')

    excludedTab?.click()
    await nextTick()
    const panel = document.querySelector('#resource-detail-panel-excluded')
    expect(panel?.textContent).toContain('星海旅途 S01E03 [v2].mkv')
    expect(panel?.textContent).toContain('命中排除规则：[v2]')
    expect(document.querySelector('#resource-detail-tab-excluded')?.getAttribute('aria-selected')).toBe('true')
  })

  it('moves between the two tabs with the arrow keys', async () => {
    const { wrapper } = mountDialog()
    await wrapper.find('#open-resources').trigger('click')
    await nextTick()

    const effectiveTab = document.querySelector<HTMLElement>('#resource-detail-tab-effective')
    effectiveTab?.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowRight', bubbles: true }))
    await nextTick()
    expect(document.querySelector('#resource-detail-tab-excluded')?.getAttribute('aria-selected')).toBe('true')
    document.querySelector<HTMLElement>('#resource-detail-tab-excluded')
      ?.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowLeft', bubbles: true }))
    await nextTick()
    expect(document.querySelector('#resource-detail-tab-effective')?.getAttribute('aria-selected')).toBe('true')
  })

  it('never renders URL-like resources, magnets or local paths', async () => {
    const { wrapper } = mountDialog({
      effective: ['https://mikan.example/rss/1', 'magnet:?xt=urn:btih:deadbeef', '正常资源 01.mkv'],
      excluded: [{ name: '/srv/library/02.mkv', reason: 'magnet:?xt=urn:btih:cafebabe' }],
    })
    await wrapper.find('#open-resources').trigger('click')
    await nextTick()

    const text = document.querySelector('.resource-dialog')?.textContent ?? ''
    expect(text).toContain('正常资源 01.mkv')
    expect(text).toContain('[已隐藏资源地址]')
    expect(text).not.toContain('mikan.example')
    expect(text).not.toContain('urn:btih')
    expect(text).not.toContain('/srv/library')

    document.querySelector<HTMLElement>('#resource-detail-tab-excluded')?.click()
    await nextTick()
    const excludedText = document.querySelector('#resource-detail-panel-excluded')?.textContent ?? ''
    expect(excludedText).toContain('[已隐藏本地路径]')
    expect(excludedText).not.toContain('/srv/library')
    expect(excludedText).not.toContain('urn:btih')
  })

  it('never renders addresses or paths embedded inside a mixed line or attribute', async () => {
    const canary = 'CANARY-dialog-7f3a'
    const { wrapper } = mountDialog({
      effective: [
        'foo=/srv/private/a.mkv',
        `路径说明：/srv/${canary}/02.mkv`,
        '资源位于/srv/private/03.mkv',
        '正常资源 01.mkv',
      ],
      excluded: [
        { name: 'path=C:\\secret\\a.mkv', reason: '命中规则：https://example.invalid/private.xml' },
        { name: 'x=\\\\server\\share\\file.mkv', reason: '排除原因：magnet:?xt=urn:btih:deadbeef' },
      ],
    })
    await wrapper.find('#open-resources').trigger('click')
    await nextTick()

    const dialog = document.querySelector('.resource-dialog')
    const text = dialog?.textContent ?? ''
    expect(text).toContain('正常资源 01.mkv')
    expect(text).toContain('[已隐藏本地路径]')
    expect(text).not.toContain('/srv/private')
    expect(text).not.toContain('C:\\secret')
    expect(text).not.toContain('\\\\server\\share')
    expect(text).not.toContain(canary)

    document.querySelector<HTMLElement>('#resource-detail-tab-excluded')?.click()
    await nextTick()
    const excludedText = document.querySelector('#resource-detail-panel-excluded')?.textContent ?? ''
    expect(excludedText).not.toContain('C:\\secret')
    expect(excludedText).not.toContain('\\\\server\\share')
    expect(excludedText).not.toContain('example.invalid')
    expect(excludedText).not.toContain('urn:btih')
    expect(excludedText).toContain('[已隐藏本地路径]')
    expect(excludedText).toContain('[已隐藏资源地址]')
    // 敏感值也不得进入任何 DOM 属性。
    const markup = dialog?.outerHTML ?? ''
    expect(markup).not.toContain('/srv/private')
    expect(markup).not.toContain('example.invalid')
    expect(markup).not.toContain(canary)
  })

  it('never renders single-segment absolute paths in text or attributes', async () => {
    const canary = 'CANARY-dialog-single-5e1a'
    const { wrapper } = mountDialog({
      effective: ['/private', `缓存目录：/${canary}`, '正常资源 01.mkv'],
      excluded: [
        { name: '临时目录 /tmp', reason: '排除原因：/srv' },
        { name: '根目录=/home', reason: `缓存目录：/${canary}` },
      ],
    })
    await wrapper.find('#open-resources').trigger('click')
    await nextTick()

    const dialog = document.querySelector('.resource-dialog')
    const text = dialog?.textContent ?? ''
    const markup = dialog?.outerHTML ?? ''
    for (const surface of [text, markup]) {
      expect(surface).not.toContain('/private')
      expect(surface).not.toContain('/tmp')
      expect(surface).not.toContain('/home')
      expect(surface).not.toContain('/srv')
      expect(surface).not.toContain(canary)
    }
    expect(text).toContain('[已隐藏本地路径]')
    expect(text).toContain('正常资源 01.mkv')

    document.querySelector<HTMLElement>('#resource-detail-tab-excluded')?.click()
    await nextTick()
    const excludedText = document.querySelector('#resource-detail-panel-excluded')?.textContent ?? ''
    const excludedMarkup = document.querySelector('#resource-detail-panel-excluded')?.outerHTML ?? ''
    for (const surface of [excludedText, excludedMarkup]) {
      expect(surface).not.toContain('/tmp')
      expect(surface).not.toContain('/home')
      expect(surface).not.toContain('/srv')
      expect(surface).not.toContain(canary)
    }
    expect(excludedText).toContain('[已隐藏本地路径]')
  })

  it('hides hyphen-separated paths while keeping CJK slash titles readable', async () => {
    const canary = 'CANARY-dialog-hyphen-8f30'
    const { wrapper } = mountDialog({
      effective: [
        `缓存目录-/srv/${canary}`,
        `说明-/tmp/${canary}`,
        '孤独/摇滚！- 01.mkv',
      ],
      excluded: [
        { name: '鬼滅の刃/遊郭編 - 01 [1080p].mkv', reason: `说明-/mnt/${canary}` },
      ],
    })
    await wrapper.find('#open-resources').trigger('click')
    await nextTick()

    const dialog = document.querySelector('.resource-dialog')
    const text = dialog?.textContent ?? ''
    const markup = dialog?.outerHTML ?? ''
    for (const surface of [text, markup]) {
      expect(surface).not.toContain(canary)
      expect(surface).not.toContain('/srv')
      expect(surface).not.toContain('/tmp')
      expect(surface).not.toContain('/mnt')
    }
    expect(text).toContain('[已隐藏本地路径]')
    expect(text).toContain('孤独/摇滚！- 01.mkv')

    document.querySelector<HTMLElement>('#resource-detail-tab-excluded')?.click()
    await nextTick()
    const excludedText = document.querySelector('#resource-detail-panel-excluded')?.textContent ?? ''
    const excludedMarkup = document.querySelector('#resource-detail-panel-excluded')?.outerHTML ?? ''
    for (const surface of [excludedText, excludedMarkup]) {
      expect(surface).not.toContain(canary)
      expect(surface).not.toContain('/mnt')
    }
    expect(excludedText).toContain('[已隐藏本地路径]')
    expect(excludedText).toContain('鬼滅の刃/遊郭編 - 01 [1080p].mkv')
  })

  it('hides paths after closing delimiters and keyword connectors', async () => {
    const canary = 'CANARY-dialog-bypass-3a71'
    const { wrapper } = mountDialog({
      effective: [
        `说明）/private/${canary}`,
        `路径】/srv/${canary}`,
        `缓存目录为/srv/${canary}`,
        '孤独/摇滚！- 01.mkv',
      ],
      excluded: [
        { name: `资源在/tmp/${canary}`, reason: `文件路径是/home/${canary}` },
        { name: '鬼滅の刃/遊郭編 - 01 [1080p].mkv', reason: `存储位置为/var/${canary}` },
      ],
    })
    await wrapper.find('#open-resources').trigger('click')
    await nextTick()

    const dialog = document.querySelector('.resource-dialog')
    const text = dialog?.textContent ?? ''
    const markup = dialog?.outerHTML ?? ''
    for (const surface of [text, markup]) {
      expect(surface).not.toContain(canary)
      expect(surface).not.toContain('/private')
      expect(surface).not.toContain('/srv')
      expect(surface).not.toContain('/tmp')
      expect(surface).not.toContain('/home')
      expect(surface).not.toContain('/var')
    }
    expect(text).toContain('[已隐藏本地路径]')
    expect(text).toContain('孤独/摇滚！- 01.mkv')

    document.querySelector<HTMLElement>('#resource-detail-tab-excluded')?.click()
    await nextTick()
    const excludedText = document.querySelector('#resource-detail-panel-excluded')?.textContent ?? ''
    const excludedMarkup = document.querySelector('#resource-detail-panel-excluded')?.outerHTML ?? ''
    for (const surface of [excludedText, excludedMarkup]) {
      expect(surface).not.toContain(canary)
      expect(surface).not.toContain('/tmp')
      expect(surface).not.toContain('/home')
      expect(surface).not.toContain('/var')
    }
    expect(excludedText).toContain('[已隐藏本地路径]')
    expect(excludedText).toContain('鬼滅の刃/遊郭編 - 01 [1080p].mkv')
  })

  it('closes on Escape and restores focus to the trigger and the pane scroll position', async () => {
    const { wrapper } = mountDialog()
    const scroller = document.createElement('div')
    scroller.style.overflowY = 'auto'
    document.body.appendChild(scroller)
    scroller.appendChild(wrapper.element)
    scroller.scrollTop = 120

    const trigger = wrapper.find('#open-resources').element as HTMLElement
    trigger.focus()
    await trigger.click()
    await nextTick()
    expect(document.querySelector('.resource-dialog')).not.toBeNull()
    // 打开时焦点进入弹窗（焦点陷阱的第一项：关闭按钮）。
    expect(document.activeElement?.id).toBe('resource-detail-close-icon')

    scroller.scrollTop = 400
    document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }))
    await nextTick()

    expect(document.querySelector('.resource-dialog')).toBeNull()
    expect(document.activeElement).toBe(trigger)
    expect(scroller.scrollTop).toBe(120)
    scroller.remove()
  })

  it('releases the focus trap and the inert siblings when unmounted while still open', async () => {
    // 已确认缺陷：弹窗打开时若组件因路由切换／父组件卸载被直接销毁，正常关闭路径
    // 的 deactivate() 不会执行，document 上的键盘监听与被设为 inert 的兄弟节点会
    // 一起遗留，后续页面无法用 Tab 访问。
    const { wrapper } = mountDialog()
    const outside = document.createElement('button')
    outside.id = 'outside-surface'
    document.body.appendChild(outside)

    await wrapper.find('#open-resources').trigger('click')
    await nextTick()
    expect(document.querySelector('.resource-dialog')).not.toBeNull()
    expect(outside.hasAttribute('inert')).toBe(true)

    wrapper.unmount()
    await nextTick()

    expect(document.querySelector('.resource-dialog')).toBeNull()
    expect(outside.hasAttribute('inert')).toBe(false)
    expect(Array.from(document.body.children).some((node) => node.hasAttribute('inert'))).toBe(false)
    // 键盘陷阱已解除：Tab 不再被吞掉，焦点可以落在弹窗之外的页面元素上。
    const tab = new KeyboardEvent('keydown', { key: 'Tab', bubbles: true, cancelable: true })
    document.dispatchEvent(tab)
    expect(tab.defaultPrevented).toBe(false)
    outside.focus()
    expect(document.activeElement).toBe(outside)
    outside.remove()
  })

  it('unmounts cleanly after a normal close and when it was never opened', async () => {
    const neverOpened = mountDialog()
    expect(() => neverOpened.wrapper.unmount()).not.toThrow()

    const closed = mountDialog()
    await closed.wrapper.find('#open-resources').trigger('click')
    await nextTick()
    document.querySelector<HTMLElement>('#resource-detail-close')?.click()
    await nextTick()
    expect(document.querySelector('.resource-dialog')).toBeNull()
    expect(() => closed.wrapper.unmount()).not.toThrow()
    expect(Array.from(document.body.children).some((node) => node.hasAttribute('inert'))).toBe(false)
  })

  it('never activates the trap when the dialog is closed before the open tick settles', async () => {
    // 已确认竞态：openDialog() 把 activate() 放在 nextTick()，若在这个 tick 之前
    // 立刻 close()，deactivate() 当时还是 no-op，而排队的 activate() 仍会执行，
    // 在弹窗已经不在 DOM 里时留下 document keydown 监听（Tab 被吞、Escape 被拦）。
    const { dialog, wrapper } = mountDialog()
    dialog.value?.open('effective')
    // 不等 nextTick，直接关闭。
    dialog.value?.close()
    await nextTick()
    await nextTick()

    expect(document.querySelector('.resource-dialog')).toBeNull()
    expect(Array.from(document.body.children).some((node) => node.hasAttribute('inert'))).toBe(false)

    const tab = new KeyboardEvent('keydown', { key: 'Tab', bubbles: true, cancelable: true })
    document.dispatchEvent(tab)
    expect(tab.defaultPrevented).toBe(false)
    const escape = new KeyboardEvent('keydown', { key: 'Escape', bubbles: true, cancelable: true })
    document.dispatchEvent(escape)
    expect(escape.defaultPrevented).toBe(false)
    expect(wrapper.find('#open-resources').exists()).toBe(true)
  })

  it('never activates the trap when the dialog is unmounted before the open tick settles', async () => {
    const { dialog, wrapper } = mountDialog()
    dialog.value?.open('effective')
    // 不等 nextTick，直接卸载（路由切换／父组件销毁的真实路径）。
    wrapper.unmount()
    await nextTick()
    await nextTick()

    expect(document.querySelector('.resource-dialog')).toBeNull()
    expect(Array.from(document.body.children).some((node) => node.hasAttribute('inert'))).toBe(false)
    const tab = new KeyboardEvent('keydown', { key: 'Tab', bubbles: true, cancelable: true })
    document.dispatchEvent(tab)
    expect(tab.defaultPrevented).toBe(false)
    const escape = new KeyboardEvent('keydown', { key: 'Escape', bubbles: true, cancelable: true })
    document.dispatchEvent(escape)
    expect(escape.defaultPrevented).toBe(false)
  })

  it('still restores focus and the scroll position on a normal close after the tick', async () => {
    const { dialog, wrapper } = mountDialog()
    const scroller = document.createElement('div')
    scroller.style.overflowY = 'auto'
    document.body.appendChild(scroller)
    scroller.appendChild(wrapper.element)
    scroller.scrollTop = 90

    const trigger = wrapper.find('#open-resources').element as HTMLElement
    trigger.focus()
    dialog.value?.open('effective')
    await nextTick()
    expect(document.querySelector('.resource-dialog')).not.toBeNull()
    expect(document.activeElement?.id).toBe('resource-detail-close-icon')

    scroller.scrollTop = 300
    dialog.value?.close()
    await nextTick()
    expect(document.querySelector('.resource-dialog')).toBeNull()
    expect(document.activeElement).toBe(trigger)
    expect(scroller.scrollTop).toBe(90)
    scroller.remove()
  })

  it('renders every resource of a long list inside the dialog and closes from the footer', async () => {
    const effective = Array.from({ length: 24 }, (_, index) => `星海旅途 S01E${String(index + 1).padStart(2, '0')} 1080p.mkv`)
    const { wrapper } = mountDialog({ effective, excluded: [] })
    await wrapper.find('#open-resources').trigger('click')
    await nextTick()

    expect(document.querySelectorAll('#resource-detail-panel-effective .resource-dialog-item')).toHaveLength(24)
    expect(document.querySelector('#resource-detail-count')?.textContent).toContain('向下滚动查看')

    document.querySelector<HTMLElement>('#resource-detail-close')?.click()
    await nextTick()
    expect(document.querySelector('.resource-dialog')).toBeNull()
  })
})
