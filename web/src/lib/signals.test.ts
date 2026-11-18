import { describe, expect, it } from 'vitest'

import type { HealthSignal } from '../api/types'
import { DETAIL } from '../test/fixtures'
import { signalValue, sortSignals, STATUS_DISPLAY } from './signals'

const signal = (overrides: Partial<HealthSignal>): HealthSignal => ({
  key: 'sales_trend',
  label: 'Sales trend',
  status: 'neutral',
  value: 0,
  summary: '',
  rule: '',
  ...overrides,
})

describe('signals', () => {
  it('gives every status a distinct label and symbol', () => {
    const labels = Object.values(STATUS_DISPLAY).map((s) => s.label)
    const symbols = Object.values(STATUS_DISPLAY).map((s) => s.symbol)
    expect(new Set(labels).size).toBe(4)
    expect(new Set(symbols).size).toBe(4)
  })

  it('formats each signal value in its own unit', () => {
    expect(signalValue(signal({ key: 'sales_trend', value: -0.25 }))).toBe('-25%')
    expect(signalValue(signal({ key: 'late_dispatch', value: 0.083 }))).toBe('8.3%')
    expect(signalValue(signal({ key: 'review_score', value: 4.1 }))).toBe('4.10 / 5')
    expect(signalValue(signal({ key: 'review_score', value: null }))).toBe('—')
  })

  it('puts attention first and insufficient data last, without changing the input', () => {
    const original = [...DETAIL.signals]
    expect(sortSignals(DETAIL.signals).map((s) => s.status)).toEqual(['attention', 'positive', 'insufficient_data'])
    expect(DETAIL.signals).toEqual(original)
  })
})
