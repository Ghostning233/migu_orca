<script setup lang="ts">
// 订阅方案（Request 列表）route (US-199).
//
// Placeholder shell until US-202 migrates the request list. The route exists
// now so the shell navigation is complete; the empty state guides the user
// while migration is pending.
import EmptyState from '@/components/feedback/EmptyState.vue'
</script>

<template>
  <section class="panel requests-panel" aria-labelledby="requests-heading">
    <div class="panel-heading">
      <h2 id="requests-heading">订阅方案</h2>
    </div>
    <p class="field-help">
      订阅方案列表将在后续迭代中迁移到新前端；旧页面在迁移完成前保持可用。
    </p>
    <EmptyState message="暂无已加载的订阅方案。" />
  </section>
</template>
