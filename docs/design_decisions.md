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

### 15. Not used: Databricks, Synapse, Fabric, Snowflake
Out of scope by design: the data volume does not need distributed compute, and each would add cost
and a second platform. They are the natural next step for much larger data or streaming sources.
