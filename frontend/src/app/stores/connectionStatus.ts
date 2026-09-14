import { computed, ref } from 'vue'

import { api } from '@/api/client'
import type { operations } from '@/api/generated/api'
import { currentStorageDir } from '@/features/requests/requestStorage'

type ConnectionSummary = NonNullable<operations['getAutoBangumiConnection']['responses']['200']['content']['application/json']['result']>
type TrackingResult = NonNullable<operations['listTrackingItems']['responses']['200']['content']['application/json']['result']>

const summary = ref<ConnectionSummary | null>(null)
const summaryGeneration = ref(0)
const summaryLoading = ref(false)
const pendingCount = ref<number | null>(null)
const pendingProfile = ref('')
let summaryRequest = 0
let trackingRequest = 0

export function useConnectionStatus() {
  const state = computed(() => {
    if (!summary.value) return { key: 'UNKNOWN', label: '需检查' }
    if (!summary.value.configured || !summary.value.credential_present) return { key: 'UNCONFIGURED', label: '未配置' }
    if (summary.value.connection_status === 'VERIFIED' || summary.value.capabilities?.probe_status === 'VERIFIED') return { key: 'VERIFIED', label: '连接可用' }
    if (summary.value.connection_status === 'CONFIGURED') return { key: 'CONFIGURED', label: '已配置' }
    return { key: 'ERROR', label: '需检查' }
  })

  async function loadSummary(): Promise<void> {
    const request = ++summaryRequest
    const generation = summaryGeneration.value
    summaryLoading.value = true
    try {
      const result = await api.get<ConnectionSummary>('/api/v1/settings/autobangumi')
      if (request === summaryRequest && generation === summaryGeneration.value) summary.value = result
    } catch {
      if (request === summaryRequest && generation === summaryGeneration.value) summary.value = null
    } finally {
      if (request === summaryRequest) summaryLoading.value = false
    }
  }

  async function loadPending(): Promise<void> {
    const request = ++trackingRequest
    const profile = currentStorageDir()
    pendingCount.value = null
    pendingProfile.value = profile
    try {
      const result = await api.get<TrackingResult>('/api/v1/tracking/items', {
        query: { ...(profile ? { storage_dir: profile } : {}), sort: 'updated_at' },
      })
      if (request !== trackingRequest || profile !== currentStorageDir()) return
      pendingCount.value = result.items.reduce((count, item) => (
        count + (item.status === 'PENDING_SUBMIT' || item.status === 'SUBMIT_FAILED' ? 1 : 0)
      ), 0)
    } catch {
      if (request === trackingRequest) pendingCount.value = null
    }
  }

  function invalidate(): void {
    summaryGeneration.value += 1
    summary.value = null
    pendingCount.value = null
    void loadSummary()
  }

  return { summary, state, summaryLoading, pendingCount, loadSummary, loadPending, invalidate }
}

/** Controlled non-persistent refresh used after server-confirmed convergence. */
export function refreshConnectionStatus(): void {
  useConnectionStatus().invalidate()
}
