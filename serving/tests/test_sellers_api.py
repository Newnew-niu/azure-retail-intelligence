"""The seller endpoints through the HTTP stack: public read-only access, validation and CORS."""
from dataclasses import replace

import pytest
from fastapi.testclient import TestClient

from serving.api.main import create_app
from serving.tests.seller_data import A, A2, B, C, D

WEB_ORIGIN = "http://localhost:5173"


@pytest.fixture
def client(seller_settings) -> TestClient:
    return TestClient(create_app(seller_settings))


def test_sellers_are_public_and_need_no_key(client):
    response = client.get("/sellers")
    assert response.status_code == 200
    body = response.json()
    assert [i["seller_id"] for i in body["items"]] == [A, C, B, A2]
    assert {k: body[k] for k in ("page", "page_size", "total", "total_pages", "sort", "order")} == {
        "page": 1, "page_size": 25, "total": 4, "total_pages": 1, "sort": "product_sales", "order": "desc"}


def test_query_parameters_reach_the_service(client):
    body = client.get("/sellers", params={"state": "SP", "q": "aaa", "sort": "orders", "order": "asc",
                                          "page_size": 1, "page": 2}).json()
    assert ([i["seller_id"] for i in body["items"]], body["total"], body["total_pages"]) == ([A], 2, 2)


def test_a_page_after_the_last_is_200_and_empty(client):
    body = client.get("/sellers", params={"page": 99}).json()
    assert (body["items"], body["total"]) == ([], 4)


def test_no_match_is_200_and_empty(client):
    assert client.get("/sellers", params={"state": "AC"}).json()["items"] == []


@pytest.mark.parametrize("params", [
    {"sort": "seller_id"}, {"sort": "price; DROP TABLE x"}, {"order": "up"},
    {"page": 0}, {"page": 10_001}, {"page": "two"},
    {"page_size": 0}, {"page_size": 101},
    {"state": "sp"}, {"state": "SPX"},
    {"q": "AAA"}, {"q": "a%"}, {"q": "a_"}, {"q": "a" * 33},
])
def test_invalid_list_parameters_get_422(client, params):
    assert client.get("/sellers", params=params).status_code == 422


@pytest.mark.parametrize("seller_id", ["abc", "A" * 32, "a" * 31 + "%", "g" * 32])
def test_a_malformed_seller_id_gets_422(client, seller_id):
    assert client.get(f"/sellers/{seller_id}").status_code == 422


def test_seller_detail(client):
    response = client.get(f"/sellers/{A}")
    assert response.status_code == 200
    body = response.json()
    assert (body["seller_id"], body["seller_state"], body["summary"]["orders"]) == (A, "SP", 13)
    assert len(body["monthly"]) == 20
    assert [s["status"] for s in body["signals"]] == ["positive", "neutral", "positive"]
    assert "not a credit score" in body["disclaimer"]


def test_an_unknown_seller_gets_404_with_a_reason(client):
    response = client.get(f"/sellers/{D}")
    assert response.status_code == 404
    assert "no sales orders in the reporting window" in response.json()["detail"]


def test_a_missing_database_gets_503(seller_settings, tmp_path):
    client = TestClient(create_app(replace(seller_settings, duckdb_path=tmp_path / "missing.duckdb")))
    assert client.get("/sellers").status_code == 503
    assert client.get(f"/sellers/{A}").status_code == 503


def test_the_seller_endpoints_are_in_the_openapi_schema(client):
    paths = client.get("/openapi.json").json()["paths"]
    assert {"/sellers", "/sellers/{seller_id}"} <= set(paths)
    assert "post" not in paths["/sellers"]


def test_query_still_needs_the_key_next_to_the_public_endpoints(client):
    assert client.post("/query", json={"sql": "SELECT 1"}).status_code == 401
    assert client.get("/datasets").status_code == 401


def test_no_cors_headers_unless_origins_are_configured(client):
    response = client.get("/sellers", headers={"Origin": WEB_ORIGIN})
    assert "access-control-allow-origin" not in response.headers


class TestCors:
    @pytest.fixture
    def client(self, seller_settings) -> TestClient:
        return TestClient(create_app(replace(seller_settings, cors_origins=(WEB_ORIGIN,))))

    def test_a_listed_origin_may_read_sellers(self, client):
        response = client.get("/sellers", headers={"Origin": WEB_ORIGIN})
        assert response.headers["access-control-allow-origin"] == WEB_ORIGIN

    def test_another_origin_gets_no_permission(self, client):
        response = client.get("/sellers", headers={"Origin": "https://example.com"})
        assert "access-control-allow-origin" not in response.headers

    def test_a_browser_may_not_send_the_api_key_header(self, client):
        preflight = client.options("/query", headers={"Origin": WEB_ORIGIN, "Access-Control-Request-Method": "POST",
                                                      "Access-Control-Request-Headers": "x-api-key"})
        assert preflight.status_code == 400
        assert "x-api-key" not in preflight.headers.get("access-control-allow-headers", "").lower()


def test_cors_origins_are_read_from_the_environment(monkeypatch):
    from serving.core.config import Settings
    monkeypatch.setenv("SERVING_CORS_ORIGINS", " http://localhost:5173 , https://example.github.io ,")
    assert Settings.from_env().cors_origins == ("http://localhost:5173", "https://example.github.io")
    monkeypatch.setenv("SERVING_CORS_ORIGINS", "")
    assert Settings.from_env().cors_origins == ()
