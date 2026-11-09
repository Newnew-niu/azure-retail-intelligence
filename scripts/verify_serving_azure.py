"""Run the serving layer against the real Azure SQL database and compare it with the DuckDB export.

Part 1 goes through the REST API with the azuresql backend, signed in with the `az login`
identity (the database admin, not the reader). It needs data/serving.duckdb and
data/serving_baseline.json from scripts/export_serving_db.py.
Part 2 runs serving/sql/serving_reader.sql for a user WITHOUT LOGIN, switches to it with
EXECUTE AS, and tries what it may and may not do. Everything happens in one transaction that
is rolled back, so the database is left unchanged.

Usage, from the repository root, with AZURE_SQL_SERVER in .env and an `az login` session:
    .venv/Scripts/python scripts/verify_serving_azure.py
The server name is never printed. A paused serverless database takes about a minute to resume.
"""
import json
import os
import re
import sys
import tempfile
import time
from decimal import Decimal
from pathlib import Path

from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
env = dotenv_values(ROOT / ".env")
server = env["AZURE_SQL_SERVER"]
if "." not in server:
    server += ".database.windows.net"
os.environ.update(SQL_SERVER=server, SQL_AUTH="azure_cli", SQL_DATABASE="retail_intelligence",
                  SERVING_BACKEND="azuresql")
SHORT = server.split(".")[0]


def hide(text):
    return str(text).replace(server, "<server>").replace(SHORT, "<server>")


from fastapi.testclient import TestClient  # noqa: E402

from serving.api.main import create_app  # noqa: E402
from serving.core.config import Settings  # noqa: E402
from serving.golden_kpis import GOLDEN_KPIS  # noqa: E402

SCRATCH = Path(tempfile.mkdtemp(prefix="verify_serving_"))
results = []


def check(name, ok, detail=""):
    results.append((name, bool(ok)))
    print(f"{'PASS' if ok else 'FAIL'}  {name}  {hide(detail)}")


KEY = {"X-API-Key": "verify"}
azure = TestClient(create_app(Settings(backend="azuresql", api_key="verify",
                                       audit_path=SCRATCH / "azure_audit.jsonl")))
duck = TestClient(create_app(Settings(backend="duckdb", api_key="verify",
                                      audit_path=SCRATCH / "duck_audit.jsonl")))


def query(client, sql, limit=None):
    body = {"sql": sql} if limit is None else {"sql": sql, "limit": limit}
    return client.post("/query", json=body, headers=KEY)


# --- wake the serverless database ---
t = time.time()
r = query(azure, "SELECT COUNT(*) AS n FROM dw.dim_date")
check("connect to Azure SQL with Entra ID (az login)", r.status_code == 200,
      f"{time.time() - t:.0f} s, status {r.status_code} {r.text[:200]}")
if r.status_code != 200:
    sys.exit(1)

# --- 1. catalog and row counts ---
datasets = azure.get("/datasets", headers=KEY).json()
check("13 datasets listed", len(datasets) == 13, str(len(datasets)))
for d in datasets:
    name = d["name"]
    a = azure.get(f"/datasets/{name}", headers=KEY).json()["row_count"]
    b = duck.get(f"/datasets/{name}", headers=KEY).json()["row_count"]
    check(f"row count {name}: Azure = export", a == b, f"Azure {a}, export {b}")

# --- 2. golden numbers: Azure = LocalDB baseline = README ---
baseline = json.loads((ROOT / "data" / "serving_baseline.json").read_text())
readme = (ROOT / "README.md").read_text(encoding="utf-8")
for name, kpi in GOLDEN_KPIS.items():
    r = query(azure, kpi["sql"])
    value = list(r.json()["rows"][0].values())[0] if r.status_code == 200 else None
    if value is None:
        check(f"golden {name}", False, r.text[:200])
        continue
    base = baseline[name]
    same = (Decimal(str(value)) == Decimal(base)) if "." not in str(base) else abs(float(value) - float(base)) < 1e-5
    check(f"golden {name}: Azure = LocalDB baseline", same, f"Azure {value}, baseline {base}")
    check(f"golden {name}: README shows it", kpi["readme"](float(value)) in readme, kpi["readme"](float(value)))

# --- 3. the five agent questions: same answer on both engines ---
QUESTIONS = {
    "2018 monthly sales": "SELECT year_month, sales_orders, product_sales FROM mart.vw_sales_monthly "
                          "WHERE year_month LIKE '2018-%' ORDER BY year_month",
    "late rate by state": "SELECT customer_state, delivered_orders, late_rate FROM mart.vw_delivery_by_state "
                          "WHERE delivered_orders >= 500 ORDER BY late_rate DESC, customer_state LIMIT 5",
    "review by delivery": "SELECT * FROM mart.vw_review_by_delivery_status ORDER BY 1",
    "top categories": "SELECT p.category_name_en AS category, SUM(i.price) AS sales "
                      "FROM dw.fact_order_items AS i JOIN dw.dim_product AS p ON p.product_key = i.product_key "
                      "WHERE i.order_status NOT IN ('canceled', 'unavailable') "
                      "AND i.purchase_date_key BETWEEN 20170101 AND 20180831 "
                      "GROUP BY p.category_name_en ORDER BY sales DESC LIMIT 5",
}


def normal(rows):
    return [{k: (round(float(v), 6) if isinstance(v, (int, float)) and not isinstance(v, bool) else v)
             for k, v in row.items()} for row in rows]


