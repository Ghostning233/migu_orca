<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, ref, watch } from 'vue'

import { api } from '@/api/client'
import type { operations } from '@/api/generated/api'
import BaseButton from '@/components/forms/BaseButton.vue'
import BaseInput from '@/components/forms/BaseInput.vue'
import BaseSelect from '@/components/forms/BaseSelect.vue'
import { useSensitiveFields } from '@/app/composables/useSensitiveFields'
import { useFocusTrap } from '@/app/composables/useFocusTrap'

type CapabilityResult = NonNullable<
  operations['probeAutoBangumiCapabilities']['responses']['200']['content']['application/json']['result']
>
type ProbeBody = NonNullable<
  operations['probeAutoBangumiCapabilities']['requestBody']['content']['application/json']
>

const props = defineProps<{ open: boolean }>()
const emit = defineEmits<{
  (event: 'update:open', value: boolean): void
  (event: 'connected', value: { config: ProbeBody['ab_config']; capabilities: CapabilityResult }): void
}>()

const fields = useSensitiveFields({
  baseUrl: { label: '服务地址' }, username: { label: '用户名' },
  password: { label: '密码' }, token: { label: 'API Token' },
})
const authMode = ref<'password' | 'api_token'>('password')
const fallbackEnabled = ref(false)
const probing = ref(false)
const probeError = ref('')
const capabilities = ref<CapabilityResult | null>(null)
const dialogEl = ref<HTMLElement | null>(null)
const { activate, deactivate } = useFocusTrap(dialogEl, () => cancel())
let probeSequence = 0
let probeController: AbortController | null = null

const baseUrl = computed({ get: () => fields.get('baseUrl'), set: (value: string) => fields.set('baseUrl', value) })
const username = computed({ get: () => fields.get('username'), set: (value: string) => fields.set('username', value) })
const password = computed({ get: () => fields.get('password'), set: (value: string) => fields.set('password', value) })
const token = computed({ get: () => fields.get('token'), set: (value: string) => fields.set('token', value) })

watch(() => props.open, async (open) => {
  if (open) {
    await nextTick()
    if (!props.open) return
    activate()
    dialogEl.value?.querySelector<HTMLInputElement>('#tracking-ab-base-url')?.focus()
  } else {
    invalidateProbe()
    fields.clearAll()
    capabilities.value = null
    deactivate()
  }
})
watch(authMode, () => {
  invalidateProbe()
  fields.reset()
  probeError.value = ''
  capabilities.value = null
})
onBeforeUnmount(() => { invalidateProbe(); fields.clearAll(); deactivate() })

function invalidateProbe(): void {
  probeSequence += 1
  probeController?.abort()
  probeController = null
  probing.value = false
}

function buildConfig(): ProbeBody['ab_config'] | null {
  if (!fields.get('baseUrl').trim()) {
    probeError.value = '请填写 Auto Bangumi 服务地址。'
    return null
  }
  if (authMode.value === 'password' && (!fields.get('username').trim() || !fields.get('password'))) {
    probeError.value = '请填写用户名和密码。'
    return null
  }
  if (authMode.value === 'api_token' && !fields.get('token')) {
    probeError.value = '请填写 API Token。'
    return null
  }
  const config: ProbeBody['ab_config'] = {
    auth_mode: authMode.value,
    base_url: fields.get('baseUrl'),
    fallback_enabled: fallbackEnabled.value,
  }
  if (authMode.value === 'password') {
    config.username = fields.get('username')
    config.password = fields.get('password')
  } else {
    config.token = fields.get('token')
  }
  return config
}

async function probe(): Promise<void> {
  if (probing.value) return
  const config = buildConfig()
  if (!config) return
  const sequence = ++probeSequence
  const controller = new AbortController()
  probeController?.abort()
  probeController = controller
  probing.value = true
  probeError.value = ''
  try {
    const result = await api.post<CapabilityResult>('/api/v1/autobangumi/capabilities', {
      body: { ab_config: config },
      signal: controller.signal,
    })
    if (sequence !== probeSequence || controller.signal.aborted) return
    capabilities.value = result
    emit('connected', { config, capabilities: result })
  } catch (error) {
    if (sequence !== probeSequence || controller.signal.aborted) return
    probeError.value = 'Auto Bangumi 连接探测失败，请检查输入后重试。'
    void error
  } finally {
    if (sequence === probeSequence) {
      probing.value = false
      if (probeController === controller) probeController = null
    }
  }
}

