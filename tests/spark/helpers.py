"""Builders for tiny hand-made source batches, shared by the Spark tests."""
from __future__ import annotations

import csv
from pathlib import Path

from spark import bronze
from spark.config import LakehouseConfig

CONTRACT = bronze.load_contract()


def hex_id(n: int) -> str:
    return f"{n:032x}"


def order(n: int, status: str = "delivered", purchased: str = "2018-01-10 10:00:00",
          approved: str = "2018-01-10 11:00:00", carrier: str = "2018-01-11 09:00:00",
          delivered: str = "2018-01-15 10:00:00", estimated: str = "2018-01-20 00:00:00", **overrides) -> dict:
    row = {"order_id": hex_id(n), "customer_id": hex_id(1000 + n), "order_status": status,
           "order_purchase_timestamp": purchased, "order_approved_at": approved,
           "order_delivered_carrier_date": carrier, "order_delivered_customer_date": delivered,
           "order_estimated_delivery_date": estimated}
    return {**row, **overrides}


def item(order_n: int, seq: int, price: str = "10.00", freight: str = "1.50", **overrides) -> dict:
    row = {"order_id": hex_id(order_n), "order_item_id": str(seq), "product_id": hex_id(5000 + seq),
           "seller_id": hex_id(7000 + seq), "shipping_limit_date": "2018-01-12 10:00:00",
           "price": price, "freight_value": freight}
    return {**row, **overrides}


def payment(order_n: int, seq: int, value: str = "11.50", kind: str = "credit_card", **overrides) -> dict:
    row = {"order_id": hex_id(order_n), "payment_sequential": str(seq), "payment_type": kind,
           "payment_installments": "1", "payment_value": value}
    return {**row, **overrides}


def customer_for(order_row: dict) -> dict:
    """The customer of an order; the person id is derived from the customer id."""
    n = int(order_row["customer_id"], 16)
    return {"customer_id": order_row["customer_id"], "customer_unique_id": hex_id(9000 + n),
            "customer_zip_code_prefix": "01001", "customer_city": "sao paulo", "customer_state": "SP"}


def write_batch(folder: Path, orders=(), items=(), payments=(), customers=None) -> Path:
    """Write the four source files of one batch, in contract column order. Empty = ''."""
    folder.mkdir(parents=True, exist_ok=True)
    customers = customers if customers is not None else [customer_for(o) for o in orders
                                                         if len(o["customer_id"]) == 32]
    data = {"orders": orders, "order_items": items, "order_payments": payments, "customers": customers}
    for entity, rows in data.items():
        spec = CONTRACT["entities"][entity]
        names = [c["name"] for c in spec["columns"]]
        with (folder / spec["file"]).open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=names)
            writer.writeheader()
            writer.writerows([{name: row.get(name, "") for name in names} for row in rows])
    return folder


def table(spark, config: LakehouseConfig, layer: str, name: str):
    return spark.read.format("delta").load(config.table(layer, name))
