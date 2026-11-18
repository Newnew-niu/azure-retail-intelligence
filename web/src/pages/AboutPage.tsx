// How the numbers are calculated, in plain words. Mirrors serving/core/sellers.py and
// serving/core/health_signals.py; the API also returns each signal's rule with the result.
import { Link } from 'react-router'

export function AboutPage() {
  return (
    <article className="prose">
      <p>
        <Link to="/">← Back to sellers</Link>
      </p>
      <h1>How the numbers are calculated</h1>
      <p>
        All figures use sales orders (status not canceled or unavailable) purchased from 1 January 2017 to 31
        August 2018. An order with items from two sellers counts once for each seller.
      </p>
      <dl className="definitions">
        <dt>Orders</dt>
        <dd>Sales orders that include the seller’s items.</dd>
        <dt>Product sales</dt>
        <dd>Sum of the seller’s item prices in BRL, excluding freight.</dd>
        <dt>Average order value</dt>
        <dd>The seller’s item prices plus freight, per order.</dd>
        <dt>Late dispatch rate</dt>
        <dd>
          Orders handed to the carrier after the seller’s shipping deadline, divided by orders handed to the
          carrier. Dates are compared, not times. This measures the seller, not the delivery company.
        </dd>
        <dt>Review score</dt>
        <dd>Mean customer review score (1 to 5) of the seller’s orders that have a review.</dd>
      </dl>
      <h2>Health signals</h2>
      <p>
        Three fixed rules over the last six months of the window, March to August 2018. Each signal shows the rule
        and the numbers behind its result. With too few orders, a signal says so instead of giving a verdict.
      </p>
      <ul>
        <li>Sales trend: positive at +10% or more, needs attention at −20% or less, compared with the three months before.</li>
        <li>Late dispatch: positive at 5% or less, needs attention above 10%.</li>
        <li>Review score: positive at 4.0 or more, needs attention below 3.5.</li>
      </ul>
      <p className="notice">
        <strong>Illustrative only.</strong> These rules help explore seller performance. They are not a credit
        score and must not be used to make lending decisions.
      </p>
    </article>
  )
}
