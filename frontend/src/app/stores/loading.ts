/**
 * Global request-loading store (US-199).
 *
 * Tracks in-flight API requests so the shell can show a global loading
 * indicator. It only stores a monotonically increasing counter — never
 * request payloads, credentials or results — so nothing sensitive can leak
 * into the UI, logs or persistence.
 */
import { defineStore } from 'pinia'

export const useLoadingStore = defineStore('loading', {
  state: () => ({
    inFlight: 0,
  }),
  getters: {
    isLoading: (state): boolean => state.inFlight > 0,
  },
  actions: {
    begin(): void {
      this.inFlight += 1
    },
    end(): void {
      if (this.inFlight > 0) {
        this.inFlight -= 1
      }
    },
  },
})
