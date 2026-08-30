import { mount } from '@vue/test-utils'
import { createPinia } from 'pinia'
import { describe, expect, it } from 'vitest'
import { createMemoryHistory, createRouter } from 'vue-router'

import App from '@/App.vue'

// The test router mirrors the application route table (paths are relative to
// the `/app/` history base used in src/app/router/index.ts). Using real
// routes keeps the shell test honest: RouterLink resolves to the actual
// workbench/settings destinations.
function makeRouter() {
  return createRouter({
    history: createMemoryHistory('/app/'),
    routes: [
      {
        path: '/',
        redirect: '/workbench',
      },
      {
        path: '/workbench',
        name: 'workbench',
        component: { template: '<p class="shell-route">工作台路由内容</p>' },
      },
      {
        path: '/settings',
        name: 'settings',
        component: { template: '<p class="shell-route">Settings 路由内容</p>' },
      },
    ],
  })
}

describe('App shell (US-197)', () => {
  it('renders the header, navigation and a routed view', async () => {
    const router = makeRouter()
    const wrapper = mount(App, {
      global: {
        plugins: [createPinia(), router],
      },
    })
    await router.isReady()
    await router.push('/workbench')

    expect(wrapper.find('.app-shell').exists()).toBe(true)
    expect(wrapper.find('.app-title').text()).toBe('MiGuOrca')
    expect(wrapper.find('.mode-summary').exists()).toBe(true)

    const navLinks = wrapper.findAll('.top-nav .nav-link')
    expect(navLinks).toHaveLength(2)
    expect(navLinks[0]?.text()).toContain('订阅方案工作台')
    expect(navLinks[1]?.text()).toContain('Settings')

    // The routed view is mounted inside <main class="app-main">.
    const main = wrapper.find('.app-main')
    expect(main.exists()).toBe(true)
    expect(main.find('.shell-route').text()).toBe('工作台路由内容')
  })

  it('renders the Settings route view', async () => {
    const router = makeRouter()
    const wrapper = mount(App, {
      global: {
        plugins: [createPinia(), router],
      },
    })
    await router.isReady()
    await router.push('/settings')

    expect(wrapper.find('.app-main .shell-route').text()).toBe('Settings 路由内容')
  })
})
