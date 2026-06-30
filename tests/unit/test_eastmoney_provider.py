"""Eastmoney provider normalization tests."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

from pytest import MonkeyPatch

from china_quant_platform.data import BarsRequest, EastmoneyMarketDataProvider
from china_quant_platform.domain import AdjustmentMode, AssetType, BarInterval, Exchange


def test_eastmoney_search_resolves_sse_etf_code(monkeypatch: MonkeyPatch) -> None:
    provider = EastmoneyMarketDataProvider()

    def fake_get_json(_url: str, params: Mapping[str, object]) -> Mapping[str, Any]:
        assert params["secid"] == "1.513300"
        return {"data": _quote_payload()}

    monkeypatch.setattr(provider, "_get_json", fake_get_json)

    securities = asyncio.run(provider.search_security("513300"))

    assert len(securities) == 1
    assert securities[0].security_id == "SSE:513300"
    assert securities[0].name == "纳斯达克ETF华夏"
    assert securities[0].asset_type is AssetType.ETF
    assert securities[0].exchange is Exchange.SSE


def test_eastmoney_quote_uses_provider_decimal_places(monkeypatch: MonkeyPatch) -> None:
    provider = EastmoneyMarketDataProvider()
    monkeypatch.setattr(provider, "_get_json", lambda _url, _params: {"data": _quote_payload()})

    quote = asyncio.run(provider.get_quote("SSE:513300"))

    assert quote.security_id == "SSE:513300"
    assert quote.latest_price == 2.668
    assert quote.previous_close == 2.65
    assert quote.open_price == 2.652
    assert quote.high_price == 2.671
    assert quote.low_price == 2.642
    assert quote.provider == "eastmoney"


def test_eastmoney_daily_klines_are_mapped_to_bars(monkeypatch: MonkeyPatch) -> None:
    provider = EastmoneyMarketDataProvider()

    def fake_get_json(_url: str, params: Mapping[str, object]) -> Mapping[str, Any]:
        assert params["secid"] == "1.513300"
        assert params["klt"] == 101
        return {"data": {"klines": ["2026-06-29,2.652,2.668,2.671,2.642,1572452,418140505.000"]}}

    monkeypatch.setattr(provider, "_get_json", fake_get_json)
    request = BarsRequest(
        security_id="SSE:513300",
        interval=BarInterval.DAILY,
        start_time=datetime(2026, 6, 1, tzinfo=UTC),
        end_time=datetime(2026, 6, 30, tzinfo=UTC),
        adjustment=AdjustmentMode.NONE,
    )

    bars = asyncio.run(provider.get_bars(request))

    assert len(bars) == 1
    assert bars[0].trade_date.isoformat() == "2026-06-29"
    assert bars[0].close_price == 2.668
    assert bars[0].volume == 1_572_452
    assert bars[0].amount == 418_140_505


def _quote_payload() -> dict[str, object]:
    return {
        "f43": 2668,
        "f44": 2671,
        "f45": 2642,
        "f46": 2652,
        "f47": 1572452,
        "f48": 418140505.0,
        "f57": "513300",
        "f58": "纳斯达克ETF华夏",
        "f59": 3,
        "f60": 2650,
        "f86": 1782720708,
    }
