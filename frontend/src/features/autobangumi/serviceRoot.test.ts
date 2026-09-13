import { describe, expect, it } from 'vitest'

import {
  normalizeAutoBangumiServiceRoot,
  validateAutoBangumiServiceRoot,
} from './serviceRoot'

describe('Auto Bangumi service root normalization', () => {
  it.each([
    ['http://192.168.1.20:7890', 'http://192.168.1.20:7890'],
    ['  192.168.1.20:7890/  ', 'http://192.168.1.20:7890'],
    ['localhost:7892', 'http://localhost:7892'],
    ['ab.example:7892', 'http://ab.example:7892'],
    ['autobangumi:7892', 'http://autobangumi:7892'],
    ['https://ab.example/', 'https://ab.example'],
    ['HTTP://localhost:80', 'http://localhost'],
    ['http://[::1]:7890/', 'http://[::1]:7890'],
  ])('normalizes %s', (input, expected) => {
    expect(normalizeAutoBangumiServiceRoot(input)).toBe(expected)
  })

  it.each([
    '', '   ', 'ftp://example.com', 'javascript:alert(1)', 'https:example.com',
    'javascript:7892', 'data:7892', 'file:7892', 'ftp:7892',
    'http://user:password@example.com', 'http://user@example.com',
    'http://example.com/api', 'example.com/api', 'http://example.com?x=1',
    'http://example.com#fragment', 'http://example.com:0', 'http://example.com:65536',
    'http://example.com:abc', 'http://[::1]:7890/path', '::1:7890',
    'http://example.com/.', 'http://example.com/..', 'http://example.com/foo/..',
    'http://example.com/%2e', 'http://example.com/%2e%2e', 'http://example.com//other',
    'http://example.com\\other', 'http://example.com/\\other',
    'http://example .com', 'http://foo_bar', 'http://example.com\n',
  ])('rejects unsafe or non-root value %s', (input) => {
    expect(normalizeAutoBangumiServiceRoot(input)).toBeNull()
    expect(validateAutoBangumiServiceRoot(input).message).toBeTruthy()
  })
})
