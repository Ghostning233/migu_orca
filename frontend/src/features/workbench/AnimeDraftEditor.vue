<script setup lang="ts">
// AnimeDraftEditor (US-270 / US-344 / WP-41-D).
//
// Shared, controlled review UI for single and batch drafts. It owns only the
// transient form controls; the parent owns the Request snapshot, draft
// capability, revision and transport. In particular, this component has no
// save/confirm endpoint dependency and never receives sensitive source data.
// It never calls `safe-info` (US-345): the default layer is built from the
// already-rendered snapshot plus an optional in-memory candidate projection.
//
// F4 information hierarchy: the default layer answers「已选哪部/哪一季、筛后有
// 什么、能否确认」— a Chinese summary row (已选合集/季度/总集数/字幕组/筛选规则)
// and the 资源摘要 section. Internal ids, the raw title, the RSS selection and
// the English section names live in the collapsed 全部信息（技术详情）.
//
// US-344: every user edit also announces *what kind* of edit it is, so the
// host can send the server-authoritative preview-modify at the right time
// (subtitle group immediately, filter rule debounced, folder name only on an
// explicit flush). The editor itself still performs no request.
import { computed, ref, watch } from 'vue'

import BaseButton from '@/components/forms/BaseButton.vue'
import BaseInput from '@/components/forms/BaseInput.vue'
import CheckboxRow from '@/components/forms/CheckboxRow.vue'
import FormField from '@/components/layout/FormField.vue'
import PanelSection from '@/components/layout/PanelSection.vue'

import { EPISODE_PLACEHOLDER, episodeCountText } from '@/features/workbench/episodeCount'
import ResourceSummary from '@/features/workbench/ResourceSummary.vue'
import ResourceDetailDialog from '@/features/workbench/ResourceDetailDialog.vue'
import SubtitleGroupSelect from '@/features/workbench/SubtitleGroupSelect.vue'
import { resourcePreview } from '@/features/workbench/resourceProjection'
import {
  collectPreviewEditPatch,
  previewEditStateFrom,
  publicPosterPath,
  type PreviewEditState,
  type PreviewPatch,
  type SelectedCollectionSummary,
} from '@/features/workbench/candidateSearch'
import {
  completeSeedGroups,
  displayValue,
  effectiveSeeds,
  excludedSeeds,
  type RequestDetailSnapshot,
  type RequestSnapshot,
} from '@/features/requests/requestDetail'
import { statusLabel } from '@/features/requests/requestsList'
import type { ReuseSuggestion } from '@/features/requests/reuseHandoff'

const props = defineProps<{
  request: RequestSnapshot | RequestDetailSnapshot
  mode?: 'draft' | 'saved'
  /**
   * #150：`batch` 使用批量草案右栏的信息层级——合集身份、字幕与筛选、四项资源结果
   * 与折叠的高级设置；默认层不再重复筛选规则、技术详情与完整种子分组列表。
   * `default`（单番草案与已保存方案）保持原结构，不产生内容或操作回归。
   */
  layout?: 'default' | 'batch'
  heading?: string
  formHeading?: string
  applyLabel?: string
  applying?: boolean
  error?: string
  disabled?: boolean
  idPrefix?: string
  containerId?: string
  formId?: string
  canRetry?: boolean
  retryLabel?: string
  /**
   * F4: in the draft review the host owns the single primary action
   * (保存并确认 / 固定批量操作栏), so its编辑动作 is rendered as a secondary
   * button. The saved-plan page keeps the default primary styling because its
   * own 保存方案修改 is the only action there.
   */
  applyVariant?: 'primary' | 'secondary'
  /**
   * Issue #91: an already-active plan keeps its identity read-only. The
   * subtitle group decides the real RSS source, so changing it is not an edit —
   * the user must delete the plan and add it again.
   */
  subtitleGroupReadOnly?: boolean
  /**
   * F4: display-only projection of the collection the user selected. The
   * unsaved draft snapshot has no season/poster/total-episode fields and this
   * Stage adds no endpoint for them, so the host passes the public candidate
   * metadata it still holds in memory. Absent => the summary says 未提供.
   */
  candidateSummary?: SelectedCollectionSummary | null
}>()

const emit = defineEmits<{
  (e: 'apply', patch: PreviewPatch): void
  (e: 'dirty-change', dirty: boolean): void
  (e: 'retry'): void
  (e: 'reset'): void
  (e: 'empty-apply'): void
  // US-344 edit intents, classified by what the change affects on the server.
  (e: 'subtitle-group-change', value: string): void
  (e: 'filter-change', state: PreviewEditState): void
  (e: 'folder-change', value: string): void
}>()

const idPrefix = computed(() => props.idPrefix ?? 'anime-draft')
const editorMode = computed(() => props.mode ?? 'draft')
const panelHeading = computed(() => props.heading ?? '订阅方案详情')
const formHeading = computed(() => props.formHeading ?? (editorMode.value === 'saved' ? '编辑已保存方案' : '编辑订阅草案'))
const applyLabel = computed(() => props.applyLabel ?? (editorMode.value === 'saved' ? '保存方案修改' : '保存修改'))

const editGroup = ref('')
const editMustContain = ref('')
const editMustNotContain = ref('')
const editUseRegex = ref(false)
const editCaseSensitive = ref(false)
const editFolderName = ref('')
const clearMustContain = ref(false)
const clearMustNotContain = ref(false)
const clearFolderName = ref(false)

function stateFromRequest(request: RequestSnapshot | RequestDetailSnapshot): PreviewEditState {
  return previewEditStateFrom(request)
}

