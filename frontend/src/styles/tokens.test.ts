import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'

import { describe, expect, it } from 'vitest'

const tokens = readFileSync(resolve(process.cwd(), 'src/styles/tokens.css'), 'utf8')
const globalStyles = readFileSync(resolve(process.cwd(), 'src/styles/main.css'), 'utf8')

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

  it('provides a reduced-motion override for motion and scrolling', () => {
    expect(tokens).toMatch(/@media \(prefers-reduced-motion: reduce\)[\s\S]*--motion-duration-standard: 0ms/)
    expect(tokens).toMatch(/@media \(prefers-reduced-motion: reduce\)[\s\S]*--motion-distance: 0px/)
    expect(tokens).toMatch(/@media \(prefers-reduced-motion: reduce\)[\s\S]*--motion-scroll-behavior: auto/)
  })

  it('keeps brand colours, focus and shell shadow out of global style declarations', () => {
    expect(globalStyles.trimStart().startsWith("@import './tokens.css';")).toBe(true)
    expect(globalStyles).not.toMatch(/#[0-9a-f]{3,8}\b/i)
    expect(globalStyles).not.toMatch(/\brgba?\(/i)
    expect(globalStyles).not.toMatch(/box-shadow\s*:/i)
    expect(globalStyles).not.toMatch(/outline:\s*[^;]*var\(--color-accent\)/i)
    expect(globalStyles).toContain('var(--color-focus-ring)')
  })
})
