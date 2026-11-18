// How a health signal is presented. The rule itself is computed by the API; this only maps a
// status to words and a symbol, so the meaning never depends on colour alone.
import type { HealthSignal, SignalStatus } from '../api/types'
import { formatChange, formatPercent, formatScore } from './format'

export const STATUS_DISPLAY: Record<SignalStatus, { label: string; symbol: string }> = {
  positive: { label: 'Positive', symbol: '▲' },
  neutral: { label: 'Neutral', symbol: '●' },
  attention: { label: 'Needs attention', symbol: '!' },
  insufficient_data: { label: 'Not enough data', symbol: '?' },
}

export function signalValue(signal: HealthSignal): string {
  switch (signal.key) {
    case 'sales_trend':
      return formatChange(signal.value)
    case 'late_dispatch':
      return formatPercent(signal.value)
    case 'review_score':
      return signal.value === null ? formatScore(null) : `${formatScore(signal.value)} / 5`
  }
}

/** Signals that need attention come first, so the analyst sees them first. */
const ORDER: Record<SignalStatus, number> = { attention: 0, neutral: 1, positive: 2, insufficient_data: 3 }

export function sortSignals(signals: readonly HealthSignal[]): HealthSignal[] {
  return [...signals].sort((a, b) => ORDER[a.status] - ORDER[b.status])
}
