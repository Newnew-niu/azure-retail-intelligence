// TanStack Query hooks: caching, loading and error state for the two endpoints.
import { keepPreviousData, useQuery } from '@tanstack/react-query'

import { ApiError, fetchSeller, fetchSellers } from './client'
import type { SellerListQuery } from './types'

export const sellerKeys = {
  list: (query: SellerListQuery) => ['sellers', 'list', query] as const,
  detail: (sellerId: string) => ['sellers', 'detail', sellerId] as const,
}

/** 4xx answers will not change on a retry; network errors and 5xx might. */
export function shouldRetry(failureCount: number, error: Error): boolean {
  if (error instanceof ApiError && error.status >= 400 && error.status < 500) return false
  return failureCount < 2
}

export function useSellers(query: SellerListQuery) {
  return useQuery({
    queryKey: sellerKeys.list(query),
    queryFn: ({ signal }) => fetchSellers(query, signal),
    placeholderData: keepPreviousData, // keep the old page on screen while the next one loads
  })
}

export function useSeller(sellerId: string) {
  return useQuery({
    queryKey: sellerKeys.detail(sellerId),
    queryFn: ({ signal }) => fetchSeller(sellerId, signal),
  })
}