// Programmatic writes (snapshot sync, reuse suggestion, explicit reset) must
// not be announced as user intent, or the host would auto-send them.
let suppressIntent = 0
function guarded(write: () => void): void {
  suppressIntent += 1
  try {
    write()
  } finally {
    suppressIntent -= 1
  }
}

function resetForm(): void {
  guarded(() => {
    const state = stateFromRequest(props.request)
    editGroup.value = state.selectedSubtitleGroup
    editMustContain.value = state.mustContain
    editMustNotContain.value = state.mustNotContain
    editUseRegex.value = state.useRegex
    editCaseSensitive.value = state.caseSensitive
    editFolderName.value = state.expectedFolderName
    clearMustContain.value = false
    clearMustNotContain.value = false
    clearFolderName.value = false
  })
  emit('dirty-change', false)
}

function currentState(): PreviewEditState {
  return {
    selectedSubtitleGroup: editGroup.value,
    mustContain: clearMustContain.value ? '' : editMustContain.value.trim(),
    mustNotContain: clearMustNotContain.value ? '' : editMustNotContain.value.trim(),
    useRegex: editUseRegex.value,
    caseSensitive: editCaseSensitive.value,
    expectedFolderName: clearFolderName.value ? '' : editFolderName.value.trim(),
  }
}

const originalState = computed(() => stateFromRequest(props.request))
const patch = computed(() => collectPreviewEditPatch(originalState.value, currentState()))
const dirty = computed(() => Object.keys(patch.value).length > 0)

watch(dirty, (value) => emit('dirty-change', value), { immediate: true })

/**
 * US-344: a new server snapshot replaces the fields the server has already
 * confirmed, but keeps an edit the user made while a request was in flight.
 * A field is the user's to keep when its local value matches neither the
 * previous snapshot nor the new one; otherwise the server value wins.
 */
function syncFromSnapshot(previous: RequestSnapshot | RequestDetailSnapshot, next: RequestSnapshot | RequestDetailSnapshot): void {
  const before = stateFromRequest(previous)
  const after = stateFromRequest(next)
  guarded(() => {
    if (editGroup.value === before.selectedSubtitleGroup || editGroup.value === after.selectedSubtitleGroup) {
      editGroup.value = after.selectedSubtitleGroup
    }
    if (!clearMustContain.value && (editMustContain.value === before.mustContain || editMustContain.value === after.mustContain)) {
      editMustContain.value = after.mustContain
    }
    if (!clearMustNotContain.value && (editMustNotContain.value === before.mustNotContain || editMustNotContain.value === after.mustNotContain)) {
      editMustNotContain.value = after.mustNotContain
    }
    if (editUseRegex.value === before.useRegex || editUseRegex.value === after.useRegex) {
      editUseRegex.value = after.useRegex
    }
    if (editCaseSensitive.value === before.caseSensitive || editCaseSensitive.value === after.caseSensitive) {
      editCaseSensitive.value = after.caseSensitive
    }
    if (!clearFolderName.value && (editFolderName.value === before.expectedFolderName || editFolderName.value === after.expectedFolderName)) {
      editFolderName.value = after.expectedFolderName
    }
  })
}

watch(
  () => props.request,
  (next, previous) => {
    if (!previous) return
    syncFromSnapshot(previous, next)
  },
  { deep: true },
)

watch(clearMustContain, (clear) => { if (clear) editMustContain.value = '' })
watch(clearMustNotContain, (clear) => { if (clear) editMustNotContain.value = '' })
watch(clearFolderName, (clear) => { if (clear) editFolderName.value = '' })

// Synchronous watchers so `guarded` still covers programmatic writes.
watch(editGroup, (value) => {
  if (suppressIntent === 0) emit('subtitle-group-change', value)
}, { flush: 'sync' })
watch([editMustContain, editMustNotContain, editUseRegex, editCaseSensitive], () => {
  if (suppressIntent === 0) emit('filter-change', currentState())
}, { flush: 'sync' })
watch(editFolderName, (value) => {
  if (suppressIntent === 0) emit('folder-change', value)
}, { flush: 'sync' })

const groupOptions = computed(() =>
  (props.request.source_info?.rss_sources ?? []).map((source) => ({
    value: source.subtitle_group ?? '',
    label: source.subtitle_group ?? '未知字幕组',
  })),
)

const effective = computed(() => effectiveSeeds(props.request))
const excluded = computed(() => excludedSeeds(props.request))
const completeGroups = computed(() => completeSeedGroups(props.request))
const selectedGroupName = computed(
  () => props.request.confirmable_config?.selected_subtitle_group ?? '未选择字幕组',
)

// ── #150 批量草案右栏 ────────────────────────────────────────────────
const batchLayout = computed(() => props.layout === 'batch')
const resourceDialog = ref<InstanceType<typeof ResourceDetailDialog> | null>(null)
/** 默认层只放少量安全示例；完整清单在弹窗里按需浏览。 */
const resourceSamples = computed(() => resourcePreview(effective.value, 2))
const hasAnyResource = computed(() => effective.value.length > 0 || excluded.value.length > 0)

/**
 * 右栏合集封面（#145）。
 *
 * 复用左栏条目卡与候选卡同一份 `publicPosterPath` 校验，而不是直接把宿主投影写进
 * `img.src`：外链、`data:`、`file:`、带凭据 URL、绝对本地路径和越界键路径一律
 * fail closed 退回占位，绝不进入任何 DOM 属性。
 */
const batchPosterUrl = computed(() => publicPosterPath(props.candidateSummary?.posterUrl))

