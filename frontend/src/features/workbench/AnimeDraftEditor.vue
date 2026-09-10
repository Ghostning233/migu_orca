<script setup lang="ts">
// AnimeDraftEditor (US-270).
//
// Shared, controlled review UI for single and batch drafts. It owns only the
// transient form controls; the parent owns the Request snapshot, draft
// capability, revision and transport. In particular, this component has no
// save/confirm endpoint dependency and never receives sensitive source data.
import { computed, ref, watch } from 'vue'

import BaseButton from '@/components/forms/BaseButton.vue'
import BaseInput from '@/components/forms/BaseInput.vue'
import CheckboxRow from '@/components/forms/CheckboxRow.vue'
import FormField from '@/components/layout/FormField.vue'
import PanelSection from '@/components/layout/PanelSection.vue'

import ResourceSummary from '@/features/workbench/ResourceSummary.vue'
import SubtitleGroupSelect from '@/features/workbench/SubtitleGroupSelect.vue'
import {
  collectPreviewEditPatch,
  type PreviewEditState,
  type PreviewPatch,
} from '@/features/workbench/candidateSearch'
import {
  completeSeedGroups,
  displayValue,
  effectiveSeeds,
  excludedSeeds,
  type RequestSnapshot,
} from '@/features/requests/requestDetail'
import { statusLabel } from '@/features/requests/requestsList'

const props = defineProps<{
  request: RequestSnapshot
  applying?: boolean
  error?: string
  disabled?: boolean
  idPrefix?: string
  containerId?: string
  formId?: string
  canRetry?: boolean
}>()

const emit = defineEmits<{
  (e: 'apply', patch: PreviewPatch): void
  (e: 'dirty-change', dirty: boolean): void
  (e: 'retry'): void
  (e: 'reset'): void
}>()

const idPrefix = computed(() => props.idPrefix ?? 'anime-draft')

const editGroup = ref('')
const editMustContain = ref('')
const editMustNotContain = ref('')
const editUseRegex = ref(false)
const editCaseSensitive = ref(false)
const editFolderName = ref('')

function stateFromRequest(request: RequestSnapshot): PreviewEditState {
  const config = request.confirmable_config
  return {
    selectedSubtitleGroup: config?.selected_subtitle_group ?? '',
    mustContain: config?.filter_rule?.must_contain ?? '',
    mustNotContain: config?.filter_rule?.must_not_contain ?? '',
    useRegex: config?.filter_rule?.use_regex === true,
    caseSensitive: config?.filter_rule?.case_sensitive === true,
    expectedFolderName: config?.expected_folder_name ?? '',
  }
}

function resetForm(): void {
  const state = stateFromRequest(props.request)
  editGroup.value = state.selectedSubtitleGroup
  editMustContain.value = state.mustContain
  editMustNotContain.value = state.mustNotContain
  editUseRegex.value = state.useRegex
  editCaseSensitive.value = state.caseSensitive
  editFolderName.value = state.expectedFolderName
  emit('dirty-change', false)
}

function currentState(): PreviewEditState {
  return {
    selectedSubtitleGroup: editGroup.value,
    mustContain: editMustContain.value.trim(),
    mustNotContain: editMustNotContain.value.trim(),
    useRegex: editUseRegex.value,
    caseSensitive: editCaseSensitive.value,
    expectedFolderName: editFolderName.value.trim(),
  }
}

const originalState = computed(() => stateFromRequest(props.request))
const patch = computed(() => collectPreviewEditPatch(originalState.value, currentState()))
const dirty = computed(() => Object.keys(patch.value).length > 0)

watch(dirty, (value) => emit('dirty-change', value), { immediate: true })
watch(() => props.request, resetForm, { deep: true })

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

resetForm()

function apply(): void {
  if (!dirty.value) return
  emit('apply', patch.value)
}

defineExpose({ patch, dirty })
</script>

