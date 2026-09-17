import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'

import CandidateCollectionList from '@/features/workbench/CandidateCollectionList.vue'
import type { MikanCandidate } from '@/features/workbench/candidateSearch'

function candidate(overrides: Record<string, unknown> = {}): MikanCandidate {
  return {
    bangumi_id: '2353',
    title: '葬送的芙莉莲 第四季',
    mikan_url: 'https://mikan.example/Home/Bangumi/2353',
    poster_url: null,
    source_query: '芙莉莲',
    aliases: [],
    recommendation: null,
    total_episodes: 28,
    season_evidence: null,
    candidate_context: 'opaque-context',
    ...overrides,
  } as MikanCandidate
}

describe('CandidateCollectionList', () => {
  it('renders zero candidates without inventing a selection', () => {
    const wrapper = mount(CandidateCollectionList, { props: { candidates: [], query: 'ghost' } })

    expect(wrapper.findAll('.candidate-card')).toHaveLength(0)
    expect(wrapper.emitted('select')).toBeUndefined()
  })

  it('keeps one candidate explicit and emits the selected candidate', async () => {
    const item = candidate()
    const wrapper = mount(CandidateCollectionList, { props: { candidates: [item], query: '芙莉莲' } })

    expect(wrapper.findAll('.candidate-card')).toHaveLength(1)
    await wrapper.find('.candidate-select').trigger('click')

    expect(wrapper.emitted('select')?.[0]).toEqual([item])
    expect(wrapper.text()).not.toContain('opaque-context')
  })

  it('shares season confirmation and conflict blocking rules', async () => {
    const confirmation = candidate({
      season_evidence: { status: 'NEEDS_CONFIRMATION', season: 4, requires_review: true },
    })
    const conflict = candidate({
      bangumi_id: '3072',
      season_evidence: { status: 'CONFLICT', season: null, requires_review: true },
    })
    const wrapper = mount(CandidateCollectionList, {
      props: { candidates: [confirmation, conflict], query: '芙莉莲', confirmedSeasons: {} },
    })

    const cards = wrapper.findAll('.candidate-card')
    expect((cards[0]!.find('.candidate-select').element as HTMLButtonElement).disabled).toBe(true)
    expect((cards[1]!.find('.candidate-select').element as HTMLButtonElement).disabled).toBe(true)

    await cards[0]!.find('input[type="checkbox"]').setValue(true)
    expect(wrapper.emitted('update:confirmedSeason')?.[0]).toEqual(['2353', 4])
  })

  // WP-41-B / US-343: the loading state is per candidate. Only the clicked
  // candidate is marked as generating; the others are merely disabled.
  it('marks only the loading candidate as generating', () => {
    const clicked = candidate()
    const other = candidate({ bangumi_id: '3072', title: '葬送的芙莉莲 第二季' })
    const wrapper = mount(CandidateCollectionList, {
      props: { candidates: [clicked, other], query: '芙莉莲', loadingCandidateId: '2353' },
    })

    const cards = wrapper.findAll('.candidate-card')
    const loadingButton = cards[0]!.find('.candidate-select')
    expect(loadingButton.attributes('aria-busy')).toBe('true')
    expect(loadingButton.text()).toContain('正在生成草案')
    expect((loadingButton.element as HTMLButtonElement).disabled).toBe(true)
    expect(cards[0]!.classes()).toContain('is-generating')

    const idleButton = cards[1]!.find('.candidate-select')
    // Disabled so a second generation cannot race, but never labelled as loading.
    expect((idleButton.element as HTMLButtonElement).disabled).toBe(true)
    expect(idleButton.attributes('aria-busy')).toBeUndefined()
    expect(idleButton.text()).toContain('选择此合集')
    expect(cards[1]!.text()).not.toContain('正在生成草案')
  })

  it('keeps a generation error beside its own candidate with a retry action', () => {
    const failed = candidate()
    const other = candidate({ bangumi_id: '3072', title: '葬送的芙莉莲 第二季' })
    const wrapper = mount(CandidateCollectionList, {
      props: {
        candidates: [failed, other],
        query: '芙莉莲',
        candidateErrors: { '2353': '从 MiKan 合集生成订阅草案失败，请稍后重试。' },
      },
    })

    const cards = wrapper.findAll('.candidate-card')
    expect(cards[0]!.text()).toContain('从 MiKan 合集生成订阅草案失败，请稍后重试。')
    expect(cards[0]!.find('[role="alert"]').exists()).toBe(true)
    expect(cards[0]!.find('.candidate-select').text()).toContain('重试生成草案')
    // The clicked candidate is selectable again; no candidate is left loading.
    expect((cards[0]!.find('.candidate-select').element as HTMLButtonElement).disabled).toBe(false)

    expect(cards[1]!.text()).not.toContain('失败')
    expect(cards[1]!.find('.candidate-select').text()).toContain('选择此合集')
  })

  it('keeps every candidate idle when no candidate is generating', () => {
    const wrapper = mount(CandidateCollectionList, {
      props: { candidates: [candidate()], query: '芙莉莲' },
    })

    const button = wrapper.find('.candidate-select')
    expect(button.attributes('aria-busy')).toBeUndefined()
    expect((button.element as HTMLButtonElement).disabled).toBe(false)
  })
})