function openResourceDetail(): void {
  resourceDialog.value?.open('effective')
}

// F4 default layer. The selected collection falls back to the server-confirmed
// matched title, then to the raw title, so the row is never blank on a saved
// plan that has no candidate projection; a redacting `displayValue` still
// guards the rendered text.
const selectedCollectionTitle = computed(
  () =>
    props.candidateSummary?.title ||
    (editorMode.value === 'saved' || batchLayout.value
      ? props.request.source_info?.matched_bangumi?.title || props.request.input?.raw_title
      : '') ||
    '未提供',
)

/**
 * #150／产品边界：批量右栏的「已选真实合集」只来自用户对真实 MiKan 合集的最终选择。
 *
 * 宿主只在用户本次会话明确点选候选（或服务端明确返回可证明的已确认选择）时才传入
 * `candidateSummary`。仅有服务端匹配信息时这里为 false：不显示「已选真实合集」，
 * 也不把匹配标题、季度或海报伪装成用户选择，而是就地提示待核对。
 */
const batchSelectionConfirmed = computed(() => Boolean(props.candidateSummary))

/**
 * #150：确认选择后给出合集名与季度；尚未确认时只显示条目自身的输入标题，
 * 不展示任何来自服务端匹配的合集名/季度。
 */
const batchCollectionHeading = computed(() => {
  if (!batchSelectionConfirmed.value) {
    return displayValue(props.request.input?.raw_title) || '未命名条目'
  }
  const title = displayValue(selectedCollectionTitle.value)
  const season = props.candidateSummary?.season
  return season ? `${title} · 第 ${season} 季` : title
})

/** 筛选规则 one-line summary for the default layer (rules stay authoritative). */
const filterSummaryText = computed(() => {
  const config = props.request.confirmable_config
  const rule = config?.filter_rule
  const mustContain = displayValue(rule?.must_contain) || '不限'
  const mustNotContain = displayValue(rule?.must_not_contain) || '不限'
  const mode = rule?.use_regex === true ? '正则' : '普通字符'
  const caseText = rule?.case_sensitive === true ? '区分大小写' : '不区分大小写'
  const folder = displayValue(config?.expected_folder_name) || '默认'
  return `包含 ${mustContain}；排除 ${mustNotContain}；${mode}；${caseText}；目录名 ${folder}`
})

resetForm()

function apply(): void {
  if (!dirty.value) {
    emit('empty-apply')
    return
  }
  emit('apply', patch.value)
}

function applySuggestion(suggestion: ReuseSuggestion): void {
  // Filling the form is not a transport decision: the suggestion is only
  // staged, and the user still submits it (or lets the scheduler send it).
  guarded(() => {
    editGroup.value = suggestion.selectedSubtitleGroup
    editMustContain.value = suggestion.filterRule.mustContain
    editMustNotContain.value = suggestion.filterRule.mustNotContain
    editUseRegex.value = suggestion.filterRule.useRegex
    editCaseSensitive.value = suggestion.filterRule.caseSensitive
    editFolderName.value = suggestion.expectedFolderName
    clearMustContain.value = false
    clearMustNotContain.value = false
    clearFolderName.value = false
  })
}

defineExpose({ patch, dirty, reset: resetForm, applySuggestion })
</script>

