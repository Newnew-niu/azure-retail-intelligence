import { Link } from 'react-router'

import { EmptyState } from '../components/StatusMessage'

export function NotFoundPage() {
  return (
    <EmptyState title="This page does not exist.">
      <Link to="/">Go to the seller list</Link>
    </EmptyState>
  )
}
