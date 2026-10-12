import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'

import SubtitleGroupSelect from '@/features/workbench/SubtitleGroupSelect.vue'

describe('SubtitleGroupSelect', () => {
  it('is controlled and emits the selected public value', async () => {
    const wrapper = mount(SubtitleGroupSelect, {
      props: {
        modelValue: '喵萌奶茶屋',
        options: [{ value: '喵萌奶茶屋', label: '喵萌奶茶屋' }, { value: 'Loli', label: 'Loli' }],
      },
      global: { stubs: { BaseSelect: false } },
    })

    await wrapper.find('select').setValue('Loli')

    expect(wrapper.emitted('update:modelValue')).toEqual([['Loli']])
    expect(wrapper.text()).toContain('Loli')
  })

  it('does not expose applying state as draft data and disables selection while applying', () => {
    const wrapper = mount(SubtitleGroupSelect, {
      props: {
        modelValue: '喵萌奶茶屋',
        options: [{ value: '喵萌奶茶屋', label: '喵萌奶茶屋' }],
        applying: true,
      },
    })

    expect(wrapper.find('select').element).toHaveProperty('disabled', true)
    expect(wrapper.text()).toContain('正在重新计算订阅方案')
    expect(wrapper.text()).not.toContain('draft_id')
  })
})
