"""Checks every caller-supplied SQL string before it can reach a database.

The guard works on sqlglot's parse tree, not on text patterns, so spacing, letter case and
quoting cannot hide a statement. It is default-deny: a statement passes only if it is one
SELECT, reads only catalog tables and calls only listed functions. It then applies the row
limit. The database's own restrictions (see backends.py) are a second, independent layer.
"""
from __future__ import annotations

import sqlglot
from sqlglot import exp
from sqlglot.errors import SqlglotError

from serving.core.errors import QueryRejected

MAX_SQL_LENGTH = 10_000

# Names as sqlglot reports them. Unknown functions are refused because some are dangerous even
# with file access disabled: DuckDB's query() table function runs a SQL string, for example.
ALLOWED_FUNCTIONS = frozenset({
    # logic and conversion
    "AND", "OR", "CASE", "IF", "COALESCE", "NULLIF", "CAST", "TRY_CAST",
    # aggregates
    "COUNT", "SUM", "AVG", "MIN", "MAX", "MEDIAN", "STDDEV", "PERCENTILE_CONT",
    # window functions
    "ROW_NUMBER", "RANK", "DENSE_RANK", "LAG", "LEAD",
    # numbers
    "ABS", "ROUND", "FLOOR", "CEIL", "GREATEST", "LEAST",
    # text
    "LOWER", "UPPER", "LENGTH", "SUBSTRING", "TRIM", "CONCAT", "REPLACE",
    # dates
    "EXTRACT", "YEAR", "MONTH", "DATEDIFF", "TIMESTAMP_TRUNC", "TIME_TO_STR",
})
WRITE_NODES = (exp.Insert, exp.Update, exp.Delete, exp.Merge, exp.Create, exp.Drop, exp.Command)


def validate_query(sql: str, allowed_tables: frozenset[str], row_limit: int) -> str:
    """Return safe DuckDB-dialect SQL that fetches at most row_limit + 1 rows, or raise QueryRejected.

    The extra row lets the caller report that a result was truncated.
    """
    if len(sql) > MAX_SQL_LENGTH:
        raise QueryRejected(f"SQL is longer than {MAX_SQL_LENGTH} characters")
    try:
        _reject_comments(sql)
        statements = [s for s in sqlglot.parse(sql, read="duckdb") if s is not None]
    except SqlglotError as exc:
        raise QueryRejected("SQL could not be parsed: " + str(exc).splitlines()[0][:200]) from exc

    if len(statements) != 1:
        raise QueryRejected(f"Expected exactly one statement, found {len(statements)}")
    tree = statements[0]
    if not isinstance(tree, exp.Select):
        raise QueryRejected(f"Only SELECT is allowed, found {type(tree).__name__.upper()}")

    _reject_writes(tree)
    _check_tables(tree, allowed_tables)
    _check_functions(tree)
    _apply_row_limit(tree, row_limit)
    return tree.sql(dialect="duckdb")


def _reject_comments(sql: str) -> None:
    """No comments at all: an agent never needs them, and they are how statements get hidden."""
    if any(token.comments for token in sqlglot.tokenize(sql, read="duckdb")):
        raise QueryRejected("Comments are not allowed")


def _reject_writes(tree: exp.Select) -> None:
    if tree.find(exp.Into):
        raise QueryRejected("SELECT INTO is not allowed")
    if tree.args.get("locks"):
        raise QueryRejected("Locking clauses are not allowed")
    write = tree.find(*WRITE_NODES)
    if write:
        raise QueryRejected(f"{type(write).__name__.upper()} is not allowed")


def _check_tables(tree: exp.Select, allowed_tables: frozenset[str]) -> None:
    cte_names = {cte.alias.lower() for cte in tree.find_all(exp.CTE)}
    for table in tree.find_all(exp.Table):
        if not isinstance(table.this, exp.Identifier):  # read_csv(...), range(...), query(...)
            raise QueryRejected(f"Table functions are not allowed: {table.this.sql(dialect='duckdb')[:80]}")
        if not table.db and not table.catalog and table.name.lower() in cte_names:
            continue
        name = ".".join(part.name for part in table.parts).lower()
        if name not in allowed_tables:
            raise QueryRejected(f"Table '{name}' is not in the catalog. Use schema.table, for example "
                                "mart.vw_sales_monthly.")


def _check_functions(tree: exp.Select) -> None:
    for function in tree.find_all(exp.Func):
        name = function.name if isinstance(function, exp.Anonymous) else function.sql_name()
        if name.upper() not in ALLOWED_FUNCTIONS:
            raise QueryRejected(f"Function '{name}' is not allowed")


def _apply_row_limit(tree: exp.Select, row_limit: int) -> None:
    """Lower the query's own LIMIT if needed; add one if it has none."""
    fetch = row_limit + 1
    existing = tree.args.get("limit")
    if existing is not None:
        value = existing.expression if isinstance(existing, exp.Limit) else None
        if not isinstance(value, exp.Literal) or not value.is_int or existing.args.get("limit_options"):
            raise QueryRejected("LIMIT must be a plain whole number")  # not -1, 50%, ALL or a subquery
        fetch = min(int(value.name), fetch)
    tree.limit(fetch, copy=False)
