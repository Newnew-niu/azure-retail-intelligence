// Test data shaped by the generated API types, so a contract change breaks the tests at compile time.
import type { HealthSignal, SellerDetail, SellerListItem, SellerMonth } from '../api/types'

/** 30 sellers with ids that sort predictably: 00…, 01…, … 29…, padded to 32 hex characters. */
export const SELLERS: SellerListItem[] = Array.from({ length: 30 }, (_, i) => {
  const n = i + 1
  return {
    seller_id: `${String(i).padStart(2, '0')}${'a'.repeat(30)}`,
    seller_state: i % 3 === 0 ? 'RJ' : 'SP',
    orders: n * 2,
    items_sold: n * 3,
    product_sales: n * 1000,
    average_order_value: 500 + n,
    late_rate: i === 29 ? null : (i % 10) / 100,
    review_score: i === 28 ? null : 3 + (i % 20) / 10,
  }
})

function month(yearMonth: string, orders: number): SellerMonth {
  return {
    year_month: yearMonth,
    orders,
    items_sold: orders,
    product_sales: orders * 100,
    average_order_value: orders ? 110 : null,
    late_rate: orders ? 0.1 : null,
    review_score: orders ? 4.5 : null,
    dispatched_orders: orders,
    reviewed_orders: orders,
  }
}

const SIGNALS: HealthSignal[] = [
  {
    key: 'sales_trend',
    label: 'Sales trend',
    status: 'positive',
    value: 0.5,
    summary: 'Product sales from 2018-06 to 2018-08 were 50% higher than from 2018-03 to 2018-05.',
    rule: 'Product sales in the last 3 months compared with the 3 months before.',
  },
  {
    key: 'late_dispatch',
    label: 'Late dispatch',
    status: 'attention',
    value: 0.125,
    summary: '3 of 24 dispatched orders (12.5%) from 2018-03 to 2018-08 were handed to the carrier late.',
    rule: 'Share of dispatched orders handed to the carrier after the shipping deadline.',
  },
  {
    key: 'review_score',
    label: 'Review score',
    status: 'insufficient_data',
    value: null,
    summary: 'Only 2 reviewed orders from 2018-03 to 2018-08, fewer than 5.',
    rule: 'Mean review score of orders with a review.',
  },
]

export const DETAIL: SellerDetail = {
  seller_id: SELLERS[0]?.seller_id ?? '',
  seller_state: 'RJ',
  window: { first_month: '2018-05', last_month: '2018-08' },
  summary: {
    orders: 24,
    items_sold: 30,
    product_sales: 2400,
    average_order_value: 110,
    late_rate: 0.125,
    review_score: null,
    dispatched_orders: 24,
    reviewed_orders: 0,
  },
  monthly: [month('2018-05', 0), month('2018-06', 6), month('2018-07', 8), month('2018-08', 10)],
  signals: SIGNALS,
  disclaimer: 'Illustrative rules for exploring seller performance. They are not a credit score.',
}
