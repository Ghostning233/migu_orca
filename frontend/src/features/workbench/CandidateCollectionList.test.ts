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
})
