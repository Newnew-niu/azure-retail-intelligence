import { describe, expect, it } from 'vitest'

import {
  EMPTY,
  formatChange,
  formatCount,
  formatCurrency,
  formatCurrencyCompact,
  formatMonth,
  formatPercent,
  formatScore,
  shortId,
} from './format'

describe('format', () => {
  it('shows a dash for missing values, never zero', () => {
    for (const formatter of [formatCurrency, formatCurrencyCompact, formatCount, formatPercent, formatChange, formatScore]) {
      expect(formatter(null)).toBe(EMPTY)
    }
  })

  it('formats money in BRL with two decimals', () => {
    expect(formatCurrency(229237.63)).toBe('R$229,237.63')
    expect(formatCurrency(0)).toBe('R$0.00')
  })

  it('formats compact money for chart axes', () => {
    expect(formatCurrencyCompact(26000)).toBe('R$26K')
  })

  it('formats counts with thousands separators', () => {
    expect(formatCount(3029)).toBe('3,029')
  })

  it('formats rates as percentages', () => {
    expect(formatPercent(0.0353669)).toBe('3.5%')
    expect(formatPercent(0.1, 0)).toBe('10%')
    expect(formatPercent(0)).toBe('0.0%')
  })

  it('formats changes with an explicit sign', () => {
    expect(formatChange(0.5)).toBe('+50%')
    expect(formatChange(-0.3626)).toBe('-36%')
    expect(formatChange(0)).toBe('0%')
  })

  it('formats review scores with two decimals', () => {
    expect(formatScore(4.136242)).toBe('4.14')
  })

  it('formats months without a time zone shift', () => {
    expect(formatMonth('2018-08')).toBe('Aug 2018')
    expect(formatMonth('2017-01')).toBe('Jan 2017')
    expect(formatMonth('not a month')).toBe('not a month')
  })

  it('shortens seller ids to 8 characters', () => {
    expect(shortId('4869f7a5dfa277a7dca6462dcf3b52b2')).toBe('4869f7a5')
  })
})
