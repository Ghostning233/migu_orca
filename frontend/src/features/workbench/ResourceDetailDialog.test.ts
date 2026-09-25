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