<template>
  <PanelSection
    :title="panelHeading"
    class="anime-draft-editor"
    :class="{ 'draft-review-editor': editorMode === 'draft' && !batchLayout, 'batch-draft-editor': batchLayout }"
    :data-mode="editorMode"
    :data-layout="batchLayout ? 'batch' : 'default'"
  >
    <!-- #150：批量草案右栏。先核对人工选择的真实 MiKan 合集，再集中修改常用筛选规则，
         资源结果只给四项计数与少量安全示例；正则、大小写与目录名留在折叠的高级设置。
         失败、结果未知与恢复动作（错误、重试、恢复上次结果）继续就地可见。 -->
    <div
      v-if="batchLayout"
      :id="props.containerId ?? 'anime-draft-editor'"
      class="request-detail batch-draft-review"
      aria-live="polite"
      aria-relevant="additions text"
    >
      <section
        class="batch-draft-identity"
        :class="{ 'is-unconfirmed': !batchSelectionConfirmed }"
        :data-selection-state="batchSelectionConfirmed ? 'confirmed' : 'unconfirmed'"
        :aria-label="batchSelectionConfirmed ? '已选真实合集' : '尚未确认真实合集'"
      >
        <span class="batch-draft-poster" :data-poster-state="batchPosterUrl ? 'ready' : 'placeholder'">
          <img
            v-if="batchPosterUrl"
            class="batch-draft-poster-image"
            :src="batchPosterUrl ?? undefined"
            alt=""
            loading="lazy"
            decoding="async"
          >
          <span v-else aria-hidden="true">暂无封面</span>
        </span>
        <div class="batch-draft-identity-text">
          <h3 class="request-detail-title">{{ batchCollectionHeading }}</h3>
          <span v-if="batchSelectionConfirmed" class="batch-draft-chip">已选真实合集</span>
          <span v-else class="batch-draft-chip is-unconfirmed">
            尚未确认真实合集：请先在左侧条目中选择真实 MiKan 合集
          </span>
        </div>
      </section>

      <section class="batch-draft-section" aria-label="字幕与筛选">
        <h4 class="batch-section-heading">字幕与筛选</h4>
        <form :id="props.formId" class="batch-draft-filter-form" @submit.prevent="apply">
          <FormField label="字幕组" :inputId="`${idPrefix}-subtitle-group`">
            <SubtitleGroupSelect
              v-model="editGroup"
              :options="groupOptions"
              :input-id="`${idPrefix}-subtitle-group`"
              :disabled="disabled || subtitleGroupReadOnly"
              :applying="applying"
            />
          </FormField>
          <FormField label="包含规则" :inputId="`${idPrefix}-must-contain`">
            <BaseInput :id="`${idPrefix}-must-contain`" v-model="editMustContain" type="text" placeholder="输入关键词，如 1080p" :disabled="disabled || clearMustContain" />
          </FormField>
          <FormField label="排除规则" :inputId="`${idPrefix}-must-not-contain`">
            <BaseInput :id="`${idPrefix}-must-not-contain`" v-model="editMustNotContain" type="text" placeholder="输入关键词，如 [v2]" :disabled="disabled || clearMustNotContain" />
          </FormField>
          <BaseButton
            :id="`${idPrefix}-apply-button`"
            class="batch-draft-apply"
            type="submit"
            :variant="props.applyVariant ?? 'secondary'"
            :loading="applying"
            :disabled="disabled || !dirty"
          >{{ applyLabel }}</BaseButton>
        </form>
        <p v-if="error" class="field-error" role="alert">{{ error }}</p>
        <div v-if="canRetry" class="detail-form-recovery" role="group" aria-label="修改失败恢复">
          <BaseButton :id="`${idPrefix}-retry-button`" type="button" variant="secondary" :loading="applying" @click="$emit('retry')">{{ retryLabel ?? '重试修改' }}</BaseButton>
          <BaseButton :id="`${idPrefix}-reset-button`" type="button" variant="secondary" :disabled="applying" @click="$emit('reset')">恢复上次结果</BaseButton>
        </div>
      </section>

      <section class="batch-draft-section batch-resource-results" aria-label="资源结果">
        <h4 class="batch-section-heading">资源结果</h4>
        <!-- #157：四项结果、安全示例与完整列表入口同处一个与「字幕与筛选」一致的描边盒子；
             盒内不再有设计图以外的横向/纵向分割线。 -->
        <div class="batch-resource-box">
          <ul class="batch-resource-metrics">
            <li class="batch-resource-metric" data-metric="effective">
              <span class="batch-metric-mark is-effective" aria-hidden="true"></span>
              <span class="batch-metric-label">有效资源</span>
              <span class="batch-metric-value">{{ effective.length }}</span>
              <span class="batch-metric-unit">个</span>
            </li>
            <li class="batch-resource-metric" data-metric="excluded">
              <span class="batch-metric-mark is-excluded" aria-hidden="true"></span>
              <span class="batch-metric-label">已排除</span>
              <span class="batch-metric-value">{{ excluded.length }}</span>
              <span class="batch-metric-unit">个</span>
            </li>
            <!-- #145/#165：不接入可信集数数据源，两个集数字段固定显示占位；文案与
                 单番候选卡、追番详情同源（features/workbench/episodeCount.ts），
                 既不从资源数推断，也不再使用「未知」作为集数占位。 -->
            <li class="batch-resource-metric" data-metric="updated-episodes">
              <span class="batch-metric-mark is-clock" aria-hidden="true"></span>
              <span class="batch-metric-label">已更新集数</span>
              <span class="batch-metric-value">{{ EPISODE_PLACEHOLDER }}</span>
            </li>
            <li class="batch-resource-metric" data-metric="total-episodes">
              <span class="batch-metric-mark is-bars" aria-hidden="true"></span>
              <span class="batch-metric-label">预期总集数</span>
              <span class="batch-metric-value">{{ EPISODE_PLACEHOLDER }}</span>
            </li>
          </ul>
          <ul v-if="resourceSamples.length" class="batch-resource-samples">
            <li v-for="seed in resourceSamples" :key="`sample-${seed}`" class="batch-resource-sample">
              <span class="batch-doc-glyph" aria-hidden="true"></span>
              <span class="batch-resource-sample-name">{{ seed }}</span>
            </li>
          </ul>
          <p v-else class="field-help">当前字幕组没有有效资源。</p>
          <button
            v-if="hasAnyResource"
            :id="`${idPrefix}-open-resources`"
            type="button"
            class="batch-resource-detail-link"
            @click="openResourceDetail"
          >
            查看完整资源列表 <span aria-hidden="true">›</span>
          </button>
        </div>
      </section>

      <!-- #150：高级设置默认折叠。display 不覆盖 details 的默认值，否则折叠时
           内容仍会被布局出来，既误导用户也撑出不可达的溢出。 -->
      <details class="batch-draft-advanced">
        <summary>高级设置</summary>
        <div class="batch-draft-advanced-body">
          <div class="filter-options">
            <CheckboxRow :id="`${idPrefix}-use-regex`" v-model:checked="editUseRegex" label="使用正则" :disabled="disabled" />
            <CheckboxRow :id="`${idPrefix}-case-sensitive`" v-model:checked="editCaseSensitive" label="大小写敏感" :disabled="disabled" />
          </div>
          <p class="field-help">默认按字面文本匹配且不区分大小写。</p>
          <FormField label="存储目录名" :inputId="`${idPrefix}-folder-name`">
            <BaseInput :id="`${idPrefix}-folder-name`" v-model="editFolderName" type="text" placeholder="期望存储目录名" :disabled="disabled || clearFolderName" />
          </FormField>
        </div>
      </details>

      <ResourceDetailDialog
        ref="resourceDialog"
        id-prefix="batch-resource-detail"
        :effective-seeds="effective"
        :excluded-seeds="excluded"
        :selected-group-name="selectedGroupName"
      />
    </div>

    <div v-else :id="props.containerId ?? 'anime-draft-editor'" class="request-detail" aria-live="polite" aria-relevant="additions text">
      <section class="draft-identity" aria-label="合集身份">
        <!-- F4: 标题同样取自公开合集投影，默认层不回显原始输入标题；技术上
             的「原始标题」留在下方折叠的技术层里。 -->
        <h3 class="request-detail-title">{{ displayValue(selectedCollectionTitle) }}</h3>

        <!-- F4 审核默认层：回答「已选哪部/哪一季、筛后有什么」。合集与季度来自
             宿主内存中的公开候选投影（未保存草案快照不含这些字段）；不适用时
             显示「未提供」而不是伪造取值。 -->
        <section class="draft-review-summary" aria-label="已选合集与筛选摘要">
          <dl class="detail-grid">
            <div class="detail-row"><dt>已选合集</dt><dd>{{ displayValue(selectedCollectionTitle) }}</dd></div>
            <div class="detail-row">
              <dt>季度</dt>
              <dd>{{ candidateSummary?.season ? `第 ${candidateSummary.season} 季` : '未提供' }}</dd>
            </div>
            <div class="detail-row">
              <dt>总集数</dt>
              <dd>{{ episodeCountText(candidateSummary?.totalEpisodes) }}</dd>
            </div>
            <div class="detail-row">
              <dt>封面</dt>
              <dd>{{ candidateSummary?.posterUrl ? '已提供' : '未提供' }}</dd>
            </div>
            <div class="detail-row">
              <dt>字幕组</dt>
              <dd>{{ displayValue(request.confirmable_config?.selected_subtitle_group) }}</dd>
            </div>
            <div class="detail-row">
              <dt>筛选规则</dt>
              <dd>{{ filterSummaryText }}</dd>
            </div>
          </dl>
        </section>
      </section>

      <form :id="props.formId" class="detail-inline-form draft-filter-column" @submit.prevent="apply">
        <h4 class="detail-form-heading">{{ formHeading }}</h4>
        <FormField :label="'字幕组'" :inputId="`${idPrefix}-subtitle-group`">
          <SubtitleGroupSelect
            v-model="editGroup"
            :options="groupOptions"
            :input-id="`${idPrefix}-subtitle-group`"
            :disabled="disabled || subtitleGroupReadOnly"
            :applying="applying"
          />
        </FormField>
        <FormField label="包含规则" :inputId="`${idPrefix}-must-contain`">
          <BaseInput :id="`${idPrefix}-must-contain`" v-model="editMustContain" type="text" placeholder="如 1080p（默认按字面匹配）" :disabled="disabled || clearMustContain" />
        </FormField>
        <CheckboxRow v-if="editorMode === 'saved'" :id="`${idPrefix}-clear-must-contain`" v-model:checked="clearMustContain" label="清空包含规则" :disabled="disabled" />
        <FormField label="排除规则" :inputId="`${idPrefix}-must-not-contain`">
          <BaseInput :id="`${idPrefix}-must-not-contain`" v-model="editMustNotContain" type="text" placeholder="如 [v2]（默认按字面匹配）" :disabled="disabled || clearMustNotContain" />
        </FormField>
        <CheckboxRow v-if="editorMode === 'saved'" :id="`${idPrefix}-clear-must-not-contain`" v-model:checked="clearMustNotContain" label="清空排除规则" :disabled="disabled" />
        <details class="advanced-settings">
          <summary>高级筛选设置</summary>
          <div class="filter-options">
            <CheckboxRow :id="`${idPrefix}-use-regex`" v-model:checked="editUseRegex" label="使用正则" :disabled="disabled" />
            <CheckboxRow :id="`${idPrefix}-case-sensitive`" v-model:checked="editCaseSensitive" label="大小写敏感" :disabled="disabled" />
          </div>
          <p class="field-help">默认按字面文本匹配且不区分大小写。</p>
          <FormField label="存储目录名" :inputId="`${idPrefix}-folder-name`">
            <BaseInput :id="`${idPrefix}-folder-name`" v-model="editFolderName" type="text" placeholder="期望存储目录名" :disabled="disabled || clearFolderName" />
            <CheckboxRow v-if="editorMode === 'saved'" :id="`${idPrefix}-clear-folder-name`" v-model:checked="clearFolderName" label="清空目录名" :disabled="disabled" />
          </FormField>
        </details>
        <p v-if="error" class="field-error" role="alert">{{ error }}</p>
        <div v-if="canRetry" class="detail-form-recovery" role="group" aria-label="修改失败恢复">
          <BaseButton :id="`${idPrefix}-retry-button`" type="button" variant="secondary" :loading="applying" @click="$emit('retry')">{{ retryLabel ?? '重试修改' }}</BaseButton>
          <BaseButton :id="`${idPrefix}-reset-button`" type="button" variant="secondary" :disabled="applying" @click="$emit('reset')">恢复上次结果</BaseButton>
        </div>
        <div class="detail-form-actions">
          <div v-if="editorMode === 'draft'" id="detail-save-modify" class="detail-save-modify-control">
            <BaseButton :id="`${idPrefix}-apply-button`" type="submit" :variant="props.applyVariant ?? 'primary'" :loading="applying" :disabled="disabled || !dirty">{{ applyLabel }}</BaseButton>
          </div>
          <BaseButton v-else :id="`${idPrefix}-apply-button`" type="submit" :variant="props.applyVariant ?? 'primary'" :loading="applying" :disabled="disabled || !dirty">{{ applyLabel }}</BaseButton>
        </div>
      </form>
      <slot name="review-note" />

      <!-- F4 技术层：内部 ID、原始标题、RSS 选择与英文区名默认折叠。 -->
      <details class="advanced-detail">
        <summary>全部信息（技术详情）</summary>

      <section class="detail-section overview-section" aria-label="Overview">
        <h4 class="detail-section-heading">Overview</h4>
        <dl class="detail-grid">
          <div class="detail-row"><dt>request_id</dt><dd>{{ displayValue(request.request_id) }}</dd></div>
          <div class="detail-row"><dt>状态</dt><dd>{{ statusLabel(request.status) }}</dd></div>
          <div class="detail-row"><dt>原始标题</dt><dd>{{ displayValue(request.input?.raw_title) }}</dd></div>
          <div class="detail-row"><dt>匹配标题</dt><dd>{{ displayValue(request.source_info?.matched_bangumi?.title) }}</dd></div>
        </dl>
      </section>

      <section class="detail-section source-section" aria-label="Source">
        <h4 class="detail-section-heading">Source</h4>
        <dl class="detail-grid">
          <div class="detail-row"><dt>字幕组</dt><dd>{{ displayValue(request.confirmable_config?.selected_subtitle_group) }}</dd></div>
          <div class="detail-row"><dt>RSS 来源</dt><dd>{{ request.confirmable_config?.selected_rss_url ? '已选择' : '未选择' }}</dd></div>
          <div class="detail-row"><dt>匹配番剧标题</dt><dd>{{ displayValue(request.source_info?.matched_bangumi?.title) }}</dd></div>
        </dl>
      </section>
      </details>

      <section class="detail-section filter-section" aria-label="筛选规则">
        <h4 class="detail-section-heading">筛选规则</h4>
        <dl class="detail-grid">
          <div class="detail-row"><dt>包含规则</dt><dd>{{ displayValue(request.confirmable_config?.filter_rule?.must_contain) }}</dd></div>
          <div class="detail-row"><dt>排除规则</dt><dd>{{ displayValue(request.confirmable_config?.filter_rule?.must_not_contain) }}</dd></div>
          <div class="detail-row"><dt>匹配模式</dt><dd>{{ request.confirmable_config?.filter_rule?.use_regex === true ? '正则' : '普通字符' }}</dd></div>
          <div class="detail-row"><dt>大小写</dt><dd>{{ request.confirmable_config?.filter_rule?.case_sensitive === true ? '区分大小写' : '不区分大小写' }}</dd></div>
          <div class="detail-row"><dt>存储目录名</dt><dd>{{ displayValue(request.confirmable_config?.expected_folder_name) }}</dd></div>
          <div class="detail-row"><dt>有效种子数</dt><dd>{{ effective.length }}</dd></div>
          <div class="detail-row"><dt>排除种子数</dt><dd>{{ excluded.length }}</dd></div>
        </dl>
      </section>

      <section class="detail-section seeds-section resource-summary-column" aria-label="资源摘要">
        <h4 class="detail-section-heading">资源摘要</h4>
        <ResourceSummary :effective-seeds="effective" :complete-groups="completeGroups" :excluded-seeds="excluded" :selected-group-name="selectedGroupName" />
      </section>
    </div>
  </PanelSection>
