"""Request and response models. They also generate the documentation at /docs."""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from serving.core.config import MAX_ROW_LIMIT


class QueryRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # No max_length here: oversized SQL must reach the guard so that it is audited.
    sql: str = Field(min_length=1, description="One SELECT in DuckDB dialect, using schema.table names.")
    limit: int | None = Field(default=None, ge=1, le=MAX_ROW_LIMIT, description="Maximum rows; default 500.")


class Health(BaseModel):
    status: str
    backend: str


class DatasetSummary(BaseModel):
    name: str
    description: str
    grain: str
    layer: str
    owner: str


class Column(BaseModel):
    name: str
    type: str
    definition: str


class DatasetDetail(DatasetSummary):
    source: str
    row_count: int
    columns: list[Column]


class QueryResponse(BaseModel):
    columns: list[str]
    rows: list[dict[str, Any]]
    row_count: int
    row_limit: int
    truncated: bool
    duration_ms: float


class PipelineRun(BaseModel):
    run_id: str
    pipeline_name: str
    batch_id: str | None
    trigger_source: str
    status: str
    started_at_utc: str
    ended_at_utc: str | None


class QualityCheck(BaseModel):
    check_name: str
    check_category: str
    target_object: str
    severity: str
    failed_rows: int
    status: str
    description: str


class DataQuality(BaseModel):
    summary: dict[str, int]
    checks: list[QualityCheck]


class PipelineStatus(BaseModel):
    latest_run: PipelineRun | None
    data_quality: DataQuality


class ErrorResponse(BaseModel):
    detail: str
