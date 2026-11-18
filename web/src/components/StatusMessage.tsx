// The three non-data states every page needs: loading, error and empty.
import { useEffect, useState, type ReactNode } from 'react'

/** The hosted API scales to zero when idle, so the first request after a quiet spell is slow. */
export const SLOW_HINT_AFTER_MS = 3000

interface LoadingStateProps {
  label: string
  slowAfterMs?: number
}

export function LoadingState({ label, slowAfterMs = SLOW_HINT_AFTER_MS }: LoadingStateProps) {
  const [slow, setSlow] = useState(false)
  useEffect(() => {
    const timer = window.setTimeout(() => {
      setSlow(true)
    }, slowAfterMs)
    return () => {
      window.clearTimeout(timer)
    }
  }, [slowAfterMs])

  return (
    <div className="status status-loading" role="status" aria-live="polite">
      <span className="spinner" aria-hidden="true" />
      <div>
        <p className="status-line">{label}</p>
        {slow && (
          <p className="status-line muted">
            The API starts on demand and can take a few seconds to wake up after a quiet period.
          </p>
        )}
      </div>
    </div>
  )
}

interface ErrorStateProps {
  title: string
  message: string
  onRetry?: () => void
  children?: ReactNode
}

export function ErrorState({ title, message, onRetry, children }: ErrorStateProps) {
  return (
    <div className="status status-error" role="alert">
      <p className="status-title">{title}</p>
      <p>{message}</p>
      {children}
      {onRetry && (
        <button type="button" className="button" onClick={onRetry}>
          Try again
        </button>
      )}
    </div>
  )
}

export function EmptyState({ title, children }: { title: string; children?: ReactNode }) {
  return (
    <div className="status status-empty" role="status">
      <p className="status-title">{title}</p>
      {children}
    </div>
  )
}
