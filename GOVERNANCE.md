# Data governance

This document lists what data the platform holds and who can reach it. It also lists the controls
that protect the data and how each one is tested, maps the platform to the main GDPR articles and
says where the data physically lives. Section 6 lists what is still missing.

**Scope and honesty rules**

- The data is the public [Olist dataset](https://www.kaggle.com/datasets/olistbr/brazilian-ecommerce)
  (CC BY-NC-SA 4.0), which its publisher released in anonymised form. The platform is governed *as if*
  it processed live customer data in the EU, because that is the standard it is built to meet. For the
  real Olist business, Brazil's LGPD would apply, not the GDPR.
- Every control points to the file that implements it and the test or run that checked it. If
  something was not tested, or was tested somewhere other than Azure, the text says so.
- This is an engineering document, not legal advice. Article summaries are paraphrased; the text that
  counts is the [official GDPR text on EUR-Lex](https://eur-lex.europa.eu/eli/reg/2016/679/oj).
- Owner of every dataset, identity and control: **Data Platform (Newnew-niu)**, the same owner as in
  [serving/catalog.yml](serving/catalog.yml). One person holds every role (see gap G10).

Contents: [1. Data classification](#1-data-classification) ·
[2. Access control matrix](#2-access-control-matrix) · [3. Control register](#3-control-register) ·
[4. GDPR mapping](#4-gdpr-mapping) · [5. Data residency](#5-data-residency) ·
[6. Known gaps and remediation plan](#6-known-gaps-and-remediation-plan)

---

## 1. Data classification

| Class | Meaning | Handling rule |
|---|---|---|
| **Personal** | Relates to an identifiable person, directly or indirectly. Pseudonymised data stays personal data under the GDPR (Art. 4(5), Recital 26). | Only named identities may read it (section 2); never published; never copied outside the EU region without a record in section 5. |
| **Internal** | Business or operational data that is not about a person. | Readable by platform identities and API-key callers; not published as row-level data. |
| **Public** | Published on purpose: aggregates and documentation. | Aggregated before publication; no person-level identifiers. |

### Inventory

The same entity exists in several layers (ADLS file → `raw` → `stg` → `dw`). A layer has the class
of its most sensitive column.

| Data | Layers | Class | Why | Sensitive columns |
|---|---|---|---|---|
| Customers | ADLS, `raw.customers`, `stg.customers`, `dw.dim_customer` | **Personal** | `customer_unique_id` links every order of one person. Together with the zip prefix, city and purchase history it can single a person out, mainly in small towns. | `customer_unique_id`, `customer_id`, `zip_code_prefix`, `city`, `state`, `latitude`, `longitude` (zip-prefix centroid, not a home address) |
| Orders, items, payments | ADLS, `raw`, `stg`, `dw.fact_orders`, `dw.fact_order_items`, `dw.fact_payments` | **Personal** | Purchase history of a pseudonymous person, through `customer_id` / `customer_key`. | `customer_id`, `customer_key`, timestamps, amounts, payment type and instalments |
| Reviews | ADLS, `raw.order_reviews`, `stg.order_reviews` | **Personal (highest risk)** | Free text written by customers can contain names, phone numbers or addresses. Not used by any KPI and not loaded into `dw` (gap G5). | `review_comment_title`, `review_comment_message` |
| Review scores | `dw.fact_orders` (score only) | Personal | Linked to the order, so to the person. | `review_score` |
| Sellers | ADLS, `raw`, `stg`, `dw.dim_seller` | **Personal (precautionary)** | Most sellers are businesses, but a seller can be a sole trader, and the dataset does not say which. | `seller_id`, `zip_code_prefix`, `city`, `latitude`, `longitude` |
| Geolocation | ADLS, `raw.geolocation`, `stg.geolocation` | Internal | Sample points per zip prefix, not linked to any person; staging keeps only one centroid per prefix. | – |
| Products, categories, dates | `raw`, `stg`, `dw.dim_product`, `dw.dim_date` | Internal | Catalogue data. | – |
| KPI views | `mart.*` | Internal | Aggregated by month, state, category or seller; no customer identifiers. `vw_seller_performance` is per seller (see Sellers). | – |
| Pipeline logs | `ops.pipeline_run`, `ops.step_log`, `ops.watermark`, `ops.dq_result` | Internal | Run metadata and counts. | `error_message` can echo values from a failed statement, so the serving reader cannot read it |
| Rejected rows | `ops.rejected_row` | Internal | Holds the rejected row's key and the reason, not the row. | `record_key` (can be a pseudonymous id) |
| Serving audit log | `logs/serving_audit.jsonl` | Internal | The SQL text of each query can contain literal ids from a `WHERE` clause. | `sql` |
| Serving export | `data/serving.duckdb` (local, and Azure Files for the hosted API) | **Personal** | Copy of the catalog datasets, including `dw.dim_customer`. | as above |
| Web dashboard data | `dashboard/data.json` on GitHub Pages | **Public** | Sums and counts by month × state × category. No identifiers. No small-cell suppression (gap G11). | – |
| Seller Health public endpoints | `GET /sellers`, `GET /sellers/{id}` | **Public** | Per-seller KPIs and state, already public in the source dataset. | `seller_id` |
| Source contract, catalog, docs, code | repository | Public | No data values; the CSVs are git-ignored ([data/README.md](data/README.md)). | – |

---

## 2. Access control matrix

No passwords or keys are used anywhere except where marked. *Verified* says how the grant was checked.

| Identity | Authenticates with | Can access | Permissions | Why this much and no more | Evidence | Verified |
|---|---|---|---|---|---|---|
| **Developer** (signed-in `az login` user) | Microsoft Entra ID, CLI token | Storage account; SQL server and database; Data Factory; Container Apps group | *Storage Blob Data Contributor* on the account (uploads); **Entra admin** of the SQL server; owner-level rights on the resource groups | Builds and deploys everything. This is the broadest identity and is not separated from the others (G10). | [infra/provision.sh](infra/provision.sh), [docs/architecture.md](docs/architecture.md#security) | ✅ Used for every deployment |
| **Data Factory** (system-assigned managed identity) | Microsoft Entra ID, managed identity | Storage account (read); SQL schemas `raw`, `stg`, `dw`, `ops` | *Storage Blob Data Reader* on the account only. SQL: `SELECT, INSERT, DELETE` on `raw`; `EXECUTE` on `stg`, `dw`, `ops`. No direct table access to `stg`/`dw`/`mart`, no DDL. | Copies a batch into `raw` (pre-copy delete + insert) and runs procedures; ownership chaining covers the tables the procedures touch. | [sql/security/adf_access.sql](sql/security/adf_access.sql), [infra/provision.sh](infra/provision.sh) | ✅ Pipeline runs succeed with these grants. ❌ No negative test that it cannot read `dw` directly. |
| **Serving reader** (Entra identity for the `azuresql` backend) | Microsoft Entra ID | 13 catalog datasets; 7 columns of `ops.pipeline_run`; 8 columns of `ops.dq_result` | `SELECT` only, object by object | An API or agent needs exactly the catalog. `raw`, `stg`, other `ops` tables and `error_message` are excluded. | [serving/sql/serving_reader.sql](serving/sql/serving_reader.sql) | ✅ Grant list = catalog (`serving/tests/test_catalog.py`). ✅ 2026-11-09 on Azure SQL: a `WITHOUT LOGIN` test user with these grants could read the catalog and could not read `raw`, `stg`, `error_message` or write ([scripts/verify_serving_azure.py](scripts/verify_serving_azure.py), rolled back). ❌ **The real identity has not been created** (G1). |
| **API caller** (application or agent with the key) | `X-API-Key` header, compared in constant time | `/datasets`, `/query`, `/runs/latest` | Read-only SQL through the guard, ≤ 5,000 rows, 10 s timeout | One shared key for trusted callers; the API refuses every request when no key is configured. | [serving/README.md](serving/README.md#safety-design) | ✅ 375 serving tests pass (2026-11-26, local) |
| **MCP client** (local agent) | None: started as a local stdio process | Same tools as the API | Same guard and limits | The trust boundary is the machine. | [serving/mcp/server.py](serving/mcp/server.py) | ✅ SDK client on CI; real client locally |
| **Public web user** | None | `GET /sellers`, `GET /sellers/{id}`, `/health` | Fixed queries only, bound parameters, ≤ 100 rows per page; CORS allows the GitHub Pages origin only | The Seller Health app needs per-seller KPIs and nothing else. | [docs/seller_health_decisions.md](docs/seller_health_decisions.md) | ✅ 2026-11-18: 23/23 checks on Container Apps ([scripts/verify_seller_api.py](scripts/verify_seller_api.py)) |
| **Seller API container** (Container Apps) | **Storage account key** for the Azure Files mount | `serving.duckdb` on the share | Read-only mount; DuckDB opened read-only with external access off | Serves the snapshot. | [infra/seller_api.sh](infra/seller_api.sh) | ✅ The share is mounted `ReadOnly`; a read-only data mount was tested in Docker on CI. ⚠️ The mount uses an account key, the only secret in the platform (G9). |
| **GitHub Actions** | `GITHUB_TOKEN` (repository-scoped) | Repository, GitHub Pages, GitHub Container Registry | Build, test, publish the dashboard and the API image | CI never receives Azure credentials or real data: serving and Docker tests use synthetic data. | [.github/workflows](.github/workflows) | ✅ |
| **Power BI Desktop user** (= developer) | Microsoft Entra ID | `dw` star schema, import mode | Read, through the developer's admin identity | No Power BI Service workspace exists, so no other viewer has access. | [powerbi/](powerbi) | ✅ By hand |

---

## 3. Control register

Type: **P** = preventive (stops a bad outcome), **D** = detective (finds it after it happened).
Every control's owner is Data Platform (Newnew-niu).

| ID | Control | Objective | Type | Frequency | Implementation | Evidence of operation | Last test and result |
|---|---|---|---|---|---|---|---|
| C01 | Source contract validation | No file with wrong columns, types or formats reaches the cloud | P | Every upload | [ingestion/](ingestion), [config/source_schema.yml](config/source_schema.yml) | `_validation_report.json` next to each batch in ADLS | 2026-11-26 local: `pytest` 125 passed, including the broken-file tests in `tests/test_validate_files.py` |
| C02 | Validation gate in Data Factory | A batch without a validation report cannot be loaded | P | Every run | `pl_olist_load_raw_and_stg` GetMetadata + Fail activity ([adf/](adf)) | ADF monitor: `BATCH_NOT_VALIDATED` | Observed in Azure: failure in ~36 s ([design decision 13](docs/design_decisions.md#13-validation-gate-before-the-cloud-and-inside-adf)) |
| C03 | Data quality gate: 12 ERROR checks | Reconciliation, validity and consistency failures stop the run before any report reads the data | P | Every run | [sql/quality/usp_run_dq_checks.sql](sql/quality/usp_run_dq_checks.sql) | One row per check per run in `ops.dq_result` | 2026-11-26 local: `pytest` 125 passed (`tests/test_dw_sql.py`, `tests/test_reconciliation.py`). 2026-11-09 Azure: latest run's results read back through the API |
| C04 | 16 WARN checks | Known source anomalies are measured every run, so a change in them is visible | D | Every run | same procedure | `ops.dq_result` | as C03 |
| C05 | Run and step logging | Every load can be traced from `ops` to the ADF monitor and back | D | Every run | [sql/ops/](sql/ops); `run_id` = ADF pipeline run ID | `ops.pipeline_run`, `ops.step_log`, `ops.rejected_row` | ✅ Checked by hand in the ADF monitor |
| C06 | Incremental = full load | Incremental loading never drifts from a full rebuild | D | On a change to the load logic | [scripts/verify_incremental.py](scripts/verify_incremental.py); Spark: `python -m spark.parity` | [reports/spark_parity.md](reports/spark_parity.md) | 0 differing rows across 22 tables and views (LocalDB); Spark parity 2026-11-22 |
| C07 | No secrets in the pipeline | Credentials cannot leak because none exist | P | Every commit | Entra-only SQL and shared-key access disabled ([infra/provision.sh](infra/provision.sh)); `tests/test_adf_definitions.py` fails on a credential property or hard-coded hostname in `adf/` | test output | 2026-11-26 local: passed. Exception: G9 |
| C08 | Least privilege for Data Factory | The orchestrator can load and transform, nothing else | P | On deployment | [sql/security/adf_access.sql](sql/security/adf_access.sql) | Grants in the database | Positive path only (runs succeed); negative path not tested |
| C09 | SQL guard, default-deny | Only one read-only `SELECT` on catalog tables with allowed functions can run | P | Every query | [serving/core/sql_guard.py](serving/core/sql_guard.py) | Audit log `status: rejected` with reason | 2026-11-26: `test_sql_guard.py` passed. Each rule disabled once to prove a test fails: 40 of 40 caught (one-off, recorded in [serving/README.md](serving/README.md#what-was-tested-where)) |
| C10 | Read-only database sandbox | A query the guard misses still cannot write or read files | P | Every connection | [serving/core/backends.py](serving/core/backends.py) | – | 2026-11-26: `test_duckdb_sandbox.py` passed |
| C11 | Reader grants = catalog | The database refuses anything outside the catalog, even if the guard fails | P | Every commit (test) and on deployment | [serving/sql/serving_reader.sql](serving/sql/serving_reader.sql) | `test_catalog.py` | 2026-11-26 local: passed. 2026-11-09 Azure: test user, 56/56 checks. Real identity: G1 |
| C12 | Row limit and timeout | No caller can export a whole table or hold the database | P | Every query | [serving/core/config.py](serving/core/config.py) | `truncated: true` in responses | 2026-11-26: serving tests passed |
| C13 | Query audit log | Every query attempt, accepted or rejected, can be reviewed | D | Every query | [serving/core/audit.py](serving/core/audit.py) | `logs/serving_audit.jsonl` | Load test: 8 clients × 20 s, 4,065 requests, audit intact. Lost on scale-to-zero when hosted: G2 |
| C14 | API authentication and CORS | Only key holders run SQL; only the published web app calls the API from a browser | P | Every request | [serving/api/main.py](serving/api/main.py), [infra/seller_api.sh](infra/seller_api.sh) | 401 / CORS rejection | 2026-11-18 Azure: protected endpoints 401 without a key; CORS allowed the Pages origin only |
| C15 | Fixed seller queries | Public callers choose values, never SQL | P | Every request | [serving/core/sellers.py](serving/core/sellers.py) | – | 97 seller tests pass; 2026-11-18 Azure 23/23 |
| C16 | Dashboard = SQL | Published numbers equal the warehouse | D | Every commit | `tests/test_dashboard.py` | – | 2026-11-26 local: passed |
| C17 | EU region | Data is stored in an EU region only | P (inherited) | On deployment | Default `francecentral` in both infra scripts; the subscription's *Allowed locations* policy, which the project does not own | – | **Not an owned control yet**: an override of `AZURE_LOCATION` would not be checked (G6) |
| C18 | Budget alert | A cost overrun is noticed within a day | D | Daily (Azure Cost Management) | [infra/provision.sh](infra/provision.sh): EUR 10 / month, alerts at 50, 80, 100 % and forecast 100 % | Alert emails | Not triggered so far |

---

## 4. GDPR mapping

Article text paraphrased; read the [official text](https://eur-lex.europa.eu/eli/reg/2016/679/oj).

### Art. 5 – Principles

| Principle | What the project does | Evidence | Not done |
|---|---|---|---|
| (a) Lawfulness, fairness, transparency | Data reused under its public licence; the source and licence are stated in the README. | [data/README.md](data/README.md) | No lawful basis or privacy notice exists for real customers; out of scope for a public dataset (G14) |
| (b) Purpose limitation | The business questions and KPIs are written down before modelling; out-of-scope uses are listed. | [docs/business_requirements.md](docs/business_requirements.md) | Purpose is not enforced technically for API-key callers |
| (c) Data minimisation | The source has no names, e-mail or street addresses. Location is reduced to a zip-prefix centroid. Review text does not reach `dw`, the catalog or the API. The serving reader cannot see `raw`, `stg` or error messages. | [docs/data_dictionary.md](docs/data_dictionary.md), [serving_reader.sql](serving/sql/serving_reader.sql) | Review free text is still stored in `raw` and `stg` (G5) |
| (d) Accuracy | 28 data quality checks every run; reconciliation to the cent from CSV to dashboard. | C01–C04, C06, C16 | – |
| (e) Storage limitation | – | – | No retention period for any layer, no deletion job (G4) |
| (f) Integrity and confidentiality | See Art. 32 below. | section 3 | – |
| (2) Accountability | This document; every control linked to a test; tests run on every push. | section 3 | One person operates and reviews (G10) |

### Art. 25 – Data protection by design and by default

| By design | By default |
|---|---|
| Pseudonymous keys only, no direct identifiers in any layer | The API refuses every request until a key is configured |
| Three access layers that do not trust each other: SQL guard, read-only connection, reader grants (C09–C11) | No CORS origins are allowed unless configured |
| Public outputs are aggregates or fixed per-seller queries (C15) | 500 rows by default, 5,000 maximum, 10 s timeout |
| ADF can run procedures but cannot read the warehouse tables (C08) | Storage: no public blob access, no shared keys; SQL: Entra-only |

### Art. 30 – Records of processing activities

A record in the shape the article asks for, for the one processing activity:

| Field | Entry |
|---|---|
| Controller | Data Platform (Newnew-niu), portfolio project |
| Purpose | Sales, delivery and customer reporting for a marketplace; read-only data access for applications and agents |
| Data subjects | Marketplace customers; sellers (where sole traders) |
| Personal data categories | Pseudonymous customer and seller ids; zip prefix, city, state, zip-prefix centroid; orders, items, payments; review scores and review text |
| Special categories (Art. 9) | None expected; review free text is not screened (G5) |
| Recipients | No external recipients. Public: aggregates and per-seller KPIs (section 1) |
| Transfers outside the EU | None intended for Azure resources; development copies are listed in section 5 |
| Retention | Not defined (G4) |
| Security measures | Section 2 and section 3 |

### Art. 32 – Security of processing

| Measure | Status | Evidence |
|---|---|---|
| Encryption in transit | ✅ TLS 1.2 minimum on storage, SQL and the Container Apps storage account; HTTPS only; Container Apps ingress with `allowInsecure: false` | [infra/provision.sh](infra/provision.sh), [infra/seller_api.sh](infra/seller_api.sh) |
| Encryption at rest | ⚠️ Azure Storage encryption and Azure SQL Transparent Data Encryption are on by default for new resources; the project relies on these defaults and does not check them (G13) | – |
| Pseudonymisation | ✅ Source ids are already pseudonymous | section 1 |
| Access control | ✅ Entra ID for every human and service identity; least-privilege grants | section 2 |
| Audit logging | ⚠️ Pipeline runs in `ops` and the ADF monitor; queries in the serving audit log. Azure SQL auditing is not enabled (G7) and the hosted audit log is lost on restart (G2) | C05, C13 |
| Availability and recovery | ⚠️ Azure SQL automatic backups (locally redundant); the pipeline can rebuild every layer from the ADLS files | [infra/provision.sh](infra/provision.sh) |
| Regular testing | ✅ 125 pipeline, 375 serving, 18 Spark and 65 web tests; serving, Spark and web suites run on GitHub Actions | section 3 |

---

## 5. Data residency

**Where each copy of the data lives**

| Copy | Location | Data class | Notes |
|---|---|---|---|
| ADLS Gen2 `raw` container | Azure **France Central** (`rg-retail-intel-dev`) | Personal | Locally redundant storage, so no copy in a second region |
| Azure SQL Database | Azure **France Central** | Personal | Backup storage redundancy set to *Local* |
| Data Factory | Azure **France Central** | – | Created in France Central. Linked services name no integration runtime, so the default Azure integration runtime (auto-resolve) runs the copies; where it executes was not verified by this project |
| Container Apps + Azure Files (`serving.duckdb`) | Azure **France Central** (`rg-seller-health`) | Personal | Locally redundant storage |
| Developer machine | Outside Azure | Personal | Full CSVs, LocalDB, `serving.duckdb`, Power BI import |
| GitHub Codespace (Spark parity run, 2026-11-22) | GitHub-hosted; region not recorded | Personal | Full CSVs; the codespace has been deleted (G12) |
| GitHub repository, Pages, Container Registry | GitHub (global) | Public | No row-level data: CSVs and the export are git-ignored; the image holds no data (checked in the Docker smoke test) |
| GitHub Actions runners | GitHub-hosted | – | Synthetic data only |

**Why France Central.** North Europe (Ireland) was the first choice but is not allowed by the
subscription's policy; France Central was the cheapest allowed EU region and close to Ireland
([design decision 12](docs/design_decisions.md#12-azure-sql-free-offer-france-central)).

**What stops a deployment outside the EU today.**

1. Both infra scripts default to `francecentral`.
2. The subscription has an *Allowed locations* policy assignment, which rejected `northeurope`
   with `RequestDisallowedByPolicy` ([deployment guide](docs/deployment_guide.md)). The project does
   not own that policy and has not checked that it allows EU regions only.

Neither is a control the project owns or tests: setting `AZURE_LOCATION=eastus` would only be
stopped if the inherited policy happens to forbid it. Making this an owned and evidenced control is
gap G6.

---

## 6. Known gaps and remediation plan

Risk is rated for a platform holding real EU customer data. For the public demo data, the practical
risk of every item is low. Owner of every item: Data Platform (Newnew-niu). Status of every item: open.

| ID | Gap | Risk | Remediation |
|---|---|---|---|
| G1 | The serving reader identity has never been created; on Azure SQL the service signed in as the database admin, so `serving_reader.sql` limited only a test user | **High** | Create a managed identity for the hosted API, add managed-identity sign-in to `ingestion/db.py`, apply `serving_reader.sql`, rerun `verify_serving_azure.py` as that identity |
| G2 | The hosted API writes its audit log inside the container; it is lost when the app scales to zero | **High** | Write audit lines to an append blob or Log Analytics; alert on `rejected` bursts |
| G3 | One shared API key: no per-client identity, scopes, rate limits or row-level security | Medium | Entra ID (OAuth) for API callers; per-client scopes; row-level security if per-region access is ever needed |
| G4 | No retention period and no deletion procedure, so no way to honour an erasure request (Art. 17) | Medium | Define retention per layer; ADLS lifecycle rule for old batches; a procedure that deletes one `customer_unique_id` through every layer, tested by a reconciliation check |
| G5 | Review free text stored in `raw` and `stg`, used by nothing | Medium | Drop the two columns in staging, or mask them; keep the score only |
| G6 | EU residency is a default plus an inherited policy, not an owned control | Medium | Own *Allowed locations* policy assignment on the resource groups; a script that lists every resource's region and every database grant, compares them with an approved list and writes a dated access review report |
| G7 | Azure SQL auditing and Microsoft Defender for SQL are not enabled | Medium | Enable server auditing to a storage account in the same region; review on a schedule |
| G8 | SQL firewall allows "Azure services"; storage and SQL have public endpoints | Medium | Managed VNet integration runtime and private endpoints ([design decision 11](docs/design_decisions.md#11-identity-instead-of-secrets) gives the cost trade-off) |
| G9 | The Container Apps file-share mount uses the storage account key | Medium | Store the key in Key Vault with rotation, or bake a read-only copy of the export into a private image |
| G10 | One person holds every role (developer, admin, operator, reviewer); no segregation of duties | Medium | In a team: separate admin and developer identities, Privileged Identity Management for the SQL admin, pull-request review by a second person |
| G11 | Public aggregates have no small-cell suppression (e.g. one state in one month) | Low | Suppress or merge cells below a minimum count before export |
| G12 | Full data was copied to a developer machine and a GitHub Codespace without a recorded region | Low | Record each copy and its region before use; keep personal data in EU regions only |
| G13 | Encryption at rest relies on platform defaults that no script checks | Low | Add the TDE and storage encryption state to the G6 report |
| G14 | No lawful basis, privacy notice or DPIA for real customers | Out of scope | Required before processing real personal data |
| – | ADF's negative path (cannot read `dw` directly) is not tested | Low | Add an `EXECUTE AS` check like the serving reader's |