</template>

<style scoped>
.request-detail { display: grid; gap: 1rem; }
.request-detail-title { margin: 0; font-size: 1.15rem; }
.draft-review-summary { display: grid; gap: 0.5rem; border: 1px solid var(--color-border); border-radius: 6px; padding: 0.75rem; background: var(--color-bg-muted); }
.draft-review-summary dd { color: var(--color-text); }
.draft-identity { display: grid; gap: var(--space-3); border: var(--border-default); border-radius: var(--radius-lg); padding: var(--space-4); background: var(--color-bg); }
.draft-identity .request-detail-title { font-size: var(--type-section-title); line-height: 1.4; }
.draft-identity .draft-review-summary { border: 0; padding: 0; background: transparent; }
.advanced-detail { display: grid; gap: 0.75rem; border: 1px solid var(--color-border); border-radius: 6px; padding: 0.75rem; }
.advanced-detail summary { cursor: pointer; font-weight: 600; }
.detail-inline-form { display: grid; gap: 0.75rem; border: 1px solid var(--color-border); border-radius: 6px; padding: 1rem; }
.detail-form-heading, .detail-section-heading { margin: 0; font-size: 1rem; }
.detail-form-actions, .filter-options { display: flex; flex-wrap: wrap; gap: 0.5rem 1.25rem; }
.detail-save-modify-control { width: 176px; }
.detail-save-modify-control .base-button { width: 100%; }
.advanced-settings { display: grid; gap: 0.75rem; border-top: 1px solid var(--color-border); padding-top: 0.75rem; }
.advanced-settings summary { cursor: pointer; font-weight: 600; }
.detail-section { display: grid; gap: 0.5rem; }
.detail-section-heading { border-bottom: 1px solid var(--color-border); padding-bottom: 0.25rem; }
.detail-grid { margin: 0; display: grid; gap: 0.3rem 1rem; grid-template-columns: max-content 1fr; }
.detail-row { display: contents; }
.detail-row dt { font-weight: 600; color: var(--color-text-muted); }
.detail-row dd { margin: 0; overflow-wrap: anywhere; }

