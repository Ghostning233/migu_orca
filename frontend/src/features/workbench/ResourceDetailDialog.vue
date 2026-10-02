<script setup lang="ts">
// ResourceDetailDialog (#151).
//
// 资源明细双页签弹窗：默认「有效资源」，另一页签显示安全标题与排除原因。列表只在
// 弹窗内滚动；不显示完整 RSS URL、magnet、路径或原始响应——所有取值都经过共享的
// resourceProjection 安全投影。
//
// 可访问性：Teleport 到 body 的 `aria-modal="true"` 对话框，复用 useFocusTrap
// （Tab 循环、Esc 关闭、关闭后焦点回到触发入口）；打开与关闭都记录并恢复触发入口
// 所在滚动容器的位置，因此工作台滚动位置不变。样式与 ConfirmDialog 保持一致。
import { computed, nextTick, onBeforeUnmount, ref, useId } from 'vue'

import BaseButton from '@/components/forms/BaseButton.vue'
import { useFocusTrap } from '@/app/composables/useFocusTrap'
import type { ExcludedSeed } from '@/features/requests/requestDetail'
import { safeResourceReason, safeResourceTitle } from '@/features/workbench/resourceProjection'

type ResourceTab = 'effective' | 'excluded'

const props = defineProps<{
  effectiveSeeds: ReadonlyArray<string>
  excludedSeeds: ReadonlyArray<ExcludedSeed>
  selectedGroupName: string
  /** id-prefix 让同一共享组件在单番与批量页面生成不同的元素 id。 */
  idPrefix?: string
}>()

const idPrefix = computed(() => props.idPrefix ?? 'resource-detail')
const open = ref(false)
const activeTab = ref<ResourceTab>('effective')
const dialogEl = ref<HTMLElement | null>(null)
const titleId = useId()

const effectiveCount = computed(() => props.effectiveSeeds.length)
const excludedCount = computed(() => props.excludedSeeds.length)
const tabCount = computed(() => (activeTab.value === 'effective' ? effectiveCount.value : excludedCount.value))

/** 触发入口所在的所有可滚动祖先（含文档）在打开时的位置。 */
let restoreScroll: Array<{ element: HTMLElement | Window; top: number }> = []

function captureScrollPositions(): void {
  const positions: Array<{ element: HTMLElement | Window; top: number }> = []
  if (typeof window !== 'undefined') positions.push({ element: window, top: window.scrollY })
  let node = restoreTarget()
  while (node) {
    if (node.scrollTop > 0) positions.push({ element: node, top: node.scrollTop })
    node = node.parentElement
  }
  restoreScroll = positions
}

function applyScrollPositions(): void {
  for (const entry of restoreScroll) {
    if (entry.element instanceof Window) entry.element.scrollTo({ top: entry.top })
    else entry.element.scrollTop = entry.top
  }
}

/** 打开弹窗的触发入口：焦点陷阱激活前的 document.activeElement。 */
let trigger: HTMLElement | null = null

function restoreTarget(): HTMLElement | null {
  return trigger
}

function setActiveTab(tab: ResourceTab): void {
  activeTab.value = tab
}

/** 页签左/右方向键在两项之间循环，Home/End 跳到首/末项。 */
function onTabKeydown(event: KeyboardEvent): void {
  const keys = ['ArrowLeft', 'ArrowRight', 'Home', 'End']
  if (!keys.includes(event.key)) return
  event.preventDefault()
  const tabs: ResourceTab[] = ['effective', 'excluded']
  const current = Math.max(0, tabs.indexOf(activeTab.value))
  let next: ResourceTab
  if (event.key === 'Home') {
    next = tabs[0] ?? 'effective'
  } else if (event.key === 'End') {
    next = tabs[tabs.length - 1] ?? 'effective'
  } else if (event.key === 'ArrowLeft') {
    // 首项继续向左回到末项（两项之间循环）。
    next = tabs[(current - 1 + tabs.length) % tabs.length] ?? 'effective'
  } else {
    next = tabs[(current + 1) % tabs.length] ?? 'effective'
  }
  activeTab.value = next
  void nextTick(() => {
    const element = dialogEl.value?.querySelector<HTMLButtonElement>(`#${idPrefix.value}-tab-${next}`)
    element?.focus()
  })
}

const { activate, deactivate } = useFocusTrap(dialogEl, () => close())

/**
 * 打开代际（参考 ConfirmDialog 的 generation 保护）。
 *
 * `activate()` 必须等 Vue 把弹窗挂到 DOM 之后才能运行，因此它排在 `nextTick()` 上。
 * 关闭、卸载或重新打开都会让这一代失效：过期的回调绝不能再激活陷阱，否则弹窗已经
 * 不在 DOM 里，`activate()` 只会留下 document 上的 keydown 监听——Tab 被吞、
 * Escape 被拦，而且没有对应容器可以解除。
 */
let dialogGeneration = 0

