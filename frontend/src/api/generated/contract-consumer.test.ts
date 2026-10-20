import { describe, expectTypeOf, it } from 'vitest'

import type { components, operations } from '@/api/generated/api'

// US-249: this is deliberately a type-only consumer fixture. Future frontend
// slices must be able to describe their boundary values from generated types
// alone; no feature-local DTO/interface is allowed to become a second schema.
type JsonBody<Operation extends keyof operations> = NonNullable<
  operations[Operation]['requestBody']
>['content']['application/json']

type JsonResult<Operation extends keyof operations> = operations[Operation]['responses'][200] extends {
  content: { 'application/json': { result: infer Result } }
}
  ? Result
  : never

type ErrorBody = components['schemas']['ApiErrorEnvelope']

describe('generated contract consumer fixture (US-249)', () => {
  it('expresses shared review and save flows from generated request/response types', () => {
    type CreateBody = JsonBody<'createRequest'>
    expectTypeOf<CreateBody>().toMatchTypeOf<{
      title: string
      source?: 'static-fixture' | 'mikan'
    }>()

    type SaveConfirmBody = JsonBody<'confirmRequestSave'>
    expectTypeOf<SaveConfirmBody>().toMatchTypeOf<{
      draft_id: string
      base_revision: number
      idempotency_key: string
    }>()

    type SaveConfirmResult = JsonResult<'confirmRequestSave'>
    expectTypeOf<SaveConfirmResult>().toMatchTypeOf<{
      outcome: string
      handoff: {
        request_id: string
        tracking_id: string | null
        tracking_ready: boolean
      }
    }>()

    type BatchResult = JsonResult<'saveConfirmBatchItems'>
    expectTypeOf<BatchResult>().toMatchTypeOf<{
      batch_id: string
      results: Array<{ item_id: string; outcome: string }>
    }>()
  })

  it('expresses tracking, capability, nullable and error branches without any', () => {
    type TrackingQuery = NonNullable<
      operations['listTrackingItems']['parameters']['query']
    >
    expectTypeOf<TrackingQuery['status_group']>().toEqualTypeOf<
      'PENDING' | 'PROCESSING' | 'ACTIVE' | 'ATTENTION' | 'INACTIVE' | undefined
    >()

    type TrackingResult = JsonResult<'getTrackingItemDetail'>
    expectTypeOf<TrackingResult['safe_info']>().toMatchTypeOf<object | null>()
    expectTypeOf<TrackingResult['updated_episode']>().toEqualTypeOf<null>()
    // Issue #228 retired the five legacy action codes from the published enum.
    expectTypeOf<
      NonNullable<TrackingResult['available_actions']>[number]['code']
    >().toEqualTypeOf<
      | 'SUBMIT'
      | 'RETRY'
      | 'MODIFY'
      | 'SET_ENABLED'
      | 'REFRESH_RSS'
    >()

    type CapabilityResult = JsonResult<'probeSavedAutoBangumiCapabilities'>
    expectTypeOf<CapabilityResult['probe_status']>().toEqualTypeOf<
      'VERIFIED' | 'PARTIAL' | 'FAILED'
    >()
    expectTypeOf<CapabilityResult['version']>().toEqualTypeOf<string | null>()

    expectTypeOf<ErrorBody>().toMatchTypeOf<{
      ok: boolean
      error_type: string
      error_message: string
      error_data: Record<string, unknown> | null
    }>()
  })
})
