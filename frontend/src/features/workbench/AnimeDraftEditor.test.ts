import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import { nextTick } from 'vue'

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
      { subtitle_group: '字幕组 B', valid_seed_names: [], excluded_seed_names: [] },
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

const snapshotConfig = request.confirmable_config as unknown as Record<string, unknown>

/** Build a new server snapshot with a patched confirmable_config. */
function snapshotWith(config: Record<string, unknown>): RequestSnapshot {
  return {
    ...request,
    confirmable_config: { ...snapshotConfig, ...config },
  } as unknown as RequestSnapshot
}

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

  it('keeps an unapplied edit while syncing the rest of a new authoritative snapshot', async () => {
    const wrapper = mount(AnimeDraftEditor, { props: { request } })
    await wrapper.find('#anime-draft-must-contain').setValue('1080p')
    expect(wrapper.find('#anime-draft-must-contain').element).toHaveProperty('value', '1080p')

    // US-344: a snapshot that does not carry the edit must not erase what the
    // user typed while the server request was still in flight.
    await wrapper.setProps({ request: snapshotWith({}) })
    expect(wrapper.find('#anime-draft-must-contain').element).toHaveProperty('value', '1080p')
    expect(wrapper.emitted('dirty-change')?.at(-1)).toEqual([true])

    // Fields the server does carry stay authoritative.
    await wrapper.setProps({ request: snapshotWith({ expected_folder_name: '服务端目录' }) })
    expect(wrapper.find('#anime-draft-folder-name').element).toHaveProperty('value', '服务端目录')
    expect(wrapper.find('#anime-draft-must-contain').element).toHaveProperty('value', '1080p')

    // Once the server echoes the edit, the form is back in sync.
    await wrapper.setProps({
      request: snapshotWith({ filter_rule: { must_contain: '1080p', must_not_contain: '', use_regex: false, case_sensitive: false } }),
    })
    expect(wrapper.find('#anime-draft-must-contain').element).toHaveProperty('value', '1080p')
    expect(wrapper.emitted('dirty-change')?.at(-1)).toEqual([false])
  })

  it('announces user edits by kind but never announces programmatic writes', async () => {
    const wrapper = mount(AnimeDraftEditor, { props: { request } })

    await wrapper.find('#anime-draft-subtitle-group').setValue('字幕组 B')
    await wrapper.find('#anime-draft-must-not-contain').setValue('v2')
    await wrapper.find('#anime-draft-folder-name').setValue('自定义目录')

    expect(wrapper.emitted('subtitle-group-change')?.at(-1)).toEqual(['字幕组 B'])
    expect(wrapper.emitted('folder-change')?.at(-1)).toEqual(['自定义目录'])
    expect(wrapper.emitted('filter-change')).toHaveLength(1)
    expect(wrapper.emitted('filter-change')?.[0]?.[0]).toMatchObject({ mustNotContain: 'v2' })

    // The snapshot sync and the explicit reset are not user intent.
    await wrapper.setProps({ request: snapshotWith({}) })
    wrapper.vm.reset()
    await nextTick()
    expect(wrapper.emitted('subtitle-group-change')).toHaveLength(1)
    expect(wrapper.emitted('filter-change')).toHaveLength(1)
    expect(wrapper.emitted('folder-change')).toHaveLength(1)
  })

  it('exposes a reset that restores the last authoritative snapshot', async () => {
    const wrapper = mount(AnimeDraftEditor, { props: { request } })
    await wrapper.find('#anime-draft-must-not-contain').setValue('v2')

    wrapper.vm.reset()
    await nextTick()

    expect(wrapper.find('#anime-draft-must-not-contain').element).toHaveProperty('value', '')
    expect(wrapper.emitted('dirty-change')?.at(-1)).toEqual([false])
  })

  it('answers the review default layer and keeps technical details collapsed', () => {
    const wrapper = mount(AnimeDraftEditor, {
      props: {
        request,
        candidateSummary: { title: '葬送的芙莉莲 第二季', season: 2, totalEpisodes: 28, posterUrl: null },
      },
    })

    // F4/US-345: 默认层回答「已选哪部/哪一季、筛后有什么」。
    const summary = wrapper.find('.draft-review-summary')
    expect(summary.text()).toContain('已选合集')
    expect(summary.text()).toContain('葬送的芙莉莲 第二季')
    expect(summary.text()).toContain('第 2 季')
    expect(summary.text()).toContain('28 集')
    expect(summary.text()).toContain('字幕组 A')
    expect(summary.text()).toContain('筛选规则')
    expect(summary.text()).not.toContain('Overview')
    // 资源摘要留在默认层；技术层默认折叠但仍可读。
    expect(wrapper.find('.resource-summary').exists()).toBe(true)
    const technical = wrapper.find('details.advanced-detail')
    expect(technical.exists()).toBe(true)
    expect((technical.element as HTMLDetailsElement).open).toBe(false)
    expect(technical.find('summary').text()).toContain('全部信息')
    expect(technical.text()).toContain('request_id')
    expect(wrapper.text()).not.toContain('private.example')
  })

  it('says 未提供 instead of inventing a season for an unsaved draft', () => {
    const wrapper = mount(AnimeDraftEditor, { props: { request } })

    const summary = wrapper.find('.draft-review-summary')
    expect(summary.text()).toContain('已选合集')
    expect(summary.text()).toContain('未提供')
    expect(summary.text()).toContain('未知')
  })

  it('does not infer the selected collection from request titles when the projection is absent', () => {
    const wrapper = mount(AnimeDraftEditor, { props: { request, candidateSummary: null } })
    const selectedRow = wrapper.findAll('.draft-review-summary .detail-row').find(
      (row) => row.find('dt').text() === '已选合集',
    )

    expect(selectedRow).toBeDefined()
    const selectedValue = selectedRow?.find('dd').text() ?? ''
    expect(selectedValue).toContain('未提供')
    expect(selectedValue).not.toContain('葬送的芙莉莲')
  })

  it('shows an explicit missing-poster value for a public candidate without a poster', () => {
    const wrapper = mount(AnimeDraftEditor, {
      props: {
        request,
        candidateSummary: {
          title: '公开候选合集',
          season: null,
          totalEpisodes: null,
          posterUrl: null,
        } as never,
      },
    })

    const summary = wrapper.find('.draft-review-summary')
    expect(summary.text()).toContain('封面')
    expect(summary.text()).toContain('未提供')
  })

  it('renders its own submit as secondary when the host owns the primary action', () => {
    const draft = mount(AnimeDraftEditor, { props: { request, applyVariant: 'secondary' } })
    expect(draft.find('#anime-draft-apply-button').classes()).toContain('secondary-button')

    // 已保存方案页面的「保存方案修改」仍是该页面唯一动作，保持主按钮。
    const saved = mount(AnimeDraftEditor, { props: { request, mode: 'saved' } })
    expect(saved.find('#anime-draft-apply-button').classes()).toContain('primary-button')
  })

  it('supports saved mode with the same controlled fields and no draft transport', async () => {
    const wrapper = mount(AnimeDraftEditor, {
      props: { request, mode: 'saved', idPrefix: 'saved-plan' },
    })

    expect(wrapper.find('[data-mode="saved"]').exists()).toBe(true)
    expect(wrapper.text()).toContain('编辑已保存方案')
    expect(wrapper.text()).toContain('保存方案修改')
    await wrapper.find('#saved-plan-folder-name').setValue('新目录')
    await wrapper.find('form').trigger('submit')

    expect(wrapper.emitted('apply')).toEqual([[{ expected_folder_name: '新目录' }]])
    expect(wrapper.emitted('apply')?.[0]?.[0]).not.toHaveProperty('draft_id')
    expect(wrapper.emitted('apply')?.[0]?.[0]).not.toHaveProperty('base_revision')
  })
})
