import type { LocationQuery, LocationQueryRaw } from 'vue-router'

/**
 * The Stage 33 route contract.
 *
 * This is deliberately separate from the router record list: US-257 freezes
 * the public route/query boundary, while US-259 will make the router consume
 * the new paths and compatibility redirects.  Keeping the boundary here lets
 * navigation, redirects and future tests share one sanitizer.
 */
export type AppRouteKey = 'add' | 'plans' | 'tracking' | 'settings'

export type PublicQueryKey = 'batch_id' | 'request_id'

export interface RouteParityBaseline {
  readonly view: 'WorkbenchView' | 'RequestsView' | 'QueueView' | 'SettingsView'
  readonly vitest: readonly string[]
  readonly chromium: readonly string[]
}

export interface AppRouteCatalogEntry {
  readonly key: AppRouteKey
  readonly path: `/app/${string}`
  readonly routerPath: `/${string}`
  readonly queryKey: PublicQueryKey | null
  readonly parity: RouteParityBaseline
}

export interface LegacyRouteMapping {
  readonly source: string
  readonly target: AppRouteKey
  readonly replace: true
}

export interface FlaskEntryMapping extends LegacyRouteMapping {
  readonly source: '/' | '/index' | '/settings' | '/Settings'
}

export const routeCatalog = {
  add: {
    key: 'add',
    path: '/app/add',
    routerPath: '/add',
    queryKey: 'batch_id',
    parity: {
      view: 'WorkbenchView',
      vitest: ['src/features/workbench/WorkbenchView.test.ts', 'src/features/workbench/BatchWorkbenchView.test.ts'],
      chromium: ['tests/browser/test_app_batch_workbench.py'],
    },
  },
  plans: {
    key: 'plans',
    path: '/app/plans',
    routerPath: '/plans',
    queryKey: 'request_id',
    parity: {
      view: 'RequestsView',
      vitest: ['src/features/requests/RequestsView.test.ts', 'src/features/requests/RequestDetailPanel.test.ts'],
      chromium: ['tests/browser/test_app_requests.py', 'tests/browser/test_app_request_detail.py'],
    },
  },
  tracking: {
    key: 'tracking',
    path: '/app/tracking',
    routerPath: '/tracking',
    queryKey: 'batch_id',
    parity: {
      view: 'QueueView',
      vitest: ['src/features/queue/QueueView.test.ts', 'src/features/queue/queueWorkbench.test.ts'],
      chromium: ['tests/browser/test_app_queue.py'],
    },
  },
  settings: {
    key: 'settings',
    path: '/app/settings',
    routerPath: '/settings',
    queryKey: 'request_id',
    parity: {
      view: 'SettingsView',
      vitest: ['src/features/settings/SettingsView.test.ts'],
      chromium: ['tests/browser/test_app_settings.py'],
    },
  },
} as const satisfies Record<AppRouteKey, AppRouteCatalogEntry>

export const legacyRouteCatalog = [
  { source: '/app/workbench', target: 'add', replace: true },
  { source: '/app/requests', target: 'plans', replace: true },
  { source: '/app/queue', target: 'tracking', replace: true },
] as const satisfies readonly LegacyRouteMapping[]

export const flaskEntryCatalog = [
  { source: '/', target: 'add', replace: true },
  { source: '/index', target: 'add', replace: true },
  { source: '/settings', target: 'settings', replace: true },
  { source: '/Settings', target: 'settings', replace: true },
] as const satisfies readonly FlaskEntryMapping[]

type QueryInput =
  | LocationQueryRaw
  | Readonly<Record<string, string | readonly string[] | null | undefined>>
  | URLSearchParams

function nonEmptyScalar(value: unknown): string | undefined {
  if (typeof value !== 'string') return undefined
  const trimmed = value.trim()
  return /^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$/.test(trimmed) ? trimmed : undefined
}

/**
 * Keep only the one public scalar identifier consumed by a target route.
 *
 * Arrays are rejected even when they contain one value. This prevents a
 * duplicate query key from being silently interpreted differently by a
 * redirect, Vue Router, or a downstream feature.
 */
export function sanitizeRouteQuery(
  route: AppRouteKey | AppRouteCatalogEntry,
  query: QueryInput,
): LocationQuery {
  const entry = typeof route === 'string' ? routeCatalog[route] : route
  if (!entry.queryKey) return {}

  if (query instanceof URLSearchParams) {
    const values = query.getAll(entry.queryKey)
    if (values.length !== 1) return {}
    const value = nonEmptyScalar(values[0])
    return value ? { [entry.queryKey]: value } : {}
  }

  const rawValue = query[entry.queryKey]
  if (Array.isArray(rawValue) || rawValue === null) return {}
  const value = nonEmptyScalar(rawValue)
  return value ? { [entry.queryKey]: value } : {}
}

export function routeLocation(
  route: AppRouteKey,
  query: QueryInput = {},
): { path: `/${string}`; query: LocationQuery } {
  const entry = routeCatalog[route]
  return { path: entry.routerPath, query: sanitizeRouteQuery(entry, query) }
}
