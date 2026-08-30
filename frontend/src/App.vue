<script setup lang="ts">
// MiGuOrca application shell (US-197): global layout + top navigation.
// Feature routes are mounted below the shell; global error/notification
// containers land here in US-199.
</script>

<template>
  <div class="app-shell">
    <header class="app-header">
      <div class="header-copy">
        <h1 class="app-title">MiGuOrca</h1>
        <p class="mode-summary">
          订阅方案工作台：创建、审核、编辑并提交订阅方案。
        </p>
      </div>
      <nav class="top-nav" aria-label="页面导航">
        <RouterLink to="/workbench" class="nav-link">订阅方案工作台</RouterLink>
        <RouterLink to="/settings" class="nav-link">Settings</RouterLink>
      </nav>
    </header>

    <main class="app-main">
      <RouterView />
    </main>
  </div>
</template>
