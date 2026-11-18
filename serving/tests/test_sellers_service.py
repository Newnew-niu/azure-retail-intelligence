"""SellerService on the synthetic seller database (serving/tests/seller_data.py)."""
import json

import pytest

from serving.core.audit import AuditLog
from serving.core.backends import DuckDBBackend
from serving.core.catalog import Catalog
from serving.core.errors import SellerNotFound
from serving.core.sellers import SellerService, window_months
from serving.tests.seller_data import A, A2, B, C, D


@pytest.fixture
def sellers(seller_settings) -> SellerService:
    window = Catalog.load(seller_settings.catalog_path).content["reporting_window"]
    return SellerService(DuckDBBackend(seller_settings.duckdb_path), AuditLog(seller_settings.audit_path),
                         window, seller_settings.query_timeout_seconds)


def ids(page: dict) -> list[str]:
    return [item["seller_id"] for item in page["items"]]


def test_window_months_cover_every_month_across_a_year_end():
    assert window_months(20171101, 20180228) == ["2017-11", "2017-12", "2018-01", "2018-02"]
    assert len(window_months(20170101, 20180831)) == 20


def test_list_kpis_are_worked_out_by_hand(sellers):
    page = sellers.list_sellers()
    assert ids(page) == [A, C, B, A2]  # product sales, highest first; D has no sales in the window
    a = page["items"][0]
    # 12 orders in 2018 + 1 two-item order in 2017; the canceled order and the 2016 order are excluded
    assert (a["orders"], a["items_sold"], a["product_sales"]) == (13, 14, 1600.0)
    assert a["average_order_value"] == pytest.approx(1730 / 13)
    assert a["late_rate"] == pytest.approx(1 / 13)
    assert a["review_score"] == pytest.approx(56 / 12)
    assert a["seller_state"] == "SP"


def test_an_order_shared_by_two_sellers_counts_once_for_each(sellers):
    by_id = {item["seller_id"]: item for item in sellers.list_sellers()["items"]}
    assert (by_id[A2]["orders"], by_id[A2]["product_sales"], by_id[A2]["average_order_value"]) == (1, 20.0, 22.0)
    assert (by_id[B]["orders"], by_id[B]["product_sales"], by_id[B]["average_order_value"]) == (2, 100.0, 55.0)
    assert by_id[B]["review_score"] == pytest.approx(2.5)


def test_missing_denominators_are_none_not_zero(sellers):
    by_id = {item["seller_id"]: item for item in sellers.list_sellers()["items"]}
    assert by_id[A2]["late_rate"] is None   # nothing dispatched yet
    assert by_id[C]["review_score"] is None  # no review
    assert by_id[C]["late_rate"] == 0.0


def test_unavailable_orders_are_not_sales(sellers):
    c = next(item for item in sellers.list_sellers()["items"] if item["seller_id"] == C)
    assert (c["orders"], c["product_sales"]) == (1, 500.0)


@pytest.mark.parametrize("sort, order, expected", [
    ("product_sales", "asc", [A2, B, C, A]),
    ("orders", "desc", [A, B, A2, C]),          # ties on 1 order are broken by seller id
    ("late_rate", "asc", [C, A, B, A2]),        # A2 has no rate, so it is last
    ("late_rate", "desc", [B, A, C, A2]),       # ... in both directions
    ("review_score", "asc", [B, A2, A, C]),
    ("review_score", "desc", [A, A2, B, C]),
])
def test_sorting_puts_empty_values_last(sellers, sort, order, expected):
    assert ids(sellers.list_sellers(sort=sort, order=order)) == expected


def test_state_filter(sellers):
    page = sellers.list_sellers(state="SP")
    assert (ids(page), page["total"]) == ([A, A2], 2)


def test_prefix_search(sellers):
    assert ids(sellers.list_sellers(prefix="aaa")) == [A, A2]
    assert ids(sellers.list_sellers(prefix=A2)) == [A2]


def test_filters_combine(sellers):
    assert ids(sellers.list_sellers(state="RJ", prefix="a")) == []


def test_no_match_is_an_empty_page(sellers):
    page = sellers.list_sellers(state="AC")
    assert (page["items"], page["total"], page["total_pages"]) == ([], 0, 0)


