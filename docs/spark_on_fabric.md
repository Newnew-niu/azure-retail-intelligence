# Running the Spark track in a Microsoft Fabric Lakehouse

> **Status: not run.** These steps describe how the notebook is meant to run in Fabric. The
> code has been run locally (Linux, GitHub Codespaces) and in GitHub Actions only, never in
> Fabric. See the verification table in the [README](../README.md).

The `spark/` package uses only Apache Spark and Delta Lake APIs (no `mssparkutils` or
`notebookutils`), and every table path comes from one base path setting, so the same code
that runs on a laptop runs in a Fabric notebook. The versions in `requirements-spark.txt`
(Spark 4.1.1, Delta Lake 4.2) were chosen to match Fabric Runtime 2.0.

## What you need

- A Fabric workspace on a capacity, or a Fabric trial. The trial is free; a paid capacity is
  billed while it runs, so pause it afterwards.
- This repository, the Olist CSV files (`python scripts/download_data.py`) and, for the
  incremental mode, the simulated batches (`python scripts/make_incremental_batches.py`).

## 1. Create a Lakehouse

In the workspace: **New item → Lakehouse**, for example `retail_lakehouse`. Leave
"Lakehouse schemas" off: the package writes flat table names such as `gold_fact_orders`,
and Fabric shows every Delta folder directly under `Tables/` as a table.

## 2. Upload the files

In the Lakehouse explorer, under **Files**, create these folders and upload:

| Folder in Files/ | Upload |
|---|---|
| `olist/raw/` | `olist_orders_dataset.csv`, `olist_order_items_dataset.csv`, `olist_order_payments_dataset.csv`, `olist_customers_dataset.csv` from `data/raw/` |
| `olist/batches/` | the `sim_01_2017-12` … `sim_09_2018-08_final` folders from `data/batches/` (incremental mode only) |
| `code/` | the `spark/` and `config/` folders of this repository (`config/source_schema.yml` drives the silver types) |

Only the four files above are read; the other Olist files are outside this module's scope.

## 3. Import the notebook

**Import → Notebook → From this computer**, choose `notebooks/spark_lakehouse_demo.ipynb`.
Open it and, in the explorer on the left, add `retail_lakehouse` as the **default**
lakehouse. Fabric then mounts it at `/lakehouse/default/`.

## 4. Set the parameters

The first cell is tagged as the parameters cell (Fabric: **⋯ → Toggle parameter cell**, if it
is not already marked). Copy the ABFS paths from the Lakehouse explorer (**⋯ → Properties**
on the `Files` and `Tables` folders):

```python
mode = "full"
data_dir = "abfss://<workspace>@onelake.dfs.fabric.microsoft.com/retail_lakehouse.Lakehouse/Files/olist/raw"
base_path = "abfss://<workspace>@onelake.dfs.fabric.microsoft.com/retail_lakehouse.Lakehouse/Tables"
repo_dir = "/lakehouse/default/Files/code"
```

- `data_dir` and `base_path` are read and written by Spark, so they use the ABFS form.
- `repo_dir` is read by Python (`import spark...`, the YAML contract), so it uses the
  local mount of the default lakehouse.
- For the incremental mode, set `mode = "incremental"`, point `data_dir` at
  `.../Files/olist/batches`, and use a base path with no tables in it yet (or a second
  Lakehouse), so that it can be compared with the full load.

## 5. Run

**Run all**. The notebook takes the session Fabric already started (`get_spark()` returns
the active session) and runs bronze → silver → gold → data quality for each batch. If an
ERROR check fails, the cell stops with `DataQualityError` after writing `gold_dq_result`.

## 6. Check the result

- The **Tables** folder shows `bronze_*`, `silver_*`, `silver_quarantine`,
  `gold_fact_orders`, `gold_fact_order_items`, `gold_fact_payments`, `gold_watermark` and
  `gold_dq_result`.
- The last notebook cells print row counts, the DQ results and the Delta history of
  `gold_fact_orders` (one MERGE per batch, with inserted / updated / deleted counts).
- Expected row counts after a full load are those in `reports/spark_parity.md`.
- The SQL analytics endpoint of the Lakehouse can query the gold tables with T-SQL, for
  example a GOLDEN_KPIS query with the table names replaced.

## Things that may differ in Fabric (unverified)

- The package sets `spark.sql.ansi.enabled=false`, `spark.sql.session.timeZone=UTC` and
  `spark.sql.legacy.timeParserPolicy=CORRECTED` on the session. Fabric allows these
  session settings, but they apply to the whole notebook session.
- Fabric may enable features such as V-Order or optimized write on Delta tables. They change
  file layout, not values, so the parity results should not change. This has not been checked.
- The parity script (`python -m spark.parity`) reads the DuckDB export from the local
  `data/` folder and is meant for a developer machine, not for Fabric.

## Clean up

Delete the Lakehouse (or the workspace) when finished, and pause a paid capacity.
