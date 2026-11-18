import { screen, waitFor, within } from '@testing-library/react'
import { delay, http, HttpResponse } from 'msw'
import { describe, expect, it } from 'vitest'

import { SELLERS } from '../test/fixtures'
import { currentUrl, renderApp } from '../test/render'
import { requests, server } from '../test/server'

/** Seller ids shown in the table, as the 8-character prefixes on screen. */
function shownIds(): string[] {
  const table = screen.getByRole('table')
  return within(table)
    .getAllByRole('link')
    .map((link) => link.textContent)
}

const short = (index: number) => SELLERS[index]?.seller_id.slice(0, 8)

describe('Seller list', () => {
  it('shows a loading state, then the first page sorted by product sales', async () => {
    renderApp('/')
    expect(screen.getByRole('status')).toHaveTextContent('Loading sellers')
    expect(await screen.findByRole('table')).toBeInTheDocument()
    expect(shownIds()).toHaveLength(25)
    expect(shownIds()[0]).toBe(short(29)) // the highest product sales
    expect(screen.getByText('Showing 1–25 of 30 sellers')).toBeInTheDocument()
  })

  it('formats values and shows missing ones as a dash', async () => {
    renderApp('/?sort=product_sales&order=desc')
    await screen.findByRole('table')
    const firstRow = screen.getAllByRole('row')[1]
    if (!firstRow) throw new Error('no rows')
    expect(within(firstRow).getByText('R$30,000.00')).toBeInTheDocument()
    expect(within(firstRow).getByText('—')).toBeInTheDocument() // seller 29 has no late rate
  })

  it('reads its state from the URL, so a shared link opens the same view', async () => {
    renderApp('/?state=RJ&sort=orders&order=asc&page=1')
    await screen.findByRole('table')
    expect(requests.at(-1)?.searchParams.get('state')).toBe('RJ')
    expect(shownIds()).toEqual([0, 3, 6, 9, 12, 15, 18, 21, 24, 27].map(short))
    expect(screen.getByRole('combobox', { name: 'Seller state' })).toHaveValue('RJ')
    expect(screen.getByRole('columnheader', { name: /Orders/ })).toHaveAttribute('aria-sort', 'ascending')
  })

  it('filters by state and goes back to page 1', async () => {
    const { router, user } = renderApp('/?page=2')
    await screen.findByRole('table')
    await user.selectOptions(screen.getByRole('combobox', { name: 'Seller state' }), 'RJ')
    await waitFor(() => {
      expect(currentUrl(router)).toBe('/?state=RJ')
    })
    await waitFor(() => {
      expect(shownIds()).toHaveLength(10)
    })
  })

  it('searches by seller id prefix on submit', async () => {
    const { router, user } = renderApp('/')
    await screen.findByRole('table')
    await user.type(screen.getByRole('searchbox', { name: 'Seller ID starts with' }), '1{Enter}')
    await waitFor(() => {
      expect(currentUrl(router)).toBe('/?q=1')
    })
    await waitFor(() => {
      expect(shownIds()).toHaveLength(10)
    })
    expect(requests.at(-1)?.searchParams.get('q')).toBe('1')
  })

  it('explains an invalid search instead of sending it', async () => {
    const { router, user } = renderApp('/')
    await screen.findByRole('table')
    const before = requests.length
    const box = screen.getByRole('searchbox', { name: 'Seller ID starts with' })
    await user.type(box, 'xyz')
    await user.click(screen.getByRole('button', { name: 'Search' }))
    expect(box).toHaveAttribute('aria-invalid', 'true')
    expect(box).toHaveAccessibleDescription(/0-9 and the letters a-f/)
    expect(currentUrl(router)).toBe('/')
    expect(requests.length).toBe(before)
  })

  it('sorts by a column header, then reverses it', async () => {
    const { router, user } = renderApp('/')
    await screen.findByRole('table')
    await user.click(screen.getByRole('button', { name: /Review score/ }))
    await waitFor(() => {
      expect(currentUrl(router)).toBe('/?sort=review_score')
    })
    await user.click(screen.getByRole('button', { name: /Review score/ }))
    await waitFor(() => {
      expect(currentUrl(router)).toBe('/?sort=review_score&order=asc')
    })
    await waitFor(() => {
      expect(screen.getByRole('columnheader', { name: /Review score/ })).toHaveAttribute('aria-sort', 'ascending')
    })
    expect(shownIds().at(-1)).not.toBe(short(28)) // 28 has no score: last overall, so on page 2
  })

  it('pages forward and back, and disables buttons at the ends', async () => {
    const { router, user } = renderApp('/')
    await screen.findByRole('table')
    expect(screen.getByRole('button', { name: 'Previous' })).toBeDisabled()
    await user.click(screen.getByRole('button', { name: 'Next' }))
    await waitFor(() => {
      expect(screen.getByText('Showing 26–30 of 30 sellers')).toBeInTheDocument()
    })
    expect(currentUrl(router)).toBe('/?page=2')
    expect(screen.getByRole('button', { name: 'Next' })).toBeDisabled()
    await user.click(screen.getByRole('button', { name: 'Previous' }))
    await waitFor(() => {
      expect(currentUrl(router)).toBe('/')
    })
  })

  it('shows an empty state when nothing matches, with a way to clear filters', async () => {
    const { router, user } = renderApp('/?state=AC')
    expect(await screen.findByText('No sellers match these filters.')).toBeInTheDocument()
    expect(screen.queryByRole('table')).not.toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Clear filters' }))
    await waitFor(() => {
      expect(currentUrl(router)).toBe('/')
    })
    expect(await screen.findByRole('table')).toBeInTheDocument()
  })

  it('handles a link to a page past the end', async () => {
    const { router, user } = renderApp('/?page=9')
    expect(await screen.findByText('Page 9 is past the last page.')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Go to the first page' }))
    await waitFor(() => {
      expect(currentUrl(router)).toBe('/')
    })
  })

  it('shows an error with a retry that works', async () => {
    let fail = true
    server.use(
      http.get('*/api/sellers', async () => {
        await delay(10)
        if (fail) return HttpResponse.json({ detail: 'Database unavailable' }, { status: 503 })
        return undefined // fall through to the normal handler
      }),
    )
    const { user } = renderApp('/')
    const alert = await screen.findByRole('alert')
    expect(alert).toHaveTextContent('Sellers could not be loaded')
    expect(alert).toHaveTextContent('Database unavailable')
    fail = false
    await user.click(within(alert).getByRole('button', { name: 'Try again' }))
    expect(await screen.findByRole('table')).toBeInTheDocument()
  })

  it('opens a seller and the back link returns to the same list view', async () => {
    const { router, user } = renderApp('/?state=RJ&sort=orders&order=asc')
    await screen.findByRole('table')
    await user.click(screen.getByRole('link', { name: `Seller ${SELLERS[0]?.seller_id ?? ''}` }))
    await user.click(await screen.findByRole('link', { name: /Back to sellers/ }))
    await waitFor(() => {
      expect(currentUrl(router)).toBe('/?state=RJ&sort=orders&order=asc')
    })
  })
})
