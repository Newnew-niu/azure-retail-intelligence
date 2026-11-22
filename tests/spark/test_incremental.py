"""Incremental loading with Delta MERGE: reruns change nothing, changed orders are rebuilt,
and batches applied in order give the same gold tables as one full load."""
from delta.tables import DeltaTable

from spark.config import LakehouseConfig
from spark.gold import FACT_KEYS
from spark.parity import diff_ok, row_diff
from tests.spark.helpers import hex_id, item, order, payment, table, write_batch


def versions(spark, config, layer, name) -> int:
    return DeltaTable.forPath(spark, config.table(layer, name)).history().count()


def first_batch(folder):
    return write_batch(folder, orders=[order(1, status="shipped", delivered=""), order(2)],
                       items=[item(1, 1), item(1, 2), item(2, 1)], payments=[payment(1, 1), payment(2, 1)])


def second_batch(folder):
    # Order 1 has now been delivered; order 3 is new. Order 2 is not sent again.
    return write_batch(folder, orders=[order(1), order(3)], items=[item(3, 1)], payments=[payment(3, 1)])


def test_rerun_writes_zero_changes(spark, lake, load, tmp_path):
    folder = first_batch(tmp_path / "b1")
    load(folder, "b1")
    before = {fact: versions(spark, lake, "gold", fact) for fact in FACT_KEYS}

    again = load(folder, "b1")

    for entity, counts in again["silver"].items():
        assert (counts["inserted"], counts["updated"]) == (0, 0), entity
    assert again["gold"]["affected_orders"] == 0
    assert {fact: versions(spark, lake, "gold", fact) for fact in FACT_KEYS} == before  # no new commit


def test_changed_order_is_rebuilt_and_others_are_untouched(spark, lake, load, tmp_path):
    first = load(first_batch(tmp_path / "b1"), "b1")
    second = load(second_batch(tmp_path / "b2"), "b2")

    assert second["gold"]["affected_orders"] == 2  # orders 1 and 3
    assert second["gold"]["facts"]["fact_orders"] == {"inserted": 1, "updated": 1, "deleted": 0}
    assert second["gold"]["facts"]["fact_order_items"] == {"inserted": 1, "updated": 2, "deleted": 0}

    facts = {r["order_id"]: r for r in table(spark, lake, "gold", "fact_orders").collect()}
    assert facts[hex_id(1)]["delivery_status"] == "On time"
    assert facts[hex_id(1)]["_run_id"] == second["run_id"]
    assert facts[hex_id(2)]["_run_id"] == first["run_id"]  # not rewritten
    statuses = {r["order_status"] for r in table(spark, lake, "gold", "fact_order_items")
                .where(f"order_id = '{hex_id(1)}'").collect()}
    assert statuses == {"delivered"}  # every item row of the order follows the status change


def test_batches_in_order_equal_one_full_load(spark, lake, load, tmp_path):
    load(first_batch(tmp_path / "b1"), "b1")
    load(second_batch(tmp_path / "b2"), "b2")

    full = LakehouseConfig.create(str(tmp_path / "full"))
    final = write_batch(tmp_path / "all", orders=[order(1), order(2), order(3)],
                        items=[item(1, 1), item(1, 2), item(2, 1), item(3, 1)],
                        payments=[payment(1, 1), payment(2, 1), payment(3, 1)])
    load(final, "full", config=full)

    for fact in FACT_KEYS:
        result = row_diff(table(spark, lake, "gold", fact).drop("_run_id"),
                          table(spark, full, "gold", fact).drop("_run_id"))
        assert diff_ok(result), (fact, result)
