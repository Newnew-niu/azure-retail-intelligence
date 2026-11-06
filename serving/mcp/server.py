"""MCP server for AI agents, over stdio. All logic is in serving/core.

    python -m serving.mcp.server        (from the repository root)

The server never calls an LLM. The agent's client turns a person's question into these tool
calls. Stdout carries the MCP protocol, so nothing else may print to it. There is no API key:
stdio means the client starts this process itself, so the boundary is the local machine.
"""
from __future__ import annotations

import json
from collections.abc import Callable
from typing import TypeVar

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp_types import ToolAnnotations

from serving.core.config import Settings
from serving.core.errors import ServingError
from serving.core.service import DataService

CATALOG_URI = "catalog://retail-intelligence"
READ_ONLY = ToolAnnotations(readOnlyHint=True, destructiveHint=False, openWorldHint=False)
T = TypeVar("T")


def explain_errors(call: Callable[[], T]) -> T:
    """The SDK hides ordinary exceptions as a crash. ToolError passes the message on, so the
    agent can read why a query was refused and fix its SQL."""
    try:
        return call()
    except ServingError as exc:
        raise ToolError(str(exc)) from exc


def instructions(service: DataService) -> str:
    window = service.catalog.content["reporting_window"]
    return (
        "Governed data from a Brazilian e-commerce warehouse (Olist). Money is in BRL.\n"
        "Work in this order: list_datasets, then describe_dataset for each dataset you will use, "
        "then run_query. Read the grain and the column definitions before you write SQL.\n"
        "Prefer mart views. Use dw facts and dimensions when you need a slice the views do not offer.\n"
        f"Reporting window: purchase_date_key {window['first_purchase_date_key']} to "
        f"{window['last_purchase_date_key']}. {window['note']}\n"
        "Say which date range and filters a number covers. Do not state causes: the data shows associations."
    )


def build_server(service: DataService) -> MCPServer:
    server = MCPServer(name="retail-intelligence", instructions=instructions(service))

    @server.tool(annotations=READ_ONLY)
    def list_datasets() -> list[dict]:
        """List every dataset you can query, with its description, grain, layer and owner.

        Call this first. Only these datasets exist; other tables are not reachable.
        """
        return explain_errors(service.list_datasets)

    @server.tool(annotations=READ_ONLY)
    def describe_dataset(name: str) -> dict:
        """Describe one dataset: column names, types and definitions, grain, source and row count.

        Call this before querying a dataset, so that you do not guess column names or double count.

        Args:
            name: Full dataset name from list_datasets, for example mart.vw_sales_monthly.
        """
        return explain_errors(lambda: service.describe_dataset(name))

    @server.tool(annotations=READ_ONLY)
    def run_query(sql: str, limit: int | None = None) -> dict:
        """Run one read-only SELECT in DuckDB dialect and return rows as JSON.

        Rules: exactly one SELECT, no comments, no top-level UNION (wrap it in a subquery), and
        schema.table names from list_datasets only. Common aggregate, date, text and window
        functions are available; other functions are refused with a message saying which one.
        Check `truncated` in the result: true means more rows existed than were returned.
        Filter or aggregate instead of fetching detail rows. If a query is refused, read the
        reason and change the SQL.

        Args:
            sql: The SELECT statement.
            limit: Maximum rows to return. The default is 500 and the maximum is 5000.
        """
        return explain_errors(lambda: service.run_query(sql, client="mcp", limit=limit))

    @server.tool(annotations=READ_ONLY)
    def get_pipeline_status() -> dict:
        """Return the latest pipeline run and its data quality results.

        Use this to judge how fresh and trustworthy the data is, or to answer questions about
        data quality. A check with status WARN is a known source anomaly. FAIL means the numbers
        may be wrong, so tell the user.
        """
        return explain_errors(service.get_pipeline_status)

    @server.resource(CATALOG_URI, name="data-catalog", mime_type="application/json",
                     description="The full catalog: datasets, columns, KPI definitions and reporting window.")
    def catalog() -> str:
        return json.dumps(service.catalog.content, ensure_ascii=False)

    return server


def main() -> None:
    build_server(DataService(Settings.from_env())).run("stdio")


if __name__ == "__main__":
    main()
