#!/usr/bin/env bash
# Builds the image and checks the running container on synthetic data. CI runs this from the
# repository root. It needs Docker and the packages in serving/requirements-test.txt.
set -euo pipefail

export SERVING_API_KEY=ci-key
URL=http://127.0.0.1:8000

python -c "from pathlib import Path; from serving.tests.conftest import build_fixture_database; \
build_fixture_database(Path('data/serving.duckdb'))"

trap 'docker compose down --volumes' EXIT
docker compose up --build --detach --wait --wait-timeout 60

expect_status() {  # expected_status curl_arguments...
    local expected=$1 actual
    shift
    actual=$(curl --silent --output /dev/null --write-out '%{http_code}' "$@")
    echo "$actual (expected $expected): ${*: -1}"
    [ "$actual" = "$expected" ]
}
query() {  # expected_status sql
    expect_status "$1" --header "X-API-Key: $SERVING_API_KEY" --header 'Content-Type: application/json' \
        --data "{\"sql\": \"$2\"}" "$URL/query"
}

expect_status 200 "$URL/health"
expect_status 401 "$URL/datasets"
expect_status 200 --header "X-API-Key: $SERVING_API_KEY" "$URL/datasets"
expect_status 200 --header "X-API-Key: $SERVING_API_KEY" "$URL/runs/latest"
query 200 'SELECT COUNT(*) AS n FROM mart.vw_sales_monthly'
query 400 'DROP TABLE dw.fact_orders'
query 400 "SELECT * FROM read_csv('/etc/passwd')"

curl --silent --header "X-API-Key: $SERVING_API_KEY" --header 'Content-Type: application/json' \
    --data '{"sql": "SELECT COUNT(*) AS n FROM mart.vw_sales_monthly"}' "$URL/query" | grep --quiet '"n":2'
docker compose exec -T api test -s /var/log/serving/serving_audit.jsonl
docker compose exec -T api test ! -e /app/data  # no data was baked into the image

# A clean stop: 137 would mean Docker had to kill it after the timeout.
container=$(docker compose ps --all --quiet api)
docker compose stop --timeout 10 api
exit_code=$(docker inspect --format '{{.State.ExitCode}}' "$container")
echo "exit code after SIGTERM: $exit_code"
[ "$exit_code" = 0 ] || [ "$exit_code" = 143 ]
! docker compose logs api | grep --quiet 'Fatal Python'

echo "Docker smoke test passed"
