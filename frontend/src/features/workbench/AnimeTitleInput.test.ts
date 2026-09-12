import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'

import AnimeTitleInput from '@/features/workbench/AnimeTitleInput.vue'

describe('AnimeTitleInput', () => {
  it('keeps the single-line input free of line breaks', async () => {
    const wrapper = mount(AnimeTitleInput, { props: { mode: 'single' } })
    await wrapper.find('input').setValue('第一行第二行')

    expect(wrapper.emitted('update:modelValue')?.at(-1)).toEqual(['第一行第二行'])
  })

  it('keeps line breaks in batch mode', async () => {
    const wrapper = mount(AnimeTitleInput, { props: { mode: 'batch' } })
    await wrapper.find('textarea').setValue('第一行\n第二行')

    expect(wrapper.emitted('update:modelValue')?.at(-1)).toEqual(['第一行\n第二行'])
  })
})
