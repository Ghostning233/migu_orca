<script setup lang="ts">
// MiGuOrca application shell (US-199): global layout + top navigation.
//
// Global state kept here is intentionally non-sensitive and non-persisted:
// the notification region (aria-live), the global loading bar and the error
// boundary. Feature routes are mounted below the shell; each feature owns its
// own loading/empty/error states (see components/feedback).
import ErrorBoundary from '@/components/feedback/ErrorBoundary.vue'
import GlobalLoadingBar from '@/components/feedback/GlobalLoadingBar.vue'
import GlobalNotification from '@/components/feedback/GlobalNotification.vue'
</script>

<template>
  <div class="app-shell">
    <GlobalLoadingBar />
    <header class="app-header">
      <div class="header-copy">
        <h1 class="app-title">MiGuOrca</h1>
        <p class="mode-summary">
          订阅方案工作台：创建、审核、编辑并提交订阅方案。
        </p>
      </div>
      <nav class="top-nav" aria-label="页面导航">
        <RouterLink to="/workbench" class="nav-link">订阅方案工作台</RouterLink>
        <RouterLink to="/requests" class="nav-link">订阅方案</RouterLink>
        <RouterLink to="/queue" class="nav-link">提交队列</RouterLink>
        <RouterLink to="/settings" class="nav-link">Settings</RouterLink>
      </nav>
    </header>

    <main class="app-main">
      <GlobalNotification />
      <ErrorBoundary>
        <RouterView />
      </ErrorBoundary>
    </main>
  </div>
</template>
