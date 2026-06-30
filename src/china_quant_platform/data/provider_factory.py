"""Market data provider assembly from runtime environment."""

from __future__ import annotations

from collections.abc import Mapping

from china_quant_platform.data.eastmoney_provider import EastmoneyMarketDataProvider
from china_quant_platform.data.multi_source_provider import MultiSourceMarketDataProvider
from china_quant_platform.data.provider import MarketDataProvider
from china_quant_platform.data.tonghuashun_provider import (
    TonghuashunIfindConfig,
    TonghuashunIfindMarketDataProvider,
)


def create_default_market_data_provider(
    env: Mapping[str, str] | None = None,
) -> MarketDataProvider:
    """Create the production provider chain with Tonghuashun first when configured."""

    providers: list[MarketDataProvider] = []
    tonghuashun_config = TonghuashunIfindConfig.from_env(env)
    if tonghuashun_config is not None:
        providers.append(TonghuashunIfindMarketDataProvider(tonghuashun_config))
    providers.append(EastmoneyMarketDataProvider())
    return MultiSourceMarketDataProvider(providers)


__all__ = ["create_default_market_data_provider"]
