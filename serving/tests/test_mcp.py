"""The MCP server: in memory for detail, and once over real stdio in a subprocess."""
import asyncio
import json
import os
import sys
from pathlib import Path

import pytest
from mcp.client import Client
from mcp.client.stdio import StdioServerParameters

from serving.mcp.server import CATALOG_URI, build_server

PROJECT_ROOT = Path(__file__).resolve().parents[2]
TOOLS = {"list_datasets", "describe_dataset", "run_query", "get_pipeline_status"}


def with_client(target, work):
    """Open a client on `target`, run `work(client)` and return its result."""
    async def run():
        async with Client(target) as client:
            return await work(client)
    return asyncio.run(run())


def payload(result) -> object:
    """A tool's result as Python data; list results come wrapped as {"result": [...]}."""
    assert not result.is_error, result.content
    data = result.structured_content
    if data is None:
        return json.loads(result.content[0].text)  # dict results arrive as JSON text
    return data["result"] if set(data) == {"result"} else data


def call(server, tool: str, **arguments):
    return with_client(server, lambda client: client.call_tool(tool, arguments))


@pytest.fixture
def server(service):
    return build_server(service)


def test_the_four_tools_are_listed_with_descriptions(server):
    tools = with_client(server, lambda client: client.list_tools()).tools
    assert {tool.name for tool in tools} == TOOLS
    assert all(len(tool.description) > 40 for tool in tools)


def test_every_tool_is_marked_read_only(server):
    tools = with_client(server, lambda client: client.list_tools()).tools
    assert all(tool.annotations.read_only_hint for tool in tools)


def test_list_datasets_tool(server, service):
    names = {d["name"] for d in payload(call(server, "list_datasets"))}
    assert names == set(service.catalog.datasets)


def test_describe_dataset_tool(server):
    dataset = payload(call(server, "describe_dataset", name="mart.vw_sales_monthly"))
    assert dataset["row_count"] == 2 and dataset["columns"][0]["definition"]


def test_describe_dataset_tool_reports_an_unknown_dataset(server):
    result = call(server, "describe_dataset", name="ops.dq_result")
    assert result.is_error and "Unknown dataset" in result.content[0].text


def test_run_query_tool(server):
    body = payload(call(server, "run_query", sql="SELECT COUNT(*) AS n FROM mart.vw_sales_monthly"))
    assert body["rows"] == [{"n": 2}]


def test_run_query_tool_honours_the_limit(server):
    body = payload(call(server, "run_query", sql="SELECT * FROM dw.fact_payments", limit=3))
    assert (body["row_count"], body["truncated"]) == (3, True)


@pytest.mark.parametrize("sql, reason", [
    ("DROP TABLE dw.fact_orders", "Only SELECT"),
    ("SELECT 1; SELECT 2", "exactly one statement"),
    ("SELECT * FROM read_csv('.env')", "not allowed"),
    ("SELECT * FROM ops.dq_result", "not in the catalog"),
])
def test_run_query_tool_gives_the_agent_the_reason_for_a_refusal(server, sql, reason):
    result = call(server, "run_query", sql=sql)
    assert result.is_error and reason in result.content[0].text


def test_pipeline_status_tool(server):
    assert payload(call(server, "get_pipeline_status"))["latest_run"]["run_id"] == "run_new"


def test_the_catalog_is_a_resource(server, service):
    async def read(client):
        listed = await client.list_resources()
        return listed.resources, await client.read_resource(CATALOG_URI)
    resources, content = with_client(server, read)
    assert [str(resource.uri) for resource in resources] == [CATALOG_URI]
    assert json.loads(content.contents[0].text) == service.catalog.content


def test_the_instructions_warn_about_the_reporting_window(service):
    text = build_server(service).instructions
    assert "20170101" in text and "20180831" in text and "list_datasets" in text


def test_mcp_queries_are_audited_as_mcp(server, service):
    call(server, "run_query", sql="SELECT 1")
    call(server, "run_query", sql="DROP TABLE x")
    lines = service.audit.path.read_text(encoding="utf-8").splitlines()
    assert [(json.loads(line)["client"], json.loads(line)["status"]) for line in lines] == [
        ("mcp", "ok"), ("mcp", "rejected")]


def test_the_server_works_over_real_stdio(settings):
    """Starts `python -m serving.mcp.server` the way a client does. Anything stray on stdout
    would corrupt the protocol, so this also proves stdout stays clean."""
    parameters = StdioServerParameters(
        command=sys.executable, args=["-m", "serving.mcp.server"], cwd=PROJECT_ROOT,
        env={**os.environ, "SERVING_BACKEND": "duckdb", "SERVING_DUCKDB_PATH": str(settings.duckdb_path),
             "SERVING_AUDIT_PATH": str(settings.audit_path)})

    async def work(client):
        tools = await client.list_tools()
        return tools, await client.call_tool("run_query", {"sql": "SELECT orders FROM mart.vw_payment_mix ORDER BY 1"})

    tools, result = with_client(parameters, work)
    assert {tool.name for tool in tools.tools} == TOOLS
    assert payload(result)["rows"] == [{"orders": 1}, {"orders": 2}]
    assert json.loads(settings.audit_path.read_text(encoding="utf-8"))["client"] == "mcp"
