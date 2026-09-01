import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { nextTick } from 'vue'

import BatchCandidatePopover from '@/features/workbench/BatchCandidatePopover.vue'
import type { BatchCandidate } from '@/features/workbench/batchWorkbench'

// US-207: the batch candidate popover must be keyboard accessible — opening
// moves focus into the dialog (close button) and Escape closes it so the
// parent can restore focus to the trigger.

function candidate(overrides: Record<string, unknown> = {}): BatchCandidate {
  return {
    bangumi_id: '2353',
    title: '葬送的芙莉莲 第四季',
    mikan_url: 'https://mikan.example/Home/Bangumi/2353',
    poster_url: '/api/v1/mikan/posters/p-2353',
    source_query: '芙莉莲',
    aliases: [],
    recommendation: null,
    total_episodes: 28,
    season_evidence: null,
    candidate_context: null,
    ...overrides,
  } as BatchCandidate
}

function mountPopover() {
  return mount(BatchCandidatePopover, {
    props: {
      title: '芙莉莲S4',
      candidates: [candidate()],
      query: '芙莉莲S4',
      confirmedSeasons: {},
    },
    attachTo: document.body,
    global: {
      stubs: { teleport: true },
    },
  })
}

describe('BatchCandidatePopover (US-207 keyboard accessibility)', () => {
  beforeEach(() => {
    document.body.innerHTML = ''
  })

  it('moves focus to the close button on mount', async () => {
    const wrapper = mountPopover()
    await nextTick()
    await flushPromises()

    const close = wrapper.find('.batch-candidate-close')
    expect(close.exists()).toBe(true)
    expect(document.activeElement).toBe(close.element)
    wrapper.unmount()
  })

  it('emits close on Escape keydown', async () => {
    const wrapper = mountPopover()
    await nextTick()

    // The keydown listener is on the root element; Escape must close.
    wrapper.find('#batch-candidate-choices').trigger('keydown', { key: 'Escape' })
    await nextTick()

    expect(wrapper.emitted('close')).toBeTruthy()
    wrapper.unmount()
  })

  it('exposes focusClose to restore focus to the trigger', async () => {
    const wrapper = mountPopover()
    await nextTick()

    const focusSpy = vi.spyOn(HTMLButtonElement.prototype, 'focus')
    ;(wrapper.vm as unknown as { focusClose: () => void }).focusClose()
    expect(focusSpy).toHaveBeenCalled()
    focusSpy.mockRestore()
    wrapper.unmount()
  })
})
