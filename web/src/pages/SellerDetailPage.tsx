// One seller: KPI cards, monthly trend and health signals.
import { Link, useLocation, useParams } from 'react-router'

import { ApiError } from '../api/client'
import { useSeller } from '../api/queries'
import { KpiCards } from '../components/KpiCards'
import { SignalList } from '../components/SignalList'
import { ErrorState, LoadingState } from '../components/StatusMessage'
import { TrendChart } from '../components/TrendChart'
import { formatMonth } from '../lib/format'

function backLink(state: unknown): string {
  // The list page passes its query string, so "Back" returns to the same filters and page.
  if (typeof state === 'object' && state !== null && 'listSearch' in state && typeof state.listSearch === 'string') {
    return state.listSearch ? `/?${state.listSearch}` : '/'
  }
  return '/'
}

export function SellerDetailPage() {
  const { sellerId = '' } = useParams()
  const location = useLocation()
  const seller = useSeller(sellerId)
  const back = (
    <p>
      <Link to={backLink(location.state)}>← Back to sellers</Link>
    </p>
  )

  if (seller.isPending) {
    return (
      <>
        {back}
        <LoadingState label="Loading seller…" />
      </>
    )
  }
  if (seller.isError) {
    const { error } = seller
    const notFound = error instanceof ApiError && (error.status === 404 || error.status === 422)
    return (
      <>
        {back}
        <h1>Seller</h1>
        {notFound ? (
          <ErrorState
            title="Seller not found"
            message={`No sales orders in the reporting window for seller ${sellerId}.`}
          />
        ) : (
          <ErrorState
            title="The seller could not be loaded"
            message={error.message}
            onRetry={() => void seller.refetch()}
          />
        )}
      </>
    )
  }

  const { data } = seller
  return (
    <>
      {back}
      <h1>
        Seller <code className="seller-id">{data.seller_id}</code>
      </h1>
      <p className="lead">
        State {data.seller_state ?? 'unknown'} · sales orders from {formatMonth(data.window.first_month)} to{' '}
        {formatMonth(data.window.last_month)}
      </p>
      <section aria-labelledby="kpi-heading">
        <h2 id="kpi-heading" className="visually-hidden">
          Key figures
        </h2>
        <KpiCards summary={data.summary} />
      </section>
      <div className="detail-grid">
        <TrendChart months={data.monthly} />
        <SignalList signals={data.signals} disclaimer={data.disclaimer} />
      </div>
    </>
  )
}
