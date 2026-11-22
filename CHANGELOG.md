# Changelog

Dates are commit dates. The history before v2 is summarised from the git log.

## v2 – PySpark lakehouse track (2026-11-22)

A third engine for the money-critical part of the warehouse, proven equal to T-SQL.

- `spark/`: bronze → silver → gold with PySpark 4.1.1 and Delta Lake 4.2.0 (the versions of
  Microsoft Fabric Runtime 2.0) for orders, order items and payments, plus customers as a
  lookup. One base path setting runs the same code on a local folder or a OneLake path.
- Silver types and reject reasons are generated from `config/source_schema.yml`; rejects
  go to a quarantine table with the reason and the raw values.
- Gold `fact_orders`, `fact_order_items` and `fact_payments` at the dw grain, with natural
  keys instead of surrogate keys. Per-order totals are aggregated before the join.
- Incremental loading with Delta MERGE: only changed orders are rebuilt; a rerun writes nothing.
- A data quality gate with 12 ERROR checks, recorded in `gold_dq_result` with the columns of
  `ops.dq_result`.
- `python -m spark.parity` and [reports/spark_parity.md](reports/spark_parity.md): on the full
  data, 0 differing rows against the SQL Server facts and between the 9 simulated batches
  and one full load; the six README KPIs match the SQL Server baseline.
- 18 Spark tests (16 on hand-made fixtures, 2 on the real data) and a GitHub Actions workflow.
- A Fabric-style notebook and [instructions for a Fabric Lakehouse](docs/spark_on_fabric.md)
  (not run in Fabric).
- Design decision #19, testing strategy and README updated; nothing existing was changed.

## v1 – Azure pipeline, serving layer and Seller Health (2026-10-28 to 2026-11-18)

**Pipeline and warehouse (2026-10-28/29)**
- Source file contract and validator; validated upload to ADLS Gen2 with managed identity.
- Data Factory pipelines calling T-SQL procedures: raw (text) → staging (typed, rejects
  logged, change-only MERGE) → star schema with watermark-based incremental fact loads.
- 28 data quality checks (12 ERROR, 16 WARN) and mart views.
- Simulated monthly batches and the incremental-equals-full acceptance check.
- Power BI project generated as code (TMDL model, three PBIR pages) and a web dashboard on
  GitHub Pages.

**Serving layer (2026-11-06/09)**
- A catalog generated from the docs, a shared core with a parsed-SQL guard, limits and an
  audit log, a FastAPI service and an MCP server on top of it.
- DuckDB export for the demo, Docker image, CI; checked on Azure SQL (56 checks).

**Seller Health (2026-11-18)**
- Public read-only seller endpoints with illustrative health signals, hosted on Azure
  Container Apps.
- A React + TypeScript web app on GitHub Pages with types generated from the OpenAPI schema.
