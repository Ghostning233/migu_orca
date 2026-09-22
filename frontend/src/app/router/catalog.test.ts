import { describe, expect, it } from 'vitest'

import {
  flaskEntryCatalog,
  legacyRouteCatalog,
  routeCatalog,
  routeLocation,
  sanitizeRouteQuery,
} from './catalog'

describe('Stage 33 route catalog (US-257)', () => {
  it('freezes the three primary paths, existing views, and query ownership', () => {
    expect(Object.values(routeCatalog).map(({ path }) => path)).toEqual([
      '/app/add',
      '/app/tracking',
      '/app/settings',
    ])
    expect(Object.values(routeCatalog).map(({ parity }) => parity.view)).toEqual([
      'WorkbenchView',
      'TrackingView',
      'SettingsView',
    ])
    expect(Object.fromEntries(Object.entries(routeCatalog).map(([key, value]) => [key, value.queryKey]))).toEqual({
      add: 'batch_id',
      tracking: 'tracking_id',
      settings: 'request_id',
    })
  })

  it('records the remaining SPA compatibility paths and four Flask entries', () => {
    // The retired 追番方案 route keeps no compatibility redirect at all.
    expect(legacyRouteCatalog).toEqual([
      { source: '/app/workbench', target: 'add', replace: true },
      { source: '/app/queue', target: 'tracking', replace: true },
    ])
    expect(flaskEntryCatalog).toEqual([
      { source: '/', target: 'add', replace: true },
      { source: '/index', target: 'add', replace: true },
      { source: '/settings', target: 'settings', replace: true },
      { source: '/Settings', target: 'settings', replace: true },
    ])
  })

  it.each([
    ['add', 'batch_id', 'batch-1'],
    ['tracking', 'tracking_id', 'tracking-2'],
    ['settings', 'request_id', 'request-2'],
  ] as const)('keeps the allowed scalar query for %s', (route, key, value) => {
    expect(sanitizeRouteQuery(route, { [key]: value })).toEqual({ [key]: value })
  })

  it.each([
    ['add', { batch_id: ['batch-1'] }, {}],
    ['tracking', { batch_id: ['batch-2', 'batch-3'] }, {}],
    ['settings', { request_id: '' }, {}],
    ['add', { batch_id: 'batch-1', request_id: 'request-1', token: 'secret' }, { batch_id: 'batch-1' }],
    ['add', { batch_id: 'https://private.invalid/credential' }, {}],
    ['settings', { request_id: 'request id with spaces' }, {}],
  ] as const)('drops arrays, empty values, unknown and sensitive query for %s', (route, query, expected) => {
    expect(sanitizeRouteQuery(route, query)).toEqual(expected)
  })

  it('rejects duplicate URLSearchParams values and trims one scalar value', () => {
    expect(sanitizeRouteQuery('add', new URLSearchParams('batch_id=batch-1&batch_id=batch-2'))).toEqual({})
    expect(sanitizeRouteQuery('tracking', new URLSearchParams('tracking_id=%20track-3%20'))).toEqual({
      tracking_id: 'track-3',
    })
    expect(sanitizeRouteQuery('tracking', { batch_id: 'batch-3' })).toEqual({})
    expect(sanitizeRouteQuery('tracking', { tracking_id: 'tracking-1', batch_id: 'batch-3' })).toEqual({ tracking_id: 'tracking-1' })
  })

  it('provides a router-ready location with a sanitized query', () => {
    expect(routeLocation('tracking', { tracking_id: 'tracking-1', batch_id: 'ignored' })).toEqual({
      path: '/tracking',
      query: { tracking_id: 'tracking-1' },
    })
    expect(routeLocation('tracking', { tracking_id: 'tracking-1' })).toEqual({
      path: '/tracking',
      query: { tracking_id: 'tracking-1' },
    })
  })
})
