"""Eastmoney public market data provider adapter."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator, Mapping, Sequence
from datetime import date, datetime, time, timedelta, timezone
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from china_quant_platform.data.provider import (
    BarsRequest,
    CorporateActionRequest,
    FundNavRequest,
    MarketDataProvider,
    ProviderCapabilities,
    ProviderCapability,
)
from china_quant_platform.domain import (
    AdjustmentMode,
    AssetType,
    Bar,
    BarInterval,
    CorporateAction,
    Currency,
    DataUnavailable,
    Exchange,
    FundNav,
    Quote,
    RecordQualityStatus,
    SecurityRef,
    SecurityStatus,
)

CHINA_TZ = timezone(timedelta(hours=8), "Asia/Shanghai")
EASTMONEY_PROVIDER_ID = "eastmoney"
QUOTE_URL = "https://push2.eastmoney.com/api/qt/stock/get"
KLINE_URL = "https://push2his.eastmoney.com/api/qt/stock/kline/get"
QUOTE_FIELDS = "f43,f44,f45,f46,f47,f48,f57,f58,f59,f60,f86"

EASTMONEY_CAPABILITIES = frozenset(
    {
        ProviderCapability.SECURITY_SEARCH,
        ProviderCapability.REALTIME_QUOTE,
        ProviderCapability.REALTIME_SUBSCRIPTION,
        ProviderCapability.HISTORICAL_BARS,
        ProviderCapability.MINUTE_BARS,
    }
)


class EastmoneyMarketDataProvider(MarketDataProvider):
    """Small adapter around Eastmoney public quote and K-line endpoints."""

    def __init__(
        self,
        *,
        provider_id: str = EASTMONEY_PROVIDER_ID,
        timeout_seconds: float = 8.0,
        poll_interval_seconds: float = 5.0,
    ) -> None:
        self._provider_id = provider_id
        self._timeout_seconds = timeout_seconds
        self._poll_interval_seconds = poll_interval_seconds
        self._capabilities = ProviderCapabilities(
            provider_id=provider_id,
            supported=EASTMONEY_CAPABILITIES,
        )

    @property
    def provider_id(self) -> str:
        return self._provider_id

    @property
    def capabilities(self) -> ProviderCapabilities:
        return self._capabilities

    async def search_security(self, keyword: str) -> list[SecurityRef]:
        self.capabilities.require(ProviderCapability.SECURITY_SEARCH)
        candidates = _candidate_secids(keyword)
        if not candidates:
            return []

        securities: list[SecurityRef] = []
        seen: set[str] = set()
        for secid in candidates:
            try:
                payload = self._quote_data(secid)
            except DataUnavailable:
                continue
            security = _security_from_quote(secid, payload)
            if security.security_id not in seen:
                securities.append(security)
                seen.add(security.security_id)
                break
        return securities

    async def get_quote(self, security_id: str) -> Quote:
        self.capabilities.require(ProviderCapability.REALTIME_QUOTE)
        secid = _security_id_to_secid(security_id)
        payload = self._quote_data(secid)
        return _quote_from_payload(
            security_id=_secid_to_security_id(secid),
            provider_id=self.provider_id,
            payload=payload,
        )

    async def get_bars(self, request: BarsRequest) -> list[Bar]:
        self.capabilities.require(ProviderCapability.HISTORICAL_BARS)
        if request.interval is not BarInterval.DAILY:
            self.capabilities.require(ProviderCapability.MINUTE_BARS)

        secid = _security_id_to_secid(request.security_id)
        response = self._get_json(
            KLINE_URL,
            {
                "secid": secid,
                "klt": _kline_type(request.interval),
                "fqt": _adjustment_type(request.adjustment),
                "beg": request.start_time.astimezone(CHINA_TZ).strftime("%Y%m%d"),
                "end": request.end_time.astimezone(CHINA_TZ).strftime("%Y%m%d"),
                "fields1": "f1,f2,f3,f4,f5,f6",
                "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61",
            },
        )
        data = _response_data(response, f"No K-line data for {request.security_id}")
        raw_klines = data.get("klines")
        if not isinstance(raw_klines, list):
            raise DataUnavailable(f"Eastmoney returned malformed K-line data for {secid}")

        bars = [
            _bar_from_kline(
                security_id=request.security_id,
                interval=request.interval,
                adjustment=request.adjustment,
                provider_id=self.provider_id,
                raw_kline=raw_kline,
            )
            for raw_kline in raw_klines
            if isinstance(raw_kline, str)
        ]
        return [
            bar
            for bar in bars
            if request.start_time <= bar.start_time and bar.end_time <= request.end_time
        ]

    def subscribe_quotes(self, security_ids: Sequence[str]) -> AsyncIterator[Quote]:
        if not security_ids:
            raise ValueError("security_ids must not be empty")
        return self._poll_quotes(tuple(security_ids))

    async def get_corporate_actions(
        self,
        request: CorporateActionRequest,
    ) -> list[CorporateAction]:
        raise DataUnavailable(
            f"Provider {self.provider_id!r} does not expose corporate actions",
            retryable=False,
        )

    async def get_fund_nav(self, request: FundNavRequest) -> list[FundNav]:
        raise DataUnavailable(
            f"Provider {self.provider_id!r} does not expose official fund NAV",
            retryable=False,
        )

    async def _poll_quotes(self, security_ids: tuple[str, ...]) -> AsyncIterator[Quote]:
        while True:
            for security_id in security_ids:
                yield await self.get_quote(security_id)
            await asyncio.sleep(self._poll_interval_seconds)

    def _quote_data(self, secid: str) -> Mapping[str, Any]:
        response = self._get_json(QUOTE_URL, {"secid": secid, "fields": QUOTE_FIELDS})
        data = _response_data(response, f"No quote data for {secid}")
        code = data.get("f57")
        name = data.get("f58")
        latest = data.get("f43")
        if not isinstance(code, str) or not isinstance(name, str) or latest in {None, "-"}:
            raise DataUnavailable(f"Eastmoney returned incomplete quote data for {secid}")
        return data

    def _get_json(self, url: str, params: Mapping[str, object]) -> Mapping[str, Any]:
        full_url = f"{url}?{urlencode(params)}"
        request = Request(
            full_url,
            headers={
                "Accept": "application/json,text/plain,*/*",
                "User-Agent": "Mozilla/5.0 ChinaQuantPlatform/0.1",
            },
        )
        try:
            with urlopen(request, timeout=self._timeout_seconds) as response:
                raw = response.read()
        except (HTTPError, TimeoutError, URLError) as exc:
            raise DataUnavailable(f"Eastmoney request failed for {full_url}: {exc}") from exc

        try:
            decoded = raw.decode("utf-8")
            parsed = json.loads(decoded)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise DataUnavailable(f"Eastmoney returned invalid JSON for {full_url}") from exc
        if not isinstance(parsed, Mapping):
            raise DataUnavailable(f"Eastmoney returned non-object JSON for {full_url}")
        return parsed


def _candidate_secids(keyword: str) -> tuple[str, ...]:
    query = keyword.strip().upper()
    if not query:
        return ()

    if "." in query and len(query.split(".", maxsplit=1)) == 2:
        market, code = query.split(".", maxsplit=1)
        if market in {"0", "1"} and code.isdigit():
            return (f"{market}.{code}",)

    if ":" in query and len(query.split(":", maxsplit=1)) == 2:
        exchange, code = query.split(":", maxsplit=1)
        if code.isdigit():
            if exchange in {"SSE", "SH"}:
                return (f"1.{code}",)
            if exchange in {"SZSE", "SZ"}:
                return (f"0.{code}",)

    if not (query.isdigit() and len(query) == 6):
        return ()
    primary_market = "1" if query[0] in {"5", "6", "9"} else "0"
    secondary_market = "0" if primary_market == "1" else "1"
    return (f"{primary_market}.{query}", f"{secondary_market}.{query}")


def _security_id_to_secid(security_id: str) -> str:
    value = security_id.strip().upper()
    if "." in value and len(value.split(".", maxsplit=1)) == 2:
        market, code = value.split(".", maxsplit=1)
        if market in {"0", "1"} and code.isdigit():
            return f"{market}.{code}"
    if ":" in value and len(value.split(":", maxsplit=1)) == 2:
        exchange, code = value.split(":", maxsplit=1)
        if exchange in {"SSE", "SH"} and code.isdigit():
            return f"1.{code}"
        if exchange in {"SZSE", "SZ"} and code.isdigit():
            return f"0.{code}"
        if exchange == "INDEX" and code.isdigit():
            market = "0" if code.startswith("399") else "1"
            return f"{market}.{code}"
    if value.isdigit() and len(value) == 6:
        return _candidate_secids(value)[0]
    raise DataUnavailable(f"Cannot convert security_id {security_id!r} to Eastmoney secid")


def _secid_to_security_id(secid: str) -> str:
    market, code = secid.split(".", maxsplit=1)
    if market == "1":
        return f"SSE:{code}"
    if market == "0":
        return f"SZSE:{code}"
    raise DataUnavailable(f"Unsupported Eastmoney market id {market!r}")


def _security_from_quote(secid: str, payload: Mapping[str, Any]) -> SecurityRef:
    security_id = _secid_to_security_id(secid)
    code = _text(payload, "f57")
    name = _text(payload, "f58")
    exchange = Exchange.SSE if secid.startswith("1.") else Exchange.SZSE
    status_date = _source_time(payload).date()
    return SecurityRef(
        security_id=security_id,
        symbol=code,
        name=name,
        asset_type=_asset_type(code, name),
        exchange=exchange,
        currency=Currency.CNY,
        listed_date=date(1990, 1, 1),
        status_date=status_date,
        status=SecurityStatus.ACTIVE,
        aliases=(f"eastmoney:{secid}",),
    )


def _quote_from_payload(
    *,
    security_id: str,
    provider_id: str,
    payload: Mapping[str, Any],
) -> Quote:
    decimals = _int_value(payload.get("f59"), default=2)
    latest_price = _scaled_price(payload.get("f43"), decimals)
    previous_close = _scaled_price(payload.get("f60"), decimals, fallback=latest_price)
    open_price = _scaled_price(payload.get("f46"), decimals, fallback=latest_price)
    high_price = _scaled_price(
        payload.get("f44"),
        decimals,
        fallback=max(latest_price, open_price),
    )
    low_price = _scaled_price(
        payload.get("f45"),
        decimals,
        fallback=min(latest_price, open_price),
    )
    high_price = max(high_price, open_price, latest_price)
    low_price = min(low_price, open_price, latest_price)
    source_time = _source_time(payload)
    received_at = datetime.now(tz=CHINA_TZ)
    if received_at < source_time:
        received_at = source_time
    return Quote(
        security_id=security_id,
        latest_price=latest_price,
        previous_close=previous_close,
        open_price=open_price,
        high_price=high_price,
        low_price=low_price,
        volume=_float_value(payload.get("f47"), default=0.0),
        amount=_float_value(payload.get("f48"), default=0.0),
        provider=provider_id,
        schema_version="eastmoney.push2.v1",
        source_time=source_time,
        observed_at=source_time,
        received_at=received_at,
        quality_status=RecordQualityStatus.OK,
    )


def _bar_from_kline(
    *,
    security_id: str,
    interval: BarInterval,
    adjustment: AdjustmentMode,
    provider_id: str,
    raw_kline: str,
) -> Bar:
    parts = raw_kline.split(",")
    if len(parts) < 7:
        raise DataUnavailable(f"Malformed Eastmoney K-line row: {raw_kline!r}")

    start_time, end_time, trade_date = _kline_window(parts[0], interval)
    open_price = _float_value(parts[1])
    close_price = _float_value(parts[2])
    high_price = max(_float_value(parts[3]), open_price, close_price)
    low_price = min(_float_value(parts[4]), open_price, close_price)
    return Bar(
        security_id=security_id,
        interval=interval,
        start_time=start_time,
        end_time=end_time,
        trade_date=trade_date,
        open_price=open_price,
        high_price=high_price,
        low_price=low_price,
        close_price=close_price,
        volume=_float_value(parts[5], default=0.0),
        amount=_float_value(parts[6], default=0.0),
        adjustment=adjustment,
        provider=provider_id,
        schema_version="eastmoney.kline.v1",
        source_time=end_time,
        observed_at=end_time,
        received_at=end_time,
        quality_status=RecordQualityStatus.OK,
    )


def _kline_window(value: str, interval: BarInterval) -> tuple[datetime, datetime, date]:
    if " " in value:
        end_time = datetime.strptime(value, "%Y-%m-%d %H:%M").replace(tzinfo=CHINA_TZ)
        minutes = _interval_minutes(interval)
        start_time = end_time - timedelta(minutes=minutes)
        return start_time, end_time, end_time.date()

    trade_date = date.fromisoformat(value)
    start_time = datetime.combine(trade_date, time(9, 30), tzinfo=CHINA_TZ)
    end_time = datetime.combine(trade_date, time(15, 0), tzinfo=CHINA_TZ)
    return start_time, end_time, trade_date


def _kline_type(interval: BarInterval) -> int:
    match interval:
        case BarInterval.TICK | BarInterval.ONE_MINUTE:
            return 1
        case BarInterval.FIVE_MINUTES:
            return 5
        case BarInterval.FIFTEEN_MINUTES:
            return 15
        case BarInterval.THIRTY_MINUTES:
            return 30
        case BarInterval.SIXTY_MINUTES:
            return 60
        case BarInterval.WEEKLY:
            return 102
        case BarInterval.MONTHLY:
            return 103
        case _:
            return 101


def _interval_minutes(interval: BarInterval) -> int:
    match interval:
        case BarInterval.FIVE_MINUTES:
            return 5
        case BarInterval.FIFTEEN_MINUTES:
            return 15
        case BarInterval.THIRTY_MINUTES:
            return 30
        case BarInterval.SIXTY_MINUTES:
            return 60
        case _:
            return 1


def _adjustment_type(adjustment: AdjustmentMode) -> int:
    match adjustment:
        case AdjustmentMode.FORWARD:
            return 1
        case AdjustmentMode.BACKWARD:
            return 2
        case _:
            return 0


def _asset_type(code: str, name: str) -> AssetType:
    normalized_name = name.upper()
    if "ETF" in normalized_name:
        return AssetType.ETF
    if "LOF" in normalized_name:
        return AssetType.LOF
    if code.startswith(("15", "16", "18", "50", "51", "52", "56", "58")):
        return AssetType.ETF
    return AssetType.STOCK


def _source_time(payload: Mapping[str, Any]) -> datetime:
    timestamp = _int_value(payload.get("f86"), default=0)
    if timestamp > 0:
        return datetime.fromtimestamp(timestamp, tz=CHINA_TZ)
    return datetime.now(tz=CHINA_TZ)


def _response_data(response: Mapping[str, Any], missing_message: str) -> Mapping[str, Any]:
    data = response.get("data")
    if not isinstance(data, Mapping):
        raise DataUnavailable(missing_message)
    return data


def _text(payload: Mapping[str, Any], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise DataUnavailable(f"Eastmoney response missing {key}")
    return value.strip()


def _scaled_price(value: object, decimals: int, *, fallback: float | None = None) -> float:
    if value in {None, "-"}:
        if fallback is None:
            raise DataUnavailable("Eastmoney response missing price field")
        return fallback
    raw_price: float = _float_value(value)
    scale: float = float(10**decimals)
    normalized_price: float = raw_price / scale
    return normalized_price


def _float_value(value: object, *, default: float | None = None) -> float:
    if value in {None, "-"}:
        if default is None:
            raise DataUnavailable("Eastmoney response missing numeric field")
        return default
    if not isinstance(value, int | float | str) or isinstance(value, bool):
        if default is not None:
            return default
        raise DataUnavailable(f"Eastmoney response has invalid numeric value {value!r}")
    try:
        return float(value)
    except (TypeError, ValueError) as exc:
        if default is not None:
            return default
        raise DataUnavailable(f"Eastmoney response has invalid numeric value {value!r}") from exc


def _int_value(value: object, *, default: int) -> int:
    if value in {None, "-"}:
        return default
    if not isinstance(value, int | float | str) or isinstance(value, bool):
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


__all__ = [
    "CHINA_TZ",
    "EASTMONEY_CAPABILITIES",
    "EASTMONEY_PROVIDER_ID",
    "EastmoneyMarketDataProvider",
]
