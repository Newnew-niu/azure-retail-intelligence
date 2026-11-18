// The seller list's state lives in the URL, so every view can be bookmarked and shared.
// Parsing is forgiving: a hand-edited or outdated link falls back to defaults instead of failing.
import type { SellerListQuery, SortKey, SortOrder } from '../api/types'
import { isStateCode } from './states'

export const PAGE_SIZE = 25

export interface SellerListParams {
  q: string
  state: string
  sort: SortKey
  order: SortOrder
  page: number
}

export const SORT_KEYS: readonly SortKey[] = ['product_sales', 'orders', 'late_rate', 'review_score']

export const DEFAULT_LIST_PARAMS: SellerListParams = {
  q: '',
  state: '',
  sort: 'product_sales',
  order: 'desc',
  page: 1,
}

const SELLER_PREFIX = /^[0-9a-f]{1,32}$/

function isSortKey(value: string | null): value is SortKey {
  return SORT_KEYS.some((key) => key === value)
}

export function parseListParams(search: URLSearchParams): SellerListParams {
  const q = (search.get('q') ?? '').trim().toLowerCase()
  const state = (search.get('state') ?? '').toUpperCase()
  const sort = search.get('sort')
  const order = search.get('order')
  const page = Number(search.get('page'))
  return {
    q: SELLER_PREFIX.test(q) ? q : '',
    state: isStateCode(state) ? state : '',
    sort: isSortKey(sort) ? sort : DEFAULT_LIST_PARAMS.sort,
    order: order === 'asc' || order === 'desc' ? order : DEFAULT_LIST_PARAMS.order,
    page: Number.isInteger(page) && page >= 1 ? page : 1,
  }
}

/** Only values that differ from the defaults, so URLs stay short. */
export function toSearchParams(params: SellerListParams): URLSearchParams {
  const search = new URLSearchParams()
  if (params.q) search.set('q', params.q)
  if (params.state) search.set('state', params.state)
  if (params.sort !== DEFAULT_LIST_PARAMS.sort) search.set('sort', params.sort)
  if (params.order !== DEFAULT_LIST_PARAMS.order) search.set('order', params.order)
  if (params.page !== 1) search.set('page', String(params.page))
  return search
}

export function toApiQuery(params: SellerListParams): SellerListQuery {
  return {
    page: params.page,
    page_size: PAGE_SIZE,
    sort: params.sort,
    order: params.order,
    ...(params.q ? { q: params.q } : {}),
    ...(params.state ? { state: params.state } : {}),
  }
}

/** Checks what the analyst typed in the search box. Returns the prefix, or an error to show. */
export function validateSellerPrefix(input: string): { prefix: string; error?: string } {
  const prefix = input.trim().toLowerCase()
  if (prefix === '' || SELLER_PREFIX.test(prefix)) return { prefix }
  return { prefix, error: 'Seller IDs contain only the digits 0-9 and the letters a-f, up to 32 characters.' }
}

/** Clicking the active column flips the direction; a new column starts with the largest values. */
export function nextSort(current: SellerListParams, sort: SortKey): Pick<SellerListParams, 'sort' | 'order'> {
  if (current.sort === sort) return { sort, order: current.order === 'desc' ? 'asc' : 'desc' }
  return { sort, order: 'desc' }
}
