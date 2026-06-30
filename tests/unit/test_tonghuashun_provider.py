"""Tonghuashun iFinD provider adapter tests."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

from pytest import MonkeyPatch

from china_quant_platform.data import BarsRequest
from china_quant_platform.data.tonghuashun_provider import (
    DEFAULT_REFRESH_TOKEN_ENV_NAMES,
    TonghuashunIfindConfig,
    TonghuashunIfindMarketDataProvider,
)
from china_quant_platform.domain import AdjustmentMode, AssetType, BarInterval, Exchange


def test_tonghuashun_config_reads_refresh_token_from_env() -> None:
    config = TonghuashunIfindConfig.from_env(
        {
            "CQP_THS_IFIND_REFRESH_TOKEN": " token ",
            "CQP_THS_IFIND_BASE_URL": "https://example.test/api/v1/",
        }
    )

    assert config is not None
    assert config.refresh_token == "token"
    assert config.base_url == "https://example.test/api/v1"


def test_tonghuashun_config_reads_refresh_token_from_dotenv(
    monkeypatch: MonkeyPatch,
    tmp_path: Any,
) -> None:
    monkeypatch.chdir(tmp_path)
    for env_name in DEFAULT_REFRESH_TOKEN_ENV_NAMES:
        monkeypatch.delenv(env_name, raising=False)
    (tmp_path / ".env").write_text(
        "CQP_THS_IFIND_REFRESH_TOKEN=dotenv-token\n",
        encoding="utf-8",
    )

    config = TonghuashunIfindConfig.from_env()

    assert config is not None
    assert config.refresh_token == "dotenv-token"


def test_tonghuashun_config_returns_none_without_token() -> None:
    assert TonghuashunIfindConfig.from_env({}) is None


def test_tonghuashun_search_can_resolve_plain_code_without_network() -> None:
    provider = TonghuashunIfindMarketDataProvider(TonghuashunIfindConfig(refresh_token="fixture"))

    securities = asyncio.run(provider.search_security("513300"))

    assert securities[0].security_id == "SSE:513300"
    assert securities[0].asset_type is AssetType.ETF
    assert securities[0].exchange is Exchange.SSE


def test_tonghuashun_quote_maps_table_response(monkeypatch: MonkeyPatch) -> None:
    provider = TonghuashunIfindMarketDataProvider(TonghuashunIfindConfig(refresh_token="fixture"))

    def fake_post_json(endpoint: str, payload: Mapping[str, object]) -> Mapping[str, Any]:
        assert endpoint == "/real_time_quotation"
        assert payload["codes"] == "513300.SH"
        return {
            "tables": [
                {
                    "thscode": "513300.SH",
                    "table": {
                        "time": ["2026-06-30 15:00:00"],
                        "latest": [2.704],
                        "preClose": [2.668],
                        "open": [2.703],
                        "high": [2.719],
                        "low": [2.696],
                        "volume": [1_676_431],
                        "amount": [453_800_145],
                    },
                }
            ]
        }

    monkeypatch.setattr(provider, "_post_json", fake_post_json)

    quote = asyncio.run(provider.get_quote("SSE:513300"))

    assert quote.provider == "tonghuashun_ifind"
    assert quote.latest_price == 2.704
    assert quote.previous_close == 2.668
    assert quote.volume == 1_676_431


def test_tonghuashun_daily_bars_map_table_response(monkeypatch: MonkeyPatch) -> None:
    provider = TonghuashunIfindMarketDataProvider(TonghuashunIfindConfig(refresh_token="fixture"))

    def fake_post_json(endpoint: str, payload: Mapping[str, object]) -> Mapping[str, Any]:
        assert endpoint == "/cmd_history_quotation"
        assert payload["codes"] == "513300.SH"
        assert payload["period"] == "D"
        return {
            "tables": [
                {
                    "thscode": "513300.SH",
                    "table": {
                        "time": ["2026-06-30"],
                        "open": [2.703],
                        "high": [2.719],
                        "low": [2.696],
                        "close": [2.704],
                        "volume": [1_676_431],
                        "amount": [453_800_145],
                    },
                }
            ]
        }

    monkeypatch.setattr(provider, "_post_json", fake_post_json)
    request = BarsRequest(
        security_id="SSE:513300",
        interval=BarInterval.DAILY,
        start_time=datetime(2026, 6, 1, tzinfo=UTC),
        end_time=datetime(2026, 7, 1, tzinfo=UTC),
        adjustment=AdjustmentMode.NONE,
    )

    bars = asyncio.run(provider.get_bars(request))

    assert len(bars) == 1
    assert bars[0].provider == "tonghuashun_ifind"
    assert bars[0].close_price == 2.704
    assert bars[0].volume == 1_676_431
