"""Tonghuashun iFinD / QuantAPI provider adapter."""

from __future__ import annotations

import asyncio
import json
import os
from collections.abc import AsyncIterator, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
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
TONGHUASHUN_PROVIDER_ID = "tonghuashun_ifind"
DEFAULT_IFIND_BASE_URL = "https://quantapi.51ifind.com/api/v1"
DEFAULT_REFRESH_TOKEN_ENV_NAMES = (
    "CQP_THS_IFIND_REFRESH_TOKEN",
    "CQP_TONGHUASHUN_REFRESH_TOKEN",
    "IFIND_REFRESH_TOKEN",
)

TONGHUASHUN_CAPABILITIES = frozenset(
    {
        ProviderCapability.SECURITY_SEARCH,
        ProviderCapability.REALTIME_QUOTE,
        ProviderCapability.REALTIME_SUBSCRIPTION,
        ProviderCapability.HISTORICAL_BARS,
        ProviderCapability.MINUTE_BARS,
    }
)


@dataclass(frozen=True, slots=True)
class TonghuashunIfindConfig:
    refresh_token: str
    base_url: str = DEFAULT_IFIND_BASE_URL
    timeout_seconds: float = 10.0
    poll_interval_seconds: float = 5.0

    @classmethod
    def from_env(
        cls,
        env: Mapping[str, str] | None = None,
    ) -> TonghuashunIfindConfig | None:
        values = _provider_env(env)
        refresh_token = next(
            (
                values[name].strip()
                for name in DEFAULT_REFRESH_TOKEN_ENV_NAMES
                if values.get(name, "").strip()
            ),
            "",
        )
        if not refresh_token:
            return None
        return cls(
            refresh_token=refresh_token,
            base_url=values.get("CQP_THS_IFIND_BASE_URL", DEFAULT_IFIND_BASE_URL).rstrip("/"),
            timeout_seconds=float(values.get("CQP_THS_IFIND_TIMEOUT_SECONDS", "10")),
            poll_interval_seconds=float(values.get("CQP_THS_IFIND_POLL_SECONDS", "5")),
        )


def _provider_env(env: Mapping[str, str] | None) -> Mapping[str, str]:
    if env is not None:
        return env
    values = _dotenv_values(Path(".env"))
    values.update(os.environ)
    return values


def _dotenv_values(path: Path) -> dict[str, str]:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return {}
    values: dict[str, str] = {}
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, raw_value = line.partition("=")
        key = key.strip()
        if key:
            values[key] = raw_value.strip().strip('"').strip("'")
    return values


