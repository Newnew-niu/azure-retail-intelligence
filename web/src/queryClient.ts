import { QueryClient } from '@tanstack/react-query'

import { shouldRetry } from './api/queries'

export function createQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: {
        retry: shouldRetry,
        staleTime: 5 * 60 * 1000, // the data is a snapshot that changes only with a new export
        refetchOnWindowFocus: false,
      },
    },
  })
}
