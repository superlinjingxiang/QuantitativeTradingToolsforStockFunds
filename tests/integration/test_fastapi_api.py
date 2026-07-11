"""FastAPI compatibility and OpenAPI contract tests."""

from __future__ import annotations

from fastapi.testclient import TestClient

from china_quant_platform.api.app import create_app
from china_quant_platform.infrastructure.cache_backend import MemoryCacheBackend


class FakeApiService:
    def health(self) -> dict[str, object]:
        return {"ok": True, "service": "fake", "provider": "fake"}

    def search(self, query: str) -> dict[str, object]:
        return {"ok": True, "query": query, "candidates": []}

    def market_overview(self) -> dict[str, object]:
        return {
            "ok": True,
            "marketOverview": {
                "indices": [
                    {
                        "security_id": "SSE:000001",
                        "name": "上证指数",
                        "latest_value": "3000.00",
                        "change_pct": "+1.00%",
                    }
                ],
                "data_health_text": "HEALTHY",
            },
        }

    def analyze(self, payload: dict[str, object]) -> dict[str, object]:
        return {
            "ok": True,
            "selectedSecurity": {"security_id": payload.get("query", "SSE:513300")},
            "chart": {"points": [], "signals": []},
            "analysis": {},
            "decision": {},
            "backtest": {},
            "accountAssessment": {},
            "marketOverview": {},
        }

    def recommendations(self, _payload: dict[str, object]) -> dict[str, object]:
        return {"ok": True, "summary": {"candidateCount": 0}, "candidates": [], "failures": []}


def test_fastapi_keeps_legacy_routes_and_openapi() -> None:
    app = create_app(service=FakeApiService(), cache_backend=MemoryCacheBackend())
    with TestClient(app) as client:
        assert client.get("/api/health").json()["provider"] == "fake"
        assert client.get("/api/search?q=513300").json()["query"] == "513300"
        first_overview = client.get("/api/market-overview").json()
        second_overview = client.get("/api/market-overview").json()
        assert first_overview["marketOverview"]["indices"][0]["name"] == "上证指数"
        assert first_overview["cache"]["status"] == "MISS"
        assert second_overview["cache"]["status"] == "HIT"
        analysis = client.post("/api/analyze", json={"query": "513300"})
        assert analysis.status_code == 200
        assert "accountAssessment" in analysis.json()
        assert client.post("/api/recommendations", json={}).json()["ok"] is True
        openapi = client.get("/openapi.json").json()
        assert "/api/analyze" in openapi["paths"]
        assert "/api/recommendations" in openapi["paths"]
        assert "/api/market-overview" in openapi["paths"]


def test_fastapi_validation_uses_safe_json_error_shape() -> None:
    app = create_app(service=FakeApiService(), cache_backend=MemoryCacheBackend())
    with TestClient(app) as client:
        response = client.post("/api/analyze", json={"maxTrades": 0})
        assert response.status_code == 422
        assert response.json()["ok"] is False
        assert response.json()["error"] == "请求参数无效"