class TonghuashunIfindMarketDataProvider(MarketDataProvider):
    """Adapter for the official Tonghuashun iFinD / QuantAPI HTTP surface."""

    def __init__(
        self,
        config: TonghuashunIfindConfig,
        *,
        provider_id: str = TONGHUASHUN_PROVIDER_ID,
    ) -> None:
        self._config = config
        self._provider_id = provider_id
        self._access_token: str | None = None
        self._capabilities = ProviderCapabilities(
            provider_id=provider_id,
            supported=TONGHUASHUN_CAPABILITIES,
        )

    @property
    def provider_id(self) -> str:
        return self._provider_id

    @property
    def capabilities(self) -> ProviderCapabilities:
        return self._capabilities

    async def search_security(self, keyword: str) -> list[SecurityRef]:
        self.capabilities.require(ProviderCapability.SECURITY_SEARCH)
        security = _fallback_security_from_code(keyword, as_of=datetime.now(tz=CHINA_TZ).date())
        return [] if security is None else [security]

    async def get_quote(self, security_id: str) -> Quote:
        self.capabilities.require(ProviderCapability.REALTIME_QUOTE)
        ths_code = _security_id_to_ths_code(security_id)
        response = self._post_json(
            "/real_time_quotation",
            {
                "codes": ths_code,
                "indicators": ("latest,preClose,open,high,low,volume,amount,bid1,ask1,time"),
            },
        )
        row = _first_table_row(response)
        latest = _required_float(row, ("latest", "price", "close", "newPrice"))
        previous_close = _optional_float(
            row,
            ("preClose", "pre_close", "previousClose", "lastClose"),
        )
        open_price = _optional_float(row, ("open", "openPrice"), default=latest)
        high_price = _optional_float(row, ("high", "highPrice"), default=latest)
        low_price = _optional_float(row, ("low", "lowPrice"), default=latest)
        volume = _optional_float(row, ("volume", "vol"), default=0.0)
        amount = _optional_float(row, ("amount", "turnover"), default=0.0)
        source_time = _parse_source_time(_optional_value(row, ("time", "datetime", "date")))
        return Quote(
            security_id=security_id,
            latest_price=latest,
            previous_close=previous_close if previous_close is not None else latest,
            open_price=open_price if open_price is not None else latest,
            high_price=max(high_price if high_price is not None else latest, latest),
            low_price=min(low_price if low_price is not None else latest, latest),
            volume=volume if volume is not None else 0.0,
            amount=amount if amount is not None else 0.0,
            bid_price=_optional_float(row, ("bid1", "bid_price", "bidPrice")),
            ask_price=_optional_float(row, ("ask1", "ask_price", "askPrice")),
            provider=self.provider_id,
            schema_version="tonghuashun.ifind.quantapi.v1",
            source_time=source_time,
            observed_at=source_time,
            received_at=datetime.now(tz=CHINA_TZ),
            quality_status=RecordQualityStatus.OK,
        )

    async def get_bars(self, request: BarsRequest) -> list[Bar]:
        self.capabilities.require(ProviderCapability.HISTORICAL_BARS)
        if request.interval is not BarInterval.DAILY:
            self.capabilities.require(ProviderCapability.MINUTE_BARS)
        ths_code = _security_id_to_ths_code(request.security_id)
        endpoint = (
            "/high_frequency"
            if request.interval is not BarInterval.DAILY
            else "/cmd_history_quotation"
        )
        response = self._post_json(
            endpoint,
            {
                "codes": ths_code,
                "indicators": "open,high,low,close,volume,amount,time",
                "starttime": request.start_time.astimezone(CHINA_TZ).strftime("%Y-%m-%d %H:%M:%S"),
                "endtime": request.end_time.astimezone(CHINA_TZ).strftime("%Y-%m-%d %H:%M:%S"),
                "period": _ifind_period(request.interval),
                "adjust": _ifind_adjustment(request.adjustment),
            },
        )
        rows = _table_rows(response)
        bars = tuple(
            bar
            for row in rows
            if (
                bar := _bar_from_row(
                    row,
                    request=request,
                    provider_id=self.provider_id,
                )
            )
            is not None
        )
        if not bars:
            raise DataUnavailable(f"Tonghuashun returned no bars for {request.security_id}")
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
            await asyncio.sleep(self._config.poll_interval_seconds)

    def _post_json(self, endpoint: str, payload: Mapping[str, object]) -> Mapping[str, Any]:
        access_token = self._get_access_token()
        url = f"{self._config.base_url}{endpoint}"
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        request = Request(
            url,
            data=body,
            headers={
                "Accept": "application/json",
                "Content-Type": "application/json",
                "access_token": access_token,
                "User-Agent": "ChinaQuantPlatform/0.1 TonghuashunIfindProvider",
            },
            method="POST",
        )
        try:
            with urlopen(request, timeout=self._config.timeout_seconds) as response:
                raw = response.read()
        except (HTTPError, TimeoutError, URLError, OSError) as exc:
            raise DataUnavailable(f"Tonghuashun request failed for {url}: {exc}") from exc
        return _decode_json(raw, url)

    def _get_access_token(self) -> str:
        if self._access_token:
            return self._access_token
        url = f"{self._config.base_url}/get_access_token"
        request = Request(
            url,
            headers={
                "Accept": "application/json",
                "Content-Type": "application/json",
                "refresh_token": self._config.refresh_token,
                "User-Agent": "ChinaQuantPlatform/0.1 TonghuashunIfindProvider",
            },
            method="POST",
        )
        try:
            with urlopen(request, timeout=self._config.timeout_seconds) as response:
                raw = response.read()
        except (HTTPError, TimeoutError, URLError, OSError) as exc:
            raise DataUnavailable(f"Tonghuashun token request failed for {url}: {exc}") from exc
        payload = _decode_json(raw, url)
        token = _extract_access_token(payload)
        self._access_token = token
        return token


def _decode_json(raw: bytes, url: str) -> Mapping[str, Any]:
    try:
        parsed = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise DataUnavailable(f"Tonghuashun returned invalid JSON for {url}") from exc
    if not isinstance(parsed, Mapping):
        raise DataUnavailable(f"Tonghuashun returned non-object JSON for {url}")
    error = parsed.get("error") or parsed.get("errmsg") or parsed.get("message")
    status = parsed.get("status") or parsed.get("code") or parsed.get("errorcode")
    if error and status not in {None, 0, "0", "success", "SUCCESS"}:
        raise DataUnavailable(f"Tonghuashun returned error for {url}: {error}")
    return parsed


def _extract_access_token(payload: Mapping[str, Any]) -> str:
    candidates = [
        payload.get("access_token"),
        payload.get("accessToken"),
        payload.get("token"),
    ]
    data = payload.get("data")
    if isinstance(data, Mapping):
        candidates.extend(
            (
                data.get("access_token"),
                data.get("accessToken"),
                data.get("token"),
            )
        )
    for token in candidates:
        if isinstance(token, str) and token.strip():
            return token.strip()
    raise DataUnavailable("Tonghuashun token response did not contain access_token")


