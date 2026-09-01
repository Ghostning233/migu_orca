import { beforeEach, describe, expect, it } from 'vitest'

import { useSensitiveFields } from '@/app/composables/useSensitiveFields'

// Vitest runs with jsdom; onUnmounted only fires when the component unmounts,
// so these tests exercise the plain composable API directly.
function makeFields() {
  return useSensitiveFields({
    endpoint: { label: '服务地址', required: true },
    username: { label: '用户名', required: true },
    password: { label: '密码', required: true },
    token: { label: 'API Token' },
  })
}

describe('useSensitiveFields (US-200)', () => {
  beforeEach(() => {
    localStorage.clear()
    sessionStorage.clear()
  })

  it('starts empty and snapshot omits empty values', () => {
    const fields = makeFields()
    expect(fields.snapshot()).toEqual({})
    expect(fields.get('endpoint')).toBe('')
  })

  it('keeps values in component-local memory until cleared', () => {
    const fields = makeFields()
    fields.set('endpoint', 'http://qb.local')
    fields.set('password', 'secret')
    expect(fields.snapshot()).toEqual({ endpoint: 'http://qb.local', password: 'secret' })
  })

  it('reset() clears every field (auth-mode switch / cancel)', () => {
    const fields = makeFields()
    fields.set('endpoint', 'http://qb.local')
    fields.set('token', 'tok-1')
    fields.reset()
    expect(fields.snapshot()).toEqual({})
    expect(fields.get('token')).toBe('')
  })

  it('clearAll() clears every field (success)', () => {
    const fields = makeFields()
    fields.set('endpoint', 'http://qb.local')
    fields.set('username', 'user')
    fields.set('password', 'pw')
    fields.clearAll()
    expect(fields.snapshot()).toEqual({})
  })

  it('firstMissing() reports the first required field missing', () => {
    const fields = makeFields()
    expect(fields.firstMissing()).toBe('endpoint')
    fields.set('endpoint', 'http://qb.local')
    expect(fields.firstMissing()).toBe('username')
    fields.set('username', 'u')
    expect(fields.firstMissing()).toBe('password')
    fields.set('password', 'p')
    expect(fields.firstMissing()).toBeNull()
  })

  it('firstMissing() ignores optional fields (token not required)', () => {
    const fields = makeFields()
    fields.set('endpoint', 'e')
    fields.set('username', 'u')
    fields.set('password', 'p')
    // token is optional → no missing field even though it is empty.
    expect(fields.firstMissing()).toBeNull()
  })

  it('snapshot() returns a fresh object (never a live reference)', () => {
    const fields = makeFields()
    fields.set('endpoint', 'http://qb.local')
    const first = fields.snapshot()
    fields.set('password', 'pw')
    expect(first).toEqual({ endpoint: 'http://qb.local' })
    expect(fields.snapshot()).toEqual({ endpoint: 'http://qb.local', password: 'pw' })
  })

  it('field() registers a new request-scoped field lazily', () => {
    const fields = makeFields()
    fields.set('endpoint', 'e')
    fields.set('username', 'u')
    fields.set('password', 'p')
    fields.field('session_id', { label: '会话', required: true })
    fields.set('session_id', 'abc')
    expect(fields.get('session_id')).toBe('abc')
    expect(fields.firstMissing()).toBeNull()
  })

  it('clearing is idempotent', () => {
    const fields = makeFields()
    fields.clearAll()
    fields.clearAll()
    fields.reset()
    expect(fields.snapshot()).toEqual({})
  })

  it('never writes values to browser storage', () => {
    const fields = makeFields()
    fields.set('endpoint', 'http://qb.local')
    fields.set('token', 'super-secret-token')
    expect(localStorage.length).toBe(0)
    expect(sessionStorage.length).toBe(0)
  })
})
