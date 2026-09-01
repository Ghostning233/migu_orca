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
 * API), posters, `/healthz`, `/readiness` and the entry routes `/index` and
 * `/settings` stay on the Flask side. The Flask fallback route only matches
 * paths that do not start with those prefixes (see routes_app.py).
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
  ],
})

router.afterEach((to) => {
  const title = typeof to.meta.title === 'string' ? to.meta.title : 'MiGuOrca'
  document.title = `${title} · MiGuOrca`
})
