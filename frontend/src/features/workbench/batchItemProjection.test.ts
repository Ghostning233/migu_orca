import { describe, expect, it } from 'vitest'

import type { BatchSaveResultItem } from '@/app/composables/useBatchReviewJourney'
import type { BatchItem } from '@/features/workbench/batchWorkbench'
import {
  projectAcceptSucceeded,
  projectDeterministicSaveFailure,
  projectDraftGenerated,
  projectResponseUnknown,
  projectSaveConfirmOutcome,
  projectSavedConfirmPending,
  projectTrackingLocated,
  projectTrackingNotFound,
} from '@/features/workbench/batchItemProjection'

function row(overrides: Record<string, unknown> = {}): BatchItem {
  return {
    item_id: 'item-1',
    raw_title: '萌王S4',
    status: 'DRAFT',
    candidates: [],
    preview_request: { request_id: 'req-1' },
    draft_id: 'draft-1',
    draft_revision: 1,
    request_id: null,
    tracking_id: null,
    ...overrides,
  } as unknown as BatchItem
}

function resultItem(overrides: Record<string, unknown> = {}): BatchSaveResultItem {
  return {
    item_id: 'item-1',
    outcome: 'CONFIRMED',
    request_id: 'req-1',
    status: 'CONFIRMED',
    error_type: null,
    error_message: null,
    tracking_id: null,
    tracking_ready: false,
    ...overrides,
  } as unknown as BatchSaveResultItem
}

describe('batchItemProjection', () => {
  it('projects a confirmed result and asks for the local draft resources to die', () => {
    const projection = projectSaveConfirmOutcome(row(), resultItem())
    expect(projection.kind).toBe('succeeded')
    expect(projection.invalidatesResources).toBe(true)
    expect(projection.clearsSelection).toBe(true)
    expect(projection.row).toMatchObject({
      status: 'CONFIRMED', draft_id: null, draft_revision: null, request_id: 'req-1',
    })
  })

  it('freezes a replayed draft as already saved and stops offering a new key', () => {
    const projection = projectSaveConfirmOutcome(row({ candidates: [{}] }), resultItem({
      outcome: 'FAILED', error_type: 'draft_replayed', request_id: null, status: null,
    }))
    expect(projection.kind).toBe('locate_pending')
    expect(projection.invalidatesResources).toBe(true)
    expect(projection.clearsSelection).toBe(true)
    expect(projection.row).toMatchObject({
      status: 'SAVED_PENDING_LOCATE', preview_request: null, draft_id: null, draft_revision: null, request_id: null,
    })
  })

  it('keeps the busy identity for a saved-but-unconfirmed result without dropping the intent', () => {
    const projection = projectSaveConfirmOutcome(row(), resultItem({
      outcome: 'FAILED', error_type: 'save_confirm_failed', status: null,
    }))
    expect(projection.kind).toBe('confirm_pending')
    expect(projection.invalidatesResources).toBe(true)
    expect(projection.clearsSelection).toBe(false)
    expect(projection.row).toMatchObject({
      status: 'SAVED_PENDING_CONFIRM', draft_id: null, draft_revision: null, request_id: 'req-1',
    })
  })

  it('routes an expired draft back to the real collection picker', () => {
    const projection = projectSaveConfirmOutcome(row({ candidates: [{ bangumi_id: '42' }] }), resultItem({
      outcome: 'FAILED', error_type: 'draft_expired', request_id: null, status: null,
    }))
    expect(projection.kind).toBe('draft_invalidated')
    expect(projection.clearsSelection).toBe(true)
    expect(projection.row).toMatchObject({
      status: 'FOUND', preview_request: null, draft_id: null, draft_revision: null,
    })

    const empty = projectSaveConfirmOutcome(row(), resultItem({
      outcome: 'FAILED', error_type: 'draft_expired', request_id: null, status: null,
    }))
    expect(empty.row.status).toBe('EMPTY')
  })

  it('keeps a retryable deterministic failure on the draft step', () => {
    const projection = projectSaveConfirmOutcome(row(), resultItem({
      outcome: 'FAILED', error_type: 'idempotency_conflict', request_id: null, status: null,
    }))
    expect(projection.kind).toBe('draft_retryable')
    expect(projection.invalidatesResources).toBe(false)
    expect(projection.clearsSelection).toBe(false)
    expect(projection.row.status).toBe('DRAFT')
  })

  it('never mutates the row it projects', () => {
    const original = row()
    const snapshot = JSON.parse(JSON.stringify(original))
    projectSaveConfirmOutcome(original, resultItem())
    projectDeterministicSaveFailure(original, 'draft_expired')
    expect(JSON.parse(JSON.stringify(original))).toEqual(snapshot)
  })

  it('projects the whole-batch deterministic failure by safe error type', () => {
    expect(projectDeterministicSaveFailure(row(), 'draft_replayed').status).toBe('SAVED_PENDING_LOCATE')
    expect(projectDeterministicSaveFailure(row({ candidates: [{}] }), 'draft_evicted').status).toBe('FOUND')
    expect(projectDeterministicSaveFailure(row(), 'draft_evicted').status).toBe('EMPTY')
    expect(projectDeterministicSaveFailure(row({ preview_request: null }), 'unexpected_error')).toMatchObject({
      status: 'DRAFT', preview_request: null,
    })
  })

  it('projects the recovery and draft lifecycle rows', () => {
    expect(projectResponseUnknown(row()).status).toBe('RESPONSE_UNKNOWN')
    expect(projectDraftGenerated(row({ status: 'FOUND' }), {
      preview_request: null, draft_id: 'draft-2', draft_revision: 3,
    })).toMatchObject({ status: 'DRAFT', draft_id: 'draft-2', draft_revision: 3 })
    expect(projectTrackingLocated(row(), 'track-1')).toMatchObject({ status: 'CONFIRMED', tracking_id: 'track-1' })
    expect(projectAcceptSucceeded(row({ tracking_id: 'stale' }), 'req-9')).toMatchObject({
      status: 'CONFIRMED', request_id: 'req-9', tracking_id: null,
    })
    expect(projectSavedConfirmPending(row(), 'req-9')).toMatchObject({
      status: 'SAVED_PENDING_CONFIRM', draft_id: null, draft_revision: null, request_id: 'req-9',
    })
    expect(projectTrackingNotFound(row({ status: 'RESPONSE_UNKNOWN' })).status).toBe('SAVED_PENDING_CONFIRM')
  })
})
