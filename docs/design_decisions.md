# Design decisions

Each decision lists the alternatives considered and why they were not chosen.

### 1. ELT with T-SQL stored procedures, ADF for orchestration only
**Chosen:** ADF copies files into `raw` and calls stored procedures; all transformation logic is T-SQL in git.
**Alternatives:** ADF Mapping Data Flows; Databricks / Synapse Spark; dbt.
**Why:** The data (~1.5 M rows) fits comfortably in one SQL database. Mapping Data Flows run on a
Spark cluster billed per vCore-hour for every run (including cluster start-up time), and their logic
cannot be tested locally.
Stored procedures run identically on LocalDB, so every transformation is unit-tested without the
cloud. dbt would add a useful testing/lineage layer, but a second toolchain for ~17 models was not
worth it here; the procedures already provide idempotency, logging and tests (dbt is listed as future work).

### 2. Raw layer stores text
**Chosen:** every raw column is `NVARCHAR`; typing happens in staging with `TRY_CONVERT`.
**Alternative:** typed raw tables, or letting ADF convert types.
**Why:** a single bad value would fail a whole Copy activity. Text-first loading never fails on
content; staging logs each unconvertible row with a reason (`ops.rejected_row`) and loads the rest.

### 3. Staging rejects only what cannot be stored
**Chosen:** staging rejects bad keys and unparseable values; business-rule violations (e.g. carrier
pick-up before approval) are kept and reported by the DQ suite.
**Why:** a delivery date before the approval date is real (if odd) source data. Dropping it would
change the totals and hide the problem; reporting it keeps both the numbers and the evidence.

### 4. Change-only MERGE in staging
**Chosen:** `MERGE ... WHEN MATCHED AND EXISTS (SELECT src... EXCEPT SELECT tgt...)`.
**Why:** `EXCEPT` compares NULLs as equal, so the update fires only when a value really changed.
Reruns write 0 rows, and `updated_at_utc` becomes a trustworthy change marker for the DW watermarks.
A test proves it (and failed when the EXCEPT was removed).

