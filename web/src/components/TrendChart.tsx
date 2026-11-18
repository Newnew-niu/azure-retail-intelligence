// Monthly trend of one KPI at a time, chosen with radio buttons (keyboard friendly). Sums are
// bars; ratios are a line with gaps where a month has no basis. The same numbers are available as
// a table for screen readers and for anyone who wants exact values.
import { useId, useState } from 'react'
import {
  Bar,
  BarChart,
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'

import type { SellerMonth } from '../api/types'
import { formatMonth } from '../lib/format'
import { METRICS, metricValue, type Metric, type MetricKey } from '../lib/metrics'

const SUMS: ReadonlySet<MetricKey> = new Set(['product_sales', 'orders'])

interface Point {
  month: string
  value: number | null
}

function Chart({ points, metric }: { points: Point[]; metric: Metric }) {
  const axis = {
    xAxis: <XAxis dataKey="month" tick={{ fontSize: 12 }} interval="preserveStartEnd" minTickGap={16} />,
    yAxis: <YAxis tickFormatter={metric.axisFormat} tick={{ fontSize: 12 }} width={72} />,
    grid: <CartesianGrid vertical={false} stroke="var(--grid)" />,
    tooltip: (
      <Tooltip
        formatter={(value) => [metric.format(typeof value === 'number' ? value : null), metric.label]}
        contentStyle={{ background: 'var(--surface)', border: '1px solid var(--border)' }}
      />
    ),
  }
  return (
    <ResponsiveContainer width="100%" height={280}>
      {SUMS.has(metric.key) ? (
        <BarChart data={points} margin={{ top: 8, right: 8, bottom: 0, left: 0 }}>
          {axis.grid}
          {axis.xAxis}
          {axis.yAxis}
          {axis.tooltip}
          <Bar dataKey="value" name={metric.label} fill="var(--series-1)" radius={[3, 3, 0, 0]} />
        </BarChart>
      ) : (
        <LineChart data={points} margin={{ top: 8, right: 8, bottom: 0, left: 0 }}>
          {axis.grid}
          {axis.xAxis}
          {axis.yAxis}
          {axis.tooltip}
          <Line
            dataKey="value"
            name={metric.label}
            stroke="var(--series-1)"
            strokeWidth={2}
            dot={{ r: 3, fill: 'var(--series-1)' }}
            connectNulls={false}
            isAnimationActive={false}
          />
        </LineChart>
      )}
    </ResponsiveContainer>
  )
}

export function TrendChart({ months }: { months: readonly SellerMonth[] }) {
  const [metricKey, setMetricKey] = useState<MetricKey>('product_sales')
  const groupName = useId()
  const metric = METRICS.find((m) => m.key === metricKey) ?? METRICS[0]
  if (!metric) return null
  const points: Point[] = months.map((m) => ({ month: formatMonth(m.year_month), value: metricValue(m, metric.key) }))
  const monthsWithData = points.filter((p) => p.value !== null && (p.value !== 0 || SUMS.has(metric.key)))

  return (
    <figure className="panel trend">
      <figcaption>
        <h2>Monthly trend</h2>
        <p className="muted">{metric.description}.</p>
      </figcaption>
      <fieldset className="segmented">
        <legend className="visually-hidden">Measure to chart</legend>
        {METRICS.map((m) => (
          <label key={m.key} className={m.key === metric.key ? 'segment segment-active' : 'segment'}>
            <input
              type="radio"
              name={groupName}
              value={m.key}
              checked={m.key === metric.key}
              onChange={() => {
                setMetricKey(m.key)
              }}
            />
            {m.label}
          </label>
        ))}
      </fieldset>
      {monthsWithData.length === 0 ? (
        <p className="status status-empty">No month in the window has data for this measure.</p>
      ) : (
        <div className="chart" role="img" aria-label={`${metric.label} by month. Exact values are in the table below.`}>
          <Chart points={points} metric={metric} />
        </div>
      )}
      <details className="chart-table">
        <summary>Show the numbers as a table</summary>
        <div className="table-scroll">
          <table className="data-table">
            <caption className="visually-hidden">{metric.label} by month</caption>
            <thead>
              <tr>
                <th scope="col">Month</th>
                <th scope="col" className="numeric">
                  {metric.label}
                </th>
                <th scope="col" className="numeric">
                  Orders
                </th>
              </tr>
            </thead>
            <tbody>
              {months.map((m) => (
                <tr key={m.year_month}>
                  <th scope="row">{formatMonth(m.year_month)}</th>
                  <td className="numeric">{metric.format(metricValue(m, metric.key))}</td>
                  <td className="numeric">{m.orders}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </details>
    </figure>
  )
}
