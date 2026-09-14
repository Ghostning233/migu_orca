/**
 * Storage preferences (US-201).
 *
 * Non-sensitive browser preferences that control the workbench's default
 * storage profile and save behavior. Mirrors the legacy `app.js` contract
 * (same localStorage keys, same sanitization) so a user who already visited
 * the old `/settings` page keeps their values when the new `/app/settings`
 * ships.
 *
 * Security boundary (US-193):
 * - only a *relative profile name* under the server storage root may ever be
 *   persisted (localStorage) or sent to the API; absolute paths (Unix or
 *   Windows drive), `..` traversal and symlink escapes are dropped and
 *   fall back to the server default (empty string),
 * - the empty value means "server default root" and is never sent as
 *   `storage_dir` (the server resolves it the same way),
 * - these are the ONLY browser-storage keys the Settings feature writes;
 *   credentials (endpoint/token/password/cookie) are never stored here.
 */
export const STORAGE_DIR_KEY = 'miguOrca.web.storageDir'
/** Legacy key retained as a named migration target; never written. */
export const SAVE_REQUEST_KEY = 'miguOrca.web.saveRequest'

export interface StoragePreferences {
  storageDir: string
  /** @deprecated Removed UI switch; accepted only for source compatibility and never persisted. */
  saveRequest?: boolean
}

/** True when the value looks like a legacy absolute path (Unix or Windows). */
export function isAbsoluteStorageProfile(value: string): boolean {
  const text = String(value || '').trim()
  if (!text) return false
  if (text.charAt(0) === '/') return true
  return /^[a-zA-Z]:[\\/]/.test(text)
}

/**
 * Sanitize a storage profile to a safe relative name. Absolute paths,
 * `..`/`\..` traversal and anything that would escape the server root are
 * dropped (fall back to the server default profile — empty string).
 */
export function sanitizeStorageProfile(value: string): string {
  const text = String(value || '').trim()
  if (isAbsoluteStorageProfile(text)) return ''
  if (
    text.split('/').includes('..') ||
    text.split('\\').includes('..')
  ) {
    return ''
  }
  return text
}

function readKey(key: string): string | null {
  try {
    return window.localStorage.getItem(key)
  } catch {
    return null
  }
}

function writeKey(key: string, value: string): void {
  try {
    window.localStorage.setItem(key, value)
  } catch {
    // localStorage unavailable (private mode / quota): preferences are a
    // convenience, never a hard dependency.
  }
}

function removeKey(key: string): void {
  try {
    window.localStorage.removeItem(key)
  } catch {
    // ignore
  }
}

/**
 * Load the saved storage preferences from localStorage, sanitizing legacy
 * values (an unsafe absolute-path value is dropped from storage so it can
 * never leak into later API payloads/URLs — same smooth-migration behavior
 * as the legacy page).
 */
export function loadStoragePreferences(): StoragePreferences {
  const savedDir = readKey(STORAGE_DIR_KEY)
  const storageDir = sanitizeStorageProfile(savedDir ?? '')

  if (savedDir !== null && savedDir !== storageDir) {
    if (storageDir) {
      writeKey(STORAGE_DIR_KEY, storageDir)
    } else {
      removeKey(STORAGE_DIR_KEY)
    }
  }
  // One-time migration: this key represented a removed, non-functional
  // browser switch. Do not touch any other localStorage entry.
  removeKey(SAVE_REQUEST_KEY)
  return { storageDir }
}

/** Persist the storage preferences (only safe relative profiles are saved). */
export function saveStoragePreferences(preferences: StoragePreferences): void {
  const storageDir = sanitizeStorageProfile(preferences.storageDir)
  if (storageDir) {
    writeKey(STORAGE_DIR_KEY, storageDir)
  } else {
    removeKey(STORAGE_DIR_KEY)
  }
}

/** Clear the storage preferences, falling back to server defaults. */
export function clearStoragePreferences(): void {
  removeKey(STORAGE_DIR_KEY)
  removeKey(SAVE_REQUEST_KEY)
}
