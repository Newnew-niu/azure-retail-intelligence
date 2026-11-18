import { describe, expect, it } from 'vitest'

import {
  DEFAULT_LIST_PARAMS,
  nextSort,
  PAGE_SIZE,
  parseListParams,
  toApiQuery,
  toSearchParams,
  validateSellerPrefix,
} from './listParams'

const parse = (query: string) => parseListParams(new URLSearchParams(query))

describe('parseListParams', () => {
  it('uses the defaults for an empty URL', () => {
    expect(parse('')).toEqual(DEFAULT_LIST_PARAMS)
  })

  it('reads every parameter', () => {
    expect(parse('q=4869f7&state=RJ&sort=late_rate&order=asc&page=3')).toEqual({
      q: '4869f7',
      state: 'RJ',
      sort: 'late_rate',
      order: 'asc',
      page: 3,
    })
  })

  it('normalises case', () => {
    expect(parse('q=ABC&state=rj')).toMatchObject({ q: 'abc', state: 'RJ' })
  })

  it.each([
    ['q=xyz', { q: '' }],
    ['q=a%25', { q: '' }],
    ['state=XX', { state: '' }],
    ['sort=seller_id', { sort: 'product_sales' }],
    ['order=up', { order: 'desc' }],
    ['page=0', { page: 1 }],
    ['page=-2', { page: 1 }],
    ['page=1.5', { page: 1 }],
    ['page=abc', { page: 1 }],
  ])('falls back to a default for a bad value: %s', (query, expected) => {
    expect(parse(query)).toMatchObject(expected)
  })
})

describe('toSearchParams', () => {
  it('leaves defaults out of the URL', () => {
    expect(toSearchParams(DEFAULT_LIST_PARAMS).toString()).toBe('')
  })

  it('round-trips through the URL', () => {
    const params = { q: 'ab', state: 'SP', sort: 'orders' as const, order: 'asc' as const, page: 4 }
    expect(parseListParams(toSearchParams(params))).toEqual(params)
  })
})

describe('toApiQuery', () => {
  it('always sends the page size and omits empty filters', () => {
    expect(toApiQuery(DEFAULT_LIST_PARAMS)).toEqual({ page: 1, page_size: PAGE_SIZE, sort: 'product_sales', order: 'desc' })
  })

  it('sends filters that are set', () => {
    expect(toApiQuery({ ...DEFAULT_LIST_PARAMS, q: 'ab', state: 'MG' })).toMatchObject({ q: 'ab', state: 'MG' })
  })
})

describe('validateSellerPrefix', () => {
  it('accepts hex prefixes, ignoring case and spaces', () => {
    expect(validateSellerPrefix('  4869F7 ')).toEqual({ prefix: '4869f7' })
    expect(validateSellerPrefix('')).toEqual({ prefix: '' })
  })

  it.each(['xyz', 'ab cd', '%', 'a'.repeat(33)])('rejects %s with an explanation', (input) => {
    expect(validateSellerPrefix(input).error).toMatch(/0-9 and the letters a-f/)
  })
})

describe('nextSort', () => {
  it('flips the direction of the active column', () => {
    expect(nextSort(DEFAULT_LIST_PARAMS, 'product_sales')).toEqual({ sort: 'product_sales', order: 'asc' })
  })

  it('starts a new column with the largest values', () => {
    expect(nextSort({ ...DEFAULT_LIST_PARAMS, order: 'asc' }, 'orders')).toEqual({ sort: 'orders', order: 'desc' })
  })
})
