"""Bronze and silver: text-only bronze, typed silver, rejects quarantined with a reason."""
from decimal import Decimal

from tests.spark.helpers import hex_id, item, order, payment, table, write_batch


def test_bronze_keeps_text_and_adds_lineage(spark, lake, load, tmp_path):
    load(write_batch(tmp_path / "b1", orders=[order(1)], items=[item(1, 1)], payments=[payment(1, 1)]), "b1")

    bronze = table(spark, lake, "bronze", "order_items")
    assert {f.dataType.typeName() for f in bronze.schema.fields if not f.name.startswith("_")} == {"string"}
    row = bronze.first()
    assert row["_batch_id"] == "b1"
    assert row["_source_file"].endswith("olist_order_items_dataset.csv")
    assert row["_ingested_at"] is not None


def test_rejects_are_quarantined_with_the_staging_reason(spark, lake, load, tmp_path):
    orders = [
        order(1),
        order(2, order_id="not-a-hex-id"),
        order(3, order_approved_at="yesterday"),
        order(4, order_estimated_delivery_date="2018-01-20 10:30:00"),
        order(5, order_status="  "),
    ]
    items = [item(1, 1), item(1, 2, price="abc"), item(1, 3, order_item_id="1.5"), item(1, 4, price="")]
    payments = [payment(1, 1), payment(1, 2, payment_type="")]
    load(write_batch(tmp_path / "b1", orders=orders, items=items, payments=payments), "b1")

    reasons = {(r["source_table"], r["record_key"]): r["reason"]
               for r in table(spark, lake, "silver", "quarantine").collect()}
    assert reasons == {
        ("bronze_orders", "not-a-hex-id"): "order_id is not a 32-character hex id",
        ("bronze_orders", hex_id(3)): "order_approved_at is not a timestamp",
        ("bronze_orders", hex_id(4)): "order_estimated_delivery_date has a time part; DATE would lose it",
        ("bronze_orders", hex_id(5)): "order_status is empty",
        ("bronze_order_items", f"{hex_id(1)}|2"): "price is empty or not a decimal(10,2)",
        ("bronze_order_items", f"{hex_id(1)}|1.5"): "order_item_id is empty or not an integer",
        ("bronze_order_items", f"{hex_id(1)}|4"): "price is empty or not a decimal(10,2)",
        ("bronze_order_payments", f"{hex_id(1)}|2"): "payment_type is empty",
    }
    raw = table(spark, lake, "silver", "quarantine").where("reason LIKE 'price%'").first()["raw_record"]
    assert '"price"' in raw  # the raw values travel with the reject

    assert [r["order_id"] for r in table(spark, lake, "silver", "orders").collect()] == [hex_id(1)]
    assert table(spark, lake, "silver", "order_items").count() == 1
    assert table(spark, lake, "silver", "order_payments").count() == 1


def test_silver_types_and_normalisation(spark, lake, load, tmp_path):
    load(write_batch(tmp_path / "b1", orders=[order(1, order_status=" Delivered ", order_approved_at="")],
                     items=[item(1, 1, price="12.345")], payments=[payment(1, 1, payment_type="BOLETO")]), "b1")

    o = table(spark, lake, "silver", "orders").first()
    assert o["order_status"] == "delivered"   # LOWER(TRIM())
    assert o["approved_at"] is None            # empty optional timestamp = NULL, not a reject
    assert str(o["estimated_delivery_date"]) == "2018-01-20"
    i = table(spark, lake, "silver", "order_items").first()
    assert i["price"] == Decimal("12.35")      # rounded to DECIMAL(10,2), like TRY_CONVERT
    assert table(spark, lake, "silver", "order_payments").first()["payment_type"] == "boleto"


def test_newer_batch_updates_and_the_latest_version_wins(spark, lake, load, tmp_path):
    load(write_batch(tmp_path / "b1", orders=[order(1, status="shipped", delivered="")]), "b1")
    load(write_batch(tmp_path / "b2", orders=[order(1, status="delivered")]), "b2")

    rows = table(spark, lake, "silver", "orders").collect()
    assert len(rows) == 1
    assert rows[0]["order_status"] == "delivered"
    assert rows[0]["_batch_id"] == "b2" and rows[0]["_updated_at"] is not None
