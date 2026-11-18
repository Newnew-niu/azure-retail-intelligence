import { screen, waitFor, within } from '@testing-library/react'
import { http, HttpResponse } from 'msw'
import { describe, expect, it } from 'vitest'

import { DETAIL } from '../test/fixtures'
import { renderApp } from '../test/render'
import { server } from '../test/server'

const PATH = `/sellers/${DETAIL.seller_id}`

describe('Seller detail', () => {
  it('shows the seller, the KPI cards with their basis, and a dash for a missing score', async () => {
    renderApp(PATH)
    expect(await screen.findByRole('heading', { level: 1 })).toHaveTextContent(DETAIL.seller_id)
    expect(screen.getByText(/State RJ · sales orders from May 2018 to Aug 2018/)).toBeInTheDocument()
    const card = (label: string) => {
      const term = screen.getByText(label, { selector: 'dt' })
      const parent = term.parentElement
      if (!parent) throw new Error(`no card for ${label}`)
      return parent
    }
    expect(card('Product sales')).toHaveTextContent('R$2,400.00')
    expect(card('Product sales')).toHaveTextContent('30 items sold')
    expect(card('Late dispatch rate')).toHaveTextContent('12.5%')
    expect(card('Late dispatch rate')).toHaveTextContent('Of 24 dispatched orders')
    expect(card('Review score')).toHaveTextContent('—')
  })

  it('lists signals with words, not only colour, attention first, each with its rule', async () => {
    renderApp(PATH)
    const section = await screen.findByRole('region', { name: 'Health signals' })
    const items = within(section).getAllByRole('listitem')
    expect(items.map((item) => within(item).getByRole('heading').textContent)).toEqual([
      'Late dispatch',
      'Sales trend',
      'Review score',
    ])
    expect(items[0]).toHaveTextContent('Needs attention')
    expect(items[0]).toHaveTextContent('12.5%')
    expect(items[0]).toHaveTextContent('Rule: Share of dispatched orders')
    expect(items[1]).toHaveTextContent('Positive')
    expect(items[1]).toHaveTextContent('+50%')
    expect(items[2]).toHaveTextContent('Not enough data')
    expect(section).toHaveTextContent('not a credit score')
  })

  it('switches the trend measure and keeps an accessible table of the numbers', async () => {
    const { user } = renderApp(PATH)
    const figure = await screen.findByRole('figure', { name: /Monthly trend/ })
    expect(within(figure).getByRole('img', { name: /Product sales by month/ })).toBeInTheDocument()
    const table = within(figure).getByRole('table', { name: 'Product sales by month' })
    expect(within(table).getAllByRole('row')).toHaveLength(5) // header + 4 months
    expect(within(table).getByRole('row', { name: /Jun 2018/ })).toHaveTextContent('R$600.00')

    await user.click(within(figure).getByRole('radio', { name: 'Late dispatch rate' }))
    const rates = within(figure).getByRole('table', { name: 'Late dispatch rate by month' })
    expect(within(rates).getByRole('row', { name: /May 2018/ })).toHaveTextContent('—') // no orders that month
    expect(within(rates).getByRole('row', { name: /Jun 2018/ })).toHaveTextContent('10.0%')
  })

  it('says when a measure has no data in any month', async () => {
    server.use(
      http.get('*/api/sellers/:sellerId', () =>
        HttpResponse.json({ ...DETAIL, monthly: DETAIL.monthly.map((m) => ({ ...m, review_score: null })) }),
      ),
    )
    const { user } = renderApp(PATH)
    const figure = await screen.findByRole('figure', { name: /Monthly trend/ })
    await user.click(within(figure).getByRole('radio', { name: 'Review score' }))
    expect(within(figure).getByText('No month in the window has data for this measure.')).toBeInTheDocument()
    expect(within(figure).queryByRole('img')).not.toBeInTheDocument()
  })

  it('shows "not found" for a seller without sales, without a retry button', async () => {
    renderApp(`/sellers/${'f'.repeat(32)}`)
    const alert = await screen.findByRole('alert')
    expect(alert).toHaveTextContent('Seller not found')
    expect(within(alert).queryByRole('button')).not.toBeInTheDocument()
  })

  it('shows a server error with a retry', async () => {
    let fail = true
    server.use(
      http.get('*/api/sellers/:sellerId', () =>
        fail ? HttpResponse.json({ detail: 'Query cancelled after 10 seconds' }, { status: 504 }) : undefined,
      ),
    )
    const { user } = renderApp(PATH)
    const alert = await screen.findByRole('alert')
    expect(alert).toHaveTextContent('The seller could not be loaded')
    expect(alert).toHaveTextContent('Query cancelled after 10 seconds')
    fail = false
    await user.click(within(alert).getByRole('button', { name: 'Try again' }))
    await waitFor(() => {
      expect(screen.getByRole('heading', { level: 1 })).toHaveTextContent(DETAIL.seller_id)
    })
  })

  it('links back to the full list when opened directly', async () => {
    renderApp(PATH)
    expect(await screen.findByRole('link', { name: /Back to sellers/ })).toHaveAttribute('href', '/')
  })
})

describe('Other pages', () => {
  it('explains the definitions on the about page', async () => {
    renderApp('/about')
    const heading = await screen.findByRole('heading', { name: 'How the numbers are calculated' })
    expect(heading.closest('article')).toHaveTextContent('not a credit score')
  })

  it('shows a not-found page for an unknown path', async () => {
    renderApp('/nowhere')
    expect(await screen.findByText('This page does not exist.')).toBeInTheDocument()
  })
})
