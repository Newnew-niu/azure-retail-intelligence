import { formatCount } from '../lib/format'

interface PaginationProps {
  page: number
  pageSize: number
  total: number
  totalPages: number
  onPage: (page: number) => void
}

export function Pagination({ page, pageSize, total, totalPages, onPage }: PaginationProps) {
  const first = (page - 1) * pageSize + 1
  const last = Math.min(page * pageSize, total)
  return (
    <nav className="pagination" aria-label="Pagination">
      <p aria-live="polite">
        {total === 0 || first > total
          ? `${formatCount(total)} sellers`
          : `Showing ${formatCount(first)}–${formatCount(last)} of ${formatCount(total)} sellers`}
      </p>
      <div className="pagination-buttons">
        <button
          type="button"
          className="button button-secondary"
          onClick={() => {
            onPage(page - 1)
          }}
          disabled={page <= 1}
        >
          Previous
        </button>
        <span>
          Page {formatCount(page)} of {formatCount(Math.max(totalPages, 1))}
        </span>
        <button
          type="button"
          className="button button-secondary"
          onClick={() => {
            onPage(page + 1)
          }}
          disabled={page >= totalPages}
        >
          Next
        </button>
      </div>
    </nav>
  )
}
