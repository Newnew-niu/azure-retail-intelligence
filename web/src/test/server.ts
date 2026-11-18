// A fake seller API for tests (MSW). The list handler really filters, sorts and pages the
// fixture sellers, so the tests check what the page asks for and what it shows.
import { http, HttpResponse } from 'msw'
import { setupServer } from 'msw/node'

import type { SellerListItem, SellerPage, SortKey } from '../api/types'
import { DETAIL, SELLERS } from './fixtures'

export const requests: URL[] = []

function compare(a: SellerListItem, b: SellerListItem, sort: SortKey, order: string): number {
  const x = a[sort]
  const y = b[sort]
  if (x === null || y === null) return x === y ? 0 : x === null ? 1 : -1 // empty values last
  return (order === 'asc' ? x - y : y - x) || a.seller_id.localeCompare(b.seller_id)
}

export const handlers = [
  http.get('*/api/sellers', ({ request }) => {
    const url = new URL(request.url)
    requests.push(url)
    const page = Number(url.searchParams.get('page') ?? '1')
    const pageSize = Number(url.searchParams.get('page_size') ?? '25')
    const sort = (url.searchParams.get('sort') ?? 'product_sales') as SortKey
    const order = url.searchParams.get('order') ?? 'desc'
    const state = url.searchParams.get('state')
    const q = url.searchParams.get('q')
    const matches = SELLERS.filter((s) => (!state || s.seller_state === state) && (!q || s.seller_id.startsWith(q)))
      .sort((a, b) => compare(a, b, sort, order))
    const body: SellerPage = {
      items: matches.slice((page - 1) * pageSize, page * pageSize),
      page,
      page_size: pageSize,
      total: matches.length,
      total_pages: Math.ceil(matches.length / pageSize),
      sort,
      order,
    }
    return HttpResponse.json(body)
  }),
  http.get('*/api/sellers/:sellerId', ({ params }) => {
    if (params.sellerId === DETAIL.seller_id) return HttpResponse.json(DETAIL)
    return HttpResponse.json({ detail: 'Seller has no sales orders in the reporting window' }, { status: 404 })
  }),
]

export const server = setupServer(...handlers)
