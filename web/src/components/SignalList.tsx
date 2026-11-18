// Health signals: each shows its status in words and a symbol (not colour alone), the value, the
// result in a sentence and the rule behind it.
import type { HealthSignal } from '../api/types'
import { STATUS_DISPLAY, signalValue, sortSignals } from '../lib/signals'

export function SignalList({ signals, disclaimer }: { signals: readonly HealthSignal[]; disclaimer: string }) {
  return (
    <section className="panel" aria-labelledby="signals-heading">
      <h2 id="signals-heading">Health signals</h2>
      <p className="notice">
        <strong>Note:</strong> {disclaimer}
      </p>
      <ul className="signal-list">
        {sortSignals(signals).map((signal) => {
          const status = STATUS_DISPLAY[signal.status]
          return (
            <li key={signal.key} className={`signal signal-${signal.status}`}>
              <div className="signal-head">
                <h3>{signal.label}</h3>
                <span className="badge">
                  <span aria-hidden="true">{status.symbol}</span> {status.label}
                </span>
              </div>
              <p className="signal-value">{signalValue(signal)}</p>
              <p>{signal.summary}</p>
              <p className="muted">
                <span className="rule-label">Rule:</span> {signal.rule}
              </p>
            </li>
          )
        })}
      </ul>
    </section>
  )
}
