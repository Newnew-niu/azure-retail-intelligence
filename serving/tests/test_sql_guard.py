"""Layer 1: the SQL guard, with no database involved."""
import pytest

from serving.core.errors import QueryRejected
from serving.core.sql_guard import MAX_SQL_LENGTH, validate_query

ALLOWED = frozenset({"mart.vw_sales_monthly", "dw.fact_orders", "dw.dim_customer"})


def check(sql: str, row_limit: int = 500) -> str:
    return validate_query(sql, ALLOWED, row_limit)


@pytest.mark.parametrize("sql", [
    "SELECT * FROM mart.vw_sales_monthly",
    "select year_month from MART.VW_SALES_MONTHLY",
    'SELECT * FROM "mart"."vw_sales_monthly"',
    "SELECT * FROM mart.vw_sales_monthly;",
    "SELECT 1",
    "WITH recent AS (SELECT * FROM dw.fact_orders) SELECT COUNT(*) FROM recent",
    "SELECT c.state, COUNT(*) FROM dw.fact_orders AS f JOIN dw.dim_customer AS c "
    "ON c.customer_key = f.customer_key GROUP BY c.state ORDER BY 2 DESC",
    "SELECT * FROM (SELECT order_id FROM dw.fact_orders) AS s",
    "SELECT order_id, ROW_NUMBER() OVER (ORDER BY purchased_at) FROM dw.fact_orders",
    "SELECT CASE WHEN is_late = 1 OR is_delivered = 0 THEN 'x' ELSE 'y' END FROM dw.fact_orders",
    "SELECT DATE_TRUNC('month', purchased_at), ROUND(AVG(delivery_days), 2) FROM dw.fact_orders GROUP BY 1",
    "SELECT order_id FROM dw.fact_orders WHERE order_status = 'it--is /*text*/ ; DROP TABLE x'",
])
def test_ordinary_analytical_queries_pass(sql):
    assert check(sql)


@pytest.mark.parametrize("sql", [
    "DROP TABLE dw.fact_orders",
    "DELETE FROM dw.fact_orders",
    "UPDATE dw.fact_orders SET order_status = 'x'",
    "INSERT INTO dw.fact_orders VALUES (1)",
    "TRUNCATE TABLE dw.fact_orders",
    "CREATE TABLE mart.x (a INT)",
    "CREATE TABLE mart.x AS SELECT * FROM dw.fact_orders",
    "ALTER TABLE dw.fact_orders ADD COLUMN a INT",
    "MERGE INTO dw.fact_orders AS t USING dw.dim_customer AS s ON 1 = 1 WHEN MATCHED THEN DELETE",
    "ATTACH 'other.db'",
    "DETACH x",
    "CALL query('SELECT 1')",
    "CALL pragma_database_list()",
    "EXPORT DATABASE 'x'",
    "CHECKPOINT",
    "VACUUM",
    "BEGIN TRANSACTION",
    "USE ops",
    "SET VARIABLE x = 1",
    "SELECT * INTO OUTFILE 'x' FROM dw.fact_orders",
    "COPY dw.fact_orders TO 'stolen.csv'",
    "COPY (SELECT * FROM dw.fact_orders) TO 'stolen.csv'",
    "SET enable_external_access = true",
    "PRAGMA database_list",
    "INSTALL httpfs",
    "LOAD httpfs",
    "EXPLAIN SELECT * FROM dw.fact_orders",
    "DESCRIBE dw.fact_orders",
    "SHOW TABLES",
    "SELECT order_id INTO stolen FROM dw.fact_orders",
    "SELECT order_id FROM dw.fact_orders FOR UPDATE",
    "WITH x AS (DELETE FROM dw.fact_orders RETURNING *) SELECT * FROM x",
    "(SELECT 1)",
])
def test_anything_but_a_plain_select_is_rejected(sql):
    with pytest.raises(QueryRejected):
        check(sql)


