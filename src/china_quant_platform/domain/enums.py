"""Shared domain enumerations."""

from __future__ import annotations

from enum import StrEnum


class AssetType(StrEnum):
    STOCK = "STOCK"
    ETF = "ETF"
    LOF = "LOF"
    MUTUAL_FUND = "MUTUAL_FUND"
    INDEX = "INDEX"


class Exchange(StrEnum):
    SSE = "SSE"
    SZSE = "SZSE"
    HKEX = "HKEX"
    NASDAQ = "NASDAQ"
    NYSE = "NYSE"
    FUND_COMPANY = "FUND_COMPANY"
    INDEX_PROVIDER = "INDEX_PROVIDER"


class Currency(StrEnum):
    CNY = "CNY"
    HKD = "HKD"
    USD = "USD"


class SecurityStatus(StrEnum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    DELISTED = "DELISTED"
    PENDING = "PENDING"


class BarInterval(StrEnum):
    TICK = "TICK"
    ONE_MINUTE = "1m"
    FIVE_MINUTES = "5m"
    FIFTEEN_MINUTES = "15m"
    THIRTY_MINUTES = "30m"
    SIXTY_MINUTES = "60m"
    DAILY = "1d"
    WEEKLY = "1w"
    MONTHLY = "1mo"


class AdjustmentMode(StrEnum):
    NONE = "NONE"
    FORWARD = "FORWARD"
    BACKWARD = "BACKWARD"


class DataHealthStatus(StrEnum):
    HEALTHY = "HEALTHY"
    DEGRADED = "DEGRADED"
    STALE = "STALE"
    INVALID = "INVALID"
    UNAUTHORIZED = "UNAUTHORIZED"


class RecordQualityStatus(StrEnum):
    OK = "OK"
    DEGRADED = "DEGRADED"
    STALE = "STALE"
    INVALID = "INVALID"
    UNAUTHORIZED = "UNAUTHORIZED"


class FinalSignal(StrEnum):
    BUY_CANDIDATE = "BUY_CANDIDATE"
    ADD_CANDIDATE = "ADD_CANDIDATE"
    HOLD = "HOLD"
    REDUCE = "REDUCE"
    SELL = "SELL"
    WATCH = "WATCH"
    ABSTAIN = "ABSTAIN"


class AbstainReason(StrEnum):
    DATA = "DATA"
    RULE = "RULE"
    MODEL_UNCERTAINTY = "MODEL_UNCERTAINTY"
    LIQUIDITY = "LIQUIDITY"
    RISK_BUDGET = "RISK_BUDGET"
    EXPECTED_VALUE = "EXPECTED_VALUE"
    INSUFFICIENT_HISTORY = "INSUFFICIENT_HISTORY"


class FundNavType(StrEnum):
    OFFICIAL = "OFFICIAL"
    ESTIMATED = "ESTIMATED"


class CorporateActionType(StrEnum):
    DIVIDEND = "DIVIDEND"
    SPLIT = "SPLIT"
    RIGHTS_ISSUE = "RIGHTS_ISSUE"
    SYMBOL_CHANGE = "SYMBOL_CHANGE"
    DELISTING = "DELISTING"


class RuleReviewStatus(StrEnum):
    DRAFT = "DRAFT"
    REVIEWED = "REVIEWED"
    APPROVED = "APPROVED"
    RETIRED = "RETIRED"
