// The only module that talks HTTP. Components use the hooks in queries.ts instead.
import type { SellerDetail, SellerListQuery, SellerPage } from './types'

/** Where the API lives. "/api" is proxied to FastAPI by Vite (dev) and nginx (Docker).
 *  An empty value means this build has no API, for example a static preview. */
export const API_BASE_URL: string = (import.meta.env.VITE_API_BASE_URL ?? '/api').replace(/\/+$/, '')

export class ApiError extends Error {
  readonly status: number

  constructor(status: number, message: string) {
    super(message)
    this.name = 'ApiError'
    this.status = status
  }
}

export const NO_API_STATUS = 0

function detailOf(body: unknown): string | undefined {
  if (typeof body !== 'object' || body === null || !('detail' in body)) return undefined
  const { detail } = body
  if (typeof detail === 'string') return detail
  if (Array.isArray(detail)) return 'The request was not valid.' // FastAPI's 422 list of field errors
  return undefined
}

async function getJson<T>(path: string, signal?: AbortSignal): Promise<T> {
  if (!API_BASE_URL) {
    throw new ApiError(NO_API_STATUS, 'This copy of the app is not connected to the seller API.')
  }
  const url = new URL(`${API_BASE_URL}${path}`, window.location.origin)
  let response: Response
  try {
    response = await fetch(url, { headers: { Accept: 'application/json' }, ...(signal ? { signal } : {}) })
  } catch (error) {
    if (signal?.aborted) throw error
    throw new ApiError(NO_API_STATUS, 'The seller API could not be reached.')
  }
  if (!response.ok) {
    const body: unknown = await response.json().catch(() => undefined)
    throw new ApiError(response.status, detailOf(body) ?? `The seller API answered ${response.status}.`)
  }
  return (await response.json()) as T
}

export function fetchSellers(query: SellerListQuery, signal?: AbortSignal): Promise<SellerPage> {
  const search = new URLSearchParams()
  for (const [key, value] of Object.entries(query)) {
    if (value !== null && value !== '') search.set(key, String(value))
  }
  return getJson<SellerPage>(`/sellers?${search.toString()}`, signal)
}

export function fetchSeller(sellerId: string, signal?: AbortSignal): Promise<SellerDetail> {
  return getJson<SellerDetail>(`/sellers/${encodeURIComponent(sellerId)}`, signal)
}
