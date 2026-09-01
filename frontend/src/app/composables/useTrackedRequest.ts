/**
 * useTrackedRequest (US-199).
 *
 * Thin wrapper around the unified transport that drives the global loading
 * indicator (loading store) while a request is in flight. The transport
 * itself stays Pinia-free; features that want the global loading bar use
 * this composable instead of calling `apiRequest` directly.
 */
import { api, type ApiRequestOptions, type ApiPath, type HttpMethod } from '@/api/client'
import { useLoadingStore } from '@/app/stores/loading'

export async function trackedRequest<T = unknown>(
  method: HttpMethod,
  path: ApiPath,
  options?: ApiRequestOptions,
): Promise<T> {
  const loading = useLoadingStore()
  loading.begin()
  try {
    return await apiRequestSafe(method, path, options)
  } finally {
    loading.end()
  }
}

// The `api` object exposes typed helpers; keep the raw request internal to
// avoid double-wrapping in features.
async function apiRequestSafe<T>(method: HttpMethod, path: ApiPath, options?: ApiRequestOptions): Promise<T> {
  switch (method) {
    case 'GET':
      return api.get<T>(path, options)
    case 'POST':
      return api.post<T>(path, options)
    case 'PUT':
      return api.put<T>(path, options)
    case 'PATCH':
      return api.patch<T>(path, options)
    case 'DELETE':
      return api.delete<T>(path, options)
  }
}

/** Tracked helpers mirroring the `api` object. */
export const trackedApi = {
  get: <T = unknown>(path: ApiPath, options?: ApiRequestOptions) => trackedRequest<T>('GET', path, options),
  post: <T = unknown>(path: ApiPath, options?: ApiRequestOptions) => trackedRequest<T>('POST', path, options),
  put: <T = unknown>(path: ApiPath, options?: ApiRequestOptions) => trackedRequest<T>('PUT', path, options),
  patch: <T = unknown>(path: ApiPath, options?: ApiRequestOptions) => trackedRequest<T>('PATCH', path, options),
  delete: <T = unknown>(path: ApiPath, options?: ApiRequestOptions) => trackedRequest<T>('DELETE', path, options),
}
