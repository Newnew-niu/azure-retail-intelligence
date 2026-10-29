"""Create SIMULATED incremental batches from the static Olist files.

    python scripts/make_incremental_batches.py [--out data/batches]

The Olist dataset is a one-off export; it has no change feed. To exercise the incremental
path of the pipeline, this script replays history as a series of monthly batches:

  * Snapshot at a cutoff = what the source would have contained at that moment:
      - orders purchased on or before the cutoff;
      - order timestamps after the cutoff blanked (not yet approved / shipped / delivered);
      - status of an order that ends 'delivered' but was not delivered yet at the cutoff
        rolled back to 'shipped', 'approved' or 'created' from the timestamps it had then.
        Other final statuses (canceled, unavailable, ...) are kept: the export does not say
        when an order reached them - a known limitation of the simulation;
      - items, payments and customers of those orders; reviews answered by the cutoff;
      - products and sellers referenced by those items; geolocation for zips first needed.
  * Batch = rows that are NEW or CHANGED in a snapshot compared with the previous one, so
    later batches contain updated versions of earlier orders (e.g. shipped -> delivered).
    The category translation (71 rows) is sent in full with every batch.
  * The last batch has no cutoff: its snapshot is the complete dataset, so loading all
    batches in order must give exactly the same result as one full load
    (checked by scripts/verify_incremental.py).

This is NOT change data capture from a live system and must not be described as such.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from ingestion import validate_files  # noqa: E402

DEFAULT_OUT = PROJECT_ROOT / "data" / "batches"
# (batch_id, cutoff); None = everything. Monthly from 2018-01; the last batch adds August 2018
# and the sparse September-October tail. (A separate batch for that tail would have no new
# products or sellers, and the source contract rejects an empty file - see README limitations.)
BATCHES = [("sim_01_2017-12", "2017-12-31")] + [
    (f"sim_{i + 2:02d}_2018-{m:02d}", f"2018-{m:02d}-{d}")
    for i, (m, d) in enumerate([(1, 31), (2, 28), (3, 31), (4, 30), (5, 31), (6, 30), (7, 31)])
] + [("sim_09_2018-08_final", None)]

ORDER_TIMESTAMPS = ["order_approved_at", "order_delivered_carrier_date", "order_delivered_customer_date"]


def read_sources(data_dir: Path, contract: dict) -> dict[str, pd.DataFrame]:
    # Everything as text, empty strings kept as "" - the batches must be byte-for-byte
    # comparable values with the source, not re-parsed numbers or dates.
    return {name: pd.read_csv(data_dir / spec["file"], dtype=str, keep_default_na=False, encoding="utf-8-sig")
            for name, spec in contract["entities"].items()}


def snapshot(src: dict[str, pd.DataFrame], cutoff: str | None) -> dict[str, pd.DataFrame]:
    if cutoff is None:
        return {name: df.copy() for name, df in src.items()}
    limit = f"{cutoff} 23:59:59"  # timestamps are 'YYYY-MM-DD HH:MM:SS', so text order = time order

    orders = src["orders"][src["orders"]["order_purchase_timestamp"] <= limit].copy()
    for col in ORDER_TIMESTAMPS:
        orders.loc[orders[col] > limit, col] = ""
    not_yet_delivered = (orders["order_status"] == "delivered") & (orders["order_delivered_customer_date"] == "")
    orders.loc[not_yet_delivered, "order_status"] = orders.loc[not_yet_delivered].apply(
        lambda o: "shipped" if o["order_delivered_carrier_date"] else ("approved" if o["order_approved_at"] else "created"),
        axis=1)

    ids = set(orders["order_id"])
    items = src["order_items"][src["order_items"]["order_id"].isin(ids)]
    reviews = src["order_reviews"]
    reviews = reviews[reviews["order_id"].isin(ids) & (reviews["review_answer_timestamp"] <= limit)]
    customers = src["customers"][src["customers"]["customer_id"].isin(set(orders["customer_id"]))]
    sellers = src["sellers"][src["sellers"]["seller_id"].isin(set(items["seller_id"]))]
    zips = set(customers["customer_zip_code_prefix"]) | set(sellers["seller_zip_code_prefix"])
    return {
        "customers": customers,
        "geolocation": src["geolocation"][src["geolocation"]["geolocation_zip_code_prefix"].isin(zips)],
        "orders": orders,
        "order_items": items,
        "order_payments": src["order_payments"][src["order_payments"]["order_id"].isin(ids)],
        "order_reviews": reviews,
        "products": src["products"][src["products"]["product_id"].isin(set(items["product_id"]))],
        "sellers": sellers,
        "product_category_translation": src["product_category_translation"],
    }


def new_or_changed(current: pd.DataFrame, previous: pd.DataFrame | None) -> pd.DataFrame:
    if previous is None or previous.empty:
        return current
    merged = current.merge(previous.drop_duplicates(), how="left", indicator=True)
    return merged[merged["_merge"] == "left_only"].drop(columns="_merge")


def geolocation_delta(current: pd.DataFrame, previous: pd.DataFrame | None) -> pd.DataFrame:
    # Geolocation has no key and many exact duplicates, so it is split by zip prefix: all
    # rows of a prefix go in the first batch that needs it, never twice.
    if previous is None:
        return current
    sent = set(previous["geolocation_zip_code_prefix"])
    return current[~current["geolocation_zip_code_prefix"].isin(sent)]


def make_batches(data_dir: Path, out_dir: Path) -> list[dict]:
    contract = validate_files.load_contract(validate_files.DEFAULT_CONTRACT)
    src = read_sources(data_dir, contract)
    previous: dict[str, pd.DataFrame] | None = None
    manifest = []
    for batch_id, cutoff in BATCHES:
        snap = snapshot(src, cutoff)
        batch_dir = out_dir / batch_id
        batch_dir.mkdir(parents=True, exist_ok=True)
        counts = {}
        for name, spec in contract["entities"].items():
            if name == "product_category_translation":
                delta = snap[name]
            elif name == "geolocation":
                delta = geolocation_delta(snap[name], previous and previous[name])
            else:
                delta = new_or_changed(snap[name], previous and previous[name])
            if delta.empty:
                raise SystemExit(f"{batch_id}: no {name} rows - every batch file needs at least 1 row (source contract)")
            delta.to_csv(batch_dir / spec["file"], index=False, encoding="utf-8", lineterminator="\n")
            counts[name] = len(delta)
            if name == "orders":
                known = set() if previous is None else set(previous["orders"]["order_id"])
                updated_orders = int(delta["order_id"].isin(known).sum())
        manifest.append({"batch_id": batch_id, "cutoff": cutoff or "none (remaining data)",
                         "orders_updated": updated_orders, "rows": counts})
        print(f"{batch_id:<21} cutoff={cutoff or 'none':<10} updated_orders={updated_orders:<6,} "
              + " ".join(f"{k}={v:,}" for k, v in counts.items() if k != "product_category_translation"))
        previous = snap
    (out_dir / "MANIFEST.json").write_text(json.dumps({
        "description": "SIMULATED incremental batches replayed from the static Olist export by "
                       "scripts/make_incremental_batches.py. Not change data capture.",
        "batches": manifest}, indent=2), encoding="utf-8")
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--data-dir", type=Path, default=validate_files.DEFAULT_DATA_DIR)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args()
    make_batches(args.data_dir, args.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