for label, sql in QUESTIONS.items():
    a, b = query(azure, sql), query(duck, sql)
    if a.status_code != 200 or b.status_code != 200:
        check(f"question '{label}'", False, f"Azure {a.status_code} {a.text[:200]} | export {b.status_code} {b.text[:200]}")
        continue
    same = normal(a.json()["rows"]) == normal(b.json()["rows"])
    check(f"question '{label}': same rows on both engines", same,
          f"{len(a.json()['rows'])} rows" + ("" if same else f"\n  Azure  {a.json()['rows'][:3]}\n  export {b.json()['rows'][:3]}"))

a = azure.get("/runs/latest", headers=KEY)
b = duck.get("/runs/latest", headers=KEY)
check("pipeline status answers on Azure", a.status_code == 200, a.text[:300])
latest = a.json()["latest_run"] if a.status_code == 200 else {}
check("pipeline status: latest Azure run came from ADF and succeeded",
      latest.get("trigger_source") == "adf" and latest.get("status") == "SUCCEEDED", str(latest.get("run_id")))
check("pipeline status: same data quality results as the export",
      a.status_code == 200 and a.json()["data_quality"] == b.json()["data_quality"],
      str(a.json().get("data_quality", {}).get("summary")))
check("pipeline status never exposes error_message", "error_message" not in a.text)

# --- 4. controls on the real engine ---
r = query(azure, "SELECT order_id FROM dw.fact_orders", limit=5)
check("row limit becomes TOP and truncated is reported", r.status_code == 200 and len(r.json()["rows"]) == 5
      and r.json()["truncated"] is True, r.text[:120])
r = query(azure, "SELECT x FROM (SELECT 1 AS x UNION ALL SELECT 2) AS u ORDER BY x")
check("wrapped UNION runs on Azure", r.status_code == 200 and [row["x"] for row in r.json()["rows"]] == [1, 2], r.text[:120])
for sql, word in [("DROP TABLE dw.fact_orders", "DROP"), ("SELECT * FROM ops.pipeline_run", "ops"),
                  ("SELECT * FROM stg.customers", "stg"), ("SELECT 1; DELETE FROM dw.fact_orders", "statement")]:
    r = query(azure, sql)
    check(f"guard refuses: {sql}", r.status_code == 400, r.json().get("detail", "")[:90])
r = query(azure, "SELECT no_such_column FROM mart.vw_sales_monthly")
check("engine error becomes 400 without the server name", r.status_code == 400 and SHORT not in r.text, r.text[:150])
slow = TestClient(create_app(Settings(backend="azuresql", api_key="verify", query_timeout_seconds=1,
                                      audit_path=SCRATCH / "azure_audit.jsonl")))
t = time.time()
r = query(slow, "SELECT COUNT(*) AS n FROM dw.fact_order_items AS a CROSS JOIN dw.fact_order_items AS b "
                "CROSS JOIN dw.dim_date AS c")
check("1 s timeout cancels a heavy query with 504", r.status_code == 504, f"{r.status_code} after {time.time() - t:.1f} s")
r = azure.get("/datasets", headers={"X-API-Key": "wrong"})
check("wrong API key gets 401", r.status_code == 401)

audit = [json.loads(line) for line in (SCRATCH / "azure_audit.jsonl").read_text().splitlines()]
attempts = 1 + len(GOLDEN_KPIS) + len(QUESTIONS) + 2 + 4 + 1 + 1  # every /query sent to Azure above
check("audit log wrote one line per Azure attempt",
      len(audit) == attempts and {x["status"] for x in audit} == {"ok", "rejected", "error"},
      f"{len(audit)} lines, statuses {sorted({x['status'] for x in audit})}")

# --- 5. reader identity from serving_reader.sql, rolled back ---
from ingestion import db  # noqa: E402
import pyodbc  # noqa: E402

script = (ROOT / "serving" / "sql" / "serving_reader.sql").read_text()
script = re.sub(r"/\*.*?\*/", "", script, flags=re.S).replace("[<SERVING_IDENTITY>]", "[serving_reader_verify]")
script = script.replace("FROM EXTERNAL PROVIDER", "WITHOUT LOGIN")
batches = [b.strip() for b in script.split("GO") if b.strip()]
conn = db.connect(autocommit=False)
cur = conn.cursor()
try:
    for batch in batches:
        cur.execute(batch)
    cur.execute("EXECUTE AS USER = 'serving_reader_verify'")

    def attempt(sql):
        try:
            cur.execute(sql)
            cur.fetchall() if cur.description else None
            return True, ""
        except pyodbc.Error as exc:
            return False, str(exc).split("]")[-1][:90]

    for sql in ["SELECT TOP 1 * FROM mart.vw_sales_monthly", "SELECT TOP 1 * FROM dw.dim_customer",
                "SELECT TOP 1 run_id, status FROM ops.pipeline_run",
                "SELECT TOP 1 check_name, failed_rows FROM ops.dq_result"]:
        ok, msg = attempt(sql)
        check(f"reader CAN: {sql}", ok, msg)
    for sql in ["SELECT TOP 1 error_message FROM ops.pipeline_run", "SELECT TOP 1 * FROM stg.customers",
                "SELECT TOP 1 * FROM raw.orders", "UPDATE dw.dim_date SET year = year WHERE 1 = 0",
                "DELETE FROM dw.fact_orders WHERE 1 = 0", "CREATE TABLE dw.x (a INT)"]:
        ok, msg = attempt(sql)
        check(f"reader CANNOT: {sql}", not ok, msg)
    cur.execute("REVERT")
finally:
    conn.rollback()
    left = conn.execute("SELECT COUNT(*) FROM sys.database_principals WHERE name = 'serving_reader_verify'").fetchval()
    conn.close()
check("test user removed by the rollback", left == 0, f"{left} left")

failed = [n for n, ok in results if not ok]
print(f"\n{len(results) - len(failed)} passed, {len(failed)} failed")
for n in failed:
    print("FAILED:", n)
