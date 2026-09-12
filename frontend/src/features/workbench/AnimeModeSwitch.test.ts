import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'

import AnimeModeSwitch from '@/features/workbench/AnimeModeSwitch.vue'

describe('AnimeModeSwitch', () => {
  it('starts with single mode selected and changes with keyboard', async () => {
    const wrapper = mount(AnimeModeSwitch)
    expect(wrapper.find('#anime-mode-single').attributes('aria-selected')).toBe('true')

    await wrapper.find('#anime-mode-single').trigger('keydown', { key: 'ArrowRight' })

    expect(wrapper.emitted('update:modelValue')?.[0]).toEqual(['batch'])
  })
})