@pytest.mark.parametrize("sql", [
    "SELECT 1; DROP TABLE dw.fact_orders",
    "SELECT 1; SELECT 2",
    "SELECT 1; COMMIT",
    "SELECT 1;\n\n  DELETE FROM dw.fact_orders;",
    "",
    "   ",
    ";",
])
def test_exactly_one_statement_is_required(sql):
    with pytest.raises(QueryRejected):
        check(sql)


@pytest.mark.parametrize("sql", [
    "SELECT 1 -- ; DROP TABLE dw.fact_orders",
    "SELECT 1 /* ; DROP TABLE dw.fact_orders */",
    "/* hidden */ SELECT 1",
    "SELECT /*+ hint */ 1",
    "SELECT 1 /* a /* nested */ ; DROP TABLE dw.fact_orders */",
    "SELECT 1; -- trailing",
    "-- only a comment",
])
def test_comments_are_rejected(sql):
    with pytest.raises(QueryRejected):
        check(sql)


@pytest.mark.parametrize("sql", [
    "SELECT * FROM stg.orders",
    "SELECT * FROM ops.dq_result",
    "SELECT * FROM ops.pipeline_run",
    "SELECT * FROM raw.orders",
    "SELECT * FROM information_schema.tables",
    "SELECT * FROM pg_catalog.pg_tables",
    "SELECT * FROM sqlite_master",
    "SELECT * FROM vw_sales_monthly",               # not schema-qualified
    "SELECT * FROM serving.mart.vw_sales_monthly",  # catalog-qualified
    "SELECT * FROM dw.fact_orders AS f JOIN ops.pipeline_run AS r ON 1 = 1",
    "SELECT * FROM mart.vw_sales_monthly WHERE year_month IN (SELECT run_id FROM ops.pipeline_run)",
    "SELECT (SELECT COUNT(*) FROM ops.dq_result)",
    "WITH a AS (SELECT * FROM ops.dq_result) SELECT * FROM a",
    "SELECT * FROM 'README.md'",
    "FROM ops.dq_result",                            # DuckDB's FROM-first syntax
    "SELECT * FROM (FROM ops.dq_result)",
    "SELECT * FROM (DESCRIBE ops.dq_result)",
    "SELECT * FROM (SUMMARIZE ops.dq_result)",
    "SELECT * FROM (PIVOT ops.dq_result ON status USING COUNT(*))",
    "SELECT * FROM (SHOW TABLES)",
    "SELECT * FROM dw.fact_orders POSITIONAL JOIN ops.dq_result",
    "SELECT * FROM dw.fact_orders ASOF JOIN ops.dq_result AS d ON 1 = 1",
    "SELECT * FROM dw.fact_orders, LATERAL (SELECT * FROM ops.dq_result)",
    "SELECT * FROM dw.fact_orders WHERE EXISTS (FROM ops.dq_result)",
    "WITH dq_result AS (SELECT 1) SELECT * FROM ops.dq_result",  # a CTE must not unlock a real table
    "WITH ops AS (SELECT 1) SELECT * FROM ops.dq_result",
    "SELECT * FROM system.main.duckdb_tables",
    "SELECT * FROM duckdb_tables",
    'SELECT * FROM "data/serving.duckdb"',
])
def test_tables_outside_the_catalog_are_rejected(sql):
    with pytest.raises(QueryRejected, match="not in the catalog"):
        check(sql)


@pytest.mark.parametrize("sql", [
    "SELECT * FROM read_csv('secrets.csv')",
    "SELECT * FROM read_csv_auto('secrets.csv')",
    "SELECT * FROM read_parquet('x.parquet')",
    "SELECT * FROM read_json('x.json')",
    "SELECT * FROM read_text('.env')",
    "SELECT * FROM read_blob('.env')",
    "SELECT * FROM glob('*')",
    "SELECT * FROM query('SELECT * FROM ops.dq_result')",
    "SELECT * FROM query_table('ops.dq_result')",
    "SELECT * FROM range(10)",
    "SELECT * FROM generate_series(1, 5)",
    "SELECT * FROM duckdb_settings()",
    "SELECT * FROM pragma_database_list()",
    "SELECT * FROM dw.fact_orders, read_csv('x.csv')",
    "SELECT * FROM mart.vw_sales_monthly.read_csv('x.csv')",
    "SELECT * FROM OPENROWSET('x')",
    "SELECT (SELECT * FROM read_text('.env'))",
    "SELECT * FROM (SELECT * FROM read_csv('x.csv'))",
    "WITH a AS (SELECT * FROM read_csv('x.csv')) SELECT * FROM a",
])
def test_table_functions_are_rejected(sql):
    with pytest.raises(QueryRejected, match="not allowed"):
        check(sql)


