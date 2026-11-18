// Seller list: the URL is the single source of truth for search, filter, sort and page.
import { Link, useSearchParams } from 'react-router'

import { useSellers } from '../api/queries'
import type { SortKey } from '../api/types'
import { Pagination } from '../components/Pagination'
import { SellerFilters } from '../components/SellerFilters'
import { SellerTable } from '../components/SellerTable'
import { EmptyState, ErrorState, LoadingState } from '../components/StatusMessage'
import { nextSort, PAGE_SIZE, parseListParams, toApiQuery, toSearchParams, type SellerListParams } from '../lib/listParams'

export function SellerListPage() {
  const [searchParams, setSearchParams] = useSearchParams()
  const params = parseListParams(searchParams)
  const sellers = useSellers(toApiQuery(params))

  /** Any change other than the page itself goes back to page 1. */
  function update(change: Partial<SellerListParams>) {
    setSearchParams(toSearchParams({ ...params, page: 1, ...change }))
  }

  const filtered = params.q !== '' || params.state !== ''

  return (
    <>
      <h1>Sellers</h1>
      <p className="lead">
        Browse marketplace sellers by sales, orders, dispatch punctuality and reviews. Select a seller to see
        the monthly trend and health signals.
      </p>
      <SellerFilters key={params.q} params={params} onChange={update} />

      {sellers.isPending ? (
        <LoadingState label="Loading sellers…" />
      ) : sellers.isError ? (
        <ErrorState
          title="Sellers could not be loaded"
          message={sellers.error.message}
          onRetry={() => void sellers.refetch()}
        />
      ) : sellers.data.items.length === 0 ? (
        sellers.data.total > 0 ? (
          <EmptyState title={`Page ${params.page} is past the last page.`}>
            <button
              type="button"
              className="button"
              onClick={() => {
                update({ page: 1 })
              }}
            >
              Go to the first page
            </button>
          </EmptyState>
        ) : (
          <EmptyState title="No sellers match these filters.">
            {filtered && <p>Try another seller ID or state, or clear the filters.</p>}
          </EmptyState>
        )
      ) : (
        <>
          <SellerTable
            sellers={sellers.data.items}
            params={params}
            busy={sellers.isPlaceholderData}
            listSearch={searchParams.toString()}
            onSort={(sortKey: SortKey) => {
              update(nextSort(params, sortKey))
            }}
          />
          <Pagination
            page={params.page}
            pageSize={PAGE_SIZE}
            total={sellers.data.total}
            totalPages={sellers.data.total_pages}
            onPage={(page) => {
              update({ page })
            }}
          />
        </>
      )}
      <p className="muted small">
        Definitions: <Link to="/about">how the numbers are calculated</Link>.
      </p>
    </>
  )
}
