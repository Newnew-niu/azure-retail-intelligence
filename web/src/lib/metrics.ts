// The KPIs shown on the detail page: one definition each, used by the cards, the chart and the table.
import type { SellerMonth } from '../api/types'
import { formatCount, formatCurrency, formatCurrencyCompact, formatPercent, formatScore } from './format'

export type MetricKey = 'product_sales' | 'orders' | 'average_order_value' | 'late_rate' | 'review_score'

export interface Metric {
  key: MetricKey
  label: string
  description: string
  format: (value: number | null) => string
  axisFormat: (value: number) => string
}

export const METRICS: readonly Metric[] = [
  {
    key: 'product_sales',
    label: 'Product sales',
    description: 'Sum of item prices in BRL, excluding freight',
    format: formatCurrency,
    axisFormat: formatCurrencyCompact,
  },
  {
    key: 'orders',
    label: 'Orders',
    description: "Sales orders that include the seller's items",
    format: formatCount,
    axisFormat: formatCount,
  },
  {
    key: 'average_order_value',
    label: 'Average order value',
    description: "The seller's price plus freight per order",
    format: formatCurrency,
    axisFormat: formatCurrencyCompact,
  },
  {
    key: 'late_rate',
    label: 'Late dispatch rate',
    description: 'Dispatched orders handed to the carrier after the shipping deadline',
    format: (value) => formatPercent(value),
    axisFormat: (value) => formatPercent(value, 0),
  },
  {
    key: 'review_score',
    label: 'Review score',
    description: 'Mean review score of orders with a review, 1 to 5',
    format: formatScore,
    axisFormat: (value) => value.toFixed(1),
  },
]

export function metricValue(month: Pick<SellerMonth, MetricKey>, key: MetricKey): number | null {
  return month[key]
}
