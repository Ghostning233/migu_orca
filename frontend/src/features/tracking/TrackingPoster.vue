<script setup lang="ts">
// Issue #84: one shared cover renderer for the tracking list and detail so both
// show the same persisted cover, and a stable placeholder whenever the cover is
// missing or its bytes are unavailable. The upstream image address never
// reaches the DOM: only the same-origin opaque route the server projected.
import { computed, ref, watch } from 'vue'

const props = withDefaults(
  defineProps<{
    posterPath?: string | null
    /** Visible size: list thumbnail or detail cover. */
    variant?: 'list' | 'detail'
  }>(),
  { posterPath: null, variant: 'list' },
)

const failed = ref(false)

// The server already projects only a same-origin opaque route, but the client
// must fail closed too: a poisoned or unexpected value must never turn into a
// request to an upstream host. Anything else renders the placeholder.
const SAME_ORIGIN_POSTER = /^\/api\/v1\/mikan\/posters\/[A-Za-z0-9_.-]+$/

const safePath = computed(() => {
  const value = props.posterPath
  if (typeof value !== 'string') return null
  const candidate = value.trim()
  return SAME_ORIGIN_POSTER.test(candidate) ? candidate : null
})

// A different cover (or a later re-read returning one) must be retried once.
watch(
  () => props.posterPath,
  () => {
    failed.value = false
  },
)

const showImage = computed(() => Boolean(safePath.value) && !failed.value)
const state = computed(() => (showImage.value ? 'ready' : 'placeholder'))
</script>

<template>
  <span class="tracking-poster" :class="`tracking-poster--${variant}`" :data-poster-state="state">
    <img
      v-if="showImage"
      class="tracking-poster-image"
      :src="safePath ?? undefined"
      alt=""
      loading="lazy"
      decoding="async"
      @error="failed = true"
    />
    <span v-else class="tracking-poster-placeholder" aria-hidden="true" />
  </span>
</template>

<style scoped>
.tracking-poster {
  display: inline-flex;
  flex: none;
  overflow: hidden;
  background: var(--color-surface-subtle);
  border: 1px solid var(--color-border-subtle);
  border-radius: var(--radius-sm);
  aspect-ratio: 2 / 3;
}

.tracking-poster--list {
  /* #225 行规格：60×90 固定 2:3，宽高都消费登记过的几何 token。 */
  inline-size: var(--tracking-poster-width);
  block-size: var(--tracking-poster-height);
}

.tracking-poster--detail {
  inline-size: 96px;
  border-radius: var(--radius-md);
}

.tracking-poster-image {
  inline-size: 100%;
  block-size: 100%;
  object-fit: cover;
  display: block;
}

.tracking-poster-placeholder {
  position: relative;
  inline-size: 100%;
  block-size: 100%;
  background: linear-gradient(
    135deg,
    var(--color-surface-subtle) 0%,
    var(--color-border-subtle) 100%
  );
}

/* Minimal "image" glyph: a horizon line with a small sun, drawn with tokens so
   the placeholder needs no extra markup, icon font or remote asset. */
.tracking-poster-placeholder::before {
  content: '';
  position: absolute;
  inset-inline: 18%;
  inset-block-end: 28%;
  block-size: 1px;
  background: var(--color-border-strong);
  box-shadow: 0 -6px 0 -1px var(--color-border-strong);
}

.tracking-poster-placeholder::after {
  content: '';
  position: absolute;
  inline-size: 5px;
  block-size: 5px;
  border-radius: 50%;
  background: var(--color-border-strong);
  inset-block-start: 22%;
  inset-inline-start: 24%;
}
</style>
