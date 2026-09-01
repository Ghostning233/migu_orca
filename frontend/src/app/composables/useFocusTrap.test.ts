import { ref } from 'vue'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { useFocusTrap } from '@/app/composables/useFocusTrap'

function buildContainer(): { container: HTMLElement; mount: () => void } {
  const container = document.createElement('div')
  container.id = 'trap'
  const first = document.createElement('button')
  first.id = 'first'
  const last = document.createElement('button')
  last.id = 'last'
  container.append(first, last)
  const mount = () => document.body.appendChild(container)
  return { container, mount }
}

describe('useFocusTrap (US-200)', () => {
  let mount: () => void
  let container: HTMLElement
  let outside: HTMLButtonElement

  beforeEach(() => {
    document.body.innerHTML = ''
    const built = buildContainer()
    container = built.container
    mount = built.mount
    outside = document.createElement('button')
    outside.id = 'outside'
    document.body.appendChild(outside)
  })

  afterEach(() => {
    vi.restoreAllMocks()
    document.body.innerHTML = ''
  })

  it('focuses the first focusable element on activate', () => {
    mount()
    const el = ref<HTMLElement | null>(container)
    const trap = useFocusTrap(el)
    trap.activate()
    expect(document.activeElement?.id).toBe('first')
    trap.deactivate()
  })

  it('restores focus to the previously focused element on deactivate', () => {
    mount()
    outside.focus()
    const el = ref<HTMLElement | null>(container)
    const trap = useFocusTrap(el)
    trap.activate()
    expect(document.activeElement?.id).toBe('first')
    trap.deactivate()
    expect(document.activeElement?.id).toBe('outside')
  })

  it('marks siblings inert while active and unmarks them on deactivate', () => {
    mount()
    const el = ref<HTMLElement | null>(container)
    const trap = useFocusTrap(el)
    trap.activate()
    expect(outside.hasAttribute('inert')).toBe(true)
    trap.deactivate()
    expect(outside.hasAttribute('inert')).toBe(false)
  })

  it('calls onEscape when Escape is pressed', () => {
    mount()
    const onEscape = vi.fn()
    const el = ref<HTMLElement | null>(container)
    const trap = useFocusTrap(el, onEscape)
    trap.activate()

    document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }))
    expect(onEscape).toHaveBeenCalledTimes(1)
    trap.deactivate()
  })

  it('isActive reflects the trap state', () => {
    mount()
    const el = ref<HTMLElement | null>(container)
    const trap = useFocusTrap(el)
    expect(trap.isActive()).toBe(false)
    trap.activate()
    expect(trap.isActive()).toBe(true)
    trap.deactivate()
    expect(trap.isActive()).toBe(false)
  })

  it('traps Tab at the last focusable and wraps to the first', () => {
    mount()
    const el = ref<HTMLElement | null>(container)
    const trap = useFocusTrap(el)
    trap.activate()
    const last = document.getElementById('last') as HTMLButtonElement
    last.focus()
    last.dispatchEvent(new KeyboardEvent('keydown', { key: 'Tab', bubbles: true }))
    expect(document.activeElement?.id).toBe('first')
    trap.deactivate()
  })

  it('traps Shift+Tab at the first focusable and wraps to the last', () => {
    mount()
    const el = ref<HTMLElement | null>(container)
    const trap = useFocusTrap(el)
    trap.activate()
    const first = document.getElementById('first') as HTMLButtonElement
    first.dispatchEvent(
      new KeyboardEvent('keydown', { key: 'Tab', shiftKey: true, bubbles: true }),
    )
    expect(document.activeElement?.id).toBe('last')
    trap.deactivate()
  })

  it('is safe when the container is not mounted', () => {
    const el = ref<HTMLElement | null>(container)
    const trap = useFocusTrap(el)
    expect(() => trap.activate()).not.toThrow()
    expect(() => trap.deactivate()).not.toThrow()
  })
})
