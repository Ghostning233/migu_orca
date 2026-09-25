<script setup lang="ts">
// ResourceSummary (US-269).
//
// Controlled public resource projection for draft review. Callers must pass
// the results of the shared request-detail helpers; this component does not
// inspect a Request, duplicate filtering rules, or call an API.
import { computed } from 'vue'
import type { CompleteSeedGroup, ExcludedSeed } from '@/features/requests/requestDetail'
import { safeResourceReason, safeResourceTitle } from '@/features/workbench/resourceProjection'

const props = defineProps<{
  effectiveSeeds: ReadonlyArray<string>
  completeGroups: ReadonlyArray<CompleteSeedGroup>
  excludedSeeds: ReadonlyArray<ExcludedSeed>
  selectedGroupName: string
}>()

const completeTotal = () => props.completeGroups.reduce((sum, group) => sum + group.seedNames.length, 0)
const previewLimit = 3
const previewEffectiveSeeds = computed(() => props.effectiveSeeds.slice(0, previewLimit))
const hasMoreEffectiveSeeds = computed(() => props.effectiveSeeds.length > previewLimit)

// #151：URL／magnet／绝对路径的安全投影与资源明细弹窗共用同一份规则模块，
// 这里不再保留第二套判定。
const safeSeedTitle = safeResourceTitle
const safeReason = safeResourceReason
</script>

<template>
  <section class="resource-summary" aria-label="资源摘要">
    <dl class="detail-grid resource-summary-grid">
      <div class="detail-row"><dt>有效资源数</dt><dd>{{ props.effectiveSeeds.length }}</dd></div>
      <div class="detail-row"><dt>完整资源数</dt><dd>{{ completeTotal() }}</dd></div>
      <div class="detail-row"><dt>排除资源数</dt><dd>{{ props.excludedSeeds.length }}</dd></div>
      <div class="detail-row"><dt>已更新集数</dt><dd>未知</dd></div>
    </dl>

    <details class="seed-details seed-group effective-seed-group" open>
      <summary>有效资源（当前选中字幕组：{{ props.selectedGroupName }}）({{ props.effectiveSeeds.length }})</summary>
      <ul v-if="props.effectiveSeeds.length" class="seed-list">
        <li v-for="seed in previewEffectiveSeeds" :key="seed">{{ safeSeedTitle(seed) }}</li>
      </ul>
      <p v-else class="muted-text">无有效种子标题。</p>
      <details v-if="hasMoreEffectiveSeeds" class="effective-seed-more">
        <summary>展开全部有效资源（{{ props.effectiveSeeds.length }}）</summary>
        <ul class="seed-list">
          <li v-for="seed in props.effectiveSeeds" :key="`all-${seed}`">{{ safeSeedTitle(seed) }}</li>
        </ul>
      </details>
    </details>

    <details class="seed-details complete-seed-details">
      <summary>完整种子（按字幕组分组）({{ completeTotal() }})</summary>
      <div class="seed-groups complete-seed-groups">
        <template v-if="props.completeGroups.length">
          <details v-for="group in props.completeGroups" :key="group.subtitleGroup" class="subgroup-seed-group">
            <summary>{{ group.subtitleGroup }} ({{ group.seedNames.length }})</summary>
            <ul v-if="group.seedNames.length" class="seed-list">
              <li v-for="seed in group.seedNames" :key="seed">{{ safeSeedTitle(seed) }}</li>
            </ul>
            <p v-else class="muted-text">无种子标题。</p>
          </details>
        </template>
        <p v-else class="muted-text">无种子标题。</p>
      </div>
    </details>

    <details class="seed-details excluded-seed-details">
      <summary>排除种子 ({{ props.excludedSeeds.length }})</summary>
      <div class="seed-group">
        <ul v-if="props.excludedSeeds.length" class="seed-list excluded-seed-list">
          <li v-for="seed in props.excludedSeeds" :key="`${seed.name}-${seed.reason}`">
            {{ safeSeedTitle(seed.name) }}<span v-if="seed.reason" class="seed-exclude-reason"> - {{ safeReason(seed.reason) }}</span>
          </li>
        </ul>
        <p v-else class="muted-text">无排除种子标题。</p>
      </div>
    </details>
  </section>
</template>

<style scoped>
.resource-summary { display: grid; gap: 0.5rem; }
.detail-grid { margin: 0; display: grid; gap: 0.3rem 1rem; grid-template-columns: max-content 1fr; }
.detail-row { display: contents; }
.detail-row dt { font-weight: 600; color: var(--color-text-muted); }
.detail-row dd { margin: 0; overflow-wrap: anywhere; }
.resource-summary-grid { margin-bottom: 0.25rem; }
.seed-details { border: 1px solid var(--color-border); border-radius: 6px; padding: 0.5rem 0.75rem; }
.seed-details summary { cursor: pointer; font-weight: 500; }
.seed-list { margin: 0.5rem 0 0; padding-left: 1.25rem; display: grid; gap: 0.25rem; }
/* F4: 完整种子按字幕组分层——字幕组是一级条目，组内资源缩进为二级。 */
.complete-seed-groups { display: grid; gap: 0.4rem; margin-top: 0.5rem; }
.subgroup-seed-group {
  border-left: 2px solid var(--color-border);
  padding: 0.15rem 0 0.15rem 0.6rem;
}
.subgroup-seed-group > summary { font-weight: 500; cursor: pointer; }
.subgroup-seed-group .seed-list { padding-left: 1.6rem; }
.seed-list li { overflow-wrap: anywhere; }
.effective-seed-more { margin-top: 0.5rem; padding-top: 0.35rem; border-top: 1px solid var(--color-border); }
.effective-seed-more summary { cursor: pointer; color: var(--color-text-muted); }
.excluded-seed-list .seed-exclude-reason, .muted-text { color: var(--color-text-muted); }
.muted-text { margin: 0.25rem 0 0; }
@media (max-width: 720px) {
  .detail-grid { grid-template-columns: 1fr; gap: 0.2rem; }
}
</style>
