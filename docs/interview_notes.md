# Interview notes

Talking points for presenting the project, and answers to likely questions. Numbers are from the
runs on 2026-10-28/29.

## 60-second summary

> I built an end-to-end Azure data platform on the public Olist e-commerce dataset, about 100,000
> orders. Files are validated in Python against a source contract before anything reaches the cloud,
> landed in ADLS Gen2, and loaded by Azure Data Factory into Azure SQL. All transformations are
> version-controlled T-SQL stored procedures: a typed staging layer, a star schema with incremental
> fact loads, and a data quality step that blocks the pipeline if the numbers don't reconcile.
> Power BI reports sales, delivery performance and customers on top. There are no secrets anywhere:
> Data Factory uses a managed identity and SQL accepts Entra ID only. It has 119 automated tests,
> reconciles from CSV to the warehouse to the cent, and the whole build cost under a euro.

## Walk-through order (10 minutes)

1. **Architecture diagram** (README) – layers and why ELT.
2. **Source contract + validator** – `config/source_schema.yml`; "nothing unvalidated reaches Azure".
3. **ADF monitor** – a real run, the try/catch master pipeline, the validation gate failing in 36 s.
4. **One staging procedure** – `sql/staging/usp_load_orders.sql`: TRY_CONVERT + reject reasons, change-only MERGE.
5. **Star schema** – three facts at their own grain; show the fan-out test.
6. **Incremental** – watermark, rebuild per order, "9 simulated batches = full load, 0 differing rows".
7. **Data quality** – ERROR vs WARN; `ops.dq_result` for a run.
8. **Power BI** – three pages; the association-not-causation note; model generated as code.
9. **Cost and clean-up** – free SQL offer, budget alert, `cleanup.sh`.

## Likely questions

**Why stored procedures and not Data Flows / Databricks / dbt?**
The data fits in one SQL database. Procedures cost nothing extra, run identically on LocalDB so I can
test them, and keep ADF to orchestration. Data Flows and Spark bill a cluster per run for no benefit at
this size. dbt would be my next step for lineage and docs, but a second toolchain wasn't justified.

**How do you avoid double counting?**
Items and payments are both many-per-order, so they are never joined to each other. Each fact keeps its
own grain; per-order totals are aggregated separately and joined 1:1. A test reproduces the fan-out
case, and an ERROR data quality check compares every order's totals with staging on every run.

**What happens if the pipeline fails halfway?**
Each procedure runs in its own transaction with XACT_ABORT; on error it rolls back, logs FAILED with
the message in `ops.step_log`, and re-throws. ADF's master pipeline records the failure in
`ops.pipeline_run` and then fails itself. Reruns are safe: raw replaces the batch, staging only
writes changes, facts resume from an unchanged watermark.

**Is it really incremental?**
The facts are: they only rebuild orders changed since the watermark – a rerun writes 0 rows. The
*source* is a static export, so I replayed it as simulated monthly batches and proved that loading
them in order gives exactly the full-load result. I'd never call that change data capture; with a
real source I'd use CDC or a change-tracking column feeding the same staging procedures.

**How do you know the numbers are right?**
Row counts, distinct keys and money totals reconcile CSV → raw → staging → facts, to the cent. The
warning counts match independent profiling of the raw files in pandas. The six mart views are
identical in LocalDB and Azure SQL, and the Power BI cards match SQL-computed expected values.

**Why is "customers" a distinct count of `customer_unique_id`?**
Olist creates a new `customer_id` for every order – 99,441 ids for 96,096 people. Counting
`customer_id` would count orders.

**Late deliveries have lower review scores – so lateness causes bad reviews?**
The data shows an association. Late orders might also differ in product, seller or region. I show the
comparison and say on the page that it is not causal; to test causality you'd need a controlled
comparison or an experiment.

**Security?**
No secrets exist: storage keys are disabled, SQL is Entra-only, ADF uses a managed identity with read
on storage and execute-only on the procedures. The one compromise is the SQL firewall allowing Azure
services, because the ADF runtime has no fixed IP – the fix is a managed VNet and private endpoint,
which costs money per hour, so I documented it rather than built it.

**What would you do with more time / in production?**
Triggers and alerting in ADF; CI running the static tests on every push; a second database to run the
incremental simulation in the cloud; allow empty deltas in the contract; dbt for lineage; Power BI
Service with row-level security; private networking; for big data, Fabric or Databricks.

**What was hardest / what did you learn?**
- Data quirks: `review_id` isn't unique, 775 orders have no items, payments don't always equal price +
  freight. Profiling first and writing down each rule saved rework.
- Idempotency had to be designed in at every layer, not added at the end.
- Being precise about what was tested where (local / cloud / manual) – the README table.

## Numbers worth remembering

| | |
|---|---|
| Raw rows | 1,550,924 (9 files) |
| Orders / items / payments | 99,441 / 112,650 / 103,886 |
| People vs customer ids | 96,096 vs 99,441 |
| Sales Jan 2017 – Aug 2018 | 13.45 M BRL product sales, 97,910 sales orders, AOV 160.19 BRL |
| Delivery | 12.5 days on average, 6.8 % late |
| Tests | 119 automated; 28 DQ checks per run (12 ERROR, 16 WARN) |
| ADF full run | 5–8 minutes; local full run ≈ 1 minute |
| Cost | estimated < €1 in total; SQL on the free offer |
