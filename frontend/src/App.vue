<script setup lang="ts">
// MiGuOrca desktop application shell (Stage 33, US-260).
//
// Global state kept here is intentionally non-sensitive and non-persisted:
// the notification region (aria-live), the global loading bar and the error
// boundary. Feature routes are mounted below the shell; each feature owns its
// own loading/empty/error states (see components/feedback).
import ErrorBoundary from '@/components/feedback/ErrorBoundary.vue'
import GlobalLoadingBar from '@/components/feedback/GlobalLoadingBar.vue'
import GlobalNotification from '@/components/feedback/GlobalNotification.vue'
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'

import { routeLocation, type AppRouteKey } from '@/app/router/catalog'
import { useConnectionStatus } from '@/app/stores/connectionStatus'
import { currentStorageDir } from '@/features/requests/requestStorage'

const route = useRoute()
const mainContent = ref<HTMLElement | null>(null)
const connection = useConnectionStatus()
const connectionState = connection.state
const pendingCount = connection.pendingCount
let profilePoll: ReturnType<typeof setInterval> | undefined
let observedProfile = ''

const navigation = [
  { route: 'add', label: '添加番剧' },
  { route: 'tracking', label: '我的追番' },
  { route: 'settings', label: '设置' },
] as const satisfies ReadonlyArray<{ route: AppRouteKey; label: string }>

function isCurrent(routeKey: AppRouteKey): boolean {
  return route.name === routeKey
}

// Stage 46 (US-361): the visible pill is compact, matching the design's short
// status chip ("未配置"). The full Chinese connection summary stays in the
// accessible name, and internal codes / endpoints / credentials never render.
const statusLabel = computed(() =>
  connectionState.value.key === 'UNCONFIGURED' ? '未配置' : connectionState.value.label,
)
const statusAriaLabel = computed(
  () => `Auto Bangumi 连接状态：${connectionState.value.label}，进入设置`,
)

onMounted(() => {
  observedProfile = currentStorageDir()
  void connection.loadSummary()
  void connection.loadPending()
  profilePoll = setInterval(() => {
    const profile = currentStorageDir()
    if (profile === observedProfile) return
    observedProfile = profile
    connection.invalidate()
  }, 100)
})

onBeforeUnmount(() => {
  if (profilePoll) clearInterval(profilePoll)
})

// Focus only when the page route changes. Query-only updates select content
// inside the current feature and must not steal focus from the user's action.
watch(
  () => route.name,
  async (current, previous) => {
    if (!previous || current === previous) return
    await nextTick()
    mainContent.value?.focus({ preventScroll: true })
  },
  { flush: 'post' },
)

function requestBrandReturn(event: MouseEvent): void {
  event.preventDefault()
  window.dispatchEvent(new Event('migu-orca:brand-return'))
}
</script>

<template>
  <div class="app-shell">
    <!-- US-207: skip link — first focusable element so keyboard users can jump
         past the header/nav straight to the feature content. -->
    <a id="skip-link" class="skip-link" href="#app-main">跳到主要内容</a>
    <GlobalLoadingBar />
    <header class="app-header">
      <div class="app-header-inner">
        <RouterLink :to="routeLocation('add')" class="brand-block" aria-label="返回添加番剧" @click="requestBrandReturn">
          <h1 class="app-title">MiGuOrca</h1>
        </RouterLink>

        <nav class="top-nav" aria-label="主导航">
          <ul class="top-nav-list">
            <li v-for="(item, index) in navigation" :key="item.route">
              <RouterLink
                :id="`shell-nav-${index + 1}`"
                :to="routeLocation(item.route)"
                class="nav-link"
                :aria-current="isCurrent(item.route) ? 'page' : undefined"
              >
                <span>{{ item.label }}</span>
              </RouterLink>
            </li>
          </ul>
        </nav>

        <RouterLink
          :to="routeLocation('settings')"
          class="workspace-status"
          role="status"
          :aria-label="statusAriaLabel"
        >
          <span class="workspace-status-dot" aria-hidden="true"></span>
          <span class="workspace-status-label">{{ statusLabel }}</span>
          <span v-if="pendingCount" class="pending-badge" aria-label="待处理追番数量">
            {{ pendingCount }}
          </span>
        </RouterLink>
      </div>
    </header>

    <main id="app-main" ref="mainContent" tabindex="-1" class="app-main">
      <GlobalNotification />
      <ErrorBoundary>
        <RouterView />
      </ErrorBoundary>
    </main>
  </div>
</template>
