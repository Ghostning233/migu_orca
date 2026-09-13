import { describe, expect, it } from 'vitest'

import { router } from './index'

describe('Stage 33 application router (US-259)', () => {
  it('mounts the four catalog routes and keeps legacy paths as redirects only', () => {
    const routes = router.getRoutes()
    const named = Object.fromEntries(
      routes.filter((route) => route.name).map((route) => [route.name, route.path]),
    )

    expect(named).toEqual({
      add: '/add',
      plans: '/plans',
      tracking: '/tracking',
      settings: '/settings',
    })
    expect(routes.find((route) => route.path === '/workbench')?.redirect).toBeTypeOf('function')
    expect(routes.find((route) => route.path === '/requests')?.redirect).toBeTypeOf('function')
    expect(routes.find((route) => route.path === '/queue')?.redirect).toBeTypeOf('function')
  })

  it.each([
    ['/', '?batch_id=batch-root&request_id=dropped', '/add?batch_id=batch-root'],
    ['/workbench', '?batch_id=batch-1&token=dropped', '/add?batch_id=batch-1'],
    ['/requests', '?request_id=request-1&batch_id=dropped', '/plans?request_id=request-1'],
    ['/queue', '?batch_id=batch-2&endpoint=dropped', '/tracking'],
    ['/workbench', '?batch_id=one&batch_id=two', '/add'],
    ['/requests', '?request_id=', '/plans'],
  ])('replace-redirects %s with a sanitized query', async (source, query, expected) => {
    await router.replace(`${source}${query}`)

    expect(router.currentRoute.value.fullPath).toBe(expected)
  })

  it('sanitizes query values on direct visits to canonical routes', async () => {
    await router.replace(
      '/add?batch_id=batch-direct&token=drop-me&endpoint=secret.example.invalid',
    )

    expect(router.currentRoute.value.fullPath).toBe('/add?batch_id=batch-direct')
  })
})
