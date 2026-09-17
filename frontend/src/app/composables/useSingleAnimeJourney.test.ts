import { describe, expect, it } from 'vitest'
import { computed, nextTick } from 'vue'

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

  it('exposes the snapshot as reactive state so host computeds recompute (US-341)', async () => {
    // FE-01: the save button derives its disabled state from this composable.
    // A non-reactive snapshot made host computeds cache their first value.
    const journey = useSingleAnimeJourney()
    const phase = computed(() => journey.state.phase)
    const confirmable = computed(() => journey.canConfirm())

    expect(phase.value).toBe('input')
    expect(confirmable.value).toBe(false)

    journey.setCandidates(1)
    journey.transition('candidates')
    journey.selectCandidate()
    journey.setDraft('draft-capability', 2)
    await nextTick()

    expect(phase.value).toBe('review')
    expect(confirmable.value).toBe(true)

    journey.setDirty(true)
    await nextTick()
    expect(confirmable.value).toBe(false)

    journey.setDraft('draft-capability', 3)
    await nextTick()
    expect(journey.state.draftRevision).toBe(3)
    expect(confirmable.value).toBe(true)
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
    expect(journey.state.phase).toBe('saved_pending_confirm')
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

  it('reuses a save key after a retryable failure', () => {
    const journey = useSingleAnimeJourney()
    journey.setCandidates(1)
    journey.transition('candidates')
    journey.selectCandidate()
    journey.setDraft('draft', 1)
    const firstKey = journey.newConfirmOperation()
    journey.begin('saving')
    journey.fail({ type: 'network_error' })
    expect(journey.newConfirmOperation()).toBe(firstKey)
  })

  it('requires the complete saved-confirm recovery details', () => {
    const journey = useSingleAnimeJourney()
    journey.setCandidates(1)
    journey.transition('candidates')
    journey.selectCandidate()
    journey.setDraft('draft', 1)
    journey.newConfirmOperation()
    journey.begin('saving')
    journey.fail({ type: 'save_confirm_failed', details: { details: { request_id: 'req-1', retry_action: 'ACCEPT_SAVED_REQUEST' } } })
    expect(journey.state.phase).toBe('review')
    expect(journey.state.error?.type).toBe('journey_error')
    expect(journey.state.idempotencyKey).not.toBeNull()
  })

  it('keeps failed tracking verification separate from accept recovery', () => {
    const journey = useSingleAnimeJourney()
    journey.setCandidates(1)
    journey.transition('candidates')
    journey.selectCandidate()
    journey.setDraft('draft', 1)
    journey.newConfirmOperation()
    journey.begin('saving')
    journey.fail({ type: 'save_confirm_failed', details: { details: { outcome: 'SAVED_CONFIRM_FAILED', request_id: 'req-1', retry_action: 'ACCEPT_SAVED_REQUEST' } } })

    expect(journey.begin('accepting')).toBe(true)
    journey.finishVerificationPending()
    expect(journey.state.phase).toBe('verification_pending')
    expect(journey.begin('accepting')).toBe(false)

    journey.returnToSavedPending()
    expect(journey.state.phase).toBe('saved_pending_confirm')
    expect(journey.begin('accepting')).toBe(true)
  })
})
