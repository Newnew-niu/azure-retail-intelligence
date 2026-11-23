"""Gold facts: natural grain, no fan-out, delivery measures as in dw.usp_load_fact_orders."""
from decimal import Decimal

from tests.spark.helpers import hex_id, item, order, payment, table, write_batch


def test_no_fan_out_with_several_items_and_payments(spark, lake, load, tmp_path):
    # 3 items x 2 payments: a single join would give 6 rows and double/triple the money.
    items = [item(1, 1, price="10.00", freight="1.00"), item(1, 2, price="20.00", freight="2.00"),
             item(1, 3, price="30.00", freight="3.00")]
    payments = [payment(1, 1, value="50.00"), payment(1, 2, value="16.00", kind="voucher")]
    load(write_batch(tmp_path / "b1", orders=[order(1)], items=items, payments=payments), "b1")

    facts = table(spark, lake, "gold", "fact_orders").collect()
    assert len(facts) == 1
    f = facts[0]
    assert (f["item_count"], f["items_price"], f["items_freight"]) == (3, Decimal("60.00"), Decimal("6.00"))
    assert (f["payment_count"], f["payment_value"]) == (2, Decimal("66.00"))
    assert table(spark, lake, "gold", "fact_order_items").count() == 3
    assert table(spark, lake, "gold", "fact_payments").count() == 2


def test_order_without_items_or_payments_gets_zeros(spark, lake, load, tmp_path):
    load(write_batch(tmp_path / "b1", orders=[order(1, status="unavailable", delivered="")]), "b1")

    f = table(spark, lake, "gold", "fact_orders").first()
    assert (f["item_count"], f["items_price"], f["payment_count"], f["payment_value"]) == (0, 0, 0, 0)
    assert (f["is_delivered"], f["is_late"], f["delivery_days"], f["delivery_status"]) == (0, None, None, "Not delivered")


def test_delivery_measures_match_the_sql_rules(spark, lake, load, tmp_path):
    orders = [
        # DATEDIFF(MINUTE) counts minute boundaries: 10:00:59 -> next day 10:01:00 is 1441 minutes.
        order(1, purchased="2018-01-10 10:00:59", delivered="2018-01-11 10:01:00", estimated="2018-01-20 00:00:00"),
        # Delivered the day after the estimate: late; on the estimated day itself: on time.
        order(2, delivered="2018-01-21 08:00:00", estimated="2018-01-20 00:00:00"),
        order(3, delivered="2018-01-20 23:59:59", estimated="2018-01-20 00:00:00"),
        # Status 'delivered' without a delivery timestamp counts as not delivered.
        order(4, delivered=""),
    ]
    load(write_batch(tmp_path / "b1", orders=orders), "b1")

    facts = {r["order_id"]: r for r in table(spark, lake, "gold", "fact_orders").collect()}
    assert facts[hex_id(1)]["delivery_days"] == Decimal("1.00")  # 1441 / 1440 = 1.0007 -> 1.00
    assert facts[hex_id(1)]["purchase_date_key"] == 20180110
    assert facts[hex_id(1)]["estimated_delivery_days"] == 10
    assert (facts[hex_id(2)]["is_late"], facts[hex_id(2)]["delivery_status"],
            facts[hex_id(2)]["delivery_vs_estimate_days"]) == (1, "Late", 1)
    assert (facts[hex_id(3)]["is_late"], facts[hex_id(3)]["delivery_status"]) == (0, "On time")
    assert (facts[hex_id(4)]["is_delivered"], facts[hex_id(4)]["delivery_status"]) == (0, "Not delivered")


def test_item_and_payment_facts_carry_order_attributes(spark, lake, load, tmp_path):
    load(write_batch(tmp_path / "b1", orders=[order(1, status="shipped", delivered="")],
                     items=[item(1, 1)], payments=[payment(1, 1)]), "b1")

    i = table(spark, lake, "gold", "fact_order_items").first()
    assert (i["customer_id"], i["order_status"], i["purchase_date_key"], i["shipping_limit_date_key"]) == \
           (hex_id(1001), "shipped", 20180110, 20180112)
    p = table(spark, lake, "gold", "fact_payments").first()
    assert (p["customer_id"], p["order_status"], p["payment_value"]) == (hex_id(1001), "shipped", Decimal("11.50"))
