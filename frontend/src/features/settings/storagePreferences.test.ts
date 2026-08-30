import { beforeEach, describe, expect, it } from 'vitest'

import {
  STORAGE_DIR_KEY,
  SAVE_REQUEST_KEY,
  clearStoragePreferences,
  isAbsoluteStorageProfile,
  loadStoragePreferences,
  sanitizeStorageProfile,
  saveStoragePreferences,
} from '@/features/settings/storagePreferences'

// US-201: the Settings page persists ONLY non-sensitive browser preferences —
// a server-root-relative storage profile and the default-save toggle — using
// the same localStorage keys as the legacy page (smooth migration). Absolute
// paths, `..` traversal and anything that would escape the server root must
// be dropped so they can never leak into API payloads or URLs (US-193).

function seed(key: string, value: string): void {
  window.localStorage.setItem(key, value)
}

describe('sanitizeStorageProfile (US-201 / US-193)', () => {
  beforeEach(() => {
    localStorage.clear()
  })

  it('keeps a safe relative profile', () => {
    expect(sanitizeStorageProfile('backups')).toBe('backups')
    expect(sanitizeStorageProfile('  backups/sub  ')).toBe('backups/sub')
  })

  it('drops Unix absolute paths', () => {
    expect(sanitizeStorageProfile('/etc/passwd')).toBe('')
    expect(sanitizeStorageProfile('/home/user/storage')).toBe('')
  })

  it('drops Windows absolute paths (drive letter)', () => {
    expect(sanitizeStorageProfile('C:\\Users\\x')).toBe('')
    expect(sanitizeStorageProfile('D:/storage')).toBe('')
  })

  it('drops traversal attempts', () => {
    expect(sanitizeStorageProfile('../../etc')).toBe('')
    expect(sanitizeStorageProfile('a/../..')).toBe('')
    expect(sanitizeStorageProfile('..\\..\\win')).toBe('')
  })

  it('treats empty as the server default root', () => {
    expect(sanitizeStorageProfile('')).toBe('')
    expect(sanitizeStorageProfile('   ')).toBe('')
  })

  it('isAbsoluteStorageProfile detects only real absolute paths', () => {
    expect(isAbsoluteStorageProfile('/abs')).toBe(true)
    expect(isAbsoluteStorageProfile('C:/abs')).toBe(true)
    expect(isAbsoluteStorageProfile('C:\\abs')).toBe(true)
    expect(isAbsoluteStorageProfile('backups')).toBe(false)
    expect(isAbsoluteStorageProfile('')).toBe(false)
  })
})

describe('loadStoragePreferences / saveStoragePreferences (US-201)', () => {
  beforeEach(() => {
    localStorage.clear()
  })

  it('defaults to server root + save-request true when nothing saved', () => {
    expect(loadStoragePreferences()).toEqual({ storageDir: '', saveRequest: true })
  })

  it('loads saved values with the legacy keys', () => {
    seed(STORAGE_DIR_KEY, 'backups')
    seed(SAVE_REQUEST_KEY, 'false')
    expect(loadStoragePreferences()).toEqual({ storageDir: 'backups', saveRequest: false })
  })

  it('sanitizes an unsafe legacy value and removes it from storage', () => {
    seed(STORAGE_DIR_KEY, '/etc/passwd')
    const loaded = loadStoragePreferences()
    expect(loaded).toEqual({ storageDir: '', saveRequest: true })
    // The unsafe value is dropped from storage so it can never leak into a
    // later API payload/URL (same smooth-migration behavior as the legacy page).
    expect(window.localStorage.getItem(STORAGE_DIR_KEY)).toBeNull()
  })

  it('persists only safe relative profiles', () => {
    saveStoragePreferences({ storageDir: 'backups', saveRequest: false })
    expect(window.localStorage.getItem(STORAGE_DIR_KEY)).toBe('backups')
    expect(window.localStorage.getItem(SAVE_REQUEST_KEY)).toBe('false')
  })

  it('never persists an unsafe profile (falls back to server root)', () => {
    saveStoragePreferences({ storageDir: '/tmp/evil', saveRequest: true })
    expect(window.localStorage.getItem(STORAGE_DIR_KEY)).toBeNull()
    expect(loadStoragePreferences().storageDir).toBe('')
  })

  it('clearStoragePreferences removes both keys and restores defaults', () => {
    saveStoragePreferences({ storageDir: 'backups', saveRequest: false })
    clearStoragePreferences()
    expect(window.localStorage.getItem(STORAGE_DIR_KEY)).toBeNull()
    expect(window.localStorage.getItem(SAVE_REQUEST_KEY)).toBeNull()
    expect(loadStoragePreferences()).toEqual({ storageDir: '', saveRequest: true })
  })
})
