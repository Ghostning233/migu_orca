/**
 * Request-feature storage helpers (US-203).
 *
 * The requests list and the detail panel both send the *relative* storage
 * profile chosen in Settings as the `storage_dir` query parameter. This module
 * centralizes that read so the two features never diverge (US-193: absolute
 * paths and traversal are dropped, empty = server default root).
 *
 * Security boundary: only a server-root-relative profile name may ever be
 * sent to the API or appear in the URL; credentials/endpoints/absolute paths
 * never reach this module.
 */
import { sanitizeStorageProfile } from '@/features/settings/storagePreferences'

/** Read the current relative storage profile from localStorage (safe). */
export function currentStorageDir(): string {
  try {
    return sanitizeStorageProfile(window.localStorage.getItem('miguOrca.web.storageDir') ?? '')
  } catch {
    return ''
  }
}

/** Build the `storage_dir` query for request-feature API calls. */
export function storageQuery(): { storage_dir?: string } {
  const dir = currentStorageDir()
  return dir ? { storage_dir: dir } : {}
}
