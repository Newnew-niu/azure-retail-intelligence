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

## Automated tests (119, `python -m pytest`)

| File | Tests | Needs | What it proves |
|---|---:|---|---|
| `test_validate_files.py` | 26 | – | The validator catches missing files, wrong headers, empty required values, bad numbers/timestamps/patterns, encoding problems; passes clean files |
| `test_staging_sql.py` | 7 | LocalDB | Rejects are logged with reasons; rerun writes 0 rows; NULL is not treated as a change; newer batch updates a row; reprocessing all batches keeps the latest version; failure rolls back, logs and re-throws; geolocation summary maths |
| `test_dw_sql.py` | 7 | LocalDB | No fan-out with several items and payments; untranslated category fallback; incremental load rewrites only changed orders and a rerun writes 0; late-arriving product is resolved; failed fact load keeps the watermark and is retried; a DQ ERROR fails the step and is recorded |
| `test_reconciliation.py` | 23 | LocalDB or Azure SQL + data | CSV = raw rows per file; staging = distinct keys − rejects; geolocation covers every zip once; price, freight and payment totals equal to the cent; mart totals = fact totals; latest run has no failed DQ check |
| `test_adf_definitions.py` | 16 | – | ADF JSON is valid and named after its file; no credential properties, SAS tokens or hard-coded hostnames; placeholders documented; copy entities = source contract; procedure list = local runner; every reference resolves |
| `test_powerbi_model.py` | 40 | – | Every DAX column/measure reference exists; imported columns exist in the dw DDL; relationships go dimension → fact only, facts not related; every report field exists on the right table |

SQL tests run in a throwaway database (`retail_intelligence_test`) deployed from the scripts at the
start of the session and dropped at the end; they are skipped automatically without LocalDB.
`test_reconciliation.py` runs against Azure SQL with
`SQL_SERVER=<server> SQL_AUTH=azure_cli python -m pytest tests/test_reconciliation.py`.

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
| Power BI | Refresh from Azure SQL; cards compared with the SQL expected values in [business requirements](business_requirements.md) | Matched (checked by the project owner) | manual |

## Tests that were deliberately broken

| Sabotage | Expected | Observed |
|---|---|---|
| Removed the EXCEPT change detection in `stg.usp_load_orders` | Rerun test fails (rows rewritten) | Failed; restored, diff empty |
| Added a `"password"` property to an ADF linked service | Secret test fails | Failed; restored |
| DAX referencing a missing column / missing measure | Model test fails | Both caught |
| Doubled `items_price` in `dw.fact_orders` | DQ step fails with the check name | `test_dq_error_check_fails_the_step_and_records_results` |
| Forced a CHECK-constraint violation in a staging and a fact load | Rollback, FAILED log, re-throw, watermark unchanged | Covered by tests |

## Not tested / limitations

- The simulated batches were verified locally, not in Azure (see README).
- ADF expressions are only tested by running them in Azure; there is no local ADF emulator.
- No load or performance testing beyond the full dataset (~1.5 M raw rows; local full run ≈ 1 min,
  ADF run 5–8 min with 2 DIU per copy).
- Power BI visuals are verified by eye; there is no automated visual test.