@pytest.mark.parametrize("sql", [
    "SELECT current_setting('enable_external_access')",
    "SELECT getenv('PATH')",
    "SELECT version()",
    "SELECT pg_read_file('.env')",
    "SELECT '.env'.read_text()",
    "SELECT CAST(read_text('.env') AS VARCHAR)",
    "SELECT getvariable('x')",
    "SELECT unnest(['a'])",
    "SELECT COLUMNS(*) FROM dw.fact_orders",
    "SELECT xp_cmdshell('dir')",
    "SELECT order_id FROM dw.fact_orders WHERE current_user() = 'x'",
])
def test_functions_outside_the_allow_list_are_rejected(sql):
    with pytest.raises(QueryRejected):
        check(sql)


def test_a_limit_is_added_with_one_extra_row_to_detect_truncation():
    assert check("SELECT * FROM mart.vw_sales_monthly", row_limit=500).endswith("LIMIT 501")


def test_a_smaller_limit_in_the_query_is_kept():
    assert check("SELECT * FROM mart.vw_sales_monthly LIMIT 10", row_limit=500).endswith("LIMIT 10")


def test_a_larger_limit_in_the_query_is_lowered():
    assert check("SELECT * FROM mart.vw_sales_monthly LIMIT 999999", row_limit=500).endswith("LIMIT 501")


@pytest.mark.parametrize("clause", [
    "LIMIT (SELECT 100000)",
    "LIMIT 1 + 1000000",
    "LIMIT -1",  # sqlglot's is_int accepts this, and reading it as text would give LIMIT 1
    "LIMIT 50%",  # sqlglot keeps the percent aside, so it would silently become LIMIT 50
    "LIMIT 50 PERCENT",
    "LIMIT ALL",
    "FETCH FIRST 100000 ROWS ONLY",
])
def test_a_limit_that_is_not_a_plain_number_is_rejected(clause):
    with pytest.raises(QueryRejected, match="plain whole number"):
        check(f"SELECT * FROM mart.vw_sales_monthly {clause}")


def test_select_into_a_catalog_table_is_rejected():
    """The target passes the allow-list, so only the INTO check can stop this one."""
    with pytest.raises(QueryRejected, match="SELECT INTO"):
        check("SELECT order_id INTO dw.dim_customer FROM dw.fact_orders")


@pytest.mark.parametrize("sql", ["SELECT 1 UNION SELECT 2", "SELECT 1 UNION ALL SELECT 2",
                                 "SELECT 1 INTERSECT SELECT 2", "SELECT 1 EXCEPT SELECT 2"])
def test_a_top_level_set_operation_is_rejected_with_a_way_forward(sql):
    with pytest.raises(QueryRejected, match="Wrap it"):
        check(sql)


def test_a_wrapped_union_passes_and_the_limit_covers_the_whole_result():
    sql = check("SELECT * FROM (SELECT year_month FROM mart.vw_sales_monthly "
                "UNION ALL SELECT year_month FROM mart.vw_sales_monthly) AS u")
    assert sql.endswith(") AS u LIMIT 501")


def test_every_branch_of_a_wrapped_union_is_checked():
    with pytest.raises(QueryRejected, match="not in the catalog"):
        check("SELECT * FROM (SELECT 1 UNION ALL SELECT check_name FROM ops.dq_result) AS u")


def test_very_long_sql_is_rejected():
    with pytest.raises(QueryRejected, match="longer than"):
        check("SELECT " + "1," * MAX_SQL_LENGTH + "1")
