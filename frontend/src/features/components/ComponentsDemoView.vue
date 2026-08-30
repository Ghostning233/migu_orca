<script setup lang="ts">
// Components demo view (US-200 browser verification).
//
// This route renders every US-200 primitive so the real-Chromium browser test
// (tests/browser/test_components_primitives.py) can verify focus, confirm,
// status and 360px behaviors against a built SPA. It is deliberately
// stateless: the sensitive credential fields hold values only in component
// memory (useSensitiveFields) and are cleared on confirm/success/cancel — the
// exact security boundary the real features (US-201+) will rely on. No values
// are persisted anywhere.
import { computed, ref } from 'vue'

import ConfirmDialog from '@/components/feedback/ConfirmDialog.vue'
import StatusAlert from '@/components/feedback/StatusAlert.vue'
import BaseButton from '@/components/forms/BaseButton.vue'
import BaseInput from '@/components/forms/BaseInput.vue'
import BaseSelect from '@/components/forms/BaseSelect.vue'
import BaseTextarea from '@/components/forms/BaseTextarea.vue'
import CheckboxRow from '@/components/forms/CheckboxRow.vue'
import PanelSection from '@/components/layout/PanelSection.vue'

import { useSensitiveFields } from '@/app/composables/useSensitiveFields'

const confirmDialog = ref<InstanceType<typeof ConfirmDialog> | null>(null)

const demoText = ref('')
const demoSelect = ref('official_title_season')
const demoChecked = ref(true)

// The credential form demo mirrors the real security boundary: every value
// lives only in this composable's component-local reactive memory, and is
// cleared on success/cancel/auth-mode switch.
const credentials = useSensitiveFields({
  endpoint: { label: '服务地址', required: true },
  username: { label: '用户名', required: true },
  password: { label: '密码', required: true },
})

const endpointModel = computed({
  get: () => credentials.get('endpoint'),
  set: (value: string) => credentials.set('endpoint', value),
})
const usernameModel = computed({
  get: () => credentials.get('username'),
  set: (value: string) => credentials.set('username', value),
})
const passwordModel = computed({
  get: () => credentials.get('password'),
  set: (value: string) => credentials.set('password', value),
})

const lastConfirmResult = ref('')
const status = ref({ kind: 'empty' as 'success' | 'error' | 'info' | 'empty', message: '尚未操作。' })

async function askConfirm(): Promise<void> {
  const ok = await confirmDialog.value?.confirm({
    title: '确认删除',
    message: '此操作不可恢复。确认继续？',
    confirmLabel: '确认删除',
    cancelLabel: '返回',
    danger: true,
  })
  lastConfirmResult.value = ok ? '已确认' : '已取消'
}

function testConnection(): void {
  const missing = credentials.firstMissing()
  if (missing) {
    status.value = { kind: 'error', message: `请填写 ${missing}。` }
    return
  }
  // In the real feature this would be a single request-scoped POST; here we
  // only demonstrate that a successful action clears the sensitive fields.
  const payload = credentials.snapshot()
  void payload
  credentials.clearAll()
  status.value = { kind: 'success', message: '连接成功；敏感字段已清空。' }
}

function cancelCredential(): void {
  credentials.reset()
  status.value = { kind: 'info', message: '已取消并清空认证信息。' }
}

function switchAuthMode(): void {
  credentials.reset()
  status.value = { kind: 'info', message: '已切换认证方式并清空认证信息。' }
}
</script>

<template>
  <div class="components-demo">
    <h2 class="components-demo-title">组件原语演示（US-200）</h2>

    <PanelSection title="确认对话框">
      <BaseButton id="demo-confirm-trigger" variant="primary" @click="askConfirm">打开确认对话框</BaseButton>
      <p class="demo-result" aria-live="polite">上次结果：{{ lastConfirmResult || '尚未操作' }}</p>
    </PanelSection>

    <PanelSection title="敏感凭据表单">
      <div class="credential-fields">
        <BaseInput
          id="demo-credential-endpoint"
          v-model="endpointModel"
          type="text"
          label="服务地址"
          placeholder="qBittorrent Web UI endpoint"
          autocomplete="off"
        />
        <BaseInput
          id="demo-credential-username"
          v-model="usernameModel"
          type="text"
          label="用户名"
          autocomplete="off"
        />
        <BaseInput
          id="demo-credential-password"
          v-model="passwordModel"
          type="password"
          label="密码"
          autocomplete="off"
        />
      </div>
      <StatusAlert :kind="status.kind" :message="status.message" />
      <div class="demo-actions">
        <BaseButton id="demo-credential-test" variant="primary" @click="testConnection">测试连接（成功后清空）</BaseButton>
        <BaseButton id="demo-credential-cancel" @click="cancelCredential">取消（清空）</BaseButton>
        <BaseButton id="demo-credential-switch" @click="switchAuthMode">切换认证方式（清空）</BaseButton>
      </div>
    </PanelSection>

    <PanelSection title="表单控件">
      <BaseInput v-model="demoText" type="text" label="文本输入" placeholder="输入内容" />
      <BaseTextarea label="多行输入" placeholder="逐行输入" />
      <BaseSelect
        v-model="demoSelect"
        label="命名策略"
        :options="[
          { value: 'official_title_season', label: '官方标题 + 季数' },
          { value: 'official_title', label: '官方标题' },
          { value: 'raw_title', label: '原始标题' },
        ]"
      />
      <CheckboxRow v-model:checked="demoChecked" label="默认保存订阅方案" help="非敏感展示偏好。" />
    </PanelSection>

    <PanelSection title="加载与状态">
      <StatusAlert kind="success" message="偏好默认值已保存。" />
      <StatusAlert kind="error" message="网络请求失败，请检查网络后重试。" />
      <StatusAlert kind="info" message="已恢复默认偏好。" />
      <StatusAlert kind="empty" message="尚未读取偏好默认值。" />
    </PanelSection>

    <ConfirmDialog ref="confirmDialog" />
  </div>
</template>

<style scoped>
.components-demo {
  display: grid;
  gap: 1.25rem;
}

.components-demo-title {
  margin: 0 0 0.25rem;
  font-size: 1.25rem;
}

.demo-result {
  color: var(--color-text-muted);
}

.credential-fields {
  display: grid;
  gap: 0.5rem;
  max-width: 480px;
}

.demo-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 0.5rem;
}
</style>