def _table_rows(response: Mapping[str, Any]) -> tuple[dict[str, object], ...]:
    tables = response.get("tables")
    if isinstance(tables, list):
        rows: list[dict[str, object]] = []
        for table in tables:
            if isinstance(table, Mapping):
                rows.extend(_rows_from_table(table))
        return tuple(rows)
    data = response.get("data")
    if isinstance(data, Mapping):
        nested = _table_rows(data)
        return nested if nested else tuple(_rows_from_table(data))
    if isinstance(data, list):
        return tuple(dict(item) for item in data if isinstance(item, Mapping))
    return tuple(_rows_from_table(response))


def _rows_from_table(table: Mapping[str, object]) -> list[dict[str, object]]:
    payload = table.get("table") if isinstance(table.get("table"), Mapping) else table
    assert isinstance(payload, Mapping)
    series = {
        str(key): value
        for key, value in payload.items()
        if isinstance(value, list) and not key.startswith("_")
    }
    if not series:
        return [dict(table)]
    row_count = max(len(values) for values in series.values())
    rows: list[dict[str, object]] = []
    for index in range(row_count):
        row = {key: values[index] for key, values in series.items() if index < len(values)}
        for key, value in table.items():
            if key not in {"table"} and not isinstance(value, list | Mapping):
                row.setdefault(str(key), value)
        rows.append(row)
    return rows


def _first_table_row(response: Mapping[str, Any]) -> Mapping[str, object]:
    rows = _table_rows(response)
    if not rows:
        raise DataUnavailable("Tonghuashun returned no rows")
    return rows[0]


def _bar_from_row(
    row: Mapping[str, object],
    *,
    request: BarsRequest,
    provider_id: str,
) -> Bar | None:
    close_price = _optional_float(row, ("close", "latest", "price"))
    open_price = _optional_float(row, ("open", "openPrice"), default=close_price)
    high_price = _optional_float(row, ("high", "highPrice"), default=close_price)
    low_price = _optional_float(row, ("low", "lowPrice"), default=close_price)
    if close_price is None or open_price is None or high_price is None or low_price is None:
        return None
    source_time = _parse_source_time(_optional_value(row, ("time", "datetime", "date")))
    if request.interval is BarInterval.DAILY:
        trade_date = source_time.date()
        start_time = datetime.combine(trade_date, time(9, 30), tzinfo=CHINA_TZ)
        end_time = datetime.combine(trade_date, time(15, 0), tzinfo=CHINA_TZ)
    else:
        end_time = source_time
        start_time = _bar_start_time(end_time, request.interval)
        trade_date = end_time.date()
    volume = _optional_float(row, ("volume", "vol"), default=0.0) or 0.0
    amount = _optional_float(row, ("amount", "turnover"), default=0.0) or 0.0
    return Bar(
        security_id=request.security_id,
        interval=request.interval,
        start_time=start_time,
        end_time=end_time,
        trade_date=trade_date,
        open_price=open_price,
        high_price=max(high_price, open_price, close_price),
        low_price=min(low_price, open_price, close_price),
        close_price=close_price,
        volume=volume,
        amount=amount,
        adjustment=request.adjustment,
        provider=provider_id,
        schema_version="tonghuashun.ifind.quantapi.v1",
        source_time=end_time,
        observed_at=end_time,
        received_at=datetime.now(tz=CHINA_TZ),
        quality_status=RecordQualityStatus.OK,
    )


def _bar_start_time(end_time: datetime, interval: BarInterval) -> datetime:
    minutes = {
        BarInterval.TICK: 0,
        BarInterval.ONE_MINUTE: 1,
        BarInterval.FIVE_MINUTES: 5,
        BarInterval.FIFTEEN_MINUTES: 15,
        BarInterval.THIRTY_MINUTES: 30,
        BarInterval.SIXTY_MINUTES: 60,
    }.get(interval, 1)
    return end_time - timedelta(minutes=minutes)


def _required_float(row: Mapping[str, object], aliases: tuple[str, ...]) -> float:
    value = _optional_float(row, aliases)
    if value is None:
        raise DataUnavailable(f"Tonghuashun response missing numeric field {aliases[0]}")
    return value


def _optional_float(
    row: Mapping[str, object],
    aliases: tuple[str, ...],
    *,
    default: float | None = None,
) -> float | None:
    value = _optional_value(row, aliases)
    if value in {None, "-", ""}:
        return default
    if isinstance(value, bool) or not isinstance(value, int | float | str):
        return default
    try:
        return float(value)
    except ValueError:
        return default


