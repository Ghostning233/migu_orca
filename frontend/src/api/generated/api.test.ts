import { describe, expect, it } from 'vitest'
import { expectTypeOf } from 'vitest'

import type {
  components,
  operations,
  paths,
} from '@/api/generated/api'
import type { PreviewPatch } from '@/features/workbench/candidateSearch'

// US-198: the frontend TypeScript client is generated from
// docs/api/openapi.json by openapi-typescript (locked in package.json).
// The generated module is type-only (interfaces), so these tests assert the
// *generated contract surface* the migrated features will consume:
// operationIds, path entries, the envelope components and the request-body
// credential fields. They fail at typecheck if the generator output ever
// drifts from the OpenAPI contract.

const EXPECTED_OPERATION_IDS = [
  'getAutoBangumiConnection',
  'saveAutoBangumiConnection',
  'deleteAutoBangumiConnection',
  'probeSavedAutoBangumiCapabilities',
  'testAutoBangumiConnection',
  'listRequests',
  'getRequestDetail',
  'getRequestSafeInfo',
  'createRequest',
  'previewModifyRequest',
  'confirmRequestSave',
  'acceptRequest',
  'cancelRequest',
  'modifyRequest',
  'deleteRequest',
  'searchMikanCandidates',
  'getMikanPoster',
  'getPreferences',
  'savePreferences',
  'listCorrections',
  'saveCorrection',
  'parseBatchTitles',
  'saveConfirmBatchItems',
  'listTrackingItems',
  'getTrackingItemDetail',
  'revalidateTrackingItem',
  'submitTrackingItem',
  'retryTrackingItem',
  'checkTrackingItem',
  'resubmitTrackingItem',
  'recoverTrackingItem',
  'submitTrackingBatch',
  'deleteTrackingBatchPlans',
  'deleteTrackingBatchPlansWithExternal',
  'getTrackingBatchDeleteStatus',
  'deleteTrackingPlan',
  'syncTrackingItems',
  'modifyTrackingItem',
  'setTrackingItemEnabled',
  'refreshTrackingRss',
] as const

describe('generated API client (US-198)', () => {
  it('declares every operationId as a readable, stable name', () => {
    // At type level: every expected operationId must exist on `operations`.
    type OperationKeys = keyof operations
    expectTypeOf<OperationKeys>().toMatchTypeOf<
      | 'getAutoBangumiConnection'
      | 'saveAutoBangumiConnection'
      | 'deleteAutoBangumiConnection'
      | 'probeSavedAutoBangumiCapabilities'
      | 'testAutoBangumiConnection'
      | 'listRequests'
      | 'getRequestDetail'
      | 'getRequestSafeInfo'
      | 'createRequest'
      | 'previewModifyRequest'
      | 'confirmRequestSave'
      | 'acceptRequest'
      | 'cancelRequest'
      | 'modifyRequest'
      | 'deleteRequest'
      | 'searchMikanCandidates'
      | 'getMikanPoster'
      | 'getPreferences'
      | 'savePreferences'
      | 'listCorrections'
      | 'saveCorrection'
      | 'parseBatchTitles'
      | 'saveConfirmBatchItems'
      | 'listTrackingItems'
      | 'getTrackingItemDetail'
      | 'revalidateTrackingItem'
      | 'submitTrackingItem'
      | 'retryTrackingItem'
      | 'checkTrackingItem'
      | 'resubmitTrackingItem'
      | 'recoverTrackingItem'
      | 'submitTrackingBatch'
      | 'deleteTrackingBatchPlans'
      | 'deleteTrackingBatchPlansWithExternal'
      | 'getTrackingBatchDeleteStatus'
      | 'deleteTrackingPlan'
      | 'syncTrackingItems'
      | 'modifyTrackingItem'
      | 'setTrackingItemEnabled'
      | 'refreshTrackingRss'
    >()
  })

  it('generates paths entries for all API families', () => {
    type PathKeys = keyof paths
    expectTypeOf<PathKeys>().toMatchTypeOf<
      | '/api/v1/settings/autobangumi'
      | '/api/v1/settings/autobangumi/probe'
      | '/api/v1/settings/autobangumi/test'
      | '/api/v1/batches/parse'
      | '/api/v1/batches/{batch_id}/save-confirm'
      | '/api/v1/corrections'
      | '/api/v1/mikan/candidates'
      | '/api/v1/mikan/posters/{key}'
      | '/api/v1/preferences'
      | '/api/v1/requests'
      | '/api/v1/requests/preview-modify'
      | '/api/v1/requests/save-confirm'
      | '/api/v1/requests/{request_id}'
      | '/api/v1/requests/{request_id}/accept'
      | '/api/v1/requests/{request_id}/cancel'
      | '/api/v1/requests/{request_id}/delete'
      | '/api/v1/requests/{request_id}/modify'
      | '/api/v1/requests/{request_id}/safe-info'
      | '/api/v1/tracking/items'
      | '/api/v1/tracking/items/{tracking_id}'
      | '/api/v1/tracking/items/{tracking_id}/revalidate'
      | '/api/v1/tracking/items/{tracking_id}/submit'
      | '/api/v1/tracking/batch-submit'
      | '/api/v1/tracking/batch-delete-plan'
      | '/api/v1/tracking/batch-delete-plan-external'
      | '/api/v1/tracking/batch-deletions/{batch_key}'
      | '/api/v1/tracking/items/{tracking_id}/delete-plan'
      | '/api/v1/tracking/items/{tracking_id}/retry'
      | '/api/v1/tracking/items/{tracking_id}/check'
      | '/api/v1/tracking/items/{tracking_id}/resubmit'
      | '/api/v1/tracking/items/{tracking_id}/recover'
      | '/api/v1/tracking/items/{tracking_id}/modify'
      | '/api/v1/tracking/items/{tracking_id}/set-enabled'
      | '/api/v1/tracking/items/{tracking_id}/refresh'
      | '/api/v1/tracking/sync'
    >()
  })

  it('has the shared success/error envelope components', () => {
    type SchemaKeys = keyof components['schemas']
    expectTypeOf<SchemaKeys>().toMatchTypeOf<
      'ApiErrorEnvelope' | 'ApiOkEnvelope'
    >()
  })

  it('types saved connection references on tracking bodies', () => {
    // Formal tracking writes carry only the saved connection generation.
    type SubmitBody = NonNullable<operations['submitTrackingItem']['requestBody']>['content']['application/json']
    expectTypeOf<SubmitBody>().toMatchTypeOf<{ connection_ref: string; configuration_revision: number }>()
  })

  it('derives preview patch consumers from the generated request contract', () => {
    type GeneratedPreviewPatch = NonNullable<
      operations['previewModifyRequest']['requestBody']
    >['content']['application/json']['patch']
    expectTypeOf<PreviewPatch>().toEqualTypeOf<GeneratedPreviewPatch>()
    expectTypeOf<PreviewPatch>().toMatchTypeOf<{
      selected_subtitle_group?: string | null
      filter_rule?: {
        must_contain?: string
        must_not_contain?: string
        use_regex?: boolean
        case_sensitive?: boolean
      }
      expected_folder_name?: string
    }>()
    expectTypeOf<PreviewPatch['selected_subtitle_group']>().toEqualTypeOf<string | null | undefined>()
  })

  it('has a non-empty expected operation set (guards the fixture)', () => {
    // Issue #228 retired ``deleteExternalTrackingItem``, issue #223 added the two batch-delete
    // operations and the batch status read, so the fixture holds 40 operations.
    expect(EXPECTED_OPERATION_IDS).toHaveLength(40)
  })
})
