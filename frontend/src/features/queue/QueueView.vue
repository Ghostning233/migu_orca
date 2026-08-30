<script setup lang="ts">
// 提交队列 route (US-199).
//
// Placeholder shell until US-206 migrates the batch submission queue. The
// route exists now so the shell navigation is complete.
import EmptyState from '@/components/feedback/EmptyState.vue'
</script>

<template>
  <section class="panel queue-panel" aria-labelledby="queue-heading">
    <div class="panel-heading">
      <h2 id="queue-heading">提交队列</h2>
    </div>
    <p class="field-help">
      提交队列将在后续迭代中迁移到新前端；旧页面在迁移完成前保持可用。
    </p>
    <EmptyState message="暂无提交中的队列。" />
  </section>
</template>
