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

describe('AnimeModeSwitch (US-362)', () => {
  it('supports mouse selection and keeps exactly one block selected', async () => {
    const wrapper = mount(AnimeModeSwitch, { props: { modelValue: 'single' } })
    await wrapper.find('#anime-mode-batch').trigger('click')
    expect(wrapper.emitted('update:modelValue')?.at(-1)).toEqual(['batch'])
    expect(wrapper.find('#anime-mode-single').attributes('aria-selected')).toBe('true')
    expect(wrapper.find('#anime-mode-batch').attributes('aria-selected')).toBe('false')
  })

  it('moves to the next option with arrow keys and selects with Enter or Space', async () => {
    const wrapper = mount(AnimeModeSwitch, { props: { modelValue: 'single' } })
    await wrapper.find('#anime-mode-single').trigger('keydown', { key: 'ArrowRight' })
    expect(wrapper.emitted('update:modelValue')?.at(-1)).toEqual(['batch'])

    const second = mount(AnimeModeSwitch, { props: { modelValue: 'batch' } })
    await second.find('#anime-mode-batch').trigger('keydown', { key: 'ArrowLeft' })
    expect(second.emitted('update:modelValue')?.at(-1)).toEqual(['single'])

    // Enter / Space activate the focused option; re-activating the option that
    // is already selected is a no-op (no duplicate emit).
    const third = mount(AnimeModeSwitch, { props: { modelValue: 'single' } })
    await third.find('#anime-mode-single').trigger('keydown', { key: 'Enter' })
    expect(third.emitted('update:modelValue')).toBeUndefined()
    await third.find('#anime-mode-batch').trigger('keydown', { key: ' ' })
    expect(third.emitted('update:modelValue')?.at(-1)).toEqual(['batch'])
  })

  it('only emits the new mode: the host owns and preserves unsaved input', async () => {
    const wrapper = mount(AnimeModeSwitch, { props: { modelValue: 'single' } })
    await wrapper.find('#anime-mode-batch').trigger('click')
    expect(wrapper.emitted('update:modelValue')).toHaveLength(1)
    expect(wrapper.emitted('update:modelValue')?.[0]).toEqual(['batch'])
  })

  it('exposes roving tabindex so keyboard users reach one stop', () => {
    const wrapper = mount(AnimeModeSwitch, { props: { modelValue: 'batch' } })
    expect(wrapper.find('#anime-mode-batch').attributes('tabindex')).toBe('0')
    expect(wrapper.find('#anime-mode-single').attributes('tabindex')).toBe('-1')
  })
})
