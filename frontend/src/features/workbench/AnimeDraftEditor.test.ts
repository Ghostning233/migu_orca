import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'

import AnimeDraftEditor from '@/features/workbench/AnimeDraftEditor.vue'
import type { RequestSnapshot } from '@/features/requests/requestDetail'

const request = {
  request_id: 'draft-public-id',
  status: 'PENDING_CONFIRM',
  input: { raw_title: '葬送的芙莉莲' },
  source_info: {
    matched_bangumi: { title: '葬送的芙莉莲' },
    rss_sources: [
      { subtitle_group: '字幕组 A', valid_seed_names: ['episode-01.mkv'], excluded_seed_names: [] },
    ],
  },
  confirmable_config: {
    selected_subtitle_group: '字幕组 A',
    selected_rss_url: 'https://private.example/rss',
    filter_rule: { must_contain: '', must_not_contain: '', use_regex: false, case_sensitive: false },
    expected_folder_name: '葬送的芙莉莲',
    effective_seed_names: ['episode-01.mkv'],
  },
} as unknown as RequestSnapshot

describe('AnimeDraftEditor', () => {
  it('renders the shared review structure and keeps URLs out of the DOM', () => {
    const wrapper = mount(AnimeDraftEditor, { props: { request } })

    expect(wrapper.find('#anime-draft-editor').exists()).toBe(true)
    expect(wrapper.findComponent({ name: 'ResourceSummary' }).exists()).toBe(true)
    expect(wrapper.text()).toContain('葬送的芙莉莲')
    expect(wrapper.text()).not.toContain('private.example')
    expect(wrapper.text()).not.toContain('https://')
    expect(wrapper.text()).not.toContain('SafeInfo')
  })

  it('emits a minimal patch and dirty state without making a request', async () => {
    const wrapper = mount(AnimeDraftEditor, { props: { request } })
    await wrapper.find('#anime-draft-must-not-contain').setValue('v2')
    expect(wrapper.emitted('dirty-change')?.at(-1)).toEqual([true])
    await wrapper.find('form').trigger('submit')

    expect(wrapper.emitted('apply')).toEqual([[{ filter_rule: { must_not_contain: 'v2', use_regex: false, case_sensitive: false } }]])
  })

  it('resets transient edits when the authoritative snapshot changes', async () => {
    const wrapper = mount(AnimeDraftEditor, { props: { request } })
    await wrapper.find('#anime-draft-must-contain').setValue('1080p')
    expect(wrapper.find('#anime-draft-must-contain').element).toHaveProperty('value', '1080p')

    await wrapper.setProps({ request: { ...request, request_id: 'new-draft' } })
    expect(wrapper.find('#anime-draft-must-contain').element).toHaveProperty('value', '')
    expect(wrapper.emitted('dirty-change')?.at(-1)).toEqual([false])
  })
})
