/**
 * useFocusTrap (US-200).
 *
 * Focus primitive for modal-style overlays (ConfirmDialog). While active it:
 *
 * - traps Tab/Shift+Tab within the container (cyclic focus),
 * - calls `onEscape` when Escape is pressed,
 * - marks every sibling of the container as `inert` so screen readers and
 *   keyboard users cannot reach the background content,
 * - remembers the previously focused element and restores focus to it on
 *   `deactivate()` (focus restore).
 *
 * The composable touches only DOM attributes (`inert`) and keyboard events;
 * it stores no sensitive data and is safe to use in any feature.
 */
import type { Ref } from 'vue'

const FOCUSABLE_SELECTOR = [
  'a[href]',
  'button:not([disabled])',
  'input:not([disabled])',
  'select:not([disabled])',
  'textarea:not([disabled])',
  '[tabindex]:not([tabindex="-1"])',
].join(', ')

export interface FocusTrap {
  /** Start trapping. Focuses the first focusable element (or the container). */
  activate: () => void
  /** Stop trapping and restore focus to the previously focused element. */
  deactivate: () => void
  /** True while the trap is active. */
  isActive: () => boolean
}

function getFocusable(root: HTMLElement | null): HTMLElement[] {
  if (!root) return []
  return Array.from(root.querySelectorAll<HTMLElement>(FOCUSABLE_SELECTOR)).filter(
    (element) => !element.hasAttribute('disabled'),
  )
}

function setSiblingsInert(element: HTMLElement, enabled: boolean): void {
  const parent = element.parentElement
  if (!parent) return
  for (const child of Array.from(parent.children)) {
    if (child !== element) {
      if (enabled) {
        child.setAttribute('inert', '')
      } else {
        child.removeAttribute('inert')
      }
    }
  }
}

export function useFocusTrap(container: Ref<HTMLElement | null>, onEscape?: () => void): FocusTrap {
  let active = false
  let restoreTarget: HTMLElement | null = null

  function onKeydown(event: KeyboardEvent): void {
    if (event.key === 'Escape') {
      event.preventDefault()
      onEscape?.()
      return
    }
    if (event.key !== 'Tab') return

    const focusables = getFocusable(container.value)
    const first = focusables[0]
    const last = focusables[focusables.length - 1]
    if (!first || !last) {
      event.preventDefault()
      return
    }

    const current = document.activeElement instanceof HTMLElement ? document.activeElement : null
    const inside = current !== null && container.value?.contains(current) === true

    if (event.shiftKey) {
      if (!inside || current === first) {
        event.preventDefault()
        last.focus()
      }
    } else if (!inside || current === last) {
      event.preventDefault()
      first.focus()
    }
  }

  function activate(): void {
    if (active) return
    active = true
    restoreTarget = document.activeElement instanceof HTMLElement ? document.activeElement : null
    const root = container.value
    if (root) {
      setSiblingsInert(root, true)
      const first = getFocusable(root)[0]
      if (first) {
        first.focus()
      } else {
        root.setAttribute('tabindex', '-1')
        root.focus()
      }
    }
    document.addEventListener('keydown', onKeydown)
  }

  function deactivate(): void {
    if (!active) return
    active = false
    document.removeEventListener('keydown', onKeydown)
    const root = container.value
    if (root) {
      setSiblingsInert(root, false)
    }
    if (restoreTarget) {
      restoreTarget.focus()
      restoreTarget = null
    }
  }

  return { activate, deactivate, isActive: () => active }
}
