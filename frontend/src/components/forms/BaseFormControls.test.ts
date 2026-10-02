import { mount } from '@vue/test-utils'
import { defineComponent } from 'vue'
import { describe, expect, it } from 'vitest'

import BaseButton from '@/components/forms/BaseButton.vue'
import BaseInput from '@/components/forms/BaseInput.vue'
import BaseTextarea from '@/components/forms/BaseTextarea.vue'
import CheckboxRow from '@/components/forms/CheckboxRow.vue'

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

describe('CheckboxRow (#156)', () => {
  it('keeps the id on the native input and associates both labels with it', () => {
    const wrapper = mount(CheckboxRow, {
      props: { label: '全选当前可见可确认项' },
      attrs: { id: 'select-all', class: 'batch-card-checkbox-row' },
    })
    const input = wrapper.find('input[type="checkbox"]')
    expect(input.attributes('id')).toBe('select-all')
    // 包装层不得复制 id（否则 label/for 会指向错误节点）。
    expect(wrapper.attributes('id')).toBeUndefined()
    const labels = wrapper.findAll('label')
    expect(labels).toHaveLength(2)
    expect(labels.map((label) => label.attributes('for'))).toEqual(['select-all', 'select-all'])
    // 透传的 class 仍落在原生 input 上，既有选择器保持有效。
    expect(input.classes()).toContain('batch-card-checkbox-row')
  })

  it('keeps an explicit id unique and generates one when absent', () => {
    const first = mount(CheckboxRow, { props: { label: 'A' } })
    const firstId = first.find('input').attributes('id')
    expect(firstId).toBeTruthy()
    expect(first.find('label').attributes('for')).toBe(firstId)

    // 同一棵组件树内自动 id 必须唯一（useId 的保证范围）。
    const pair = mount(
      defineComponent({
        components: { CheckboxRow },
        template: '<div><CheckboxRow label="A" /><CheckboxRow label="B" /></div>',
      }),
    )
    const ids = pair.findAll('input').map((input) => input.attributes('id'))
    expect(ids).toHaveLength(2)
    expect(new Set(ids).size).toBe(2)
  })

  it('is controlled by checked and emits update:checked from the native change event', async () => {
    const wrapper = mount(CheckboxRow, { props: { label: '只看需处理', checked: false } })
    const input = wrapper.find('input')
    expect((input.element as HTMLInputElement).checked).toBe(false)
    await input.setValue(true)
    expect(wrapper.emitted('update:checked')).toEqual([[true]])
    // 受控：prop 未变化前不自行翻转 DOM 状态之外的权威值。
    await wrapper.setProps({ checked: true })
    expect((wrapper.find('input').element as HTMLInputElement).checked).toBe(true)
  })

  it('applies indeterminate as a DOM property, not an attribute', async () => {
    const wrapper = mount(CheckboxRow, { props: { label: '部分选择', indeterminate: true } })
    const input = wrapper.find('input').element as HTMLInputElement
    expect(input.indeterminate).toBe(true)
    expect(wrapper.find('input').attributes('indeterminate')).toBeUndefined()
    await wrapper.setProps({ indeterminate: false })
    expect(input.indeterminate).toBe(false)
  })

  it('renders help copy and forwards disabled to the native control', () => {
    const wrapper = mount(CheckboxRow, {
      props: { label: '搜索无结果时使用直连合集', help: '仅用于本次生成。', checked: true },
      attrs: { disabled: true },
    })
    expect(wrapper.find('.checkbox-row-help').text()).toBe('仅用于本次生成。')
    const input = wrapper.find('input')
    expect(input.attributes('disabled')).toBeDefined()
    expect((input.element as HTMLInputElement).checked).toBe(true)
  })
})
