"""Eastmoney public market data provider adapter."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator, Mapping, Sequence
from datetime import date, datetime, time, timedelta, timezone
from http.client import HTTPException
from time import sleep
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
YAHOO_CHART_URLS = (
    "https://query2.finance.yahoo.com/v8/finance/chart/{symbol}",
    "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}",
)
QUOTE_FIELDS = "f43,f44,f45,f46,f47,f48,f57,f58,f59,f60,f86"
EASTMONEY_UT = "fa5fd1943c7b386f172d6893dbfba10b"
YAHOO_INTERVALS = {
    BarInterval.TICK: "1m",
    BarInterval.ONE_MINUTE: "1m",
    BarInterval.FIVE_MINUTES: "5m",
    BarInterval.FIFTEEN_MINUTES: "15m",
    BarInterval.THIRTY_MINUTES: "30m",
    BarInterval.SIXTY_MINUTES: "60m",
    BarInterval.DAILY: "1d",
    BarInterval.WEEKLY: "1wk",
    BarInterval.MONTHLY: "1mo",
}
YAHOO_INTRADAY_MAX_LOOKBACK = {
    BarInterval.TICK: timedelta(days=7),
    BarInterval.ONE_MINUTE: timedelta(days=7),
    BarInterval.FIVE_MINUTES: timedelta(days=60),
    BarInterval.FIFTEEN_MINUTES: timedelta(days=60),
    BarInterval.THIRTY_MINUTES: timedelta(days=60),
    BarInterval.SIXTY_MINUTES: timedelta(days=60),
}

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
        timeout_seconds: float = 2.0,
        max_attempts: int = 1,
        fallback_timeout_seconds: float = 8.0,
        poll_interval_seconds: float = 5.0,
    ) -> None:
        self._provider_id = provider_id
        self._timeout_seconds = timeout_seconds
        self._fallback_timeout_seconds = fallback_timeout_seconds
        self._max_attempts = max(1, max_attempts)
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
        if _is_yahoo_native_security_id(security_id):
            return self._get_yahoo_quote(_normalize_yahoo_native_security_id(security_id))
        secid = _security_id_to_secid(security_id)
        try:
            payload = self._quote_data(secid)
            return _quote_from_payload(
                security_id=_secid_to_security_id(secid),
                provider_id=self.provider_id,
                payload=payload,
            )
        except DataUnavailable:
            return self._get_yahoo_quote(_secid_to_security_id(secid))

    async def get_bars(self, request: BarsRequest) -> list[Bar]:
        self.capabilities.require(ProviderCapability.HISTORICAL_BARS)
        if request.interval is not BarInterval.DAILY:
            self.capabilities.require(ProviderCapability.MINUTE_BARS)
        if _is_yahoo_native_security_id(request.security_id):
            normalized_request = request.model_copy(
                update={"security_id": _normalize_yahoo_native_security_id(request.security_id)}
            )
            return self._get_yahoo_bars(normalized_request)

        if _prefer_yahoo_for_long_daily_history(request):
            try:
                return self._get_yahoo_bars(request)
            except DataUnavailable:
                pass

        secid = _security_id_to_secid(request.security_id)
        try:
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
                    "ut": EASTMONEY_UT,
                },
            )
            data = _response_data(response, f"No K-line data for {request.security_id}")
            raw_klines = data.get("klines")
            if not isinstance(raw_klines, list):
                raise DataUnavailable(f"Eastmoney returned malformed K-line data for {secid}")
        except DataUnavailable:
            return self._get_yahoo_bars(request)

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
        filtered_bars = [
            bar
            for bar in bars
            if request.start_time <= bar.start_time and bar.end_time <= request.end_time
        ]
        if _daily_history_looks_truncated(request, filtered_bars):
            try:
                fallback_bars = self._get_yahoo_bars(request)
            except DataUnavailable:
                return filtered_bars
            if len(fallback_bars) > len(filtered_bars):
                return fallback_bars
        return filtered_bars

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

    def _get_json(
        self,
        url: str,
        params: Mapping[str, object],
        *,
        timeout_seconds: float | None = None,
        max_attempts: int | None = None,
    ) -> Mapping[str, Any]:
        full_url = f"{url}?{urlencode(params)}"
        source_name = "Yahoo" if "finance.yahoo.com" in url else "Eastmoney"
        timeout = self._timeout_seconds if timeout_seconds is None else timeout_seconds
        attempts = self._max_attempts if max_attempts is None else max(1, max_attempts)
        request = Request(
            full_url,
            headers={
                "Accept": "application/json,text/plain,*/*",
                "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
                "Connection": "close",
                "Referer": "https://quote.eastmoney.com/",
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/126.0 Safari/537.36 ChinaQuantPlatform/0.1"
                ),
            },
        )
        raw: bytes | None = None
        for attempt in range(attempts):
            try:
                with urlopen(request, timeout=timeout) as response:
                    raw = response.read()
                break
            except (HTTPError, TimeoutError, URLError, HTTPException, OSError) as exc:
                if attempt < attempts - 1:
                    sleep(0.25 * (attempt + 1))
                    continue
                raise DataUnavailable(
                    f"{source_name} request failed for {full_url}: {exc}"
                ) from exc
        if raw is None:
            raise DataUnavailable(f"{source_name} request failed for {full_url}: empty response")

        try:
            decoded = raw.decode("utf-8")
            parsed = json.loads(decoded)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise DataUnavailable(f"{source_name} returned invalid JSON for {full_url}") from exc
        if not isinstance(parsed, Mapping):
            raise DataUnavailable(f"{source_name} returned non-object JSON for {full_url}")
        return parsed

    def _get_yahoo_json(self, symbol: str, params: Mapping[str, object]) -> Mapping[str, Any]:
        failures: list[str] = []
        for url_template in YAHOO_CHART_URLS:
            url = url_template.format(symbol=symbol)
            try:
                return self._get_json(
                    url,
                    params,
                    timeout_seconds=self._fallback_timeout_seconds,
                    max_attempts=1,
                )
            except DataUnavailable as exc:
                failures.append(exc.engineering_message)
        raise DataUnavailable("；".join(failures))

    def _get_yahoo_bars(self, request: BarsRequest) -> list[Bar]:
        symbol = _security_id_to_yahoo_symbol(request.security_id)
        start_time = _yahoo_period_start(request)
        response = self._get_yahoo_json(
            symbol,
            {
                "period1": int(start_time.timestamp()),
                "period2": int(request.end_time.timestamp()),
                "interval": _yahoo_interval(request.interval),
                "events": "history",
                "includeAdjustedClose": "true",
            },
        )
        result = _yahoo_chart_result(response, symbol)
        timestamps = result.get("timestamp")
        indicators = result.get("indicators")
        if not isinstance(timestamps, list) or not isinstance(indicators, Mapping):
            raise DataUnavailable(f"Yahoo returned malformed chart data for {symbol}")
        quotes = indicators.get("quote")
        if not isinstance(quotes, list) or not quotes or not isinstance(quotes[0], Mapping):
            raise DataUnavailable(f"Yahoo returned no daily quote data for {symbol}")
        adjclose_items = indicators.get("adjclose")
        adjclose = (
            adjclose_items[0].get("adjclose")
            if isinstance(adjclose_items, list)
            and adjclose_items
            and isinstance(adjclose_items[0], Mapping)
            else None
        )
        quote = quotes[0]
        bars: list[Bar] = []
        for index, raw_timestamp in enumerate(timestamps):
            if not isinstance(raw_timestamp, int):
                continue
            open_price = _sequence_float(quote.get("open"), index)
            high_price = _sequence_float(quote.get("high"), index)
            low_price = _sequence_float(quote.get("low"), index)
            close_price = _sequence_float(quote.get("close"), index)
            volume = _sequence_float(quote.get("volume"), index, default=0.0)
            if None in {open_price, high_price, low_price, close_price}:
                continue
            assert open_price is not None
            assert high_price is not None
            assert low_price is not None
            assert close_price is not None
            adjusted_close = _sequence_float(adjclose, index)
            ratio = (
                adjusted_close / close_price
                if adjusted_close is not None
                and close_price > 0
                and request.adjustment is not AdjustmentMode.NONE
                else 1.0
            )
            source_time = datetime.fromtimestamp(raw_timestamp, tz=CHINA_TZ)
            bar_start_time, bar_end_time, trade_date = _yahoo_bar_window(
                source_time,
                request.interval,
            )
            adjusted_open = _normalized_history_price(open_price * ratio)
            adjusted_close = _normalized_history_price(close_price * ratio)
            adjusted_high = max(
                _normalized_history_price(high_price * ratio),
                adjusted_open,
                adjusted_close,
            )
            adjusted_low = min(
                _normalized_history_price(low_price * ratio),
                adjusted_open,
                adjusted_close,
            )
            received_at = datetime.now(tz=CHINA_TZ)
            if received_at < bar_end_time:
                received_at = bar_end_time
            bars.append(
                Bar(
                    security_id=request.security_id,
                    interval=request.interval,
                    start_time=bar_start_time,
                    end_time=bar_end_time,
                    trade_date=trade_date,
                    open_price=adjusted_open,
                    high_price=adjusted_high,
                    low_price=adjusted_low,
                    close_price=adjusted_close,
                    volume=volume or 0.0,
                    amount=(volume or 0.0) * adjusted_close,
                    adjustment=request.adjustment,
                    provider="yahoo",
                    schema_version="yahoo.chart.v8.fallback",
                    source_time=bar_end_time,
                    observed_at=bar_end_time,
                    received_at=received_at,
                    quality_status=RecordQualityStatus.OK,
                )
            )
        return [
            bar
            for bar in bars
            if request.start_time <= bar.start_time and bar.end_time <= request.end_time
        ]

    def _get_yahoo_quote(self, security_id: str) -> Quote:
        symbol = _security_id_to_yahoo_symbol(security_id)
        end_time = datetime.now(tz=CHINA_TZ)
        response = self._get_yahoo_json(
            symbol,
            {
                "period1": int((end_time - timedelta(days=14)).timestamp()),
                "period2": int(end_time.timestamp()),
                "interval": "1d",
                "events": "history",
                "includeAdjustedClose": "true",
            },
        )
        result = _yahoo_chart_result(response, symbol)
        timestamps = result.get("timestamp")
        indicators = result.get("indicators")
        if not isinstance(timestamps, list) or not isinstance(indicators, Mapping):
            raise DataUnavailable(f"Yahoo returned malformed quote data for {symbol}")
        quotes = indicators.get("quote")
        if not isinstance(quotes, list) or not quotes or not isinstance(quotes[0], Mapping):
            raise DataUnavailable(f"Yahoo returned no quote data for {symbol}")
        quote = quotes[0]
        close_values = quote.get("close")
        indexes = [
            index
            for index, _timestamp in enumerate(timestamps)
            if _sequence_float(close_values, index) is not None
        ]
        if not indexes:
            raise DataUnavailable(f"Yahoo returned no latest price for {symbol}")
        latest_index = indexes[-1]
        previous_index = indexes[-2] if len(indexes) >= 2 else latest_index
        latest_price = _sequence_float(close_values, latest_index)
        previous_close = _sequence_float(close_values, previous_index, default=latest_price)
        open_price = _sequence_float(quote.get("open"), latest_index, default=latest_price)
        high_price = _sequence_float(quote.get("high"), latest_index, default=latest_price)
        low_price = _sequence_float(quote.get("low"), latest_index, default=latest_price)
        volume = _sequence_float(quote.get("volume"), latest_index, default=0.0) or 0.0
        if (
            latest_price is None
            or previous_close is None
            or open_price is None
            or high_price is None
            or low_price is None
        ):
            raise DataUnavailable(f"Yahoo returned incomplete quote data for {symbol}")
        source_time = datetime.fromtimestamp(timestamps[latest_index], tz=CHINA_TZ)
        received_at = datetime.now(tz=CHINA_TZ)
        if received_at < source_time:
            received_at = source_time
        return Quote(
            security_id=security_id,
            latest_price=latest_price,
            previous_close=previous_close,
            open_price=open_price,
            high_price=max(high_price, open_price, latest_price),
            low_price=min(low_price, open_price, latest_price),
            volume=volume,
            amount=volume * latest_price,
            provider="yahoo",
            schema_version="yahoo.chart.v8.fallback",
            source_time=source_time,
            observed_at=source_time,
            received_at=received_at,
            quality_status=RecordQualityStatus.OK,
        )


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


def _security_id_to_yahoo_symbol(security_id: str) -> str:
    if _is_yahoo_native_security_id(security_id):
        normalized = _normalize_yahoo_native_security_id(security_id)
        exchange, _, symbol = normalized.partition(":")
        if exchange == "HKEX":
            return _hk_yahoo_symbol(symbol)
        return symbol
    secid = _security_id_to_secid(security_id)
    market, code = secid.split(".", maxsplit=1)
    if market == "1":
        return f"{code}.SS"
    if market == "0":
        return f"{code}.SZ"
    raise DataUnavailable(f"Cannot convert security_id {security_id!r} to Yahoo symbol")


def _is_yahoo_native_security_id(security_id: str) -> bool:
    return _try_normalize_yahoo_native_security_id(security_id) is not None


def _try_normalize_yahoo_native_security_id(security_id: str) -> str | None:
    value = security_id.strip().upper()
    if ":" in value:
        exchange, _, symbol = value.partition(":")
        if exchange in _HK_EXCHANGE_ALIASES:
            hk_code = _canonical_hk_code(symbol)
            return None if hk_code is None else f"HKEX:{hk_code}"
        if exchange in {"NASDAQ", "NYSE", "US"} and _looks_like_yahoo_symbol(symbol):
            return f"{exchange}:{symbol}"
        return None
    hk_code = _hk_code_from_yahoo_symbol(value)
    if hk_code is not None:
        return f"HKEX:{hk_code}"
    if _looks_like_yahoo_symbol(value):
        return f"NASDAQ:{value}"
    return None


def _normalize_yahoo_native_security_id(security_id: str) -> str:
    normalized = _try_normalize_yahoo_native_security_id(security_id)
    if normalized is not None:
        return normalized
    raise DataUnavailable(f"Cannot convert security_id {security_id!r} to Yahoo symbol")


_HK_EXCHANGE_ALIASES = frozenset({"HK", "HKEX", "HKG", "SEHK"})


def _hk_code_from_yahoo_symbol(symbol: str) -> str | None:
    value = symbol.strip().upper()
    if value.endswith(".HK"):
        return _canonical_hk_code(value.removesuffix(".HK"))
    return None


def _canonical_hk_code(code: str) -> str | None:
    value = code.strip().upper()
    if not value.isdigit() or not (1 <= len(value) <= 5):
        return None
    return (value.lstrip("0") or "0").zfill(5)


def _hk_yahoo_symbol(code: str) -> str:
    canonical = _canonical_hk_code(code) or code
    stripped = canonical.lstrip("0") or "0"
    yahoo_code = stripped.zfill(4) if len(stripped) <= 4 else stripped
    return f"{yahoo_code}.HK"


def _looks_like_yahoo_symbol(symbol: str) -> bool:
    value = symbol.strip().upper()
    if not 1 <= len(value) <= 10:
        return False
    return all(character.isalnum() or character in {".", "-"} for character in value) and any(
        character.isalpha() for character in value
    )


def _yahoo_period_start(request: BarsRequest) -> datetime:
    max_lookback = YAHOO_INTRADAY_MAX_LOOKBACK.get(request.interval)
    if max_lookback is None:
        return request.start_time
    return max(request.start_time, request.end_time - max_lookback)


def _yahoo_interval(interval: BarInterval) -> str:
    try:
        return YAHOO_INTERVALS[interval]
    except KeyError as exc:
        raise DataUnavailable(f"Yahoo does not support interval {interval.value}") from exc


def _yahoo_bar_window(
    source_time: datetime,
    interval: BarInterval,
) -> tuple[datetime, datetime, date]:
    if interval in {BarInterval.DAILY, BarInterval.WEEKLY, BarInterval.MONTHLY}:
        trade_date = source_time.date()
        start_time = datetime.combine(trade_date, time(9, 30), tzinfo=CHINA_TZ)
        end_time = datetime.combine(trade_date, time(15, 0), tzinfo=CHINA_TZ)
        return start_time, end_time, trade_date
    start_time = source_time
    end_time = start_time + timedelta(minutes=_interval_minutes(interval))
    return start_time, end_time, start_time.date()


def _secid_to_security_id(secid: str) -> str:
    market, code = secid.split(".", maxsplit=1)
    if market == "1":
        return f"SSE:{code}"
    if market == "0":
        return f"SZSE:{code}"
    raise DataUnavailable(f"Unsupported Eastmoney market id {market!r}")


def _yahoo_chart_result(response: Mapping[str, Any], symbol: str) -> Mapping[str, Any]:
    chart = response.get("chart")
    if not isinstance(chart, Mapping):
        raise DataUnavailable(f"Yahoo returned malformed chart wrapper for {symbol}")
    error = chart.get("error")
    if error is not None:
        raise DataUnavailable(f"Yahoo returned chart error for {symbol}: {error}")
    results = chart.get("result")
    if not isinstance(results, list) or not results or not isinstance(results[0], Mapping):
        raise DataUnavailable(f"Yahoo returned empty chart data for {symbol}")
    return results[0]


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


def _daily_history_looks_truncated(request: BarsRequest, bars: Sequence[Bar]) -> bool:
    if request.interval is not BarInterval.DAILY:
        return False
    requested_days = (request.end_time - request.start_time).days
    if requested_days < 365:
        return False
    if not bars:
        return True
    ordered = sorted(bars, key=lambda bar: bar.start_time)
    covered_days = (ordered[-1].end_time - ordered[0].start_time).days
    minimum_plausible_count = max(120, int(requested_days * 0.20))
    return len(ordered) < minimum_plausible_count and covered_days < requested_days * 0.50


def _prefer_yahoo_for_long_daily_history(request: BarsRequest) -> bool:
    return (
        request.interval is BarInterval.DAILY
        and (request.end_time - request.start_time).days >= 730
    )


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


def _normalized_history_price(value: float) -> float:
    return round(value, 3)


def _sequence_float(
    values: object,
    index: int,
    *,
    default: float | None = None,
) -> float | None:
    if not isinstance(values, list) or index >= len(values):
        return default
    value = values[index]
    if value is None:
        return default
    try:
        return _float_value(value)
    except DataUnavailable:
        return default


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