<template>
  <PanelSection title="订阅方案详情" class="anime-draft-editor">
    <div :id="props.containerId ?? 'anime-draft-editor'" class="request-detail" aria-live="polite" aria-relevant="additions text">
      <h3 class="request-detail-title">
        {{ request.input?.raw_title || request.source_info?.matched_bangumi?.title || '订阅方案' }}
      </h3>

      <form :id="props.formId" class="detail-inline-form" @submit.prevent="apply">
        <h4 class="detail-form-heading">编辑订阅草案</h4>
        <FormField :label="'字幕组'" :inputId="`${idPrefix}-subtitle-group`">
          <SubtitleGroupSelect
            v-model="editGroup"
            :options="groupOptions"
            :input-id="`${idPrefix}-subtitle-group`"
            :disabled="disabled"
            :applying="applying"
          />
        </FormField>
        <FormField label="包含规则" :inputId="`${idPrefix}-must-contain`">
          <BaseInput :id="`${idPrefix}-must-contain`" v-model="editMustContain" type="text" placeholder="如 1080p（默认按字面匹配）" :disabled="disabled" />
        </FormField>
        <FormField label="排除规则" :inputId="`${idPrefix}-must-not-contain`">
          <BaseInput :id="`${idPrefix}-must-not-contain`" v-model="editMustNotContain" type="text" placeholder="如 [v2]（默认按字面匹配）" :disabled="disabled" />
        </FormField>
        <details class="advanced-settings">
          <summary>高级筛选设置</summary>
          <div class="filter-options">
            <CheckboxRow :id="`${idPrefix}-use-regex`" v-model:checked="editUseRegex" label="使用正则" :disabled="disabled" />
            <CheckboxRow :id="`${idPrefix}-case-sensitive`" v-model:checked="editCaseSensitive" label="大小写敏感" :disabled="disabled" />
          </div>
          <p class="field-help">默认按字面文本匹配且不区分大小写。</p>
          <FormField label="存储目录名" :inputId="`${idPrefix}-folder-name`">
            <BaseInput :id="`${idPrefix}-folder-name`" v-model="editFolderName" type="text" placeholder="期望存储目录名" :disabled="disabled" />
          </FormField>
        </details>
        <p v-if="error" class="field-error" role="alert">{{ error }}</p>
        <div v-if="canRetry" class="detail-form-recovery" role="group" aria-label="修改失败恢复">
          <BaseButton :id="`${idPrefix}-retry-button`" type="button" variant="secondary" :loading="applying" @click="$emit('retry')">重试修改</BaseButton>
          <BaseButton :id="`${idPrefix}-reset-button`" type="button" variant="secondary" :disabled="applying" @click="$emit('reset')">恢复上次结果</BaseButton>
        </div>
        <div class="detail-form-actions">
          <BaseButton :id="`${idPrefix}-apply-button`" type="submit" variant="primary" :loading="applying" :disabled="disabled || !dirty">应用修改</BaseButton>
        </div>
      </form>
      <slot name="review-note" />

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

      <section class="detail-section filter-section" aria-label="Filter">
        <h4 class="detail-section-heading">Filter</h4>
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

      <section class="detail-section seeds-section" aria-label="Seeds">
        <h4 class="detail-section-heading">Seeds</h4>
        <ResourceSummary :effective-seeds="effective" :complete-groups="completeGroups" :excluded-seeds="excluded" :selected-group-name="selectedGroupName" />
      </section>
    </div>
  </PanelSection>
</template>

<style scoped>
.request-detail { display: grid; gap: 1rem; }
.request-detail-title { margin: 0; font-size: 1.15rem; }
.detail-inline-form { display: grid; gap: 0.75rem; border: 1px solid var(--color-border); border-radius: 6px; padding: 1rem; }
.detail-form-heading, .detail-section-heading { margin: 0; font-size: 1rem; }
.detail-form-actions, .filter-options { display: flex; flex-wrap: wrap; gap: 0.5rem 1.25rem; }
.advanced-settings { display: grid; gap: 0.75rem; border-top: 1px solid var(--color-border); padding-top: 0.75rem; }
.advanced-settings summary { cursor: pointer; font-weight: 600; }
.detail-section { display: grid; gap: 0.5rem; }
.detail-section-heading { border-bottom: 1px solid var(--color-border); padding-bottom: 0.25rem; }
.detail-grid { margin: 0; display: grid; gap: 0.3rem 1rem; grid-template-columns: max-content 1fr; }
.detail-row { display: contents; }
.detail-row dt { font-weight: 600; color: var(--color-text-muted); }
.detail-row dd { margin: 0; overflow-wrap: anywhere; }
@media (max-width: 720px) { .detail-grid { grid-template-columns: 1fr; gap: 0.2rem; } }
</style>
