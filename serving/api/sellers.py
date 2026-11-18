"""Seller endpoints. Read-only fixed queries, so they are open without an API key.

Callers choose values, never SQL, and every value is validated here before serving/core sees
it: a wrong type, pattern or range is a 422. Why these endpoints are public while /query is
not is explained in docs/seller_health_decisions.md.
"""
from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Path, Query

from serving.api.schemas import SELLER_ID_PATTERN, ErrorResponse, SellerDetail, SellerPage
from serving.core.sellers import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE, SellerService

MAX_PAGE = 10_000  # far beyond the ~3,000 sellers; stops absurd OFFSET values
ERRORS = {503: {"model": ErrorResponse, "description": "Database unavailable"},
          504: {"model": ErrorResponse, "description": "Query cancelled by the timeout"}}


def create_sellers_router(sellers: SellerService) -> APIRouter:
    router = APIRouter(prefix="/sellers", tags=["sellers"])

    @router.get("", response_model=SellerPage, responses=ERRORS)
    def list_sellers(
        page: int = Query(1, ge=1, le=MAX_PAGE),
        page_size: int = Query(DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
        state: str | None = Query(None, pattern=r"^[A-Z]{2}$", description="Two-letter seller state"),
        q: str | None = Query(None, pattern=r"^[0-9a-f]{1,32}$", description="Start of the seller id"),
        sort: Literal["product_sales", "orders", "late_rate", "review_score"] = "product_sales",
        order: Literal["asc", "desc"] = "desc",
    ) -> dict:
        """Sellers with sales in the reporting window, with their KPIs. Empty KPIs sort last."""
        return sellers.list_sellers(page=page, page_size=page_size, state=state, prefix=q,
                                    sort=sort, order=order)

    @router.get("/{seller_id}", response_model=SellerDetail,
                responses={**ERRORS, 404: {"model": ErrorResponse, "description": "No sales for this seller"}})
    def get_seller(seller_id: str = Path(pattern=SELLER_ID_PATTERN)) -> dict:
        """One seller: KPIs, a monthly trend and illustrative health signals (not a credit score)."""
        return sellers.get_seller(seller_id)

    return router
