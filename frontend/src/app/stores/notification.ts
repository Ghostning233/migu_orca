/**
 * Global notification store (US-199).
 *
 * Renders transient status/error messages in the shell's `aria-live`
 * region. Copy stays Chinese business language; messages are always
 * pre-sanitized (see api/client.ts) and must never contain endpoints,
 * tokens, cookies, raw bodies or absolute paths.
 */
import { defineStore } from 'pinia'

export type NotificationKind = 'success' | 'error' | 'info'

export interface NotificationMessage {
  id: number
  kind: NotificationKind
  title: string
  message?: string
}

let nextId = 1

export const useNotificationStore = defineStore('notification', {
  state: () => ({
    current: null as NotificationMessage | null,
  }),
  actions: {
    show(kind: NotificationKind, title: string, message?: string): void {
      this.current = { id: nextId++, kind, title, message }
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
      this.current = null
    },
  },
})
