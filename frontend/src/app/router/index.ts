import { createRouter, createWebHistory } from 'vue-router'

/**
 * MiGuOrca application router (US-199).
 *
 * The SPA mounts at `/app/` (Flask serves the shell at `/app/` and falls back
 * to it for `/app/*` SPA routes — see apps/migu_orca_web/routes_app.py). The
 * router history base is `/app/`, so route paths below are relative to that
 * base: the workbench lives at `/app/workbench` and Settings at
 * `/app/settings`.
 *
 * Non-SPA routes must never be captured by the fallback: `/api/v1/*` (JSON
 * API), `/migu-orca-static/*` (legacy static assets), `/healthz`,
 * `/readiness` and the legacy Flask pages `/index` and `/settings` stay on the
 * Flask side. The Flask fallback route only matches paths that do not start
 * with those prefixes (see routes_app.py).
 */
export const router = createRouter({
  history: createWebHistory('/app/'),
  routes: [
    {
      path: '/',
      redirect: '/workbench',
    },
    {
      path: '/workbench',
      name: 'workbench',
      component: () => import('@/features/workbench/WorkbenchView.vue'),
      meta: { title: '订阅方案工作台' },
    },
    {
      path: '/requests',
      name: 'requests',
      component: () => import('@/features/requests/RequestsView.vue'),
      meta: { title: '订阅方案' },
    },
    {
      path: '/queue',
      name: 'queue',
      component: () => import('@/features/queue/QueueView.vue'),
      meta: { title: '提交队列' },
    },
    {
      path: '/settings',
      name: 'settings',
      component: () => import('@/features/settings/SettingsView.vue'),
      meta: { title: 'Settings' },
    },
    // US-200 primitive gallery. This route is a staging artifact used by the
    // real-Chromium verification test (tests/browser/test_components_primitives.py);
    // it is not part of the user-facing navigation. US-201+ builds the real
    // features on the same primitives, and US-209 removes this route together
    // with the other migration scaffolding.
    {
      path: '/components-demo',
      name: 'components-demo',
      component: () => import('@/features/components/ComponentsDemoView.vue'),
      meta: { title: '组件原语' },
    },
  ],
})

router.afterEach((to) => {
  const title = typeof to.meta.title === 'string' ? to.meta.title : 'MiGuOrca'
  document.title = `${title} · MiGuOrca`
})
