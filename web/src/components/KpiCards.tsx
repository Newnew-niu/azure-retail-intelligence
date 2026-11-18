import type { SellerSummary } from '../api/types'
import { formatCount } from '../lib/format'
import { METRICS, type MetricKey } from '../lib/metrics'

/** The basis of each ratio, so a 0% late rate over 3 orders is not mistaken for a strong record. */
function basis(summary: SellerSummary, key: MetricKey): string {
  switch (key) {
    case 'product_sales':
      return `${formatCount(summary.items_sold)} items sold`
    case 'orders':
      return 'Sales orders in the window'
    case 'average_order_value':
      return 'Price plus freight per order'
    case 'late_rate':
      return `Of ${formatCount(summary.dispatched_orders)} dispatched orders`
    case 'review_score':
      return `Over ${formatCount(summary.reviewed_orders)} reviewed orders`
  }
}

export function KpiCards({ summary }: { summary: SellerSummary }) {
  return (
    <dl className="kpi-grid">
      {METRICS.map((metric) => (
        <div className="kpi-card" key={metric.key}>
          <dt>{metric.label}</dt>
          <dd className="kpi-value">{metric.format(summary[metric.key])}</dd>
          <dd className="kpi-basis">{basis(summary, metric.key)}</dd>
        </div>
      ))}
    </dl>
  )
}
