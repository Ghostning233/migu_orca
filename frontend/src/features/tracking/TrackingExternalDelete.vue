<script setup lang="ts">
/**
 * Per-record external delete (US-315).
 *
 * The delete is the one management action that removes an external object, so
 * this component is deliberately narrow:
 *
 * - it addresses exactly one tracking record (the one whose inspector is open),
 *   so there is no checkbox, no batch selection and no global delete;
 * - the target is the user's *explicit* choice among the scopes the server
 *   offered *and* the live page session proved the delete capability for — the
 *   same intersection every other management action uses, so an unproven or
 *   unknown scope has no control at all;
 * - it renders only the record's own external object as copy; no external id,
 *   URL or raw server value ever reaches the DOM.
 *
 * The page owns the credential, the impact confirmation (danger-styled, focused
 * on cancel), the latest revision, the single opaque key and the request itself.
 */
import { computed, ref, watch } from 'vue'

import BaseButton from '@/components/forms/BaseButton.vue'
import {
  isTrackingManagementScope,
  MANAGEMENT_SCOPE_LABELS,
  type TrackingAction,
  type TrackingItem,
  type TrackingManagementScope,
} from './trackingProjection'
import type { TrackingWriteSession } from './useTrackingWriteSession'

const props = defineProps<{
  item: TrackingItem
  /** The server-computed DELETE_EXTERNAL action, with this page's scopes only. */
  action?: TrackingAction | null
  /** Page-level management result for this item; the page owns the request. */
  result?: TrackingWriteSession | null
  /** Fixed read-only degradation copy when this page cannot delete. */
  hint: string
  /** Page-level single-flight/blocked state; the page owns the request. */
  busy?: boolean
  /** This item's own management request is in flight. */
  loading?: boolean
}>()

const emit = defineEmits<{
  (e: 'submit', payload: {
    action: TrackingAction
    item: TrackingItem
    targetScope: TrackingManagementScope
    patch: unknown
  }): void
}>()

/** The external objects this page may delete, in server order. */
const scopes = computed<TrackingManagementScope[]>(() => (
  (props.action?.target_scopes ?? []).filter(isTrackingManagementScope)
))

// The deleted object is never pre-selected: which external object disappears is
// the user's explicit choice, and a new server revision invalidates the old one.
const selectedScope = ref<TrackingManagementScope | ''>('')
watch(() => [props.item.tracking_id, props.item.revision], () => { selectedScope.value = '' })

/** The scope label of the page-level delete result; empty when it has none. */
const resultTargetLabel = computed(() => (
  props.result?.targetScope ? MANAGEMENT_SCOPE_LABELS[props.result.targetScope] : ''
))

function submitDelete(): void {
  if (props.busy || !props.action || !selectedScope.value) return
  emit('submit', {
    action: props.action, item: props.item, targetScope: selectedScope.value, patch: null,
  })
}
</script>

<template>
  <div class="tracking-external-delete">
    <form
      v-if="action"
      class="tracking-external-delete-form"
      aria-labelledby="tracking-delete-external-heading"
      @submit.prevent="submitDelete"
    >
      <h5 id="tracking-delete-external-heading">{{ action.label }}</h5>
      <p class="field-help">
        删除只影响 Auto Bangumi 中的外部对象：本地订阅方案、追番记录、审计记录、下载任务和已下载媒体文件都会保留，也不会删除任何媒体文件。
      </p>
      <fieldset class="tracking-external-delete-scopes">
        <legend>请选择要删除的外部对象</legend>
        <label v-for="scope in scopes" :key="scope" class="tracking-external-delete-scope">
          <input
            :id="`tracking-delete-external-scope-${scope}`"
            v-model="selectedScope"
            type="radio"
            class="base-checkbox"
            name="tracking-delete-external-scope"
            :value="scope"
          />
          <span>{{ MANAGEMENT_SCOPE_LABELS[scope] }}</span>
        </label>
      </fieldset>
      <p v-if="!selectedScope" id="tracking-delete-external-hint" class="field-help" role="status">
        请先明确选择要删除的外部对象；未选择前不会发送任何请求。
      </p>
      <BaseButton
        id="tracking-delete-external-submit"
        type="submit"
        variant="danger"
        :disabled="busy || !selectedScope"
        :loading="loading"
      >{{ action.label }}</BaseButton>
    </form>
    <p v-else class="field-help">{{ hint }}</p>

    <div
      v-if="result"
      id="tracking-delete-external-result"
      class="tracking-external-delete-result"
      :class="`is-${result.state.toLowerCase()}`"
      role="status"
    >
      <p class="tracking-external-delete-verdict">
        本次目标：{{ resultTargetLabel }}。{{ result.message }}
      </p>
      <p v-if="result.manualNotice" id="tracking-delete-external-manual-notice" class="tracking-external-delete-manual">
        {{ result.manualNotice }}
      </p>
    </div>
  </div>
</template>

<style scoped>
.tracking-external-delete { display: grid; gap: .65rem; }
.tracking-external-delete-form { display: grid; gap: .55rem; padding: var(--space-3); border: 1px solid var(--color-border-subtle); border-radius: var(--radius-sm); }
.tracking-external-delete-form h5 { margin: 0; font-size: .95rem; }
.tracking-external-delete-scopes { display: grid; gap: .35rem; margin: 0; padding: var(--space-2) var(--space-3); border: 1px dashed var(--color-border); border-radius: var(--radius-sm); }
.tracking-external-delete-scopes legend { font-size: .85rem; font-weight: 600; }
.tracking-external-delete-scope { display: flex; align-items: center; gap: .45rem; font-size: .85rem; font-weight: 600; }
.tracking-external-delete-result { display: grid; gap: .4rem; padding: var(--space-3); border: 1px solid var(--color-border-subtle); border-left: 0.3rem solid var(--color-text-muted); border-radius: var(--radius-sm); background: var(--color-surface-raised); }
.tracking-external-delete-result.is-succeeded { border-left-color: var(--color-feedback-success-border); }
.tracking-external-delete-result.is-failed, .tracking-external-delete-result.is-conflict, .tracking-external-delete-result.is-rejected, .tracking-external-delete-result.is-unknown { border-left-color: var(--color-feedback-error-border); }
.tracking-external-delete-verdict, .tracking-external-delete-manual { font-weight: 600; }
</style>
