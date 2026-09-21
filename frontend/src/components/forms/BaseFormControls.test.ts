import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'

import BaseButton from '@/components/forms/BaseButton.vue'
import BaseInput from '@/components/forms/BaseInput.vue'
import BaseTextarea from '@/components/forms/BaseTextarea.vue'

describe('BaseInput (US-200)', () => {
  it('renders with label, type and passes through attrs', () => {
    const wrapper = mount(BaseInput, {
      props: { label: '服务地址', type: 'password' },
      attrs: { id: 'endpoint', autocomplete: 'off' },
    })
    const input = wrapper.find('input')
    expect(input.attributes('type')).toBe('password')
    expect(input.attributes('aria-label')).toBe('服务地址')
    expect(input.attributes('id')).toBe('endpoint')
    expect(input.attributes('autocomplete')).toBe('off')
  })

  it('supports v-model and emits update:modelValue on input', async () => {
    const wrapper = mount(BaseInput, {
      props: { modelValue: 'initial' },
    })
    const input = wrapper.find('input')
    expect((input.element as HTMLInputElement).value).toBe('initial')

    await input.setValue('http://qb.local')
    expect(wrapper.emitted('update:modelValue')).toEqual([['http://qb.local']])
  })

  it('sets aria-invalid when invalid is true', () => {
    const wrapper = mount(BaseInput, {
      props: { invalid: true },
    })
    expect(wrapper.find('input').attributes('aria-invalid')).toBe('true')
  })

  it('does not set aria-invalid when valid', () => {
    const wrapper = mount(BaseInput)
    expect(wrapper.find('input').attributes('aria-invalid')).toBeUndefined()
  })
})

describe('BaseTextarea (US-200)', () => {
  it('renders with label and passes through attrs', () => {
    const wrapper = mount(BaseTextarea, {
      props: { label: '偏好字幕组' },
      attrs: { id: 'preferred', rows: '4' },
    })
    const textarea = wrapper.find('textarea')
    expect(textarea.attributes('aria-label')).toBe('偏好字幕组')
    expect(textarea.attributes('id')).toBe('preferred')
    expect(textarea.attributes('rows')).toBe('4')
  })

  it('supports v-model', async () => {
    const wrapper = mount(BaseTextarea, {
      props: { modelValue: '喵萌' },
    })
    await wrapper.find('textarea').setValue('Loli')
    expect(wrapper.emitted('update:modelValue')).toEqual([['Loli']])
  })
})

describe('BaseButton (US-362)', () => {
  it('defaults to the 44px medium control and offers the 52px home-page size', () => {
    const medium = mount(BaseButton, { slots: { default: '搜索' } })
    expect(medium.classes()).toContain('base-button-md')
    expect(medium.attributes('aria-busy')).toBeUndefined()

    const large = mount(BaseButton, { props: { size: 'lg' }, slots: { default: '搜索候选合集' } })
    expect(large.classes()).toContain('base-button-lg')
  })

  it('keeps the loading label and busy state instead of collapsing to a spinner', () => {
    const wrapper = mount(BaseButton, { props: { loading: true }, slots: { default: '搜索' } })
    expect(wrapper.attributes('aria-busy')).toBe('true')
    expect(wrapper.attributes('disabled')).toBeDefined()
    expect(wrapper.find('.base-button-spinner').exists()).toBe(true)
    expect(wrapper.find('.base-button-loading-label').text()).toBe('处理中…')
  })

  it('accepts a custom loading label and keeps the button geometry variant', () => {
    const wrapper = mount(BaseButton, {
      props: { loading: true, size: 'lg', loadingLabel: '正在搜索' },
      slots: { default: '搜索' },
    })
    expect(wrapper.classes()).toContain('base-button-lg')
    expect(wrapper.find('.base-button-loading-label').text()).toBe('正在搜索')
  })
})
