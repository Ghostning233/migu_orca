<script setup lang="ts">
// PanelSection (US-200).
//
// Layout primitive: a titled section with optional heading actions. Replaces
// the repeated `.panel` + `.panel-heading` markup from the legacy pages.
// `title` is rendered as a real `<h2>` so the document outline stays
// meaningful; features pass Chinese business copy.
defineProps<{
  title: string
}>()
</script>

<template>
  <section class="panel panel-section" :aria-labelledby="`panel-section-${title}`">
    <div class="panel-heading">
      <h2 :id="`panel-section-${title}`">{{ title }}</h2>
      <div v-if="$slots.actions" class="panel-section-actions">
        <slot name="actions" />
      </div>
    </div>
    <slot />
  </section>
</template>

<style scoped>
.panel-section-actions {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-2);
  align-items: center;
}
</style>