def _optional_value(row: Mapping[str, object], aliases: tuple[str, ...]) -> object | None:
    normalized = {str(key).lower(): value for key, value in row.items()}
    for alias in aliases:
        if alias in row:
            return row[alias]
        value = normalized.get(alias.lower())
        if value is not None:
            return value
    return None


def _parse_source_time(value: object | None) -> datetime:
    if isinstance(value, int | float) and not isinstance(value, bool):
        timestamp = int(value)
        if timestamp > 10_000_000_000:
            timestamp //= 1000
        return datetime.fromtimestamp(timestamp, tz=CHINA_TZ)
    if isinstance(value, str) and value.strip():
        text = value.strip().replace("/", "-")
        formats = (
            "%Y-%m-%d %H:%M:%S",
            "%Y-%m-%d %H:%M",
            "%Y%m%d %H:%M:%S",
            "%Y%m%d%H%M%S",
            "%Y-%m-%d",
            "%Y%m%d",
        )
        for date_format in formats:
            try:
                parsed = datetime.strptime(text, date_format)
                return parsed.replace(tzinfo=CHINA_TZ)
            except ValueError:
                continue
    return datetime.now(tz=CHINA_TZ)


def _security_id_to_ths_code(security_id: str) -> str:
    value = security_id.strip().upper()
    if ":" in value:
        exchange, _, symbol = value.partition(":")
        if exchange in {"SSE", "SH"} and symbol.isdigit():
            return f"{symbol}.SH"
        if exchange in {"SZSE", "SZ"} and symbol.isdigit():
            return f"{symbol}.SZ"
    if "." in value:
        symbol, _, suffix = value.partition(".")
        if symbol.isdigit() and suffix in {"SH", "SS", "SSE"}:
            return f"{symbol}.SH"
        if symbol.isdigit() and suffix in {"SZ", "SZSE"}:
            return f"{symbol}.SZ"
    if value.isdigit() and len(value) == 6:
        suffix = "SH" if value[0] in {"5", "6", "9"} else "SZ"
        return f"{value}.{suffix}"
    raise DataUnavailable(f"Cannot convert security_id {security_id!r} to Tonghuashun code")


def _ths_code_to_security_ref(
    ths_code: str, *, as_of: date, name: str | None = None
) -> SecurityRef:
    symbol, _, suffix = ths_code.upper().partition(".")
    exchange = Exchange.SSE if suffix in {"SH", "SS"} else Exchange.SZSE
    return SecurityRef(
        security_id=f"{exchange.value}:{symbol}",
        symbol=symbol,
        name=name or f"{symbol}（同花顺）",
        asset_type=_asset_type(symbol, name or ""),
        exchange=exchange,
        currency=Currency.CNY,
        listed_date=date(1990, 1, 1),
        status_date=as_of,
        status=SecurityStatus.ACTIVE,
        aliases=(f"ifind:{ths_code}",),
    )


def _fallback_security_from_code(query: str, *, as_of: date) -> SecurityRef | None:
    try:
        return _ths_code_to_security_ref(_security_id_to_ths_code(query), as_of=as_of)
    except DataUnavailable:
        return None


def _asset_type(symbol: str, name: str) -> AssetType:
    normalized_name = name.upper()
    if "ETF" in normalized_name or symbol.startswith(
        ("15", "16", "18", "50", "51", "52", "56", "58")
    ):
        return AssetType.ETF
    if "LOF" in normalized_name:
        return AssetType.LOF
    return AssetType.STOCK


def _ifind_period(interval: BarInterval) -> str:
    return {
        BarInterval.TICK: "tick",
        BarInterval.ONE_MINUTE: "1m",
        BarInterval.FIVE_MINUTES: "5m",
        BarInterval.FIFTEEN_MINUTES: "15m",
        BarInterval.THIRTY_MINUTES: "30m",
        BarInterval.SIXTY_MINUTES: "60m",
        BarInterval.DAILY: "D",
        BarInterval.WEEKLY: "W",
        BarInterval.MONTHLY: "M",
    }[interval]


def _ifind_adjustment(adjustment: AdjustmentMode) -> str:
    return {
        AdjustmentMode.NONE: "none",
        AdjustmentMode.FORWARD: "forward",
        AdjustmentMode.BACKWARD: "backward",
    }[adjustment]


__all__ = [
    "DEFAULT_REFRESH_TOKEN_ENV_NAMES",
    "TONGHUASHUN_CAPABILITIES",
    "TONGHUASHUN_PROVIDER_ID",
    "TonghuashunIfindConfig",
    "TonghuashunIfindMarketDataProvider",
]
