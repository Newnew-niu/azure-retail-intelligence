# Testing strategy

## Principles

1. **Test where the logic lives.** Business logic is in T-SQL, so it is tested in a real SQL Server
   engine (LocalDB), not mocked.
2. **Reconcile, don't just count.** Every layer is checked against the one before it: rows, distinct
   keys and money to the cent.
3. **Exercise the paths the real data never takes.** Rejects, changed records, late-arriving
   dimensions and failures are tested on tiny hand-made data.
4. **Prove a test can fail.** Key tests were checked by deliberately breaking the code (see below).
5. **Label the evidence.** Locally tested, cloud-tested and manually verified are reported separately.

## Automated tests (125, `python -m pytest`)

| File | Tests | Needs | What it proves |
|---|---:|---|---|
| `test_validate_files.py` | 26 | – | The validator catches missing files, wrong headers, empty required values, bad numbers/timestamps/patterns, encoding problems; passes clean files |
| `test_staging_sql.py` | 7 | LocalDB | Rejects are logged with reasons; rerun writes 0 rows; NULL is not treated as a change; newer batch updates a row; reprocessing all batches keeps the latest version; failure rolls back, logs and re-throws; geolocation summary maths |
| `test_dw_sql.py` | 7 | LocalDB | No fan-out with several items and payments; untranslated category fallback; incremental load rewrites only changed orders and a rerun writes 0; late-arriving product is resolved; failed fact load keeps the watermark and is retried; a DQ ERROR fails the step and is recorded |
| `test_reconciliation.py` | 23 | LocalDB or Azure SQL + data | CSV = raw rows per file; staging = distinct keys − rejects; geolocation covers every zip once; price, freight and payment totals equal to the cent; mart totals = fact totals; latest run has no failed DQ check |
| `test_adf_definitions.py` | 16 | – | ADF JSON is valid and named after its file; no credential properties, SAS tokens or hard-coded hostnames; placeholders documented; copy entities = source contract; procedure list = local runner; every reference resolves |
| `test_powerbi_model.py` | 40 | – | Every DAX column/measure reference exists; imported columns exist in the dw DDL; relationships go dimension → fact only, facts not related; every report field exists on the right table |
| `test_dashboard.py` | 6 | Node.js + LocalDB | The web dashboard's `metrics.js`, run on its exported data, equals independent SQL for the full period and for one state over three months; matches the Power BI card and category values; breakdowns add up to the totals |

SQL tests run in a throwaway database (`retail_intelligence_test`) deployed from the scripts at the
start of the session and dropped at the end; they are skipped automatically without LocalDB.
`test_reconciliation.py` runs against Azure SQL with
`SQL_SERVER=<server> SQL_AUTH=azure_cli python -m pytest tests/test_reconciliation.py`.

## Spark lakehouse tests (18, `python -m pytest tests/spark --confcutdir=tests/spark`)

Linux or WSL2 with Java 17 and `requirements-spark.txt`. One local SparkSession is shared by
the session; every test gets an empty lakehouse folder and writes its own hand-made CSV
batch. On a machine without PySpark or Java the folder is not collected (the pytest header
says why), so `python -m pytest` on Windows still runs the 125 tests above.

| File | Tests | Needs | What it proves |
|---|---:|---|---|
| `test_silver.py` | 4 | – | Bronze keeps text and adds lineage; rejects are quarantined with the staging reason and raw values; types and text normalisation as in staging; a newer batch updates a row |
| `test_gold.py` | 4 | – | No fan-out with 3 items × 2 payments; an order without items or payments gets zeros; delivery days, late and status follow the SQL rules (including minute boundaries); item and payment facts carry the order's attributes |
| `test_incremental.py` | 3 | – | A rerun writes 0 rows and makes no new Delta commit; a changed order rewrites only its own rows; batches in order = one full load |
| `test_quality.py` | 3 | – | A clean load passes all 12 checks and records them; a doubled `items_price` in gold and a duplicated payment key each stop the run with the check's name |
| `test_kpi_rules.py` | 2 | – | Counts and money must match digit for digit; an average may differ by one unit in the last shared decimal place |
| `test_parity.py` | 2 | real data + DuckDB export | A full Spark load gives the six README KPIs of SQL Server and every fact row of the SQL Server export |