function openDialog(tab: ResourceTab = 'effective'): void {
  if (open.value) return
  const generation = ++dialogGeneration
  trigger = document.activeElement instanceof HTMLElement ? document.activeElement : null
  captureScrollPositions()
  activeTab.value = tab
  open.value = true
  void nextTick().then(() => {
    // 仍是当前代际、弹窗仍打开、容器真的挂上了，才允许激活。
    if (generation !== dialogGeneration || !open.value || dialogEl.value === null) return
    // 焦点陷阱默认落在第一个可聚焦元素（关闭按钮）；页签可继续用 Tab 到达。
    activate()
  })
}

function close(): void {
  if (!open.value) return
  // 让仍在排队的打开回调失效，避免「打开后立刻关闭」时激活一个不存在的弹窗。
  dialogGeneration += 1
  open.value = false
  deactivate()
  // 关闭后恢复工作台（或任一滚动祖先）的滚动位置；触发入口的焦点由焦点陷阱恢复。
  applyScrollPositions()
  restoreScroll = []
  trigger = null
}

// #151 缺陷修复：弹窗打开时组件若因路由切换、父组件卸载或条件渲染被直接销毁，
// 正常关闭路径不会执行。这里按 ConfirmDialog 的生命周期清理方式回收焦点陷阱，
// 保证 document 上的键盘监听与被设为 inert 的兄弟节点都被解除，后续页面仍可 Tab
// 访问。清理是幂等的：已经正常 close() 过（陷阱已解除）或从未打开过都不会出错；
// 销毁时不再把焦点移回正在离开 DOM 的触发入口。
onBeforeUnmount(() => {
  dialogGeneration += 1
  deactivate({ restoreFocus: false })
  restoreScroll = []
  trigger = null
  open.value = false
})

defineExpose({ open: openDialog, close, isOpen: () => open.value })
</script>

<template>
  <Teleport to="body">
    <div v-if="open" ref="dialogEl" class="resource-dialog-backdrop">
      <div
        class="resource-dialog"
        role="dialog"
        aria-modal="true"
        :aria-labelledby="titleId"
      >
        <div class="resource-dialog-header">
          <h2 :id="titleId" class="resource-dialog-title">资源明细</h2>
          <button
            :id="`${idPrefix}-close-icon`"
            type="button"
            class="icon-button resource-dialog-close-icon"
            aria-label="关闭资源明细"
            title="关闭"
            @click="close"
          >
            ×
          </button>
        </div>

        <div class="resource-dialog-tabs" role="tablist" aria-label="资源明细页签">
          <button
            :id="`${idPrefix}-tab-effective`"
            type="button"
            role="tab"
            class="resource-dialog-tab"
            :aria-selected="activeTab === 'effective' ? 'true' : 'false'"
            :tabindex="activeTab === 'effective' ? 0 : -1"
            :aria-controls="`${idPrefix}-panel-effective`"
            @keydown="onTabKeydown"
            @click="setActiveTab('effective')"
          >
            有效资源（{{ effectiveCount }}）
          </button>
          <button
            :id="`${idPrefix}-tab-excluded`"
            type="button"
            role="tab"
            class="resource-dialog-tab"
            :aria-selected="activeTab === 'excluded' ? 'true' : 'false'"
            :tabindex="activeTab === 'excluded' ? 0 : -1"
            :aria-controls="`${idPrefix}-panel-excluded`"
            @keydown="onTabKeydown"
            @click="setActiveTab('excluded')"
          >
            已排除（{{ excludedCount }}）
          </button>
        </div>

        <p class="resource-dialog-group">
          当前字幕组：<strong>{{ selectedGroupName || '未选择字幕组' }}</strong>
        </p>

        <div
          :id="`${idPrefix}-panel-effective`"
          class="resource-dialog-list"
          role="tabpanel"
          :aria-labelledby="`${idPrefix}-tab-effective`"
          :hidden="activeTab !== 'effective'"
        >
          <ul v-if="effectiveCount" class="resource-dialog-items">
            <li v-for="(seed, index) in effectiveSeeds" :key="`effective-${index}-${seed}`" class="resource-dialog-item">
              <span class="batch-doc-glyph" aria-hidden="true"></span>
              <span class="resource-dialog-name">{{ safeResourceTitle(seed) }}</span>
            </li>
          </ul>
          <p v-else class="resource-dialog-empty">当前字幕组没有有效资源。</p>
        </div>

        <div
          :id="`${idPrefix}-panel-excluded`"
          class="resource-dialog-list"
          role="tabpanel"
          :aria-labelledby="`${idPrefix}-tab-excluded`"
          :hidden="activeTab !== 'excluded'"
        >
          <ul v-if="excludedCount" class="resource-dialog-items">
            <li
              v-for="(seed, index) in excludedSeeds"
              :key="`excluded-${index}-${seed.name}`"
              class="resource-dialog-item"
            >
              <span class="batch-doc-glyph" aria-hidden="true"></span>
              <span class="resource-dialog-name">{{ safeResourceTitle(seed.name) }}</span>
              <span v-if="seed.reason" class="resource-dialog-reason">{{ safeResourceReason(seed.reason) }}</span>
            </li>
          </ul>
          <p v-else class="resource-dialog-empty">没有被排除的资源。</p>
        </div>

        <div class="resource-dialog-footer">
          <span :id="`${idPrefix}-count`" class="resource-dialog-count" role="status">
            共 {{ tabCount }} 条{{ tabCount > 6 ? ' · 向下滚动查看' : '' }}
          </span>
          <BaseButton :id="`${idPrefix}-close`" variant="secondary" @click="close">关闭</BaseButton>
        </div>
      </div>
    </div>
  </Teleport>
