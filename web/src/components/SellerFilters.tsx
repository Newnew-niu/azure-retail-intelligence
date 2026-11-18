// Search by seller ID prefix and filter by state. The search is submitted (Enter or the button),
// not sent on every keystroke, so typing does not fire a request per character.
import { useId, useState, type SubmitEvent } from 'react'

import { validateSellerPrefix, type SellerListParams } from '../lib/listParams'
import { BRAZILIAN_STATES } from '../lib/states'

interface SellerFiltersProps {
  params: SellerListParams
  onChange: (change: Partial<Pick<SellerListParams, 'q' | 'state'>>) => void
}

export function SellerFilters({ params, onChange }: SellerFiltersProps) {
  // Keyed by the URL value in the parent, so a new URL (back button, shared link) resets the box.
  const [draft, setDraft] = useState(params.q)
  const [error, setError] = useState<string>()
  const searchId = useId()
  const errorId = useId()
  const stateId = useId()

  function submit(event: SubmitEvent<HTMLFormElement>) {
    event.preventDefault()
    const result = validateSellerPrefix(draft)
    setError(result.error)
    if (!result.error) onChange({ q: result.prefix })
  }

  function clear() {
    setDraft('')
    setError(undefined)
    onChange({ q: '', state: '' })
  }

  return (
    <form className="filters" role="search" aria-label="Filter sellers" onSubmit={submit}>
      <div className="field">
        <label htmlFor={searchId}>Seller ID starts with</label>
        <div className="field-row">
          <input
            id={searchId}
            type="search"
            value={draft}
            onChange={(event) => {
              setDraft(event.target.value)
            }}
            placeholder="for example 4869f7a5"
            autoComplete="off"
            spellCheck={false}
            aria-invalid={error ? true : undefined}
            aria-describedby={error ? errorId : undefined}
          />
          <button type="submit" className="button">
            Search
          </button>
        </div>
        {error && (
          <p id={errorId} className="field-error">
            {error}
          </p>
        )}
      </div>
      <div className="field">
        <label htmlFor={stateId}>Seller state</label>
        <select
          id={stateId}
          value={params.state}
          onChange={(event) => {
            onChange({ state: event.target.value })
          }}
        >
          <option value="">All states</option>
          {BRAZILIAN_STATES.map((state) => (
            <option key={state.code} value={state.code}>
              {state.code} – {state.name}
            </option>
          ))}
        </select>
      </div>
      {(params.q !== '' || params.state !== '') && (
        <button type="button" className="button button-secondary" onClick={clear}>
          Clear filters
        </button>
      )}
    </form>
  )
}
