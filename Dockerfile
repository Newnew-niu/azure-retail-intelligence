# The FastAPI service with the DuckDB backend. The data is mounted at run time and is never in
# the image (licence: CC BY-NC-SA). The azuresql backend is not included: it needs ODBC drivers.
FROM python:3.10-slim

WORKDIR /app
COPY serving/requirements.txt serving/requirements.txt
RUN pip install --no-cache-dir -r serving/requirements.txt
COPY serving/ serving/

# Run as an unprivileged user that owns only the audit log folder.
RUN useradd --system --no-create-home serving \
    && mkdir -p /var/log/serving \
    && chown serving /var/log/serving
USER serving

ENV SERVING_DUCKDB_PATH=/data/serving.duckdb \
    SERVING_AUDIT_PATH=/var/log/serving/serving_audit.jsonl \
    PYTHONUNBUFFERED=1
EXPOSE 8000
HEALTHCHECK --interval=5s --timeout=3s --start-period=10s --retries=5 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=2)"]

CMD ["uvicorn", "serving.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
