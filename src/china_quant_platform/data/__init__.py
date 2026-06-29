"""Market data protocols, adapters, normalization, and quality gates."""

from china_quant_platform.data.cache import BarCacheAppendResult, HistoricalBarCache
from china_quant_platform.data.fake_provider import (
    DEFAULT_FAKE_CAPABILITIES,
    DeterministicFakeMarketDataProvider,
)
from china_quant_platform.data.gateway import (
    MarketDataGateway,
    RealtimeConnectionStatus,
    RealtimeSubscriptionState,
)
from china_quant_platform.data.provider import (
    BarsRequest,
    CorporateActionRequest,
    FundNavRequest,
    MarketDataProvider,
    ProviderCapabilities,
    ProviderCapability,
)
from china_quant_platform.data.rate_limit import AsyncRateLimiter
from china_quant_platform.data.security_master import (
    RecentSecuritySelection,
    SecurityMasterRecord,
    SecurityMasterService,
    SecuritySearchResult,
)

__all__ = [
    "AsyncRateLimiter",
    "BarCacheAppendResult",
    "BarsRequest",
    "CorporateActionRequest",
    "DEFAULT_FAKE_CAPABILITIES",
    "DeterministicFakeMarketDataProvider",
    "FundNavRequest",
    "HistoricalBarCache",
    "MarketDataGateway",
    "MarketDataProvider",
    "ProviderCapabilities",
    "ProviderCapability",
    "RecentSecuritySelection",
    "RealtimeConnectionStatus",
    "RealtimeSubscriptionState",
    "SecurityMasterRecord",
    "SecurityMasterService",
    "SecuritySearchResult",
]