/* Stage 47 图 03：审核页的左侧编辑/规则与右侧资源摘要保持稳定双栏。
 * 只挂在 draft-review-editor 上，批量工作台和已保存方案继续使用共享旧布局。 */
.draft-review-editor {
  border: 0;
  padding: 0;
  background: transparent;
}
.draft-review-editor :deep(.panel-heading) { display: none; }

@media (min-width: 960px) {
  .draft-review-editor .request-detail {
    grid-template-columns: minmax(0, 480px) minmax(0, 1fr);
    column-gap: var(--space-6);
    align-items: start;
  }
  .draft-review-editor .draft-identity,
  .draft-review-editor > .request-detail > .review-note {
    grid-column: 1 / -1;
  }
  .draft-review-editor .detail-inline-form,
  .draft-review-editor .advanced-detail,
  .draft-review-editor .filter-section {
    grid-column: 1;
  }
  .draft-review-editor .seeds-section {
    grid-column: 2;
    grid-row: 2 / span 3;
    min-width: 0;
  }
  .draft-review-editor .detail-grid { grid-template-columns: max-content minmax(0, 1fr); }
  .draft-review-editor .draft-identity .detail-grid {
    grid-template-columns: max-content minmax(0, 1fr) max-content minmax(0, 1fr) max-content minmax(0, 1fr);
  }
  .draft-review-editor .advanced-detail { margin-top: 0; }
}
@media (max-width: 720px) { .detail-grid { grid-template-columns: 1fr; gap: 0.2rem; } }

