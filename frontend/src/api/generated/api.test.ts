import { describe, expect, it } from 'vitest'
import { expectTypeOf } from 'vitest'

import type {
  components,
  operations,
  paths,
} from '@/api/generated/api'

// US-198: the frontend TypeScript client is generated from
// docs/api/openapi.json by openapi-typescript (locked in package.json).
// The generated module is type-only (interfaces), so these tests assert the
// *generated contract surface* the migrated features will consume:
// operationIds, path entries, the envelope components and the request-body
// credential fields. They fail at typecheck if the generator output ever
// drifts from the OpenAPI contract.

const EXPECTED_OPERATION_IDS = [
  'listRequests',
  'getRequestDetail',
  'getRequestSafeInfo',
  'createRequest',
  'previewModifyRequest',
  'previewSaveRequest',
  'confirmRequestSave',
  'acceptRequest',
  'cancelRequest',
  'modifyRequest',
  'deleteRequest',
  'submitRequestToAutoBangumi',
  'searchMikanCandidates',
  'getMikanPoster',
  'getPreferences',
  'savePreferences',
  'listCorrections',
  'saveCorrection',
  'parseBatchTitles',
  'saveConfirmBatchItems',
  'acceptBatchItems',
  'getBatchQueue',
  'submitBatchQueue',
  'retryBatchQueueItem',
  'recoverBatchQueueItem',
  'testQbittorrentConnection',
  'testAutoBangumiConnection',
] as const

describe('generated API client (US-198)', () => {
  it('declares every operationId as a readable, stable name', () => {
    // At type level: every expected operationId must exist on `operations`.
    type OperationKeys = keyof operations
    expectTypeOf<OperationKeys>().toEqualTypeOf<
      | 'listRequests'
      | 'getRequestDetail'
      | 'getRequestSafeInfo'
      | 'createRequest'
      | 'previewModifyRequest'
      | 'previewSaveRequest'
      | 'confirmRequestSave'
      | 'acceptRequest'
      | 'cancelRequest'
      | 'modifyRequest'
      | 'deleteRequest'
      | 'submitRequestToAutoBangumi'
      | 'searchMikanCandidates'
      | 'getMikanPoster'
      | 'getPreferences'
      | 'savePreferences'
      | 'listCorrections'
      | 'saveCorrection'
      | 'parseBatchTitles'
      | 'saveConfirmBatchItems'
      | 'acceptBatchItems'
      | 'getBatchQueue'
      | 'submitBatchQueue'
      | 'retryBatchQueueItem'
      | 'recoverBatchQueueItem'
      | 'testQbittorrentConnection'
      | 'testAutoBangumiConnection'
    >()
  })

  it('generates paths entries for all API families', () => {
    type PathKeys = keyof paths
    expectTypeOf<PathKeys>().toEqualTypeOf<
      | '/api/v1/autobangumi/test-connection'
      | '/api/v1/batches/parse'
      | '/api/v1/batches/{batch_id}/accept'
      | '/api/v1/batches/{batch_id}/queue'
      | '/api/v1/batches/{batch_id}/recover'
      | '/api/v1/batches/{batch_id}/retry'
      | '/api/v1/batches/{batch_id}/save-confirm'
      | '/api/v1/batches/{batch_id}/submit'
      | '/api/v1/corrections'
      | '/api/v1/mikan/candidates'
      | '/api/v1/mikan/posters/{key}'
      | '/api/v1/preferences'
      | '/api/v1/qbittorrent/test-connection'
      | '/api/v1/requests'
      | '/api/v1/requests/preview-modify'
      | '/api/v1/requests/preview-save'
      | '/api/v1/requests/save-confirm'
      | '/api/v1/requests/{request_id}'
      | '/api/v1/requests/{request_id}/accept'
      | '/api/v1/requests/{request_id}/cancel'
      | '/api/v1/requests/{request_id}/delete'
      | '/api/v1/requests/{request_id}/modify'
      | '/api/v1/requests/{request_id}/safe-info'
      | '/api/v1/requests/{request_id}/submit-ab'
    >()
  })

  it('has the shared success/error envelope components', () => {
    type SchemaKeys = keyof components['schemas']
    expectTypeOf<SchemaKeys>().toEqualTypeOf<
      'ApiErrorEnvelope' | 'ApiOkEnvelope'
    >()
  })

  it('types request-scoped credential fields on the submit-ab body', () => {
    // submit-ab's request body carries ab_config (request-scoped credentials);
    // the transport layer will use this generated type for the POST body.
    type SubmitAbBody = NonNullable<
      operations['submitRequestToAutoBangumi']['requestBody']
    >['content']['application/json']
    expectTypeOf<SubmitAbBody>().toMatchTypeOf<{
      ab_config: { auth_mode: 'password' | 'api_token'; fallback_enabled: boolean }
      storage_dir?: string
    }>()
    // Credential fields are present (the transport must never persist them).
    expectTypeOf<SubmitAbBody['ab_config']>().toMatchTypeOf<{
      base_url?: string
      username?: string
      password?: string
      token?: string
    }>()
  })

  it('has a non-empty expected operation set (guards the fixture)', () => {
    expect(EXPECTED_OPERATION_IDS).toHaveLength(27)
  })
})