GitHub Actions (`.github/workflows/spark.yml`) runs the 16 fixture tests; the 2 parity tests
skip there because the licensed data is not committed. First run on 2026-11-22: 16 passed,
2 skipped in 6 min 47 s (Ubuntu, Java 17, Python 3.11). Results in a 4-core GitHub
Codespace on 2026-11-22: 18 passed in 7 min 53 s.

### Spark parity evidence (`python -m spark.parity`, 2026-11-22)

Generated into [reports/spark_parity.md](../reports/spark_parity.md) (PySpark 4.1.1, Delta
Lake 4.2.0, 4-core Codespace):

| Check | Result |
|---|---|
| Full load (data/raw), bronze → gold + DQ | 67.6 s; 99,441 / 112,650 / 103,886 rows in fact_orders / fact_order_items / fact_payments; DQ 12 of 12 PASS |
| 9 SIMULATED batches, one by one | 286.3 s in total (30–33 s per batch); each batch rebuilt 7,979–10,676 changed orders after the first; DQ 12 of 12 PASS every batch |
| Incremental = full | 0 differing rows in all three facts; money totals identical |
| Rows = SQL Server (DuckDB export of `dw`, surrogate keys mapped to natural keys) | 0 differing rows in all three facts, every column including all money columns |
| KPIs = SQL Server (`GOLDEN_KPIS` vs `data/serving_baseline.json`) | `sales_orders` 97,910 and `product_sales` 13,449,529.68 identical; the 4 averages and ratios within one unit of the last shared decimal place (see below) |
| Rerun of the last batch on the finished tables | 0 orders rebuilt, 0 silver rows inserted or updated |

`average_delivery_days` is 12.538482 in SQL Server and 12.538483 in Spark. The report shows
why: SUM 1,206,239.64 / COUNT 96,203 = 12.5384825837… in both engines; SQL Server truncates
the sixth decimal of a DECIMAL average, Spark rounds it.

Replaying all 9 batches a second time on top of the finished tables rolls order statuses
back to their older versions on the way (as in SQL, see README footnote 1), so those
reruns are not 0-row; after the last batch the facts were again identical to the full load
(0 differing rows), checked on 2026-11-22.

## Data quality checks in the pipeline (`ops.usp_run_dq_checks`)

Run as the last step of every pipeline run; results in `ops.dq_result`.

**ERROR – blocks the pipeline** (the numbers would be wrong or the pipeline is defective):

| Check | Rule |
|---|---|
| `fact_orders_row_count`, `fact_order_items_row_count`, `fact_payments_row_count` | Fact rows = staged rows |
| `fact_orders_items_price_matches_stg` | Per order, items_price = sum of staged item prices (catches fan-out) |
| `fact_orders_payment_value_matches_stg` | Per order, payment_value = sum of staged payments |
| `fact_order_items_price_total`, `fact_payments_value_total` | Fact totals = staging totals |
| `fact_date_keys_in_dim_date` | Every date key exists in the calendar |
| `review_score_between_1_and_5`, `item_price_positive`, `payment_value_not_negative` | Values that would distort KPIs |
| `dim_customer_unique_id_consistent` | The person key matches staging |

**WARN – known source anomalies, counted every run** (full load, all 2026-10-28/29 runs):