/* ── #150：批量草案右栏 ──────────────────────────────────────────────
   默认层只有合集身份、字幕与筛选、四项资源结果与折叠的高级设置。面板标题、
   重复的筛选规则摘要、技术详情与按字幕组分组的完整种子列表都不在这里出现。 */
.batch-draft-editor {
  border: 0;
  background: transparent;
  padding: 0;
}

/* #150：批量草案右栏默认层不重复面板标题；但父级 PanelSection 用
   `aria-labelledby` 指向这个 h2，所以它必须留在可访问性树里——只做视觉隐藏，
   不能用 `display: none` 让 `aria-labelledby` 指向一个不渲染的元素。
   Issue #145：面板标题的隐藏规则见下（视觉隐藏而不是 display: none）。 */
.batch-draft-editor :deep(.panel-heading) {
  border: 0;
  clip-path: inset(50%);
  height: 1px;
  overflow: hidden;
  position: absolute;
  white-space: nowrap;
  width: 1px;
}

.batch-draft-review {
  display: grid;
  gap: 0;
}

/* 合集身份：设计图里是较大的横向封面 + 深海蓝标题 + 珊瑚橙「已选真实合集」胶囊。 */
.batch-draft-identity {
  align-items: center;
  border-bottom: 1px solid var(--color-border);
  display: flex;
  gap: var(--space-5);
  min-width: 0;
  padding-bottom: var(--space-4);
}

.batch-draft-poster {
  align-items: center;
  background: var(--color-surface-subtle);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  color: var(--color-text-muted);
  display: inline-flex;
  flex: 0 0 auto;
  font-size: 0.72rem;
  height: 70px;
  justify-content: center;
  overflow: hidden;
  width: 120px;
}

.batch-draft-poster-image {
  display: block;
  height: 100%;
  object-fit: cover;
  width: 100%;
}

.batch-draft-identity-text {
  display: grid;
  gap: var(--space-2);
  min-width: 0;
}

.batch-draft-identity-text .request-detail-title {
  color: var(--color-primary);
  font-size: var(--type-section-title);
  font-weight: var(--font-weight-bold);
  line-height: 1.3;
  margin: 0;
}

/* 珊瑚橙只做状态强调：这是「已选真实合集」的确认胶囊，不是可点击控件。 */
.batch-draft-chip {
  background: color-mix(in srgb, var(--color-accent) 12%, var(--color-surface));
  border-radius: var(--radius-pill);
  color: color-mix(in srgb, var(--color-accent) 78%, var(--color-text));
  font-size: var(--font-size-sm);
  font-weight: var(--font-weight-medium);
  justify-self: start;
  padding: 0.1rem var(--space-3);
}

/* 尚未确认选择：中性偏警示语气，绝不复用「已选」的珊瑚橙确认色，避免把服务端匹配
   信息读成用户已完成的选择。 */
.batch-draft-chip.is-unconfirmed {
  background: var(--color-warning-surface);
  color: var(--color-warning);
}

/* 「字幕与筛选」「资源结果」「高级设置」之间不用分割线：靠留白（分区上下内边距）区分模块，
   每个模块自身仍是一张带描边的盒子。 */
.batch-draft-section {
  display: grid;
  gap: var(--space-3);
  padding: var(--space-5) 0;
}

.batch-section-heading {
  color: var(--color-primary);
  font-size: var(--type-section-title);
  font-weight: var(--font-weight-semibold);
  margin: 0;
}

/* 字幕组、包含规则、排除规则与「保存修改」同一排；窄视口自然换行。
   常用筛选规则装在一张浅描边子卡里，与设计图的层级一致。 */
.batch-draft-filter-form {
  align-items: end;
  background: var(--color-surface);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-3);
  padding: var(--space-3) var(--space-4);
}

.batch-draft-filter-form :deep(.form-field) {
  flex: 1 1 12rem;
  min-width: 0;
}

.batch-draft-apply {
  flex: 0 0 auto;
}

/* #145/#157：资源结果与「字幕与筛选」同属一个描边盒子层级——盒内四项同排、安全示例
   自然换行，不再用无设计依据的横/竖分割线切分。 */
.batch-resource-box {
  background: var(--color-surface);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  display: grid;
  gap: var(--space-3);
  padding: var(--space-3) var(--space-4);
}

