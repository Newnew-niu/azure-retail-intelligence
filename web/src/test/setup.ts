import '@testing-library/jest-dom/vitest'
import { cleanup, configure } from '@testing-library/react'
import { afterAll, afterEach, beforeAll, vi } from 'vitest'

import { requests, server } from './server'

// jsdom has no layout, so Recharts' ResponsiveContainer would measure 0 x 0 and draw nothing.
// Give the chart a fixed size instead; the tests read numbers from the table, not the drawing.
vi.mock('recharts', async (importOriginal) => {
  const recharts = await importOriginal<typeof import('recharts')>()
  const { cloneElement, isValidElement } = await import('react')
  return {
    ...recharts,
    ResponsiveContainer: ({ children }: { children: unknown }) =>
      isValidElement<{ width?: number; height?: number }>(children)
        ? cloneElement(children, { width: 640, height: 280 })
        : null,
  }
})

// The detail page and its chart library are loaded lazily; the first import can take over a second.
configure({ asyncUtilTimeout: 5000 })

beforeAll(() => {
  server.listen({ onUnhandledRequest: 'error' })
})

afterEach(() => {
  cleanup()
  server.resetHandlers()
  requests.length = 0
})

afterAll(() => {
  server.close()
})
