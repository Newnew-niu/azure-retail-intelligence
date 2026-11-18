import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { createMemoryRouter, RouterProvider } from 'react-router'

import { routes } from '../routes'

/** Renders the whole app at a path, with a fresh cache and no retries, so errors show at once. */
export function renderApp(path = '/') {
  const router = createMemoryRouter(routes, { initialEntries: [path] })
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  const user = userEvent.setup()
  const view = render(
    <QueryClientProvider client={queryClient}>
      <RouterProvider router={router} />
    </QueryClientProvider>,
  )
  return { ...view, router, user }
}

/** The current location as "/path?query", for asserting URL state. */
export function currentUrl(router: ReturnType<typeof createMemoryRouter>): string {
  const { pathname, search } = router.state.location
  return pathname + search
}
