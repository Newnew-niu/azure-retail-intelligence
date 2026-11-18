"""The health signal rules, on hand-made months: thresholds, boundaries and too little data."""
import pytest

from serving.core.health_signals import (LATE_MIN_DISPATCHED, REVIEW_MIN_REVIEWED, TREND_MIN_ORDERS,
                                         health_signals, late_dispatch, review_score, sales_trend)

MONTHS = ["2018-03", "2018-04", "2018-05", "2018-06", "2018-07", "2018-08"]


def months(prior_sales=100.0, recent_sales=100.0, orders=5, dispatched=5, late=0, reviewed=5, review=4.0):
    """Six months; sales are split evenly over each half; the counts apply to every month."""
    return [{"year_month": ym, "orders": orders,
             "product_sales": (prior_sales if i < 3 else recent_sales) / 3,
             "dispatched_orders": dispatched, "late_orders": late,
             "reviewed_orders": reviewed, "review_total": review * reviewed}
            for i, ym in enumerate(MONTHS)]


@pytest.mark.parametrize("recent, status", [
    (110.0, "positive"),   # exactly +10 %
    (150.0, "positive"),
    (109.0, "neutral"),
    (81.0, "neutral"),
    (80.0, "attention"),   # exactly -20 %
    (10.0, "attention"),
])
def test_sales_trend_thresholds(recent, status):
    signal = sales_trend(months(prior_sales=300.0, recent_sales=recent * 3))
    assert signal["status"] == status
    assert signal["value"] == pytest.approx(recent / 100 - 1)


def test_sales_trend_explains_itself():
    signal = sales_trend(months(prior_sales=300.0, recent_sales=450.0))
    assert signal["summary"] == ("Product sales from 2018-06 to 2018-08 were 50% higher "
                                 "than from 2018-03 to 2018-05.")
    assert "+10%" in signal["rule"] and "-20%" in signal["rule"]


def test_sales_trend_needs_enough_orders():
    few = months(orders=0)
    few[0]["orders"] = TREND_MIN_ORDERS - 1
    signal = sales_trend(few)
    assert (signal["status"], signal["value"]) == ("insufficient_data", None)


def test_sales_trend_without_earlier_sales_is_not_a_division_by_zero():
    assert sales_trend(months(prior_sales=0.0, recent_sales=300.0))["status"] == "insufficient_data"


@pytest.mark.parametrize("late, status", [(0, "positive"), (1, "positive"), (2, "neutral"),
                                          (3, "attention"), (4, "attention")])
def test_late_dispatch_thresholds(late, status):
    # 20 dispatched orders a month = 120; late per month * 6 / 120: 0 %, 5 %, 10 %, 15 %, 20 %
    signal = late_dispatch(months(dispatched=20, late=late))
    assert signal["status"] == status
    assert signal["value"] == pytest.approx(late * 6 / 120)


def test_late_dispatch_needs_enough_dispatched_orders():
    few = months(dispatched=0)
    few[-1]["dispatched_orders"] = LATE_MIN_DISPATCHED - 1
    assert late_dispatch(few)["status"] == "insufficient_data"


@pytest.mark.parametrize("score, status", [(4.0, "positive"), (3.99, "neutral"), (3.5, "neutral"),
                                           (3.49, "attention")])
def test_review_score_thresholds(score, status):
    signal = review_score(months(review=score))
    assert signal["status"] == status
    assert signal["value"] == pytest.approx(score)


def test_review_score_needs_enough_reviews():
    few = months(reviewed=0)
    few[0]["reviewed_orders"], few[0]["review_total"] = REVIEW_MIN_REVIEWED - 1, 20
    assert review_score(few)["status"] == "insufficient_data"


def test_signals_use_only_the_last_six_months():
    older = [{"year_month": "2017-12", "orders": 1000, "product_sales": 1e9, "dispatched_orders": 1000,
              "late_orders": 1000, "reviewed_orders": 1000, "review_total": 1000}]
    signals = health_signals(older + months(dispatched=20))
    assert [s["key"] for s in signals] == ["sales_trend", "late_dispatch", "review_score"]
    assert [s["status"] for s in signals] == ["neutral", "positive", "positive"]


def test_fewer_than_six_months_is_a_programming_error():
    with pytest.raises(ValueError):
        health_signals(months()[:5])
