"""A small synthetic database for the seller tests. Every expected number can be worked out by hand.

It is separate from conftest's fixture database, so the existing tests keep their own data.
The reporting window comes from the real catalog: 2017-01-01 to 2018-08-31.

Sellers (ids are 32 hex characters, like Olist's):
  A  'a' * 32        SP  12 orders Mar-Aug 2018 (+50 % trend, 1 late), 1 two-item order in 2017,
                         1 canceled order and 1 order before the window (both excluded)
  A2 'a' * 31 + 'b'  SP  1 order, shared with B, not dispatched yet
  B  'b' * 32        RJ  the shared order, plus 1 late order with review score 1
  C  'c' * 32        MG  1 order, dispatched on time, no review; 1 unavailable order (excluded)
  D  'd' * 32        SP  only a canceled order and an order before the window: not listed
"""
from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

import duckdb

from serving.core.catalog import Catalog

A, A2, B, C, D = "a" * 32, "a" * 31 + "b", "b" * 32, "c" * 32, "d" * 32
SELLERS = [(1, A, "SP"), (2, A2, "SP"), (3, B, "RJ"), (4, C, "MG"), (5, D, "SP")]
SELLER_KEY = {seller_id: key for key, seller_id, _ in SELLERS}


def key(day: date) -> int:
    return int(day.strftime("%Y%m%d"))


class Builder:
    def __init__(self) -> None:
        self.items: list[tuple] = []
        self.orders: list[tuple] = []

    def order(self, order_id: str, purchased: date, lines: list[tuple[str, float, float]], *,
              status: str = "delivered", dispatch_days: int | None = 2, review: float | None = 5.0) -> None:
        """lines: (seller, price, freight). The shipping deadline is 3 days after purchase, so a
        dispatch after more than 3 days is late. dispatch_days=None: not handed to the carrier."""
        deadline = key(purchased + timedelta(days=3))
        for position, (seller, price, freight) in enumerate(lines, start=1):
            self.items.append((order_id, position, SELLER_KEY[seller], key(purchased), deadline, status,
                               price, freight))
        carrier = None if dispatch_days is None else key(purchased + timedelta(days=dispatch_days))
        self.orders.append((order_id, key(purchased), status, carrier, review))


def seller_rows() -> Builder:
    b = Builder()
    # Seller A: 2 orders a month, Mar-May 2018 at 100, Jun-Aug 2018 at 150, freight 10 each.
    for month in (3, 4, 5, 6, 7, 8):
        price = 100.0 if month <= 5 else 150.0
        for n in (1, 2):
            late = month == 7 and n == 1
            review = 3.0 if month == 8 else 5.0
            b.order(f"a_{month}_{n}", date(2018, month, 10 + n), [(A, price, 10.0)],
                    dispatch_days=5 if late else 2, review=review)
    b.order("a_2017", date(2017, 1, 15), [(A, 50.0, 5.0), (A, 50.0, 5.0)], review=None)
    b.order("a_canceled", date(2018, 4, 20), [(A, 999.0, 9.0)], status="canceled", dispatch_days=None)
    b.order("a_2016", date(2016, 12, 20), [(A, 777.0, 7.0)])

    b.order("shared", date(2018, 8, 20), [(A2, 20.0, 2.0), (B, 30.0, 3.0)], dispatch_days=None, review=4.0)
    b.order("b_2017", date(2017, 6, 1), [(B, 70.0, 7.0)], dispatch_days=6, review=1.0)
    b.order("c_2018", date(2018, 1, 5), [(C, 500.0, 50.0)], review=None)
    b.order("c_unavailable", date(2018, 1, 9), [(C, 888.0, 8.0)], status="unavailable", dispatch_days=None)
    b.order("d_canceled", date(2018, 2, 1), [(D, 10.0, 1.0)], status="canceled", dispatch_days=None)
    b.order("d_2016", date(2016, 11, 1), [(D, 10.0, 1.0)])
    return b


def build_seller_database(path: Path, catalog_path: Path) -> None:
    catalog = Catalog.load(catalog_path)
    connection = duckdb.connect(str(path))
    for schema in ("mart", "dw"):
        connection.execute(f"CREATE SCHEMA {schema}")
    for name, dataset in catalog.datasets.items():
        definitions = ", ".join(f'"{c["name"]}" {c["type"]}' for c in dataset["columns"])
        connection.execute(f"CREATE TABLE {name} ({definitions})")

    connection.execute("""
        INSERT INTO dw.dim_date (date_key, year_month)
        SELECT CAST(strftime(d, '%Y%m%d') AS INTEGER), strftime(d, '%Y-%m')
          FROM range(DATE '2016-01-01', DATE '2019-01-01', INTERVAL 1 DAY) AS t(d)""")
    connection.executemany("INSERT INTO dw.dim_seller (seller_key, seller_id, state) VALUES (?, ?, ?)", SELLERS)
    rows = seller_rows()
    connection.executemany("""
        INSERT INTO dw.fact_order_items (order_id, order_item_id, seller_key, purchase_date_key,
                                         shipping_limit_date_key, order_status, price, freight_value)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)""", rows.items)
    connection.executemany("""
        INSERT INTO dw.fact_orders (order_id, purchase_date_key, order_status, delivered_carrier_date_key,
                                    review_score_avg)
        VALUES (?, ?, ?, ?, ?)""", rows.orders)
    connection.close()
