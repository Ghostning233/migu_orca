import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'

import TrackingPoster from './TrackingPoster.vue'

const cover = `/api/v1/mikan/posters/${'a'.repeat(64)}`

describe('TrackingPoster', () => {
  it('renders the server-projected same-origin cover without an upstream address', () => {
    const wrapper = mount(TrackingPoster, { props: { posterPath: cover, variant: 'detail' } })

    const image = wrapper.find('img')
    expect(image.attributes('src')).toBe(cover)
    expect(image.attributes('alt')).toBe('')
    expect(wrapper.attributes('data-poster-state')).toBe('ready')
    expect(wrapper.classes()).toContain('tracking-poster--detail')
    expect(wrapper.html()).not.toContain('mikan.example')
  })

  it('shows a stable placeholder when the cover is missing or unavailable', async () => {
    const missing = mount(TrackingPoster, { props: { posterPath: null } })
    expect(missing.find('img').exists()).toBe(false)
    expect(missing.attributes('data-poster-state')).toBe('placeholder')
    expect(missing.find('.tracking-poster-placeholder').exists()).toBe(true)

    const wrapper = mount(TrackingPoster, { props: { posterPath: cover } })
    await wrapper.find('img').trigger('error')
    expect(wrapper.find('img').exists()).toBe(false)
    expect(wrapper.attributes('data-poster-state')).toBe('placeholder')
  })

  it('retries once a different cover reference arrives', async () => {
    const wrapper = mount(TrackingPoster, { props: { posterPath: cover } })
    await wrapper.find('img').trigger('error')

    await wrapper.setProps({ posterPath: `/api/v1/mikan/posters/${'b'.repeat(64)}` })

    expect(wrapper.find('img').exists()).toBe(true)
    expect(wrapper.attributes('data-poster-state')).toBe('ready')
  })

  it('never requests an upstream or unsafe cover reference', () => {
    for (const unsafe of [
      'https://mikan.example/cover.jpg',
      '//mikan.example/cover.jpg',
      '/api/v1/mikan/posters/../escape',
      '/etc/passwd',
      '/api/v1/mikan/posters/a b',
      '',
    ]) {
      const wrapper = mount(TrackingPoster, { props: { posterPath: unsafe } })
      expect(wrapper.find('img').exists()).toBe(false)
      expect(wrapper.attributes('data-poster-state')).toBe('placeholder')
      expect(wrapper.html()).not.toContain('mikan.example')
    }
  })
})
