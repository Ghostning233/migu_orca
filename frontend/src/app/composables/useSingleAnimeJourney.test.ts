import { describe, expect, it } from 'vitest'

import { toSafeJourneyError, useSingleAnimeJourney } from '@/app/composables/useSingleAnimeJourney'

describe('useSingleAnimeJourney (US-275)', () => {
  it('models the legal input → candidates → review → confirm → tracking flow', () => {
    const journey = useSingleAnimeJourney()
    journey.setTitle('  芙莉莲  ')
    expect(journey.state.title).toBe('芙莉莲')

    expect(journey.begin('searching')).toBe(true)
    expect(journey.state.busy).toBe('searching')
    journey.fail({ type: 'network_error', details: { raw_body: 'must not leak' } })
    journey.transition('candidates')
    journey.setCandidates(1)
    journey.selectCandidate()
    journey.setDraft('draft-capability', 3)
    expect(journey.state.phase).toBe('review')
    expect(journey.canConfirm()).toBe(true)

    const key = journey.newConfirmOperation()
    expect(key).toBeTruthy()
    expect(journey.begin('saving')).toBe(true)
    journey.finishConfirm({ requestId: 'request-1' })
    expect(journey.state.phase).toBe('confirmed_pending_tracking')
    expect(journey.state.idempotencyKey).toBeNull()
    journey.finishTracking('tracking-1')
    expect(journey.state.phase).toBe('complete')
  })

  it('keeps saved-confirm recovery separate from draft saving', () => {
    const journey = useSingleAnimeJourney()
    journey.setCandidates(1)
    journey.transition('candidates')
    journey.selectCandidate()
    journey.setDraft('draft', 1)
    journey.newConfirmOperation()
    journey.begin('saving')
    journey.fail({ type: 'save_confirm_failed', details: { details: { outcome: 'SAVED_CONFIRM_FAILED', request_id: 'req-1', retry_action: 'ACCEPT_SAVED_REQUEST', secret: 'no' } } })
    expect(journey.state.phase).toBe('review')
    expect(journey.state.error).toEqual({
      type: 'save_confirm_failed',
      message: '已保存订阅方案，但确认未完成，可直接重试确认。',
      requestId: 'req-1',
      retryAction: 'ACCEPT_SAVED_REQUEST',
    })
    journey.finishConfirm({ savedOnly: true, requestId: 'req-1' })
    expect(journey.state.phase).toBe('saved_pending_confirm')
    expect(journey.state.draftId).toBeNull()
    expect(journey.state.idempotencyKey).toBeNull()
    expect(journey.begin('accepting')).toBe(true)
  })

  it('only exposes stable types and allowlisted details', () => {
    expect(toSafeJourneyError({ type: 'unknown', message: 'secret', details: { token: 'secret', current_revision: 9 } })).toEqual({
      type: 'journey_error',
      message: '操作失败，请重新尝试。',
    })
  })
})
