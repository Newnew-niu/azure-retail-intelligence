"""Request and response models. They also generate the documentation at /docs."""
from __future__ import annotations

from typing import Any, Literal

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


SELLER_ID_PATTERN = r"^[0-9a-f]{32}$"


class SellerKpis(BaseModel):
    orders: int = Field(description="Sales orders that include the seller's items")
    items_sold: int
    product_sales: float = Field(description="Sum of item prices in BRL, excluding freight")
    average_order_value: float | None = Field(description="Seller's price + freight per order, in BRL")
    late_rate: float | None = Field(
        description="Dispatched orders handed to the carrier after the shipping deadline / dispatched orders")
    review_score: float | None = Field(description="Mean review score of orders with a review, 1 to 5")


class SellerListItem(SellerKpis):
    seller_id: str
    seller_state: str | None


class SellerPage(BaseModel):
    items: list[SellerListItem]
    page: int
    page_size: int
    total: int = Field(description="Sellers that match the filters")
    total_pages: int
    sort: str
    order: str


class SellerSummary(SellerKpis):
    dispatched_orders: int
    reviewed_orders: int


class SellerMonth(SellerSummary):
    year_month: str = Field(description="Purchase month, yyyy-mm")


class HealthSignal(BaseModel):
    key: Literal["sales_trend", "late_dispatch", "review_score"]
    label: str
    status: Literal["positive", "neutral", "attention", "insufficient_data"]
    value: float | None = Field(description="Change, rate or score the status is based on")
    summary: str = Field(description="The result in one sentence, with the numbers behind it")
    rule: str = Field(description="The fixed rule and thresholds")


class ReportingWindow(BaseModel):
    first_month: str
    last_month: str


class SellerDetail(BaseModel):
    seller_id: str
    seller_state: str | None
    window: ReportingWindow
    summary: SellerSummary
    monthly: list[SellerMonth] = Field(description="Every month of the window, zeros included")
    signals: list[HealthSignal]
    disclaimer: str
