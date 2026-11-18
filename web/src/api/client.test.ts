import { http, HttpResponse } from 'msw'
import { describe, expect, it } from 'vitest'

import { requests, server } from '../test/server'
import { ApiError, fetchSeller, fetchSellers, NO_API_STATUS } from './client'
import { shouldRetry } from './queries'

describe('api client', () => {
  it('sends only the parameters that are set', async () => {
    await fetchSellers({ page: 2, page_size: 25, sort: 'orders', order: 'asc', state: 'RJ' })
    expect(Object.fromEntries(requests[0]?.searchParams ?? [])).toEqual({
      page: '2',
      page_size: '25',
      sort: 'orders',
      order: 'asc',
      state: 'RJ',
    })
  })

  it('turns an error body into an ApiError with the API detail', async () => {
    const error = await fetchSeller('ffffffffffffffffffffffffffffffff').catch((e: unknown) => e)
    expect(error).toBeInstanceOf(ApiError)
    expect(error).toMatchObject({ status: 404, message: 'Seller has no sales orders in the reporting window' })
  })

  it('summarises a validation error list', async () => {
    server.use(http.get('*/api/sellers', () => HttpResponse.json({ detail: [{ loc: ['q'] }] }, { status: 422 })))
    await expect(fetchSellers({})).rejects.toMatchObject({ status: 422, message: 'The request was not valid.' })
  })

  it('reports a body without detail by its status', async () => {
    server.use(http.get('*/api/sellers', () => new HttpResponse('Bad gateway', { status: 502 })))
    await expect(fetchSellers({})).rejects.toMatchObject({ status: 502, message: 'The seller API answered 502.' })
  })

  it('reports a network failure as unreachable', async () => {
    server.use(http.get('*/api/sellers', () => HttpResponse.error()))
    await expect(fetchSellers({})).rejects.toMatchObject({ status: NO_API_STATUS })
  })

  it('escapes the seller id in the path', async () => {
    let seen = ''
    server.use(
      http.get('*/api/sellers/:sellerId', ({ request }) => {
        seen = new URL(request.url).pathname
        return HttpResponse.json({ detail: 'x' }, { status: 404 })
      }),
    )
    await fetchSeller('a/b?c').catch(() => undefined)
    expect(seen).toBe('/api/sellers/a%2Fb%3Fc')
  })
})

describe('shouldRetry', () => {
  it('does not retry answers that will not change', () => {
    expect(shouldRetry(0, new ApiError(404, 'x'))).toBe(false)
    expect(shouldRetry(0, new ApiError(422, 'x'))).toBe(false)
  })

  it('retries server and network errors twice', () => {
    expect(shouldRetry(0, new ApiError(503, 'x'))).toBe(true)
    expect(shouldRetry(1, new ApiError(NO_API_STATUS, 'x'))).toBe(true)
    expect(shouldRetry(2, new ApiError(503, 'x'))).toBe(false)
  })
})
