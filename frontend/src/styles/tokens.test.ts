import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'

import { describe, expect, it } from 'vitest'

const tokens = readFileSync(resolve(process.cwd(), 'src/styles/tokens.css'), 'utf8')
const globalStyles = readFileSync(resolve(process.cwd(), 'src/styles/main.css'), 'utf8')
const sharedFocusStyles = [
  'src/components/forms/BaseButton.vue',
  'src/components/forms/BaseInput.vue',
  'src/components/forms/BaseSelect.vue',
  'src/components/forms/BaseTextarea.vue',
  'src/components/forms/CheckboxRow.vue',
  'src/styles/main.css',
].map((path) => ({
  path,
  content: readFileSync(resolve(process.cwd(), path), 'utf8'),
}))

describe('Stage 33 semantic design tokens (US-258)', () => {
  it.each([
    '--color-surface-canvas',
    '--color-text-primary',
    '--color-action-primary',
    '--color-danger-emphasis',
    '--color-focus-ring',
    '--font-family-sans',
    '--space-4',
    '--size-shell-header',
    '--radius-md',
    '--shadow-shell',
    '--z-overlay',
    '--motion-duration-standard',
  ])('defines the required semantic family %s', (name) => {
    expect(tokens).toContain(`${name}:`)
  })

  it('maps the shared semantic roles to Token V1 values and control geometry', () => {
    expect(tokens).toContain('--color-canvas: #f7f8fa')
    expect(tokens).toContain('--color-text: #10233f')
    expect(tokens).toContain('--color-primary: #0b2a55')
    expect(tokens).toContain('--color-focus: #2563eb')
    expect(tokens).toContain('--control-height-md: 44px')
    expect(tokens).toContain('--control-height-lg: 52px')
    expect(tokens).toContain('--radius-lg: 14px')
    expect(tokens).toContain('--motion-base: 180ms')
  })

  it('maps every shared focus-visible outline to the focus width token', () => {
    expect(tokens).toContain('--focus-ring-width: 3px')

    for (const { path, content } of sharedFocusStyles) {
      expect(content, path).toMatch(
        /outline:\s*var\(--focus-ring-width\)\s+solid\s+var\(--color-focus-ring\)/,
      )
      expect(content, path).not.toMatch(/outline:\s*3px\b/)
    }
  })

  it('provides a reduced-motion override for motion and scrolling', () => {
    expect(tokens).toMatch(/@media \(prefers-reduced-motion: reduce\)[\s\S]*--motion-duration-standard: 0ms/)
    expect(tokens).toMatch(/@media \(prefers-reduced-motion: reduce\)[\s\S]*--motion-distance: 0px/)
    expect(tokens).toMatch(/@media \(prefers-reduced-motion: reduce\)[\s\S]*--motion-scroll-behavior: auto/)
  })

  it('keeps brand colours, focus and shell shadow out of global style declarations', () => {
    expect(globalStyles.trimStart().startsWith("@import './tokens.css';")).toBe(true)
    expect(globalStyles).not.toMatch(/#[0-9a-f]{3,8}\b/i)
    expect(globalStyles).not.toMatch(/\brgba?\(/i)
    const shadowDeclarations = globalStyles.match(/box-shadow\s*:[^;]+;/gi) ?? []
    expect(shadowDeclarations).toEqual(['box-shadow: var(--shadow-shell);'])
    expect(globalStyles).not.toMatch(/outline:\s*[^;]*var\(--color-accent\)/i)
    expect(globalStyles).toContain('var(--color-focus-ring)')
  })
})
