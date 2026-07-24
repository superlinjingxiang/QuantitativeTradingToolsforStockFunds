"""FastAPI application exposing the existing analysis service."""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any, cast

from fastapi import Depends, FastAPI, Query, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from china_quant_platform.api.schemas import ApiPayload, RecommendationPayload
from china_quant_platform.electron_api import ElectronBackendService
from china_quant_platform.infrastructure.cache_backend import CacheBackend, build_cache_backend
from china_quant_platform.infrastructure.cached_service import CachedApplicationService


def create_app(
    *,
    service: Any | None = None,
    cache_backend: CacheBackend | None = None,
) -> FastAPI:
    raw_service = service or ElectronBackendService()
    supplied_backend = cache_backend

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        backend = supplied_backend or await build_cache_backend(dict(os.environ))
        app.state.service = CachedApplicationService(raw_service, backend)
        yield
        await backend.close()

    app = FastAPI(
        title="中国股票与基金量化分析平台 API",
        version="0.2.0",
        description="行情、策略、预测、回测、荐股和手动账户评估服务。",
        lifespan=lifespan,
    )

    @app.exception_handler(RequestValidationError)
    async def validation_error(_request: Request, exc: RequestValidationError) -> JSONResponse:
        return JSONResponse(
            status_code=422,
            content={"ok": False, "error": "请求参数无效", "details": exc.errors()},
        )

    @app.exception_handler(Exception)
    async def internal_error(_request: Request, exc: Exception) -> JSONResponse:
        return JSONResponse(
            status_code=400,
            content={"ok": False, "error": str(exc)[:500], "retryable": True},
        )

    @app.get("/api/health")
    async def health(
        service_adapter: CachedApplicationService = Depends(_service),  # noqa: B008
    ) -> dict[str, Any]:
        return await service_adapter.health()

    @app.get("/api/search")
    async def search(
        q: str = Query(default="", max_length=120),
        service_adapter: CachedApplicationService = Depends(_service),  # noqa: B008
    ) -> dict[str, Any]:
        return await service_adapter.search(q)

    @app.get("/api/quote")
    async def quote(
        response: Response,
        q: str = Query(min_length=1, max_length=120),
        service_adapter: CachedApplicationService = Depends(_service),  # noqa: B008
    ) -> dict[str, Any]:
        response.headers["Cache-Control"] = "no-store"
        return await service_adapter.quote(q)

    @app.get("/api/market-overview")
    async def market_overview(
        service_adapter: CachedApplicationService = Depends(_service),  # noqa: B008
    ) -> dict[str, Any]:
        return await service_adapter.market_overview()

    @app.post("/api/analyze")
    async def analyze(
        payload: ApiPayload,
        service_adapter: CachedApplicationService = Depends(_service),  # noqa: B008
    ) -> dict[str, Any]:
        return await service_adapter.analyze(payload.to_payload())

    @app.post("/api/recommendations")
    async def recommendations(
        payload: RecommendationPayload,
        service_adapter: CachedApplicationService = Depends(_service),  # noqa: B008
    ) -> dict[str, Any]:
        return await service_adapter.recommendations(payload.to_payload())

    @app.get("/api/cache/status")
    async def cache_status(request: Request) -> dict[str, Any]:
        adapter: CachedApplicationService = request.app.state.service
        backend_name = type(adapter.backend).__name__
        return {
            "ok": True,
            "backend": backend_name,
            "namespace": os.getenv("CQP_CACHE_NAMESPACE", "china_quant_platform"),
        }

    return app


def _service(request: Request) -> CachedApplicationService:
    return cast(CachedApplicationService, request.app.state.service)


app = create_app()
