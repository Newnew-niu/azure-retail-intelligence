"""Seller health signals: three fixed, readable rules over a seller's last six months.

They are illustrative, not a credit score. Each signal returns its value, the rule and a
sentence explaining the result, so a reader can check it by hand. Pure functions: no database.
The thresholds and why they were chosen are in docs/seller_health_decisions.md.
"""
from __future__ import annotations

from decimal import Decimal
from typing import Iterable

SIGNAL_MONTHS = 6  # the last six months of the reporting window: two halves of three months

TREND_POSITIVE_CHANGE = 0.10
TREND_ATTENTION_CHANGE = -0.20
TREND_MIN_ORDERS = 10

LATE_POSITIVE_MAX = 0.05
LATE_ATTENTION_ABOVE = 0.10
LATE_MIN_DISPATCHED = 10

REVIEW_POSITIVE_MIN = 4.0
REVIEW_ATTENTION_BELOW = 3.5
REVIEW_MIN_REVIEWED = 5

DISCLAIMER = ("Illustrative rules for exploring seller performance. "
              "They are not a credit score and must not be used to make lending decisions.")


def _total(months: Iterable[dict], field: str) -> Decimal:
    return sum((Decimal(str(m[field] or 0)) for m in months), Decimal(0))


def _period(months: list[dict]) -> str:
    return f"{months[0]['year_month']} to {months[-1]['year_month']}"


def _signal(key: str, label: str, status: str, value: float | None, summary: str, rule: str) -> dict:
    return {"key": key, "label": label, "status": status, "value": value, "summary": summary, "rule": rule}


def sales_trend(months: list[dict]) -> dict:
    prior, recent = months[:3], months[3:]
    rule = (f"Product sales in the last 3 months compared with the 3 months before. Positive at "
            f"{TREND_POSITIVE_CHANGE:+.0%} or more, attention at {TREND_ATTENTION_CHANGE:+.0%} or less. "
            f"Needs at least {TREND_MIN_ORDERS} orders in the 6 months.")
    orders = _total(months, "orders")
    before, after = _total(prior, "product_sales"), _total(recent, "product_sales")
    if orders < TREND_MIN_ORDERS:
        return _signal("sales_trend", "Sales trend", "insufficient_data", None,
                       f"Only {orders} orders from {_period(months)}, fewer than {TREND_MIN_ORDERS}.", rule)
    if before == 0:
        return _signal("sales_trend", "Sales trend", "insufficient_data", None,
                       f"No sales from {_period(prior)}, so there is nothing to compare with.", rule)
    change = float(after / before - 1)
    status = ("positive" if change >= TREND_POSITIVE_CHANGE
              else "attention" if change <= TREND_ATTENTION_CHANGE else "neutral")
    direction = "higher" if change >= 0 else "lower"
    return _signal("sales_trend", "Sales trend", status, change,
                   f"Product sales from {_period(recent)} were {abs(change):.0%} {direction} "
                   f"than from {_period(prior)}.", rule)


def late_dispatch(months: list[dict]) -> dict:
    rule = (f"Share of dispatched orders handed to the carrier after the seller's shipping deadline. "
            f"Positive at {LATE_POSITIVE_MAX:.0%} or less, attention above {LATE_ATTENTION_ABOVE:.0%}. "
            f"Needs at least {LATE_MIN_DISPATCHED} dispatched orders in the 6 months.")
    dispatched, late = _total(months, "dispatched_orders"), _total(months, "late_orders")
    if dispatched < LATE_MIN_DISPATCHED:
        return _signal("late_dispatch", "Late dispatch", "insufficient_data", None,
                       f"Only {dispatched} dispatched orders from {_period(months)}, "
                       f"fewer than {LATE_MIN_DISPATCHED}.", rule)
    rate = float(late / dispatched)
    status = ("positive" if rate <= LATE_POSITIVE_MAX
              else "attention" if rate > LATE_ATTENTION_ABOVE else "neutral")
    return _signal("late_dispatch", "Late dispatch", status, rate,
                   f"{late} of {dispatched} dispatched orders ({rate:.1%}) from {_period(months)} "
                   f"were handed to the carrier late.", rule)


def review_score(months: list[dict]) -> dict:
    rule = (f"Mean review score of orders with a review. Positive at {REVIEW_POSITIVE_MIN:.1f} or more, "
            f"attention below {REVIEW_ATTENTION_BELOW:.1f}. "
            f"Needs at least {REVIEW_MIN_REVIEWED} reviewed orders in the 6 months.")
    reviewed, total = _total(months, "reviewed_orders"), _total(months, "review_total")
    if reviewed < REVIEW_MIN_REVIEWED:
        return _signal("review_score", "Review score", "insufficient_data", None,
                       f"Only {reviewed} reviewed orders from {_period(months)}, "
                       f"fewer than {REVIEW_MIN_REVIEWED}.", rule)
    score = float(total / reviewed)
    status = ("positive" if score >= REVIEW_POSITIVE_MIN
              else "attention" if score < REVIEW_ATTENTION_BELOW else "neutral")
    return _signal("review_score", "Review score", status, score,
                   f"Mean score {score:.2f} out of 5 over {reviewed} reviewed orders from {_period(months)}.",
                   rule)


def health_signals(monthly: list[dict]) -> list[dict]:
    """`monthly` covers the whole reporting window in order, one dict per month, months
    without orders included with zeros."""
    months = monthly[-SIGNAL_MONTHS:]
    if len(months) < SIGNAL_MONTHS:
        raise ValueError(f"Expected at least {SIGNAL_MONTHS} months, got {len(months)}")
    return [sales_trend(months), late_dispatch(months), review_score(months)]