| Check | Rows | Handling |
|---|---:|---|
| `carrier_pickup_before_approval` | 1,359 | Kept; timestamps as delivered |
| `orders_without_items` | 775 | Kept, `item_count = 0`; mostly canceled/unavailable |
| `orders_without_reviews` | 768 | Excluded from score averages |
| `products_without_category` | 610 | `uncategorised` |
| `orders_with_multiple_reviews` | 547 | Score = mean of the order's reviews |
| `payment_differs_from_price_plus_freight` | 303 | Payment Value and Product Sales reported separately |
| `customers_without_geolocation` | 279 | No map coordinates |
| `products_category_not_translated` | 13 | Portuguese name used |
| `delivered_status_without_delivery_date` | 8 | Treated as not delivered |
| `sellers_without_geolocation` | 7 | No map coordinates |
| `delivery_date_on_undelivered_order` | 6 | Treated as not delivered |
| `payment_type_not_defined` | 3 | Kept as its own type |
| `orders_without_payments` | 1 | `payment_value = 0` |
| `delivered_before_purchase`, `facts_with_unknown_dimension`, `order_items_without_order` | 0 | – |

Every count that was also measured when profiling the raw CSV files in pandas (all except the two
geolocation checks) is identical, which is independent evidence that the SQL transformations neither
lose nor invent anomalies.

## End-to-end checks

| Check | How | Result | Evidence |
|---|---|---|---|
| Local full load and rerun | `run_local_pipeline.py` twice | Rerun: stg and dw write 0 rows | `ops.step_log` |
| Incremental = full | `verify_incremental.py`: 9 simulated batches into a fresh database, EXCEPT both ways against the full load on 22 objects | **0 differing rows** | script output (local `logs/`, not committed) |
| ADF full load | `scripts/adf.py run` | Succeeded; 21 reconciliation tests pass on Azure SQL | ADF run `f7ee2950-…` |
| ADF rerun | same batch again | raw replaced (one run_id), stg 0 rows written | ADF run `55591796-…` |
| ADF failure | batch `does_not_exist` | Fails in 36 s at the validation gate; `ops.pipeline_run` = FAILED with the reason; existing data untouched | ADF runs `64c783df-…` (before the gate), `d1ba0575-…` |
| ADF raw → stg → dw → DQ | `scripts/adf.py run` | Succeeded; DQ 15 PASS / 13 WARN / 0 FAIL, as locally | ADF run `7402c0db-…` |
| Cloud = local | All 6 mart views dumped from LocalDB and Azure SQL and compared | Identical (3,185 rows) | session log |
| Power BI | Refresh from Azure SQL; the 11 cards and 3 category review scores compared with SQL-computed expected values | All matched | screenshots in `docs/images/` |

## Tests that were deliberately broken

| Sabotage | Expected | Observed |
|---|---|---|
| Removed the EXCEPT change detection in `stg.usp_load_orders` | Rerun test fails (rows rewritten) | Failed; restored, diff empty |
| Added a `"password"` property to an ADF linked service | Secret test fails | Failed; restored |
| DAX referencing a missing column / missing measure | Model test fails | Both caught |
| Doubled `items_price` in `dw.fact_orders` | DQ step fails with the check name | `test_dq_error_check_fails_the_step_and_records_results` |
| Forced a CHECK-constraint violation in a staging and a fact load | Rollback, FAILED log, re-throw, watermark unchanged | Covered by tests |
| Spark: joined items to payments before aggregating in `gold.build_fact_orders` (2026-11-22) | `test_no_fan_out_with_several_items_and_payments` fails | Failed: the run stopped with `DataQualityError: ... fact_orders_items_price_matches_stg (1)`; reverted, file identical to the committed one (md5), test passes again |

## Not tested / limitations

- The simulated batches were verified locally, not in Azure (see README).
- The Spark track ran in a GitHub Codespace and on GitHub Actions (fixtures only); it has not
  been run in Microsoft Fabric ([steps](spark_on_fabric.md)). It covers three facts only.
- ADF expressions are only tested by running them in Azure; there is no local ADF emulator.
- No load or performance testing beyond the full dataset (~1.5 M raw rows; local full run ≈ 1 min,
  ADF run 5–8 min with 2 DIU per copy).
- Power BI visuals are verified by eye; there is no automated visual test.