### 5. Three fact tables at their natural grain
**Chosen:** `fact_order_items`, `fact_payments`, `fact_orders` (with per-order aggregates computed separately).
**Alternative:** one wide order-item fact with payments and reviews joined in.
**Why:** items and payments are both many-per-order; joining them multiplies rows and inflates both
sales and payment totals. See [data model](data_model.md#why-three-fact-tables).

### 6. `dim_customer` at `customer_id` grain
**Chosen:** one row per `customer_id`; "customers" = distinct `customer_unique_id`.
**Alternative:** one row per person with SCD type 2 addresses.
**Why:** Olist issues a `customer_id` per order, so the order-level address is exact and needs no
history logic. Person-level counts are a distinct count on an attribute.

### 7. SCD type 1, stable surrogate keys, Unknown members
**Why:** the source has no attribute history, so type 2 would add complexity with nothing to track.
Identity keys never change, so attribute updates never require fact rewrites. `-1` members keep facts
whose dimension row is missing, and those facts are re-resolved on every run.

### 8. Watermark-based incremental facts, rebuilt per order
**Chosen:** `ops.watermark` per fact; affected orders = staging changes since the mark; delete and
re-insert those orders in one transaction together with the new mark.
**Alternatives:** full rebuild each run; row-level MERGE into facts.
**Why:** a full rebuild is simpler but does not demonstrate or scale incremental processing.
Row-level MERGE leaves an order half-updated when only some of its rows change (e.g. a status change
must update every item row). Rebuilding whole orders is simple and always consistent; the
transaction makes failure safe and retries automatic.

### 9. Simulated monthly batches, clearly labelled
**Chosen:** replay the static export as snapshots at month ends (timestamps after the cutoff
blanked, delivered status rolled back), send new-or-changed rows, prove "all batches = full load".
**Why:** the dataset has no change feed. Claiming change data capture would be false; a replay with
a provable end state is honest and still exercises inserts, updates, late reviews and new dimension rows.
**Limitation:** canceled/unavailable status timing is unknown and kept as final.

### 10. ERROR vs WARN data quality
**Chosen:** ERROR checks (reconciliation, keys, KPI-breaking values) fail the pipeline; WARN checks
count documented source anomalies.
**Why:** failing on known source quirks would block every run; ignoring them would hide changes.
The split separates "our pipeline is wrong" from "the source is odd, and here is how we handle it".

### 11. Identity instead of secrets
**Chosen:** managed identity for ADF; Entra-only SQL; storage shared keys disabled; CLI tokens for scripts.
**Alternative:** connection strings / account keys in ADF linked services or Key Vault.
**Why:** a secret that does not exist cannot leak or expire. Key Vault would be the next step only if a
source required a password.
**Trade-off:** SQL firewall allows "Azure services" because the ADF Azure integration runtime has no
fixed IP. Closing that needs a managed VNet + private endpoint (managed VNet pipeline activity was
€0.88 per hour in North Europe when checked for this project), not justified for public demo data.

### 12. Azure SQL free offer, France Central
**Why:** the free offer cannot bill (auto-pauses when the allowance is used). North Europe (Ireland)
was the first choice but is not allowed by the student subscription policy; France Central was the
cheapest allowed region for storage and close to Ireland.

### 13. Validation gate before the cloud and inside ADF
**Chosen:** Python validates files against a YAML contract before upload; the upload writes the
report next to the files; ADF refuses a batch without that report.
**Why:** bad files are stopped before they cost anything, and the cloud pipeline cannot be pointed at
an unvalidated folder by mistake (observed: fails in 36 s instead of ~6 min).

### 14. Power BI as code (PBIP / TMDL / PBIR), import mode
**Chosen:** the semantic model and pages are generated by Python scripts and committed as text.
**Why:** the model is reviewable in diffs and tested (DAX references, columns vs DDL, relationships).
Import mode suits ~350k fact rows and avoids waking the serverless database on every visual.
**Trade-off:** layout changes go through the generator, not drag-and-drop.

### 15. One shared core for REST and MCP
**Chosen:** `serving/core` holds the catalog, SQL guard, limits, audit log and database access.
`serving/api` and `serving/mcp` only translate requests and errors.
**Alternatives:** two separate services; or an MCP server that calls the REST API.
**Why:** a safety rule that lives in one place cannot differ between clients, and one test suite
covers both. Separate services would duplicate the most important code. Calling the API from MCP
would add a network hop and a key to manage for no extra safety.
**Trade-off:** core changes affect both clients at once, which is intended here.

### 16. Parse SQL and sandbox the database, instead of trusting either
**Chosen:** a default-deny sqlglot guard, plus a read-only DuckDB connection with external access off.
**Alternatives:** a fixed set of metric endpoints; a regular-expression filter; the sandbox alone.
**Why:** agents need ad-hoc questions, which fixed endpoints cannot answer. Regular expressions
cannot understand nesting or quoting. The sandbox alone is not enough: DuckDB's `query()` function
still runs, and only the guard enforces the catalog allow-list and row limit.
**Trade-off:** the function allow-list refuses some harmless functions. The error says which one.

### 17. DuckDB export for the demo
**Chosen:** an exported, git-ignored file by default; Azure SQL by configuration.
**Why:** anyone can run the demo without a cloud bill or a paused serverless database, and CI needs
no cloud secret. The export stops if row counts or money totals differ from SQL Server.
**Trade-off:** it is a snapshot. The Azure SQL path is checked by `scripts/verify_serving_azure.py`,
which needs an `az login` session and resumes the paused database.

### 18. Not used: Databricks, Synapse, Fabric, Snowflake
Out of scope by design: the data volume does not need distributed compute, and each would add cost
and a second platform. They are the natural next step for much larger data or streaming sources.

### 19. Revisiting #18: a PySpark lakehouse track
**Chosen:** rebuild the money-critical part of the warehouse (orders, items, payments, with
customers as a lookup) a second time in PySpark + Delta Lake, in a bronze / silver / gold
layout, and prove it gives the same results as T-SQL. Code in `spark/`, evidence in
[reports/spark_parity.md](../reports/spark_parity.md).
**Why:** #18 is still true for this data volume, so this is not a migration. It does two things:
- **Readiness for Fabric and Databricks.** Teams on those platforms build pipelines like
  this one in PySpark notebooks on Delta tables. The package uses only Spark and Delta APIs
  and one base path setting, and the versions match Fabric Runtime 2.0, so it is meant to
  run unchanged on OneLake ([steps](spark_on_fabric.md), not yet run there).
- **The model does not depend on the engine.** The project already requires LocalDB and
  DuckDB to agree. A third engine with a different SQL dialect, different decimal rules and no
  primary keys gives the same facts row for row, which shows that the grain, the no-fan-out
  rule and the incremental design (#5, #8) are properties of the model, not of T-SQL.

**How each warehouse rule was ported:**
| T-SQL | Spark |
|---|---|
| Raw layer of NVARCHAR (#2) | Bronze: every column a string; `replaceWhere` replaces a rerun batch |
| `TRY_CONVERT` + first `reject_reason` (#3) | Types and reasons generated from `source_schema.yml`, in column order, same wording; non-ANSI casts plus regular expressions where Spark is more lenient (`'1.5'` as an integer, `'1e5'` as a decimal) |
| `ops.rejected_row` | `silver_quarantine`, with the raw values as JSON |
| Change-only MERGE with `EXCEPT` (#4) | Delta MERGE whose update condition uses the null-safe `<=>` |
| Watermark, rebuild affected orders in one transaction (#8) | Same watermark logic; the new version of each fact (untouched rows + rebuilt rows) is applied with **one** MERGE per table, so each fact changes in a single commit |
| Primary keys | Explicit uniqueness checks in the DQ gate (Delta has no primary keys) |
| `ops.usp_run_dq_checks` ERROR checks (#10) | `spark/quality.py`, results in `gold_dq_result` with the same columns |

**Differences, on purpose:**
- **Natural keys instead of surrogate keys.** IDENTITY values depend on the engine and the
  load order, so no second engine can reproduce them. The gold facts carry `customer_id`,
  `product_id` and `seller_id`; the parity check maps the SQL keys back to these.
- **No transaction across tables.** Delta commits one table at a time. The watermark is saved
  after the three fact commits; if a run stops in between, the next run rebuilds the same
  orders again, and because a rebuild from silver is idempotent the result is the same.
- **Rounding of averages.** For a DECIMAL average SQL Server truncates the last digit and Spark
  rounds it, so `average_delivery_days` is 12.538482 in SQL Server and 12.538483 in Spark
  from the identical SUM and COUNT. Counts and money are compared digit for digit; averages and
  ratios may differ by one unit in the last shared decimal place, and the report shows the exact value.

**Why T-SQL stays the production path:** it is deployed, orchestrated by ADF, feeds Power BI
and the serving layer, and costs almost nothing. At ~100k orders a Spark cluster would add
start-up time and cost, not speed: the full Spark load of three facts took 67.6 s on a 4-core
Codespace, while the whole local T-SQL pipeline (all 9 sources) takes about a minute on the
development laptop (testing strategy) – different machines, so only a rough comparison. Spark becomes the better
choice when data no longer fits one database, or when the platform is Fabric or Databricks anyway.

**Deliberately left out:** the other six sources (reviews, products, sellers, geolocation,
category translation), dimensions and their Unknown members, `fact_orders`' review columns, the
16 WARN checks, the marts, Power BI and the serving layer. Running in Fabric, Spark Structured
Streaming and table maintenance (OPTIMIZE, VACUUM) are not part of this iteration.
