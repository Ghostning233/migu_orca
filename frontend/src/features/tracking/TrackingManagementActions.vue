<script setup lang="ts">
/**
 * Enable/disable and associated-RSS refresh actions (US-314).
 *
 * Both actions are server-computed with explicit target scopes, so this
 * component only ever renders the scopes the server offered *and* the live page
 * session proved the matching capability for.  It owns the one user choice that
 * has no field to type — which object to enable/disable — and emits it with the
 * latest detail; the page owns the confirmation, the credential, the revision,
 * the opaque key and the request itself.
 *
 * The refresh action has exactly one legitimate target (this record's own
 * associated RSS), so it needs no scope choice and no scope is emitted for it.
 *
 * Issue #233 D3/D4: these are the 管理操作 peer entries.  An action the server
 * did not offer renders nothing at all (no fake disabled button, no "not
 * available" filler); the parent section only exists when at least one entry
 * does.
 */
import { computed } from 'vue'

import BaseButton from '@/components/forms/BaseButton.vue'
import {
  type TrackingAction,
  type TrackingItem,
} from './trackingProjection'
import {
  isTrackingManagementScope,
  type TrackingManagementScope,
  type TrackingWriteSession,
} from './useTrackingWriteSession'

const props = defineProps<{
  item: TrackingItem
  /** The server-computed SET_ENABLED action, with this page's scopes only. */
  setEnabled?: TrackingAction | null
  /** The server-computed REFRESH_RSS action, with this page's scopes only. */
  refreshRss?: TrackingAction | null
  /** Page-level management result for this item; the page owns the request. */
  result?: TrackingWriteSession | null
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

/** The enable/disable targets this page may request, in server order. */
const setEnabledScopes = computed<TrackingManagementScope[]>(() => (
  (props.setEnabled?.target_scopes ?? []).filter(isTrackingManagementScope)
))
/** A refresh can only address this record's own associated RSS. */
const refreshScope = computed<TrackingManagementScope | null>(() => (
  (props.refreshRss?.target_scopes ?? []).filter(isTrackingManagementScope)
    .find((scope) => scope === 'ASSOCIATED_RSS') ?? null
))

// Issue #89: enable/disable always addresses the current controlled external
// anime subscription; the target scope is a server detail, never a user choice.
const setEnabledScope = computed<TrackingManagementScope | null>(() => (
  setEnabledScopes.value.find((scope) => scope === 'SUBSCRIPTION') ?? null
))

function submitSetEnabled(): void {
  if (props.busy || !props.setEnabled || !setEnabledScope.value) return
  emit('submit', {
    action: props.setEnabled, item: props.item, targetScope: setEnabledScope.value, patch: null,
  })
}

function submitRefresh(): void {
  if (props.busy || !props.refreshRss || !refreshScope.value) return
  emit('submit', {
    action: props.refreshRss, item: props.item, targetScope: refreshScope.value, patch: null,
  })
}
</script>

<template>
  <div class="tracking-management-actions">
    <form
      v-if="setEnabled && setEnabledScope"
      class="tracking-management-entry"
      aria-labelledby="tracking-set-enabled-heading"
      @submit.prevent="submitSetEnabled"
    >
      <h5 id="tracking-set-enabled-heading" class="tracking-visually-hidden">{{ setEnabled.label }}</h5>
      <BaseButton
        id="tracking-set-enabled-submit"
        type="submit"
        variant="secondary"
        :disabled="busy"
        :loading="loading"
      >{{ setEnabled.label }}</BaseButton>
    </form>

    <form
      v-if="refreshRss && refreshScope"
      class="tracking-management-entry"
      aria-labelledby="tracking-refresh-rss-heading"
      @submit.prevent="submitRefresh"
    >
      <h5 id="tracking-refresh-rss-heading" class="tracking-visually-hidden">{{ refreshRss.label }}</h5>
      <BaseButton
        id="tracking-refresh-rss-submit"
        type="submit"
        variant="secondary"
        :disabled="busy"
        :loading="loading"
      >{{ refreshRss.label }}</BaseButton>
    </form>

    <div
      v-if="result"
      id="tracking-management-result"
      class="tracking-management-result"
      :class="`is-${result.state.toLowerCase()}`"
      role="status"
    >
      <p class="tracking-management-verdict">{{ result.message }}</p>
      <p v-if="result.manualNotice" id="tracking-management-manual-notice" class="tracking-management-manual">
        {{ result.manualNotice }}
      </p>
    </div>
  </div>
</template>

<style scoped>
.tracking-management-actions { display: contents; }
/* Labelled peer entries: the h5 keeps the form's accessible name, visually
   hidden so the row stays compact (no new ARIA, no deleted attribute). */
.tracking-visually-hidden {
  position: absolute;
  width: 1px;
  height: 1px;
  margin: -1px;
  padding: 0;
  overflow: hidden;
  clip-path: inset(50%);
  white-space: nowrap;
  border: 0;
}
.tracking-management-scopes { display: grid; gap: .35rem; margin: 0; padding: var(--space-2) var(--space-3); border: 1px dashed var(--color-border); border-radius: var(--radius-sm); }
.tracking-management-scopes legend { font-size: .85rem; font-weight: 600; }
.tracking-management-scope { display: flex; align-items: center; gap: .45rem; font-size: .85rem; font-weight: 600; }
.tracking-management-result { flex: 1 0 100%; display: grid; gap: .4rem; padding: var(--space-3); border: 1px solid var(--color-border-subtle); border-left: 0.3rem solid var(--color-text-muted); border-radius: var(--radius-sm); background: var(--color-surface-raised); }
.tracking-management-result.is-succeeded { border-left-color: var(--color-feedback-success-border); }
.tracking-management-result.is-failed, .tracking-management-result.is-conflict, .tracking-management-result.is-rejected, .tracking-management-result.is-unknown { border-left-color: var(--color-feedback-error-border); }
.tracking-management-verdict, .tracking-management-manual { font-weight: 600; }
</style>
