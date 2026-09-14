import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it } from 'vitest'
import { createMemoryHistory, createRouter } from 'vue-router'

import App from '@/App.vue'
import { useNotificationStore } from '@/app/stores/notification'

// The test router mirrors the application route table (paths are relative to
// the `/app/` history base used in src/app/router/index.ts). Using real
// routes keeps the shell test honest: RouterLink resolves to the actual
// add/settings destinations.
function makeRouter() {
  return createRouter({
    history: createMemoryHistory('/app/'),
    routes: [
      {
        path: '/',
        redirect: '/add',
      },
      {
        path: '/add',
        name: 'add',
        component: { template: '<p class="shell-route">工作台路由内容</p>' },
      },
      {
        path: '/plans',
        name: 'plans',
        component: { template: '<p class="shell-route">订阅方案路由内容</p>' },
      },
      {
        path: '/tracking',
        name: 'tracking',
        component: { template: '<p class="shell-route">提交队列路由内容</p>' },
      },
      {
        path: '/settings',
        name: 'settings',
        component: { template: '<p class="shell-route">Settings 路由内容</p>' },
      },
    ],
  })
}

describe('App shell (US-260)', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
  })

  it('renders the header, 4-route navigation and a routed view', async () => {
    const router = makeRouter()
    const wrapper = mount(App, {
      global: {
        plugins: [createPinia(), router],
      },
    })
    await router.isReady()
    await router.push('/add')

    expect(wrapper.find('.app-shell').exists()).toBe(true)
    expect(wrapper.find('.app-title').text()).toBe('MiGuOrca')
    expect(wrapper.find('.brand-eyebrow').text()).toBe('桌面番剧工作台')
    expect(wrapper.find('.workspace-status').text()).toContain('Auto Bangumi：需检查')

    const navLinks = wrapper.findAll('.top-nav .nav-link')
    expect(navLinks).toHaveLength(4)
    expect(navLinks[0]?.text()).toContain('添加番剧')
    expect(navLinks[1]?.text()).toContain('追番方案')
    expect(navLinks[2]?.text()).toContain('追番管理')
    expect(navLinks[3]?.text()).toContain('设置')
    expect(navLinks[0]?.attributes('aria-current')).toBe('page')
    expect(navLinks[0]?.find('.nav-current-marker').text()).toBe('当前')
    expect(navLinks.slice(1).every((link) => link.attributes('aria-current') === undefined)).toBe(true)

    const main = wrapper.find('.app-main')
    expect(main.exists()).toBe(true)
    expect(main.find('.shell-route').text()).toBe('工作台路由内容')
  })

  it('renders the Requests, Queue and Settings route views', async () => {
    const router = makeRouter()
    const wrapper = mount(App, {
      global: {
        plugins: [createPinia(), router],
      },
    })
    await router.isReady()

    await router.push('/plans')
    expect(wrapper.find('.app-main .shell-route').text()).toBe('订阅方案路由内容')

    await router.push('/tracking')
    expect(wrapper.find('.app-main .shell-route').text()).toBe('提交队列路由内容')

    await router.push('/settings')
    expect(wrapper.find('.app-main .shell-route').text()).toBe('Settings 路由内容')
  })

  it('moves focus to the main content only when the page route changes', async () => {
    const host = document.createElement('div')
    document.body.append(host)
    const router = makeRouter()
    const wrapper = mount(App, {
      attachTo: host,
      global: {
        plugins: [createPinia(), router],
      },
    })
    await router.isReady()

    await router.push('/plans')
    await wrapper.vm.$nextTick()
    expect(document.activeElement).toBe(wrapper.find('main#app-main').element)
    expect(wrapper.findAll('.nav-link')[1]?.attributes('aria-current')).toBe('page')

    const search = document.createElement('input')
    wrapper.find('main#app-main').element.append(search)
    search.focus()
    await router.push({ path: '/plans', query: { request_id: 'request-1' } })
    await wrapper.vm.$nextTick()
    expect(document.activeElement).toBe(search)

    wrapper.unmount()
    host.remove()
  })

  it('shows the global notification region with an aria-live role', async () => {
    const router = makeRouter()
    const wrapper = mount(App, {
      global: {
        plugins: [createPinia(), router],
      },
    })
    await router.isReady()

    const notification = useNotificationStore()
    notification.success('保存成功', '订阅方案已保存。')
    await wrapper.vm.$nextTick()

    const region = wrapper.find('.global-notification')
    expect(region.exists()).toBe(true)
    expect(region.attributes('aria-live')).toBe('polite')
    expect(region.attributes('role')).toBe('status')
    expect(region.text()).toContain('保存成功')
    expect(region.text()).toContain('订阅方案已保存。')

    notification.clear()
    await wrapper.vm.$nextTick()
    expect(wrapper.find('.global-notification').exists()).toBe(false)
  })

  it('renders error notifications with role=alert and a close button', async () => {
    const router = makeRouter()
    const wrapper = mount(App, {
      global: {
        plugins: [createPinia(), router],
      },
    })
    await router.isReady()

    const notification = useNotificationStore()
    notification.error('请求失败', '网络请求失败，请检查网络后重试。')
    await wrapper.vm.$nextTick()

    const region = wrapper.find('.global-notification')
    expect(region.attributes('role')).toBe('alert')
    expect(region.classes()).toContain('global-notification-error')

    await wrapper.find('.global-notification-close').trigger('click')
    expect(wrapper.find('.global-notification').exists()).toBe(false)
  })

  it('renders a keyboard skip link to the main landmark (US-207)', async () => {
    const router = makeRouter()
    const wrapper = mount(App, {
      global: {
        plugins: [createPinia(), router],
      },
    })
    await router.isReady()
    await router.push('/plans')

    const skip = wrapper.find('.skip-link')
    expect(skip.exists()).toBe(true)
    expect(skip.attributes('href')).toBe('#app-main')
    expect(skip.text()).toBe('跳到主要内容')

    const main = wrapper.find('main#app-main')
    expect(main.exists()).toBe(true)
    expect(main.attributes('tabindex')).toBe('-1')
  })
})
