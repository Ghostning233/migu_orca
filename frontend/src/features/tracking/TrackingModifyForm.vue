<script setup lang="ts">
/**
 * Scope-separated modify form (US-313).
 *
 * One form per server-offered target scope — an external 番剧订阅 form and an
 * associated RSS form — so the two field sets can never be mixed: the emitted
 * payload is built by the scope's own builder in ``trackingManagement`` and is
 * ``null`` (never sent) when nothing was selected or a value is malformed.
 *
 * The form deliberately does not read the current external values: it is a
 * write-only field set, so an enabled-but-empty field is an explicit clear
 * rather than a silent "keep the existing value".
 */
import { computed, ref, watch } from 'vue'

import BaseButton from '@/components/forms/BaseButton.vue'
import BaseInput from '@/components/forms/BaseInput.vue'
import BaseSelect from '@/components/forms/BaseSelect.vue'
import FormField from '@/components/layout/FormField.vue'
import {
  buildRssPatch,
  buildSubscriptionPatch,
  emptyRssForm,
  emptySubscriptionForm,
  rssTextValue,
  setRssTextValue,
  setSubscriptionTextValue,
  subscriptionTextValue,
  type TrackingRssForm,
  type TrackingSubscriptionForm,
  type TrackingSubscriptionTextField,
} from './trackingManagement'
import {
  MODIFY_FORM_HELP,
  type TrackingAction,
  type TrackingItem,
  type TrackingManagementScope,
} from './trackingProjection'