.batch-resource-metrics {
  align-items: center;
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-2) var(--space-6);
  list-style: none;
  margin: 0;
  padding: 0;
}

.batch-resource-metric {
  align-items: center;
  display: flex;
  gap: var(--space-2);
  min-width: 0;
}

/* 资源结果的标记完全由 CSS 画成，不依赖 emoji/符号字体在各环境的可用性。 */
.batch-metric-mark {
  border: 2px solid var(--color-text-muted);
  border-radius: 50%;
  color: var(--color-text-muted);
  display: inline-block;
  flex: 0 0 auto;
  height: 18px;
  position: relative;
  width: 18px;
}

/* 有效资源：绿色实心对勾。 */
.batch-metric-mark.is-effective {
  background: var(--color-success);
  border-color: var(--color-success);
}

.batch-metric-mark.is-effective::after {
  border: solid var(--color-text-inverse);
  border-width: 0 2px 2px 0;
  content: '';
  height: 9px;
  left: 6px;
  position: absolute;
  top: 2px;
  transform: rotate(45deg);
  width: 4px;
}

/* 已排除：灰色实心横杠。 */
.batch-metric-mark.is-excluded {
  background: var(--color-text-disabled);
  border-color: var(--color-text-disabled);
}

.batch-metric-mark.is-excluded::after {
  background: var(--color-text-inverse);
  content: '';
  height: 2px;
  left: 4px;
  position: absolute;
  top: 8px;
  width: 10px;
}

/* 已更新集数：时钟轮廓（圆 + 两条指针）。 */
.batch-metric-mark.is-clock::after {
  border-bottom: 2px solid currentColor;
  border-left: 2px solid currentColor;
  content: '';
  height: 5px;
  left: 4px;
  position: absolute;
  top: 3px;
  width: 5px;
}

/* 预期总集数：三根柱子的柱状图。 */
.batch-metric-mark.is-bars {
  border: 0;
  border-radius: 0;
  height: 16px;
  width: 18px;
}

.batch-metric-mark.is-bars::after {
  background:
    linear-gradient(currentColor, currentColor) left bottom / 4px 9px no-repeat,
    linear-gradient(currentColor, currentColor) center bottom / 4px 16px no-repeat,
    linear-gradient(currentColor, currentColor) right bottom / 4px 6px no-repeat;
  content: '';
  inset: 0;
  position: absolute;
}

.batch-doc-glyph {
  border: 1.5px solid var(--color-primary);
  border-radius: 3px;
  display: inline-block;
  flex: 0 0 auto;
  height: 16px;
  position: relative;
  width: 13px;
}

.batch-doc-glyph::after {
  background: var(--color-primary);
  content: '';
  height: 1.5px;
  left: 3px;
  position: absolute;
  top: 5px;
  width: 6px;
}

.batch-metric-label {
  color: var(--color-text-secondary);
}

.batch-metric-value {
  color: var(--color-text);
  font-weight: var(--font-weight-semibold);
}

.batch-metric-unit {
  color: var(--color-text-secondary);
}

.batch-resource-samples {
  display: grid;
  gap: var(--space-1);
  list-style: none;
  margin: 0;
  padding: 0;
}

.batch-resource-sample {
  align-items: center;
  display: flex;
  gap: var(--space-3);
  min-width: 0;
  padding: 0;
}

.batch-resource-sample-name {
  min-width: 0;
  overflow-wrap: anywhere;
}

/* #157：入口默认就是 primary 蓝的文本按钮；悬停给淡蓝圆角背景，键盘聚焦有可见焦点，
   不只靠下划线反馈。它仍是打开双页签弹窗的真实按钮，开关不改变右栏滚动位置。 */
.batch-resource-detail-link {
  background: none;
  border: 0;
  border-radius: var(--radius-sm);
  color: var(--color-primary);
  cursor: pointer;
  font-size: var(--font-size-md);
  font-weight: var(--font-weight-semibold);
  justify-self: start;
  margin-inline-start: calc(-1 * var(--space-2));
  padding: var(--space-1) var(--space-2);
}

.batch-resource-detail-link:hover {
  background: var(--color-primary-subtle);
}

.batch-resource-detail-link:focus-visible {
  background: var(--color-primary-subtle);
  outline: var(--focus-ring-width) solid var(--color-focus-ring);
  outline-offset: var(--focus-ring-offset);
}

/* #157：高级设置默认折叠，展开后紧凑对齐；不再用大内边距撑成一块粗重表单。 */
.batch-draft-advanced {
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  margin-top: var(--space-4);
  padding: var(--space-2) var(--space-3);
}

.batch-draft-advanced > summary {
  align-items: center;
  cursor: pointer;
  display: flex;
  font-size: var(--font-size-sm);
  font-weight: var(--font-weight-medium);
  justify-content: space-between;
  list-style: none;
  min-height: 1.5rem;
}

.batch-draft-advanced > summary::-webkit-details-marker {
  display: none;
}

.batch-draft-advanced > summary::after {
  border: solid var(--color-text-muted);
  border-width: 0 2px 2px 0;
  content: '';
  height: 7px;
  margin-inline-end: var(--space-1);
  transform: rotate(45deg);
  transition: transform 0.15s ease;
  width: 7px;
}

.batch-draft-advanced[open] > summary::after {
  transform: rotate(-135deg);
}

.batch-draft-advanced-body {
  display: grid;
  gap: var(--space-2);
  margin-top: var(--space-2);
}

.batch-draft-advanced-body .filter-options {
  gap: var(--space-2) var(--space-5);
}

.batch-draft-advanced-body .field-help {
  margin: 0;
}

</style>
