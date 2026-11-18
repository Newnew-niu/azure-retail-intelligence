import { act, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { LoadingState } from './StatusMessage'

describe('LoadingState', () => {
  afterEach(() => {
    vi.useRealTimers()
  })

  it('explains a slow start only after the threshold', () => {
    vi.useFakeTimers()
    render(<LoadingState label="Loading sellers…" slowAfterMs={3000} />)
    expect(screen.getByRole('status')).toHaveTextContent('Loading sellers…')
    expect(screen.queryByText(/wake up/)).not.toBeInTheDocument()
    act(() => {
      vi.advanceTimersByTime(3000)
    })
    expect(screen.getByRole('status')).toHaveTextContent(/can take a few seconds to wake up/)
  })
})
