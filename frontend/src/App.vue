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
import { nextTick, ref, watch } from 'vue'
import { useRoute } from 'vue-router'

import { routeLocation, type AppRouteKey } from '@/app/router/catalog'

const route = useRoute()
const mainContent = ref<HTMLElement | null>(null)

const navigation = [
  { route: 'add', label: '添加番剧' },
  { route: 'plans', label: '追番方案' },
  { route: 'tracking', label: '追番管理' },
  { route: 'settings', label: '设置' },
] as const satisfies ReadonlyArray<{ route: AppRouteKey; label: string }>

function isCurrent(routeKey: AppRouteKey): boolean {
  return route.name === routeKey
}

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
</script>

<template>
  <div class="app-shell">
    <!-- US-207: skip link — first focusable element so keyboard users can jump
         past the header/nav straight to the feature content. -->
    <a id="skip-link" class="skip-link" href="#app-main">跳到主要内容</a>
    <GlobalLoadingBar />
    <header class="app-header">
      <div class="app-header-inner">
        <div class="brand-block">
          <span class="brand-mark" aria-hidden="true">M</span>
          <div class="header-copy">
            <p class="brand-eyebrow">桌面番剧工作台</p>
            <h1 class="app-title">MiGuOrca</h1>
          </div>
        </div>

        <nav class="top-nav" aria-label="主导航">
          <ul class="top-nav-list">
            <li v-for="item in navigation" :key="item.route">
              <RouterLink
                :to="routeLocation(item.route)"
                class="nav-link"
                :aria-current="isCurrent(item.route) ? 'page' : undefined"
              >
                <span>{{ item.label }}</span>
                <span v-if="isCurrent(item.route)" class="nav-current-marker" aria-hidden="true">
                  当前
                </span>
              </RouterLink>
            </li>
          </ul>
        </nav>

        <p class="workspace-status" role="status" aria-label="当前运行环境">
          <span class="workspace-status-dot" aria-hidden="true"></span>
          本地桌面工作区
        </p>
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
