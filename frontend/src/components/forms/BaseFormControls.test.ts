import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'

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
