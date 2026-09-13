import { readFileSync, readdirSync, statSync } from 'node:fs'
import { join, relative } from 'node:path'
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
    ['/queue', '?batch_id=batch-2&endpoint=dropped', '/tracking?batch_id=batch-2'],
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

/** Every source file under `frontend/src`, as paths relative to `src`. */
function sourceFiles(dir = join(process.cwd(), 'src')): string[] {
  const found: string[] = []
  for (const entry of readdirSync(dir)) {
    const full = join(dir, entry)
    if (statSync(full).isDirectory()) {
      found.push(...sourceFiles(full))
    } else if (/\.(ts|vue)$/.test(entry)) {
      found.push(full)
    }
  }
  return found
}

describe('retired queue runtime entry (US-316)', () => {
  it('keeps legacy /app/queue as a redirect into the formal tracking route', async () => {
    const routes = router.getRoutes()
    const legacy = routes.find((route) => route.path === '/queue')
    expect(legacy?.redirect).toBeTypeOf('function')
    expect(legacy?.components).toBeUndefined()

    await router.replace('/queue?batch_id=batch-legacy&token=dropped')
    expect(router.currentRoute.value.name).toBe('tracking')
    expect(router.currentRoute.value.fullPath).toBe('/tracking?batch_id=batch-legacy')
  })

  it('mounts TrackingView on /app/tracking and no queue view anywhere', async () => {
    const record = router.getRoutes().find((route) => route.name === 'tracking')
    const component: unknown = record?.components?.default
    // A route that has already been resolved hands back the component itself;
    // an untouched lazy route hands back its loader.
    const resolved = typeof component === 'function'
      ? (await (component as () => Promise<{ default: unknown }>)()).default
      : component
    expect((resolved as { __name?: string } | null)?.__name).toBe('TrackingView')
    // No record keeps a second component to fall back to.
    expect(Object.keys(record?.components ?? {})).toEqual(['default'])
  })

  it('has no runtime import of the retired queue feature outside its own folder', () => {
    const srcRoot = join(process.cwd(), 'src')
    const queueDir = ['features', 'queue', ''].join('/')
    const specifier = /(?:from|import|require)\s*\(?\s*['"`]([^'"`]+)['"`]/g
    const offenders: string[] = []
    for (const file of sourceFiles()) {
      const path = relative(srcRoot, file)
      if (path.startsWith(queueDir)) continue
      const content = readFileSync(file, 'utf8')
      for (const match of content.matchAll(specifier)) {
        if (match[1]?.includes('/queue/')) offenders.push(`${path} -> ${match[1]}`)
      }
    }
    // The component may stay in the repo for rollback (Stage 38 §10.2), but
    // nothing may import it into the default runtime again.
    expect(offenders).toEqual([])
  })
})
