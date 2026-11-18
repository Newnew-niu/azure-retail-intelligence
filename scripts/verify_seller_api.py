"""Check the hosted seller API against the local DuckDB export, and its access rules.

Every response of the hosted API must be identical to the same request answered locally from
data/serving.duckdb, the file that infra/seller_api.sh uploaded. The script also checks that the
protected endpoints refuse a request without a key, that bad parameters get 422, and that CORS
allows the GitHub Pages origin only.

Usage, from the repository root:
    .venv/Scripts/python scripts/verify_seller_api.py https://<app>.<region>.azurecontainerapps.io
The first request can take a few seconds while the app scales up from zero.
"""
from __future__ import annotations

import json
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from fastapi.testclient import TestClient  # noqa: E402

from serving.api.main import create_app  # noqa: E402
from serving.core.config import Settings  # noqa: E402

PAGES_ORIGIN = "https://newnew-niu.github.io"
LIST_REQUESTS = [
    "/sellers",
    "/sellers?page_size=100",
    "/sellers?page_size=100&page=31",
    "/sellers?state=RJ&sort=late_rate&order=asc&page=2",
    "/sellers?sort=review_score&order=asc&page=121",
    "/sellers?sort=orders&state=MG",
    "/sellers?q=4a3c",
    "/sellers?state=AC",
    "/sellers?page=500",
]


def fetch(base: str, path: str, headers: dict[str, str] | None = None) -> tuple[int, dict, bytes]:
    request = urllib.request.Request(base + path, headers=headers or {})
    try:
        with urllib.request.urlopen(request, timeout=90) as response:
            return response.status, dict(response.headers), response.read()
    except urllib.error.HTTPError as error:
        return error.code, dict(error.headers), error.read()


def main(base: str) -> int:
    base = base.rstrip("/")
    results: list[tuple[bool, str]] = []

    def check(passed: bool, label: str) -> None:
        results.append((passed, label))
        print(("PASS " if passed else "FAIL ") + label)

    started = time.perf_counter()
    status, _, _ = fetch(base, "/health")
    check(status == 200, f"/health answers ({time.perf_counter() - started:.1f} s, including any cold start)")

    audit = Path(tempfile.mkdtemp()) / "audit.jsonl"
    local = TestClient(create_app(Settings(audit_path=audit)))

    first_page = local.get("/sellers?page_size=5").json()["items"]
    detail_requests = [f"/sellers/{item['seller_id']}" for item in first_page]
    for path in LIST_REQUESTS + detail_requests:
        status, _, body = fetch(base, path)
        expected = local.get(path)
        check(status == expected.status_code and json.loads(body) == expected.json(), f"identical: {path}")

    for path, expected_status in [("/sellers?sort=seller_id", 422), ("/sellers?q=XYZ", 422),
                                  ("/sellers/not-a-seller", 422), (f"/sellers/{'f' * 32}", 404),
                                  ("/datasets", 401), ("/runs/latest", 401)]:
        status, _, _ = fetch(base, path)
        check(status == expected_status, f"{path} -> {expected_status}")

    _, headers, _ = fetch(base, "/sellers?page_size=1", {"Origin": PAGES_ORIGIN})
    allowed = {key.lower(): value for key, value in headers.items()}.get("access-control-allow-origin")
    check(allowed == PAGES_ORIGIN, "CORS allows the GitHub Pages origin")
    _, headers, _ = fetch(base, "/sellers?page_size=1", {"Origin": "https://example.com"})
    check("access-control-allow-origin" not in {key.lower() for key in headers}, "CORS refuses another origin")

    passed = sum(ok for ok, _ in results)
    print(f"\n{passed} of {len(results)} checks passed")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    sys.exit(main(sys.argv[1]))