const props = defineProps<{
  item: TrackingItem
  action: TrackingAction
  /** Page-level single-flight/blocked state; the page owns the request. */
  busy?: boolean
  /** This item's own modify request is in flight. */
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

const subscription = ref<TrackingSubscriptionForm>(emptySubscriptionForm())
const rss = ref<TrackingRssForm>(emptyRssForm())

// A new server revision means the request that produced the current form state
// is spent; the form resets so a stale selection can never be resubmitted.
watch(() => [props.item.tracking_id, props.item.revision], () => {
  subscription.value = emptySubscriptionForm()
  rss.value = emptyRssForm()
})

const SUBSCRIPTION_FIELDS = [
  { value: 'title', label: '官方标题', id: 'tracking-modify-title', help: '提交为空时会将 Auto Bangumi 的标题设为空。' },
  { value: 'season', label: '季度', id: 'tracking-modify-season', help: '0～100 的整数；提交为空时会将季度设为空。' },
  { value: 'subtitle_group', label: '字幕组', id: 'tracking-modify-subtitle-group', help: '提交为空时会将字幕组设为空。' },
  { value: 'offset', label: '集数偏移', id: 'tracking-modify-offset', help: '不小于 0 的整数；提交为空时会将偏移设为空。' },
  { value: 'expected_folder_name', label: '期望文件夹名称', id: 'tracking-modify-folder', help: '相对名称；提交为空时会将文件夹名称设为空。' },
] as const satisfies ReadonlyArray<{
  value: TrackingSubscriptionTextField
  label: string
  id: string
  help: string
}>

const BOOLEAN_OPTIONS = [
  { value: 'false', label: '否' },
  { value: 'true', label: '是' },
]

/** Server-offered scopes, in server order, intersected with the known set. */
const scopes = computed<TrackingManagementScope[]>(() => (
  (props.action.target_scopes ?? []).filter(
    (scope): scope is TrackingManagementScope =>
      scope === 'SUBSCRIPTION' || scope === 'ASSOCIATED_RSS',
  )
))
const subscriptionOffered = computed(() => scopes.value.includes('SUBSCRIPTION'))
const rssOffered = computed(() => scopes.value.includes('ASSOCIATED_RSS'))

const subscriptionPatch = computed(() => (
  subscriptionOffered.value ? buildSubscriptionPatch(subscription.value) : null
))
const rssPatch = computed(() => (rssOffered.value ? buildRssPatch(rss.value) : null))
const subscriptionBlocked = computed(() => subscriptionOffered.value && !subscriptionPatch.value)
const rssBlocked = computed(() => rssOffered.value && !rssPatch.value)

function toggleSubscriptionField(field: string, enabled: boolean): void {
  if (enabled) subscription.value.enabled[field] = true
  else delete subscription.value.enabled[field]
}

function toggleFilterField(field: string, enabled: boolean): void {
  if (enabled) subscription.value.filter[field] = true
  else delete subscription.value.filter[field]
}

function submitScope(scope: TrackingManagementScope, patch: unknown): void {
  if (props.busy) return
  if (!patch) return
  emit('submit', { action: props.action, item: props.item, targetScope: scope, patch })
}
</script>

<template>
  <div class="tracking-modify">
    <p class="field-help">{{ MODIFY_FORM_HELP }}</p>

    <form
      v-if="subscriptionOffered"
      class="tracking-modify-form"
      aria-labelledby="tracking-modify-subscription-heading"
      @submit.prevent="submitScope('SUBSCRIPTION', subscriptionPatch)"
    >
      <h5 id="tracking-modify-subscription-heading">修改外部番剧订阅</h5>
      <p class="field-help">只修改 Auto Bangumi 中的外部番剧订阅，不修改 MiGuOrca 本地方案。</p>
      <div
        v-for="field in SUBSCRIPTION_FIELDS"
        :key="field.value"
        class="tracking-modify-field"
      >
        <label class="tracking-modify-toggle" :for="`${field.id}-enabled`">
          <input
            :id="`${field.id}-enabled`"
            type="checkbox"
            class="base-checkbox"
            :checked="subscription.enabled[field.value] === true"
            @change="toggleSubscriptionField(field.value, ($event.target as HTMLInputElement).checked)"
          />
          <span>修改{{ field.label }}</span>
        </label>
        <template v-if="subscription.enabled[field.value] === true">
          <FormField :label="field.label" :input-id="field.id" :help="field.help">
            <BaseInput
              :id="field.id"
              :type="field.value === 'season' || field.value === 'offset' ? 'number' : 'text'"
              :model-value="subscriptionTextValue(subscription, field.value)"
              @update:model-value="setSubscriptionTextValue(subscription, field.value, $event)"
            />
          </FormField>
        </template>
      </div>

      <div class="tracking-modify-field">
        <label class="tracking-modify-toggle" for="tracking-modify-filter-enabled">
          <input
            id="tracking-modify-filter-enabled"
            type="checkbox"
            class="base-checkbox"
            :checked="subscription.enabled.filter_rule === true"
            @change="toggleSubscriptionField('filter_rule', ($event.target as HTMLInputElement).checked)"
          />
          <span>修改筛选规则</span>
        </label>
        <fieldset v-if="subscription.enabled.filter_rule === true" class="tracking-modify-filter">
          <legend>筛选规则</legend>
          <p class="field-help">
            未勾选的文本条件不会被提交，Auto Bangumi 中的对应值保持不变；两个开关会一起提交，因为
            Auto Bangumi 的筛选是一条完整的排除表达式。
          </p>
          <div class="tracking-modify-filter-field">
            <label class="tracking-modify-toggle" for="tracking-modify-must-contain-enabled">
              <input
                id="tracking-modify-must-contain-enabled"
                type="checkbox"
                class="base-checkbox"
                :checked="subscription.filter.must_contain === true"
                @change="toggleFilterField('must_contain', ($event.target as HTMLInputElement).checked)"
              />
              <span>修改必须包含</span>
            </label>
            <FormField
              v-if="subscription.filter.must_contain === true"
              label="必须包含"
              input-id="tracking-modify-must-contain"
              help="提交为空时该条件会被清空。"
            >
              <BaseInput id="tracking-modify-must-contain" type="text" v-model="subscription.mustContain" />
            </FormField>
          </div>
          <div class="tracking-modify-filter-field">
            <label class="tracking-modify-toggle" for="tracking-modify-must-not-contain-enabled">
              <input
                id="tracking-modify-must-not-contain-enabled"
                type="checkbox"
                class="base-checkbox"
                :checked="subscription.filter.must_not_contain === true"
                @change="toggleFilterField('must_not_contain', ($event.target as HTMLInputElement).checked)"
              />
              <span>修改必须不包含</span>
            </label>
            <FormField
              v-if="subscription.filter.must_not_contain === true"
              label="必须不包含"
              input-id="tracking-modify-must-not-contain"
              help="提交为空时该条件会被清空。"
            >
              <BaseInput id="tracking-modify-must-not-contain" type="text" v-model="subscription.mustNotContain" />
            </FormField>
          </div>
          <FormField label="使用正则" input-id="tracking-modify-use-regex">
            <BaseSelect
              id="tracking-modify-use-regex"
              label="使用正则"
              :options="BOOLEAN_OPTIONS"
              :model-value="subscription.useRegex ? 'true' : 'false'"
              @update:model-value="subscription.useRegex = $event === 'true'"
            />
          </FormField>
          <FormField label="区分大小写" input-id="tracking-modify-case-sensitive">
            <BaseSelect
              id="tracking-modify-case-sensitive"
              label="区分大小写"
              :options="BOOLEAN_OPTIONS"
              :model-value="subscription.caseSensitive ? 'true' : 'false'"
              @update:model-value="subscription.caseSensitive = $event === 'true'"
            />
          </FormField>
        </fieldset>
      </div>

      <p v-if="subscriptionBlocked" class="field-help" role="status">
        请至少勾选一个要修改的字段并填写合法的修改内容。
      </p>
      <BaseButton
        id="tracking-modify-subscription-submit"
        type="submit"
        :disabled="busy || subscriptionBlocked"
        :loading="loading"
      >确认修改外部番剧订阅</BaseButton>
    </form>

    <form
      v-if="rssOffered"
      class="tracking-modify-form"
      aria-labelledby="tracking-modify-rss-heading"
      @submit.prevent="submitScope('ASSOCIATED_RSS', rssPatch)"
    >
      <h5 id="tracking-modify-rss-heading">修改关联 RSS</h5>
      <p class="field-help">只修改 Auto Bangumi 中该追番的关联 RSS，不修改 MiGuOrca 本地方案。</p>
      <div class="tracking-modify-field">
        <label class="tracking-modify-toggle" for="tracking-modify-rss-name-enabled">
          <input
            id="tracking-modify-rss-name-enabled"
            type="checkbox"
            class="base-checkbox"
            :checked="rss.enabled.name === true"
            @change="rss.enabled.name = ($event.target as HTMLInputElement).checked"
          />
          <span>修改名称</span>
        </label>
        <FormField
          v-if="rss.enabled.name === true"
          label="名称"
          input-id="tracking-modify-rss-name"
          help="提交为空时会将 Auto Bangumi 的 RSS 名称设为空。"
        >
          <BaseInput
            id="tracking-modify-rss-name"
            type="text"
            :model-value="rssTextValue(rss, 'name')"
            @update:model-value="setRssTextValue(rss, 'name', $event)"
          />
        </FormField>
      </div>
      <div class="tracking-modify-field">
        <label class="tracking-modify-toggle" for="tracking-modify-rss-aggregate-enabled">
          <input
            id="tracking-modify-rss-aggregate-enabled"
            type="checkbox"
            class="base-checkbox"
            :checked="rss.enabled.aggregate === true"
            @change="rss.enabled.aggregate = ($event.target as HTMLInputElement).checked"
          />
          <span>修改聚合</span>
        </label>
        <FormField
          v-if="rss.enabled.aggregate === true"
          label="聚合"
          input-id="tracking-modify-rss-aggregate"
          help="聚合会合并同一 RSS 的多个资源；按你的明确选择提交。"
        >
          <BaseSelect
            id="tracking-modify-rss-aggregate"
            label="聚合"
            :options="BOOLEAN_OPTIONS"
            :model-value="rss.aggregate ? 'true' : 'false'"
            @update:model-value="rss.aggregate = $event === 'true'"
          />
        </FormField>
      </div>
      <div class="tracking-modify-field">
        <label class="tracking-modify-toggle" for="tracking-modify-rss-parser-enabled">
          <input
            id="tracking-modify-rss-parser-enabled"
            type="checkbox"
            class="base-checkbox"
            :checked="rss.enabled.parser === true"
            @change="rss.enabled.parser = ($event.target as HTMLInputElement).checked"
          />
          <span>修改解析器</span>
        </label>
        <FormField
          v-if="rss.enabled.parser === true"
          label="解析器"
          input-id="tracking-modify-rss-parser"
          help="提交为空时会将 Auto Bangumi 的解析器设为空。"
        >
          <BaseInput
            id="tracking-modify-rss-parser"
            type="text"
            :model-value="rssTextValue(rss, 'parser')"
            @update:model-value="setRssTextValue(rss, 'parser', $event)"
          />
        </FormField>
      </div>

      <p v-if="rssBlocked" class="field-help" role="status">
        请至少勾选一个 RSS 字段并填写合法的修改内容。
      </p>
      <BaseButton
        id="tracking-modify-rss-submit"
        type="submit"
        :disabled="busy || rssBlocked"
        :loading="loading"
      >确认修改关联 RSS</BaseButton>
    </form>
  </div>
</template>

<style scoped>
.tracking-modify { display: grid; gap: .65rem; }
.tracking-modify-form { display: grid; gap: .55rem; padding: var(--space-3); border: 1px solid var(--color-border-subtle); border-radius: var(--radius-sm); }
.tracking-modify-form h5 { margin: 0; font-size: .95rem; }
.tracking-modify-field { display: grid; gap: .35rem; }
.tracking-modify-toggle { display: flex; align-items: center; gap: .45rem; font-size: .85rem; font-weight: 600; }
.tracking-modify-filter { display: grid; gap: .5rem; margin: 0; padding: var(--space-3); border: 1px dashed var(--color-border); border-radius: var(--radius-sm); }
.tracking-modify-filter legend { font-size: .85rem; font-weight: 600; }
.tracking-modify-filter-field { display: grid; gap: .35rem; }
</style>
