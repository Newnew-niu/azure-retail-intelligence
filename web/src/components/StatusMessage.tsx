// The three non-data states every page needs: loading, error and empty.
import type { ReactNode } from 'react'

export function LoadingState({ label }: { label: string }) {
  return (
    <div className="status status-loading" role="status" aria-live="polite">
      <span className="spinner" aria-hidden="true" />
      {label}
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
