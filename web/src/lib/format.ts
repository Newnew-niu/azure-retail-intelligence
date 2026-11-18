// Display formatting. Every function accepts null and shows a dash, because the API returns null
// when a value has no basis (for example, no reviewed orders), and that is not the same as zero.
export const EMPTY = '—'

const currency = new Intl.NumberFormat('en-US', { style: 'currency', currency: 'BRL', maximumFractionDigits: 2 })
const currencyCompact = new Intl.NumberFormat('en-US', {
  style: 'currency',
  currency: 'BRL',
  notation: 'compact',
  maximumFractionDigits: 1,
})
const count = new Intl.NumberFormat('en-US', { maximumFractionDigits: 0 })
const monthFormat = new Intl.DateTimeFormat('en-US', { month: 'short', year: 'numeric', timeZone: 'UTC' })

export function formatCurrency(value: number | null): string {
  return value === null ? EMPTY : currency.format(value)
}

export function formatCurrencyCompact(value: number | null): string {
  return value === null ? EMPTY : currencyCompact.format(value)
}

export function formatCount(value: number | null): string {
  return value === null ? EMPTY : count.format(value)
}

export function formatPercent(value: number | null, digits = 1): string {
  return value === null ? EMPTY : `${(value * 100).toFixed(digits)}%`
}

/** A change such as 0.5 is shown as "+50%". */
export function formatChange(value: number | null): string {
  if (value === null) return EMPTY
  const percent = Math.round(value * 100)
  return `${percent > 0 ? '+' : ''}${percent}%`
}

export function formatScore(value: number | null): string {
  return value === null ? EMPTY : value.toFixed(2)
}

/** "2018-08" becomes "Aug 2018". */
export function formatMonth(yearMonth: string): string {
  const match = /^(\d{4})-(\d{2})$/.exec(yearMonth)
  if (!match) return yearMonth
  return monthFormat.format(new Date(Date.UTC(Number(match[1]), Number(match[2]) - 1, 1)))
}

/** Seller IDs are 32 characters; the first 8 are enough to tell sellers apart on screen. */
export function shortId(sellerId: string): string {
  return sellerId.slice(0, 8)
}
