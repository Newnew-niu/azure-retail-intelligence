// The seller list. Sortable columns are buttons inside the headers, and aria-sort tells screen
// readers which column is sorted and in which direction.
import { Link } from 'react-router'

import type { SellerListItem, SortKey } from '../api/types'
import { formatCount, formatCurrency, formatPercent, formatScore, shortId } from '../lib/format'
import type { SellerListParams } from '../lib/listParams'

interface Column {
  label: string
  sortKey?: SortKey
  text?: boolean // left-aligned; numbers are right-aligned so digits line up
  render: (seller: SellerListItem) => string
}

const COLUMNS: readonly Column[] = [
  { label: 'State', text: true, render: (s) => s.seller_state ?? '—' },
  { label: 'Orders', sortKey: 'orders', render: (s) => formatCount(s.orders) },
  { label: 'Product sales', sortKey: 'product_sales', render: (s) => formatCurrency(s.product_sales) },
  { label: 'Avg order value', render: (s) => formatCurrency(s.average_order_value) },
  { label: 'Late dispatch', sortKey: 'late_rate', render: (s) => formatPercent(s.late_rate) },
  { label: 'Review score', sortKey: 'review_score', render: (s) => formatScore(s.review_score) },
]

interface SellerTableProps {
  sellers: readonly SellerListItem[]
  params: SellerListParams
  onSort: (sortKey: SortKey) => void
  busy: boolean
  listSearch: string
}

export function SellerTable({ sellers, params, onSort, busy, listSearch }: SellerTableProps) {
  return (
    <div className="table-scroll">
      <table className="data-table" aria-busy={busy}>
        <caption className="visually-hidden">
          Sellers, sorted by {params.sort.replace('_', ' ')}, {params.order === 'desc' ? 'highest' : 'lowest'} first.
          Empty values are listed last.
        </caption>
        <thead>
          <tr>
            <th scope="col">Seller</th>
            {COLUMNS.map((column) => {
              const active = column.sortKey !== undefined && column.sortKey === params.sort
              const ariaSort = active ? (params.order === 'asc' ? 'ascending' : 'descending') : undefined
              const sortKey = column.sortKey
              return (
                <th key={column.label} scope="col" className={column.text ? undefined : 'numeric'} aria-sort={ariaSort}>
                  {sortKey ? (
                    <button
                      type="button"
                      className="sort-button"
                      onClick={() => {
                        onSort(sortKey)
                      }}
                    >
                      {column.label}
                      <span aria-hidden="true" className="sort-indicator">
                        {active ? (params.order === 'asc' ? '↑' : '↓') : '↕'}
                      </span>
                    </button>
                  ) : (
                    column.label
                  )}
                </th>
              )
            })}
          </tr>
        </thead>
        <tbody>
          {sellers.map((seller) => (
            <tr key={seller.seller_id}>
              <th scope="row">
                <Link
                  to={`/sellers/${seller.seller_id}`}
                  state={{ listSearch }}
                  className="seller-link"
                  aria-label={`Seller ${seller.seller_id}`}
                >
                  <code>{shortId(seller.seller_id)}</code>
                </Link>
              </th>
              {COLUMNS.map((column) => (
                <td key={column.label} className={column.text ? undefined : 'numeric'}>
                  {column.render(seller)}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