function cancel(): void {
  invalidateProbe()
  probeError.value = ''
  capabilities.value = null
  fields.clearAll()
  emit('update:open', false)
}

function clearSession(): void {
  invalidateProbe()
  fields.clearAll()
  capabilities.value = null
  probeError.value = ''
}

defineExpose({ clearSession })
</script>

<template>
  <Teleport to="body">
    <div v-if="props.open" ref="dialogEl" class="credential-dialog-backdrop" @click.self="cancel">
      <section class="credential-dialog" role="dialog" aria-modal="true" aria-labelledby="credential-dialog-title">
        <h2 id="credential-dialog-title">连接 Auto Bangumi</h2>
        <p class="field-help">凭据仅用于当前追番管理页面，不会保存或显示在页面外。</p>
        <label for="tracking-ab-auth-mode">认证方式</label>
        <BaseSelect id="tracking-ab-auth-mode" v-model="authMode" label="认证方式" :options="[
          { value: 'password', label: '用户名密码' }, { value: 'api_token', label: 'API Token' },
        ]" />
        <label for="tracking-ab-base-url">服务地址</label>
        <BaseInput id="tracking-ab-base-url" v-model="baseUrl" type="url" autocomplete="off" />
        <template v-if="authMode === 'password'">
          <label for="tracking-ab-username">用户名</label>
          <BaseInput id="tracking-ab-username" v-model="username" autocomplete="off" />
          <label for="tracking-ab-password">密码</label>
          <BaseInput id="tracking-ab-password" v-model="password" type="password" autocomplete="off" />
        </template>
        <template v-else>
          <label for="tracking-ab-token">API Token</label>
          <BaseInput id="tracking-ab-token" v-model="token" type="password" autocomplete="off" />
        </template>
        <p v-if="probeError" class="credential-dialog-error" role="alert">{{ probeError }}</p>
        <section v-if="capabilities" class="credential-capability-summary" aria-live="polite">
          <h3>能力探测结果</h3>
          <p>探测状态：{{ capabilities.probe_status }}</p>
          <p>版本：{{ capabilities.version || '未确认' }}</p>
          <p>提交能力：{{ capabilities.subscription_submit }}</p>
          <p>读取能力：{{ capabilities.subscription_list }} / {{ capabilities.subscription_detail }}</p>
          <p class="field-help">管理写能力仍需服务端按当前认证与版本逐项确认。</p>
        </section>
        <div class="credential-dialog-actions">
          <BaseButton variant="secondary" @click="cancel">取消</BaseButton>
          <BaseButton id="tracking-ab-probe" :loading="probing" :disabled="probing" @click="probe">探测并连接</BaseButton>
        </div>
      </section>
    </div>
  </Teleport>
</template>

<style scoped>
.credential-dialog-backdrop { position: fixed; inset: 0; z-index: var(--z-overlay); display: grid; place-items: center; padding: var(--space-4); background: var(--color-feedback-scrim); }
.credential-dialog { display: grid; gap: .65rem; width: min(30rem, 100%); max-height: min(42rem, 100%); overflow: auto; padding: var(--space-5); border: 1px solid var(--color-border-subtle); border-radius: var(--radius-lg); background: var(--color-surface-raised); color: var(--color-text); }
.credential-dialog h2, .credential-dialog h3, .credential-dialog p { margin: 0; }
.credential-dialog label { font-weight: 600; }
.credential-dialog-error { color: var(--color-danger-emphasis); }
.credential-capability-summary { display: grid; gap: .35rem; padding: var(--space-3); border: 1px solid var(--color-border); border-radius: var(--radius-md); }
.credential-dialog-actions { display: flex; justify-content: flex-end; gap: var(--space-2); margin-top: .5rem; }
</style>
