# Deployment guide

Commands are for Git Bash on Windows, run from the repository root. Python commands assume the
virtual environment: `.venv/Scripts/python` (or activate it first).

## 1. Prerequisites

| Tool | Used for | Tested version |
|---|---|---|
| Python | ingestion, scripts, tests | 3.10.10 |
| ODBC Driver 17 for SQL Server | all SQL connections | 17 |
| SQL Server Express LocalDB | local development and SQL tests | 2022 (16.0) |
| Azure CLI | provisioning and sign-in | 2.91.0 |
| Power BI Desktop | report | 2.159 |
| An Azure subscription | cloud deployment | Azure for Students |

```bash
python -m venv .venv
.venv/Scripts/pip install -r requirements.txt
cp .env.example .env
python scripts/download_data.py        # data/raw/*.csv, archive SHA-256 verified
```

## 2. Local pipeline (LocalDB)

```bash
python scripts/deploy_sql.py           # creates database retail_intelligence and all objects
python scripts/run_local_pipeline.py   # validate -> raw -> stg -> dw -> data quality (~1 min)
python -m pytest                       # all tests
```

Optional – incremental simulation:

```bash
python scripts/make_incremental_batches.py   # data/batches/sim_01 ... sim_09 (SIMULATED)
python scripts/verify_incremental.py         # loads them into retail_intelligence_sim, compares with the full load
```

## 3. Azure resources

```bash
az login                               # the account that owns the subscription
bash infra/provision.sh                # idempotent; prints the resource names at the end
```

`provision.sh` creates, in resource group `rg-retail-intel-dev` (France Central by default,
`AZURE_LOCATION` to change it – check your subscription's *Allowed locations* policy first):

| Resource | Configuration | Cost |
|---|---|---|
| Budget `budget-retail-intel` | €10/month on the subscription, email at 50/80/100 % actual and 100 % forecast | free |
| Storage account `stretailintel<suffix>` | StorageV2, LRS, Hot, hierarchical namespace, shared keys off, public access off, container `raw` | cents |
| SQL server `sql-retail-intel-<suffix>` | Entra-only authentication, you as admin, TLS 1.2, firewall: your IP + Azure services | free |
| SQL database `retail_intelligence` | Serverless GP Gen5 2 vCores, **free offer**, auto-pause when the free allowance is used up, local backup redundancy | free |
| Data Factory `adf-retail-intel-<suffix>` | System-assigned managed identity | pay per activity run / DIU-hour |
| Role assignments | ADF identity: Storage Blob Data Reader; you: Storage Blob Data Contributor | – |

Copy the printed names into `.env` (they are not secrets; `.env` is git-ignored anyway).

## 4. Database objects in Azure SQL

```bash
SQL_SERVER=<AZURE_SQL_SERVER> SQL_AUTH=azure_cli python scripts/deploy_sql.py
```

This deploys the same scripts as locally and, because `AZURE_DATA_FACTORY` is set, creates the
factory's managed-identity database user with its least-privilege grants.

## 5. Upload a batch and run the pipeline

```bash
python -m ingestion.upload_to_adls --batch-id full_load   # validates first; uploads only if all files pass
python scripts/adf.py deploy                              # linked services, datasets, pipelines
python scripts/adf.py run --batch-id full_load            # triggers pl_olist_master and waits (5-8 min)
SQL_SERVER=<AZURE_SQL_SERVER> SQL_AUTH=azure_cli python -m pytest tests/test_reconciliation.py
```

The run is also visible in ADF Studio → Monitor, and in `ops.pipeline_run` / `ops.step_log` /
`ops.dq_result` under the same run ID.

## 6. Power BI

1. Open `powerbi/RetailIntelligence.pbip` in Power BI Desktop.
2. **Home → Refresh.** Credentials: *Microsoft account* → sign in with the Entra account that has
   access to the database → Connect. Privacy level: *Organizational*.
3. To use LocalDB instead: **Home → Transform data → Edit parameters**, set `Server` to
   `(localdb)\MSSQLLocalDB` (Windows credentials).

The model and pages are generated from code. To change them, close Power BI Desktop, edit
`scripts/build_powerbi_model.py` or `scripts/build_powerbi_report.py`, run them, and reopen.

## 7. Clean-up

```bash
bash infra/cleanup.sh            # lists the resources, asks you to type the group name, deletes group + budget
az group exists -n rg-retail-intel-dev   # false when done
```

Everything can be recreated from the repository with steps 3–5.

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `Database ... is not currently available` (40613) | Serverless database resuming from auto-pause | Retried automatically by `ingestion/db.py`; in Power BI, refresh again after a minute |
| `Cannot open server ... Client with IP address ... is not allowed` | Your public IP changed | `az sql server firewall-rule update -g rg-retail-intel-dev -s <server> -n allow-dev-client --start-ip-address <ip> --end-ip-address <ip>` (or rerun `provision.sh`) |
| `RequestDisallowedByPolicy` when provisioning | Region not allowed by the subscription policy | `az policy assignment list` → pick an allowed region, set `AZURE_LOCATION` |
| ADF fails with `BATCH_NOT_VALIDATED` | No `_validation_report.json` for the batch in ADLS | Upload the batch with `ingestion/upload_to_adls.py` |
| ADF Copy `UserErrorFileNotFound` | File name or batch folder differs from the contract | Check `raw/olist/batch_id=<id>/` against `config/source_schema.yml` |
| HTTP 504 / 429 from `scripts/adf.py` | Transient ARM error | Retried automatically with back-off |
| DQ step fails | An ERROR-level check found rows | `SELECT * FROM ops.dq_result WHERE run_id = '<run>' AND status = 'FAIL'` |
