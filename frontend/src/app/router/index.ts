import { createRouter, createWebHistory, type LocationQuery } from 'vue-router'

import type { AppRouteKey } from './catalog'
import { legacyRouteCatalog, routeCatalog, routeLocation } from './catalog'

/**
 * MiGuOrca application router (US-199).
 *
 * The SPA mounts at `/app/` (Flask serves the shell at `/app/` and falls back
 * to it for `/app/*` SPA routes — see apps/migu_orca_web/routes_app.py). The
 * router history base is `/app/`, so route paths below are relative to that
 * base: the add page lives at `/app/add` and Settings at `/app/settings`.
 *
 * Non-SPA routes must never be captured by the fallback: `/api/v1/*` (JSON
 * API), posters, `/healthz`, `/readiness` and the entry routes `/index` and
 * `/settings` stay on the Flask side. The Flask fallback route only matches
 * paths that do not start with those prefixes (see routes_app.py).
 */
const routeComponents = {
  add: () => import('@/features/workbench/WorkbenchView.vue'),
  plans: () => import('@/features/requests/RequestsView.vue'),
  tracking: () => import('@/features/queue/QueueView.vue'),
  settings: () => import('@/features/settings/SettingsView.vue'),
} satisfies Record<AppRouteKey, () => Promise<unknown>>

const routeTitles = {
  add: '添加番剧',
  plans: '追番方案',
  tracking: '追番管理',
  settings: '设置',
} satisfies Record<AppRouteKey, string>

export const appRoutes = [
  {
    path: '/',
    redirect: (to: { query: LocationQuery }) => routeLocation('add', to.query),
  },
  ...Object.values(routeCatalog).map((entry) => ({
    path: entry.routerPath,
    name: entry.key,
    component: routeComponents[entry.key],
    meta: { title: routeTitles[entry.key] },
  })),
  ...legacyRouteCatalog.map((mapping) => ({
    path: mapping.source.slice('/app'.length),
    redirect: (to: { query: LocationQuery }) => routeLocation(mapping.target, to.query),
  })),
]

export const router = createRouter({
  history: createWebHistory('/app/'),
  routes: appRoutes,
})

router.afterEach((to) => {
  const title = typeof to.meta.title === 'string' ? to.meta.title : 'MiGuOrca'
  document.title = `${title} · MiGuOrca`
})

router.beforeEach((to) => {
  if (typeof to.name !== 'string' || !(to.name in routeCatalog)) return true

  const route = to.name as AppRouteKey
  const sanitized = routeLocation(route, to.query).query
  const currentKeys = Object.keys(to.query)
  const sanitizedKeys = Object.keys(sanitized)
  const queryMatches =
    currentKeys.length === sanitizedKeys.length &&
    sanitizedKeys.every((key) => {
      const current = to.query[key]
      const expected = sanitized[key]
      return typeof current === 'string' && current === expected
    })

  if (queryMatches) return true
  return { path: to.path, query: sanitized, replace: true }
})
