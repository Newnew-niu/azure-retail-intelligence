"""How a Spark KPI is compared with the SQL Server baseline (pure Python, no Spark job)."""
from decimal import Decimal

from spark.parity import compare_kpi


def test_counts_and_money_must_be_identical():
    assert compare_kpi("product_sales", Decimal("13449529.68"), Decimal("13449529.68")) == (True, "exact")
    assert compare_kpi("product_sales", Decimal("13449529.69"), Decimal("13449529.68"))[0] is False
    assert compare_kpi("sales_orders", Decimal("97911"), Decimal("97910"))[0] is False


def test_an_average_may_differ_by_one_unit_in_the_last_shared_place():
    # Exact value 12.5384825837...: SQL Server truncates to ...482, Spark rounds to ...483.
    assert compare_kpi("average_delivery_days", Decimal("12.538483"), Decimal("12.538482"))[0] is True
    assert compare_kpi("average_delivery_days", Decimal("12.538484"), Decimal("12.538482"))[0] is False
    # More digits on one side: compared at the less precise side's 13 places.
    assert compare_kpi("average_order_value", Decimal("160.193113119861090"), Decimal("160.1931131198611"))[0] is True
