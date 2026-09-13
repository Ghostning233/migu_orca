import { describe, expectTypeOf, it } from 'vitest'

import type { components, operations } from '@/api/generated/api'

// US-255: the handoff is a type-only boundary. These aliases derive directly
// from generated OpenAPI operations and deliberately do not define DTOs.
type JsonBody<Operation extends keyof operations> = NonNullable<
  operations[Operation]['requestBody']
>['content']['application/json']

type JsonResult<Operation extends keyof operations> = operations[Operation]['responses'][200] extends {
  content: { 'application/json': { result: infer Result } }
}
  ? Result
  : never

type TrackingResult = JsonResult<'getTrackingItemDetail'>
type TrackingAction = NonNullable<TrackingResult['available_actions']>[number]

describe('versioned frontend contract handoff (US-255)', () => {
  it('covers F-B through F-E using generated request and result types', () => {
    expectTypeOf<JsonBody<'createRequest'>>().toHaveProperty('title')
    expectTypeOf<JsonBody<'previewModifyRequest'>>().toHaveProperty('draft_id')
    expectTypeOf<JsonBody<'confirmRequestSave'>>().toMatchTypeOf<{
      draft_id: string
      base_revision: number
      idempotency_key: string
    }>()
    expectTypeOf<JsonBody<'saveConfirmBatchItems'>>().toHaveProperty('items')
    expectTypeOf<JsonResult<'getRequestSafeInfo'>>().toHaveProperty('safe_info')
    expectTypeOf<JsonResult<'listTrackingItems'>>().toHaveProperty('items')
    expectTypeOf<JsonBody<'revalidateTrackingItem'>>().toMatchTypeOf<{
      expected_revision: number
    }>()
  })

  it('covers F-F management, recovery, capability, nullable and error types', () => {
    type ManagementBody = JsonBody<'modifyTrackingItem'>
    expectTypeOf<ManagementBody>().toMatchTypeOf<{
      target_scope: 'SUBSCRIPTION' | 'ASSOCIATED_RSS'
      expected_revision: number
      idempotency_key: string
      confirm: true
    }>()
    expectTypeOf<JsonBody<'setTrackingItemEnabled'>>().toHaveProperty('target_scope')
    expectTypeOf<JsonBody<'refreshTrackingRss'>>().toMatchTypeOf<{
      target_scope: 'ASSOCIATED_RSS'
    }>()
    expectTypeOf<JsonBody<'deleteExternalTrackingItem'>>().toHaveProperty('confirm')
    expectTypeOf<JsonBody<'submitTrackingItem'>>().toHaveProperty('idempotency_key')
    expectTypeOf<JsonBody<'retryTrackingItem'>>().toHaveProperty('expected_revision')
    expectTypeOf<JsonBody<'recoverTrackingItem'>>().toHaveProperty('action')
    expectTypeOf<JsonBody<'syncTrackingItems'>>().toMatchTypeOf<{ confirm: true }>()
    expectTypeOf<JsonResult<'probeAutoBangumiCapabilities'>['probe_status']>().toEqualTypeOf<
      'VERIFIED' | 'PARTIAL' | 'FAILED'
    >()
    expectTypeOf<JsonResult<'probeAutoBangumiCapabilities'>['subscription_submit']>().toEqualTypeOf<
      'SUPPORTED' | 'UNSUPPORTED' | 'UNKNOWN'
    >()
    // The generated union must reject a write with no allowed patch field.
    const emptyModify: JsonBody<'modifyTrackingItem'> = {
      target_scope: 'SUBSCRIPTION', expected_revision: 1,
      idempotency_key: 'intent-test', confirm: true,
      ab_config: { auth_mode: 'password', fallback_enabled: false },
      // @ts-expect-error an empty patch is not a valid modify request
      patch: {},
    }
    void emptyModify
    const emptyFilterModify: JsonBody<'modifyTrackingItem'> = {
      target_scope: 'SUBSCRIPTION', expected_revision: 1,
      idempotency_key: 'intent-test', confirm: true,
      ab_config: { auth_mode: 'password', fallback_enabled: false },
      // @ts-expect-error a non-null filter_rule also needs at least one field
      patch: { filter_rule: {} },
    }
    void emptyFilterModify
    const emptyRssModify: JsonBody<'modifyTrackingItem'> = {
      target_scope: 'ASSOCIATED_RSS', expected_revision: 1,
      idempotency_key: 'intent-test', confirm: true,
      ab_config: { auth_mode: 'password', fallback_enabled: false },
      // @ts-expect-error an empty RSS patch is not a valid modify request
      patch: {},
    }
    void emptyRssModify
    expectTypeOf<TrackingAction['requires_confirmation']>().toEqualTypeOf<boolean>()
    expectTypeOf<TrackingResult['updated_episode']>().toEqualTypeOf<null>()
    expectTypeOf<components['schemas']['ApiErrorEnvelope']>().toMatchTypeOf<{
      error_type: string
      error_message: string
      error_data: Record<string, unknown> | null
    }>()
  })
})
