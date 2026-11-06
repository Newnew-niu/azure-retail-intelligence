"""REST API for applications. All logic is in serving/core; this file only translates HTTP.

    SERVING_API_KEY=<key> uvicorn serving.api.main:app

Endpoints are plain `def`, so FastAPI runs them on a thread pool and a slow query does not
block the others.
"""
from __future__ import annotations

import secrets

from fastapi import Depends, FastAPI, HTTPException, Request, Security, status
from fastapi.responses import JSONResponse
from fastapi.security import APIKeyHeader

from serving.api.schemas import (DatasetDetail, DatasetSummary, ErrorResponse, Health, PipelineStatus,
                                 QueryRequest, QueryResponse)
from serving.core.config import Settings
from serving.core.errors import (DatabaseUnavailable, DatasetNotFound, QueryFailed, QueryRejected,
                                 QueryTimedOut, ServingError)
from serving.core.service import DataService

API_KEY_HEADER = APIKeyHeader(name="X-API-Key", auto_error=False, description="Key from SERVING_API_KEY")
STATUS_BY_ERROR = {
    QueryRejected: status.HTTP_400_BAD_REQUEST,
    QueryFailed: status.HTTP_400_BAD_REQUEST,
    DatasetNotFound: status.HTTP_404_NOT_FOUND,
    DatabaseUnavailable: status.HTTP_503_SERVICE_UNAVAILABLE,
    QueryTimedOut: status.HTTP_504_GATEWAY_TIMEOUT,
}
AUTH_RESPONSES = {401: {"model": ErrorResponse, "description": "Missing or wrong API key"}}
QUERY_RESPONSES = {**AUTH_RESPONSES,
                   400: {"model": ErrorResponse, "description": "SQL rejected by a safety rule, or it failed"},
                   503: {"model": ErrorResponse, "description": "Database unavailable"},
                   504: {"model": ErrorResponse, "description": "Query cancelled by the timeout"}}


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings.from_env()
    service = DataService(settings)
    app = FastAPI(title="Retail Intelligence Data API", version="1.0.0",
                  description="Discover and query the governed datasets of the retail warehouse.")

    def require_api_key(key: str | None = Security(API_KEY_HEADER)) -> None:
        # compare_digest takes the same time wherever the strings differ, which stops timing
        # attacks. An unset server key refuses everyone rather than letting everyone in.
        if not settings.api_key or not key or not secrets.compare_digest(key.encode(), settings.api_key.encode()):
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Missing or invalid API key",
                                headers={"WWW-Authenticate": "ApiKey"})

    @app.exception_handler(ServingError)
    def serving_error(_: Request, exc: ServingError) -> JSONResponse:
        return JSONResponse(status_code=STATUS_BY_ERROR[type(exc)], content={"detail": str(exc)})

    protected = [Depends(require_api_key)]

    @app.get("/health", response_model=Health, tags=["operations"])
    def health() -> dict:
        """Liveness check, open without a key. It does not touch the database, so that it never
        wakes a paused serverless Azure SQL database."""
        return {"status": "ok", "backend": service.backend.name}

    @app.get("/datasets", response_model=list[DatasetSummary], dependencies=protected,
             responses=AUTH_RESPONSES, tags=["catalog"])
    def list_datasets() -> list[dict]:
        """List the datasets that can be queried."""
        return service.list_datasets()

    @app.get("/datasets/{name}", response_model=DatasetDetail, dependencies=protected, tags=["catalog"],
             responses={**AUTH_RESPONSES, 404: {"model": ErrorResponse, "description": "Unknown dataset"}})
    def describe_dataset(name: str) -> dict:
        """Describe one dataset: columns, definitions, grain, source and row count."""
        return service.describe_dataset(name)

    @app.post("/query", response_model=QueryResponse, dependencies=protected,
              responses=QUERY_RESPONSES, tags=["query"])
    def run_query(request: QueryRequest) -> dict:
        """Run one read-only SELECT on catalog datasets. Every attempt is audited."""
        return service.run_query(request.sql, client="api", limit=request.limit)

    @app.get("/runs/latest", response_model=PipelineStatus, dependencies=protected,
             responses=AUTH_RESPONSES, tags=["operations"])
    def latest_run() -> dict:
        """Latest pipeline run and its data quality results."""
        return service.get_pipeline_status()

    return app


app = create_app()
