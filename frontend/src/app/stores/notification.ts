/**
 * Global notification store (US-199, Stage 42 / US-346).
 *
 * Feeds the single floating toast that summarises non-critical success,
 * info and global error outcomes. It stays the only message source: features
 * keep their own field/candidate/draft/batch recovery copy in place, and this
 * store never becomes the sole carrier of an error.
 *
 * Copy stays Chinese business language; messages are always pre-sanitized by
 * the caller (see api/client.ts) and must never contain endpoints, tokens,
 * cookies, raw bodies, absolute paths or full Requests. Nothing here is
 * persisted to a URL, history or browser storage.
 */
import { defineStore } from 'pinia'

export type NotificationKind = 'success' | 'error' | 'info'

export interface NotificationMessage {
  id: number
  kind: NotificationKind
  title: string
  message?: string
}

/**
 * Auto-close budget per kind, in milliseconds (US-346): success/info 10s,
 * error 20s. A kind missing from this map gets no budget at all — see
 * `show()`.
 */
export const NOTIFICATION_AUTO_CLOSE_MS: Readonly<Record<NotificationKind, number>> = {
  success: 10_000,
  info: 10_000,
  error: 20_000,
}

let nextId = 1

/**
 * Pending auto-close timers, keyed by message id and kept out of the reactive
 * state so a host timer object never lives inside Pinia. Every timer is
 * removed by exactly one of: its own expiry, a replacement, `clear()`, or the
 * toast unmounting — so at most one entry exists per store at any time.
 */
const autoCloseTimers = new Map<number, ReturnType<typeof setTimeout>>()

function cancelAutoClose(id: number): void {
  const handle = autoCloseTimers.get(id)
  if (handle === undefined) return
  clearTimeout(handle)
  autoCloseTimers.delete(id)
}

export const useNotificationStore = defineStore('notification', {
  state: () => ({
    current: null as NotificationMessage | null,
  }),
  actions: {
    show(kind: NotificationKind, title: string, message?: string): void {
      // Replacing a message retires the previous auto-close timer, so a slow
      // timer can never expire the message the user is actually reading.
      const previous = this.current
      if (previous) cancelAutoClose(previous.id)

      const id = nextId++
      this.current = { id, kind, title, message }

      // An unrecognised kind (possible for untyped callers) gets no duration:
      // fail closed by keeping the message up until it is closed by hand
      // rather than silently applying success's 10 seconds to what may be an
      // error summary.
      const budget = NOTIFICATION_AUTO_CLOSE_MS[kind]
      if (typeof budget !== 'number') return

      autoCloseTimers.set(
        id,
        setTimeout(() => {
          autoCloseTimers.delete(id)
          // Defence in depth for a timer that outlived its message: expire
          // only the id it was scheduled for, never whatever replaced it.
          if (this.current?.id !== id) return
          this.current = null
        }, budget),
      )
    },
    success(title: string, message?: string): void {
      this.show('success', title, message)
    },
    error(title: string, message?: string): void {
      this.show('error', title, message)
    },
    info(title: string, message?: string): void {
      this.show('info', title, message)
    },
    clear(): void {
      const current = this.current
      if (current) cancelAutoClose(current.id)
      this.current = null
    },
  },
})