</template>

<style scoped>
.resource-dialog-backdrop {
  position: fixed;
  inset: 0;
  z-index: var(--z-overlay);
  display: flex;
  align-items: center;
  justify-content: center;
  background: var(--color-feedback-scrim);
  padding: var(--space-4);
}

.resource-dialog {
  background: var(--color-surface);
  color: var(--color-text);
  border: 1px solid var(--color-border-subtle);
  border-radius: var(--radius-lg);
  box-shadow: var(--shadow-dialog);
  padding: var(--space-5) var(--space-6);
  max-width: 768px;
  width: 100%;
  /* 设计图两个页签共用同一弹窗框：高度固定，列表在框内滚动。 */
  height: min(78vh, 700px);
  display: grid;
  gap: var(--space-4);
  grid-template-rows: auto auto auto minmax(0, 1fr) auto;
}

.resource-dialog-header {
  align-items: center;
  display: flex;
  justify-content: space-between;
}

.resource-dialog-title {
  margin: 0;
  color: var(--color-primary);
  font-size: var(--type-page-title);
  font-weight: var(--font-weight-bold);
  line-height: 1.2;
}

.resource-dialog-tabs {
  border-bottom: 1px solid var(--color-border);
  display: flex;
  gap: var(--space-6);
}

.resource-dialog-tab {
  background: none;
  border: 0;
  border-bottom: 3px solid transparent;
  color: var(--color-text-muted);
  cursor: pointer;
  font-size: var(--type-card-title);
  font-weight: var(--font-weight-medium);
  padding: var(--space-2) 0.1rem;
}

.resource-dialog-tab[aria-selected='true'] {
  border-bottom-color: var(--color-primary);
  color: var(--color-primary);
  font-weight: var(--font-weight-semibold);
}

.resource-dialog-group {
  color: var(--color-text-muted);
  margin: 0;
}

.resource-dialog-group strong {
  color: var(--color-text);
  font-weight: var(--font-weight-semibold);
}

/* 长清单只在弹窗内滚动；滚动条留在弹窗里，不影响工作台。 */
.resource-dialog-list {
  min-height: 0;
  overflow-y: auto;
  overscroll-behavior: contain;
}

.resource-dialog-list[hidden] {
  display: none;
}

.resource-dialog-items {
  display: grid;
  gap: 0;
  list-style: none;
  margin: 0;
  padding: 0;
}

.resource-dialog-item {
  align-items: center;
  border-bottom: 1px solid var(--color-border);
  display: flex;
  gap: var(--space-3);
  min-height: 56px;
  min-width: 0;
  padding: var(--space-3) var(--space-1);
}

/* 文档图标由 CSS 画出，避免依赖 emoji 字体。 */
.batch-doc-glyph {
  border: 1.5px solid var(--color-primary);
  border-radius: 3px;
  display: inline-block;
  flex: 0 0 auto;
  height: 18px;
  position: relative;
  width: 14px;
}

.batch-doc-glyph::after {
  background: var(--color-primary);
  content: '';
  height: 1.5px;
  left: 3px;
  position: absolute;
  top: 6px;
  width: 6px;
}

.resource-dialog-name {
  flex: 1 1 auto;
  font-size: var(--font-size-md);
  min-width: 0;
  overflow-wrap: anywhere;
}

.resource-dialog-reason {
  background: color-mix(in srgb, var(--color-danger-emphasis) 12%, transparent);
  border-radius: var(--radius-pill);
  color: var(--color-danger-emphasis);
  flex: 0 0 auto;
  font-size: var(--font-size-sm);
  font-weight: var(--font-weight-medium);
  padding: 0.15rem var(--space-3);
}

.resource-dialog-empty {
  color: var(--color-text-muted);
  margin: var(--space-2) 0 0;
}

.resource-dialog-footer {
  align-items: center;
  border-top: 1px solid var(--color-border);
  display: flex;
  gap: var(--space-3);
  justify-content: space-between;
  padding-top: var(--space-3);
}

.resource-dialog-count {
  color: var(--color-text-muted);
  font-size: var(--font-size-sm);
}
</style>
