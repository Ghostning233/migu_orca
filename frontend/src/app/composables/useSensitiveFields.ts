/**
 * useSensitiveFields (US-200).
 *
 * Credential-form primitive: holds request-scoped sensitive values (endpoint,
 * username, password, token, ...) in component-local reactive memory and
 * actively clears them on the events required by the security boundary:
 *
 * - `reset()` — switching authentication mode (e.g. password ↔ API token),
 * - `clearAll()` — after a successful request,
 * - `reset()` + calling `onCancel()` — user cancels/leaves the form,
 * - `onUnmount` — the component unmounts (e.g. leaving the route).
 *
 * The cleared fields become `undefined` so they are never serialized into a
 * POST body, URL, store, log or trace. Values are only ever read back via
 * `snapshot()` at the exact moment a single request body is built; nothing is
 * persisted between requests.
 *
 * This composable stores no persistent state by design: it is instantiated
 * per component, holds plain strings in memory, and never writes to Pinia,
 * localStorage/sessionStorage, the URL or any log.
 */
import { getCurrentInstance, onUnmounted, reactive } from 'vue'

export interface SensitiveField {
  /** Display label used for error messages (Chinese business copy). */
  label: string
  /** True when the field is required for the current auth mode. */
  required?: boolean
}

export interface SensitiveFields {
  /** Register a request-scoped field. */
  field: (name: string, field?: SensitiveField) => void
  /** Set/clear a field value (only ever component-local memory). */
  set: (name: string, value: string) => void
  /** Reset every field to empty (auth-mode switch / cancel). */
  reset: () => void
  /** Clear every field (success / explicit clear). */
  clearAll: () => void
  /** Snapshot current non-empty values for a single POST body. */
  snapshot: () => Record<string, string>
  /** Validate required fields; returns the first missing field name or null. */
  firstMissing: () => string | null
  /** Access a field's current value. */
  get: (name: string) => string
}

/**
 * Create a request-scoped sensitive-field group. `fields` maps names to
 * optional labels; the returned object never persists values anywhere.
 */
export function useSensitiveFields(fields: Record<string, SensitiveField> = {}): SensitiveFields {
  const values = reactive<Record<string, string>>({})

  for (const name of Object.keys(fields)) {
    values[name] = ''
  }

  function field(name: string, spec?: SensitiveField): void {
    if (!(name in values)) {
      values[name] = ''
    }
    if (spec) {
      fields[name] = spec
    }
  }

  function set(name: string, value: string): void {
    values[name] = value
  }

  function reset(): void {
    for (const name of Object.keys(values)) {
      values[name] = ''
    }
  }

  function clearAll(): void {
    reset()
  }

  function snapshot(): Record<string, string> {
    const result: Record<string, string> = {}
    for (const [name, value] of Object.entries(values)) {
      if (value) {
        result[name] = value
      }
    }
    return result
  }

  function firstMissing(): string | null {
    for (const [name, value] of Object.entries(values)) {
      const spec = fields[name]
      if (spec?.required && !value) {
        return name
      }
    }
    return null
  }

  function get(name: string): string {
    return values[name] ?? ''
  }

  // Register the unmount cleanup only when an active component instance
  // exists (the normal case: the composable is created in a component's
  // setup). Guarding with getCurrentInstance keeps the composable safe to
  // instantiate in plain unit tests and non-component contexts.
  if (getCurrentInstance()) {
    onUnmounted(reset)
  }

  return { field, set, reset, clearAll, snapshot, firstMissing, get }
}