def test_paging(sellers):
    first, last = sellers.list_sellers(page_size=3), sellers.list_sellers(page_size=3, page=2)
    assert (ids(first), ids(last)) == ([A, C, B], [A2])
    assert (last["total"], last["total_pages"]) == (4, 2)


def test_a_page_after_the_last_is_empty_but_keeps_the_total(sellers):
    page = sellers.list_sellers(page_size=3, page=3)
    assert (page["items"], page["total"]) == ([], 4)


@pytest.mark.parametrize("arguments", [{"sort": "price; DROP TABLE x"}, {"order": "sideways"},
                                       {"page": 0}, {"page_size": 101}, {"page_size": 0}])
def test_the_service_refuses_values_the_api_would_never_send(sellers, arguments):
    with pytest.raises(ValueError):
        sellers.list_sellers(**arguments)


def test_detail_summary_equals_the_list_row(sellers):
    listed = {item["seller_id"]: item for item in sellers.list_sellers()["items"]}
    for seller_id, row in listed.items():
        summary = sellers.get_seller(seller_id)["summary"]
        for kpi in ("orders", "items_sold", "product_sales", "average_order_value", "late_rate", "review_score"):
            assert summary[kpi] == pytest.approx(row[kpi]), (seller_id, kpi)


def test_detail_has_every_month_of_the_window(sellers):
    detail = sellers.get_seller(A)
    months = {m["year_month"]: m for m in detail["monthly"]}
    assert list(months) == window_months(20170101, 20180831)
    assert detail["window"] == {"first_month": "2017-01", "last_month": "2018-08"}
    assert (months["2017-01"]["orders"], months["2017-01"]["items_sold"]) == (1, 2)
    assert (months["2018-04"]["orders"], months["2018-04"]["product_sales"]) == (2, 200.0)  # canceled excluded
    assert months["2017-02"] == {"year_month": "2017-02", "orders": 0, "items_sold": 0, "product_sales": 0.0,
                                 "average_order_value": None, "late_rate": None, "review_score": None,
                                 "dispatched_orders": 0, "reviewed_orders": 0}
    assert months["2018-07"]["late_rate"] == 0.5


def test_detail_signals_for_seller_a(sellers):
    signals = {s["key"]: s for s in sellers.get_seller(A)["signals"]}
    assert (signals["sales_trend"]["status"], signals["sales_trend"]["value"]) == ("positive", pytest.approx(0.5))
    assert (signals["late_dispatch"]["status"], signals["late_dispatch"]["value"]) == ("neutral", pytest.approx(1 / 12))
    assert signals["review_score"]["status"] == "positive"
    assert "1 of 12 dispatched orders" in signals["late_dispatch"]["summary"]


def test_a_small_seller_gets_insufficient_data_not_a_verdict(sellers):
    assert {s["status"] for s in sellers.get_seller(A2)["signals"]} == {"insufficient_data"}


def test_the_disclaimer_is_part_of_the_response(sellers):
    assert "not a credit score" in sellers.get_seller(A)["disclaimer"]


@pytest.mark.parametrize("seller_id", [D, "f" * 32])
def test_a_seller_without_sales_in_the_window_is_not_found(sellers, seller_id):
    with pytest.raises(SellerNotFound):
        sellers.get_seller(seller_id)


def test_values_are_bound_not_spliced(sellers):
    assert sellers.list_sellers(state="SP' OR '1'='1")["total"] == 0
    with pytest.raises(SellerNotFound):
        sellers.get_seller("' OR '1'='1")


def test_every_fixed_query_is_audited_with_its_parameters(sellers, seller_settings):
    sellers.list_sellers(state="SP")
    sellers.get_seller(A)
    lines = [json.loads(line) for line in seller_settings.audit_path.read_text(encoding="utf-8").splitlines()]
    assert [(e["client"], e["status"], e["sql"].split()[0]) for e in lines] == [
        ("api", "ok", "sellers.count"), ("api", "ok", "sellers.list"), ("api", "ok", "sellers.detail")]
    assert '"SP"' in lines[0]["sql"] and A in lines[2]["sql"]
