"""Short-term A-share-account-buyable stock and ETF recommendation pool.

This module produces research candidates only. It does not create orders and it
does not treat unavailable event/news data as confirmed evidence.
"""

from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from china_quant_platform.domain import AssetType, Bar, Quote, SecurityRef


@dataclass(frozen=True, slots=True)
class RecommendationUniverseMember:
    security_id: str
    symbol: str
    name: str
    asset_type: str
    bucket: str
    exchange: str
    linked_theme: str = ""

    @classmethod
    def from_security(
        cls,
        security: SecurityRef,
        *,
        bucket: str,
        linked_theme: str = "",
    ) -> RecommendationUniverseMember:
        return cls(
            security_id=str(security.security_id),
            symbol=str(security.symbol),
            name=str(security.name),
            asset_type=security.asset_type.value,
            bucket=bucket,
            exchange=security.exchange.value,
            linked_theme=linked_theme,
        )


@dataclass(frozen=True, slots=True)
class CandidateInput:
    member: RecommendationUniverseMember
    bars: tuple[Bar, ...]
    quote: Quote | None = None


DEFAULT_RECOMMENDATION_UNIVERSE: tuple[RecommendationUniverseMember, ...] = (
    RecommendationUniverseMember("SSE:600519", "600519", "贵州茅台", "STOCK", "消费", "SSE"),
    RecommendationUniverseMember("SZSE:000858", "000858", "五粮液", "STOCK", "消费", "SZSE"),
    RecommendationUniverseMember("SZSE:000333", "000333", "美的集团", "STOCK", "消费制造", "SZSE"),
    RecommendationUniverseMember("SSE:600036", "600036", "招商银行", "STOCK", "金融", "SSE"),
    RecommendationUniverseMember("SSE:601318", "601318", "中国平安", "STOCK", "金融", "SSE"),
    RecommendationUniverseMember("SSE:600030", "600030", "中信证券", "STOCK", "券商", "SSE"),
    RecommendationUniverseMember("SSE:600276", "600276", "恒瑞医药", "STOCK", "医药", "SSE"),
    RecommendationUniverseMember("SZSE:300750", "300750", "宁德时代", "STOCK", "新能源", "SZSE"),
    RecommendationUniverseMember("SZSE:002594", "002594", "比亚迪", "STOCK", "新能源", "SZSE"),
    RecommendationUniverseMember("SSE:601012", "601012", "隆基绿能", "STOCK", "新能源", "SSE"),
    RecommendationUniverseMember("SZSE:002475", "002475", "立讯精密", "STOCK", "科技制造", "SZSE"),
    RecommendationUniverseMember("SZSE:000725", "000725", "京东方A", "STOCK", "科技制造", "SZSE"),
    RecommendationUniverseMember("SSE:601899", "601899", "紫金矿业", "STOCK", "周期资源", "SSE"),
    RecommendationUniverseMember("SSE:600900", "600900", "长江电力", "STOCK", "防御红利", "SSE"),
    RecommendationUniverseMember("SZSE:300059", "300059", "东方财富", "STOCK", "金融科技", "SZSE"),
    RecommendationUniverseMember("SSE:510300", "510300", "沪深300ETF", "ETF", "宽基ETF", "SSE"),
    RecommendationUniverseMember("SZSE:159915", "159915", "创业板ETF", "ETF", "宽基ETF", "SZSE"),
    RecommendationUniverseMember(
        "SSE:513300",
        "513300",
        "纳斯达克ETF华夏",
        "ETF",
        "海外ETF",
        "SSE",
        "NASDAQ",
    ),
    RecommendationUniverseMember(
        "SZSE:159941",
        "159941",
        "广发纳指100ETF",
        "ETF",
        "海外ETF",
        "SZSE",
        "NASDAQ",
    ),
    RecommendationUniverseMember(
        "SSE:513100",
        "513100",
        "纳斯达克100ETF国泰",
        "ETF",
        "海外ETF",
        "SSE",
        "NASDAQ",
    ),
    RecommendationUniverseMember(
        "SZSE:159501",
        "159501",
        "纳斯达克100ETF嘉实",
        "ETF",
        "海外ETF",
        "SZSE",
        "NASDAQ",
    ),
    RecommendationUniverseMember(
        "SSE:513500",
        "513500",
        "标普500ETF博时",
        "ETF",
        "海外ETF",
        "SSE",
        "S&P 500",
    ),
    RecommendationUniverseMember(
        "SZSE:159612",
        "159612",
        "标普500ETF国泰",
        "ETF",
        "海外ETF",
        "SZSE",
        "S&P 500",
    ),
    RecommendationUniverseMember(
        "SZSE:161125",
        "161125",
        "标普500LOF易方达",
        "ETF",
        "海外ETF",
        "SZSE",
        "S&P 500",
    ),
    RecommendationUniverseMember(
        "SSE:518880",
        "518880",
        "黄金ETF",
        "ETF",
        "商品ETF",
        "SSE",
        "黄金",
    ),
    RecommendationUniverseMember(
        "SSE:511010",
        "511010",
        "国债ETF",
        "ETF",
        "债券ETF",
        "SSE",
        "利率债",
    ),
)


def build_recommendation_report(
    *,
    candidates: tuple[CandidateInput, ...],
    failures: tuple[dict[str, str], ...],
    as_of: datetime | None = None,
    limit: int = 10,
    horizon_days: int = 10,
) -> dict[str, Any]:
    """Build a short-term recommendation candidate report."""

    now = as_of or datetime.now(tz=UTC)
    scored_inputs = [item for item in candidates if item.bars]
    bucket_returns = _bucket_returns(scored_inputs)
    market_score, market_note = _market_environment(scored_inputs)

    results = [
        _score_candidate(
            item,
            market_score=market_score,
            market_note=market_note,
            bucket_return=bucket_returns.get(item.member.bucket, 0.0),
            horizon_days=horizon_days,
        )
        for item in scored_inputs
    ]
    results.sort(
        key=lambda row: (row["sort_score"], row["total_score"], row["symbol"]),
        reverse=True,
    )
    visible = [row for row in results if row["grade"] != "剔除"][: max(1, limit)]
    rejected = [row for row in results if row["grade"] == "剔除"]
    strong_count = sum(1 for row in visible if row["grade"] == "强候选")
    observe_count = sum(1 for row in visible if row["grade"] == "观察候选")

    return {
        "ok": True,
        "asOf": now.isoformat(),
        "universeCount": len(candidates) + len(failures),
        "evaluatedCount": len(scored_inputs),
        "failedCount": len(failures),
        "marketState": market_note,
        "summary": {
            "title": "A股账户可买短线候选池",
            "horizonDays": horizon_days,
            "strongCount": strong_count,
            "observeCount": observe_count,
            "candidateCount": len(visible),
            "rejectedCount": len(rejected),
            "note": (
                "候选池仅包含A股账户可买的沪深股票、场内ETF/LOF；"
                "海外方向以国内跨境ETF替代，不推荐QQQ/SPY直连标的。"
            ),
        },
        "candidates": visible,
        "rejected": rejected[:20],
        "failures": list(failures),
        "method": {
            "weights": {
                "market_environment": 15,
                "sector_theme": 20,
                "capital_strength": 20,
                "trend_pattern": 15,
                "relative_strength": 15,
                "exit_risk": 15,
            },
            "gradeRule": "85-100 强候选；70-84 观察候选；60-69 弱观察；低于60剔除。",
            "riskDisclosure": "新闻、解禁、减持、财务异常等外部事件数据暂未接入，需人工复核。",
        },
    }


def _score_candidate(
    item: CandidateInput,
    *,
    market_score: float,
    market_note: str,
    bucket_return: float,
    horizon_days: int,
) -> dict[str, Any]:
    member = item.member
    bars = tuple(sorted(item.bars, key=lambda bar: bar.end_time))
    closes = [bar.close_price for bar in bars if bar.close_price > 0]
    amounts = [bar.amount for bar in bars if bar.amount >= 0]
    latest = bars[-1]
    prev = bars[-2] if len(bars) >= 2 else bars[-1]
    latest_price = item.quote.latest_price if item.quote is not None else latest.close_price
    latest_change = _safe_div(latest_price, prev.close_price) - 1.0 if prev.close_price else 0.0

    hard_rejects = _hard_rejects(member, bars)
    data_warnings = ["新闻/解禁/减持/财务异常数据未接入，需人工复核。"]
    if len(bars) < 60:
        data_warnings.append("历史样本少于60根，短线评分降级。")

    returns_5 = _return(closes, 5)
    returns_10 = _return(closes, 10)
    returns_20 = _return(closes, 20)
    ma5 = _mean(closes[-5:])
    ma10 = _mean(closes[-10:])
    ma20 = _mean(closes[-20:])
    ma60 = _mean(closes[-60:]) if len(closes) >= 60 else ma20
    volatility = _stdev(_daily_returns(closes[-21:]))
    drawdown = _max_drawdown(closes[-60:])
    avg_amount_20 = _mean(amounts[-20:]) if amounts else 0.0
    latest_amount = (
        item.quote.amount if item.quote is not None and item.quote.amount else latest.amount
    )
    volume_ratio = _safe_div(latest_amount, avg_amount_20) if avg_amount_20 else 0.0

    sector_score = _clip(10 + bucket_return * 350, 0, 20)
    capital_score = _clip(
        7 + math.log10(max(avg_amount_20, 1)) * 1.15 + min(volume_ratio, 3.0) * 2.4,
        0,
        20,
    )
    trend_score = _trend_score(latest_price, ma5, ma10, ma20, ma60, returns_5, returns_20)
    relative_score = _clip(7 + (returns_5 * 120) + (returns_20 * 75) + (bucket_return * 120), 0, 15)
    exit_score = _exit_score(member, avg_amount_20, volatility, drawdown)
    market_component = _clip(market_score, 0, 15)

    components = {
        "market_environment": round(market_component, 1),
        "sector_theme": round(sector_score, 1),
        "capital_strength": round(capital_score, 1),
        "trend_pattern": round(trend_score, 1),
        "relative_strength": round(relative_score, 1),
        "exit_risk": round(exit_score, 1),
    }
    total = round(sum(components.values()), 1)
    grade = _grade(total)
    downgrade_reasons: list[str] = []
    if hard_rejects:
        grade = "剔除"
        downgrade_reasons.extend(hard_rejects)
    elif market_component < 8 and grade == "强候选":
        grade = "观察候选"
        downgrade_reasons.append("市场环境分低于8，强候选降为观察。")
    if exit_score < 8 and grade in {"强候选", "观察候选"}:
        grade = "弱观察"
        downgrade_reasons.append("可退出性不足，最高只能弱观察。")
    if len(bars) < 60 and grade in {"强候选", "观察候选"}:
        grade = "弱观察"
    if data_warnings and grade == "强候选":
        grade = "观察候选"
        downgrade_reasons.append("外部事件数据未接入，强候选降为观察。")

    trigger, stop_loss, take_profit = _trade_plan(latest_price, bars, ma10, returns_5)
    trading_system = _trading_system(member)
    max_position = _position_limit(grade, market_component)
    core_logic = _core_logic(
        returns_5=returns_5,
        returns_20=returns_20,
        volume_ratio=volume_ratio,
        latest_price=latest_price,
        ma5=ma5,
        ma20=ma20,
    )
    risk_notes = tuple(dict.fromkeys([*hard_rejects, *downgrade_reasons, *data_warnings]))

    return {
        "securityId": member.security_id,
        "symbol": member.symbol,
        "name": member.name,
        "assetType": member.asset_type,
        "bucket": member.bucket,
        "exchange": member.exchange,
        "linkedTheme": member.linked_theme,
        "buyableMarket": "A股账户可买" if _a_share_account_buyable(member) else "需确认",
        "grade": grade,
        "gradeClass": _grade_class(grade),
        "totalScore": total,
        "total_score": total,
        "sort_score": 0 if grade == "剔除" else total,
        "components": components,
        "componentReasons": {
            "market_environment": market_note,
            "sector_theme": f"{member.bucket}近20日相对表现约{bucket_return * 100:.1f}%。",
            "capital_strength": (
                f"20日均成交额约{_money(avg_amount_20)}，当日量能倍率{volume_ratio:.2f}。"
            ),
            "trend_pattern": (
                f"MA5/10/20={ma5:.2f}/{ma10:.2f}/{ma20:.2f}，20日收益{returns_20 * 100:.1f}%。"
            ),
            "relative_strength": (
                f"5日收益{returns_5 * 100:.1f}%，10日收益{returns_10 * 100:.1f}%。"
            ),
            "exit_risk": f"近60日最大回撤{drawdown * 100:.1f}%，21日波动{volatility * 100:.1f}%。",
        },
        "coreLogic": core_logic,
        "buyTrigger": trigger,
        "stopLoss": stop_loss,
        "takeProfit": take_profit,
        "tradingSystem": trading_system,
        "maxPosition": f"{max_position * 100:.0f}%",
        "riskNotes": risk_notes,
        "latestPrice": round(latest_price, 4),
        "latestChangePct": round(latest_change * 100, 2),
        "horizonDays": horizon_days,
        "dataAsOf": latest.end_time.isoformat(),
        "hardFilters": tuple(hard_rejects)
        if hard_rejects
        else ("通过可计算硬过滤；事件类风险需人工复核。",),
    }


def _hard_rejects(member: RecommendationUniverseMember, bars: tuple[Bar, ...]) -> list[str]:
    reasons: list[str] = []
    name = member.name.upper()
    if "ST" in name or "退" in member.name:
        reasons.append("ST、退市或异常名称风险。")
    if len(bars) < 30:
        reasons.append("历史K线少于30根，样本不足。")
    avg_amount = _mean([bar.amount for bar in bars[-20:]]) if bars else 0.0
    if avg_amount < 30_000_000 and member.asset_type == AssetType.STOCK.value:
        reasons.append("20日均成交额低于3000万，流动性不足。")
    closes = [bar.close_price for bar in bars if bar.close_price > 0]
    if len(closes) >= 10 and abs(_return(closes, 5)) > 0.32:
        reasons.append("5日波动过大，短线追高/杀跌风险高。")
    return reasons


def _bucket_returns(items: list[CandidateInput]) -> dict[str, float]:
    grouped: dict[str, list[float]] = defaultdict(list)
    for item in items:
        closes = [bar.close_price for bar in item.bars if bar.close_price > 0]
        if len(closes) >= 20:
            grouped[item.member.bucket].append(_return(closes, 20))
    return {bucket: _mean(values) for bucket, values in grouped.items() if values}


def _market_environment(items: list[CandidateInput]) -> tuple[float, str]:
    if not items:
        return 5.0, "市场样本为空，环境分保守处理。"
    positive_20 = 0
    positive_5 = 0
    usable = 0
    returns_20: list[float] = []
    for item in items:
        closes = [bar.close_price for bar in item.bars if bar.close_price > 0]
        if len(closes) < 20:
            continue
        usable += 1
        ret20 = _return(closes, 20)
        ret5 = _return(closes, 5)
        returns_20.append(ret20)
        positive_20 += int(ret20 > 0)
        positive_5 += int(ret5 > 0)
    if usable == 0:
        return 5.0, "市场可用样本不足，环境分保守处理。"
    breadth = positive_20 / usable
    short_breadth = positive_5 / usable
    mean_return = _mean(returns_20)
    score = _clip(4 + breadth * 6 + short_breadth * 3 + mean_return * 90, 0, 15)
    state = "RISK_ON" if score >= 11 else "BALANCED" if score >= 8 else "RISK_OFF"
    return (
        score,
        f"{state}：20日上涨占比{breadth * 100:.0f}%，"
        f"5日上涨占比{short_breadth * 100:.0f}%，"
        f"候选均值{mean_return * 100:.1f}%。",
    )


def _trend_score(
    price: float,
    ma5: float,
    ma10: float,
    ma20: float,
    ma60: float,
    ret5: float,
    ret20: float,
) -> float:
    score = 5.0
    score += 2.5 if price >= ma5 else -1.0
    score += 2.5 if ma5 >= ma10 else -1.0
    score += 2.0 if ma10 >= ma20 else -1.0
    score += 1.5 if ma20 >= ma60 else -0.5
    score += _clip(ret5 * 90, -2.0, 2.0)
    score += _clip(ret20 * 45, -2.0, 2.5)
    return _clip(score, 0, 15)


def _exit_score(
    member: RecommendationUniverseMember,
    avg_amount_20: float,
    volatility: float,
    drawdown: float,
) -> float:
    liquidity = _clip(math.log10(max(avg_amount_20, 1)) - 6.8, 0, 2.2) / 2.2
    if member.asset_type == AssetType.ETF.value:
        liquidity = min(1.0, liquidity + 0.12)
    vol_score = _clip(1.0 - volatility / 0.055, 0, 1)
    dd_score = _clip(1.0 - drawdown / 0.28, 0, 1)
    return _clip((liquidity * 0.45 + vol_score * 0.25 + dd_score * 0.30) * 15, 0, 15)


def _trade_plan(
    latest_price: float,
    bars: tuple[Bar, ...],
    ma10: float,
    ret5: float,
) -> tuple[str, str, str]:
    high_20 = max((bar.high_price for bar in bars[-20:]), default=latest_price)
    low_10 = min((bar.low_price for bar in bars[-10:]), default=latest_price)
    trigger_price = max(latest_price * 1.01, high_20 * 1.003)
    retrace_price = max(low_10, ma10)
    stop_price = min(latest_price * 0.94, retrace_price * 0.985)
    if ret5 > 0.04:
        trigger = f"回踩不破{retrace_price:.3f}且量能不缩弱，或放量突破{trigger_price:.3f}。"
    else:
        trigger = f"放量突破{trigger_price:.3f}并站稳，或回踩{retrace_price:.3f}企稳。"
    stop_loss = f"跌破{stop_price:.3f}或收盘跌破10日均线后退出。"
    take_profit = "盈利5%-8%先减半；若继续放量创新高，用5日线或前一日低点移动止盈。"
    return trigger, stop_loss, take_profit


def _trading_system(member: RecommendationUniverseMember) -> dict[str, Any]:
    if member.asset_type == AssetType.STOCK.value and member.exchange in {"SSE", "SZSE"}:
        return {
            "label": "T+1",
            "isT0": False,
            "detail": "A股股票通常当日买入不能当日卖出，短线信号按T+1执行。",
        }
    if member.exchange in {"NASDAQ", "NYSE"}:
        return {
            "label": "不可用于A股账户",
            "isT0": False,
            "detail": "默认荐股池不应推荐美股直连标的；请改用境内跨境ETF替代。",
        }
    if member.asset_type == AssetType.ETF.value:
        t0_prefixes = ("511", "513", "518")
        if member.symbol.startswith(t0_prefixes) or member.bucket in {
            "海外ETF",
            "债券ETF",
            "商品ETF",
        }:
            return {
                "label": "T+0",
                "isT0": True,
                "detail": (
                    "A股账户可买的跨境、债券、黄金等场内ETF通常可日内交易，"
                    "需以交易所和券商规则确认。"
                ),
            }
        return {
            "label": "T+1",
            "isT0": False,
            "detail": "普通A股宽基/行业ETF先按T+1保守处理。",
        }
    return {
        "label": "需确认",
        "isT0": False,
        "detail": "当前资产类型交易制度需人工确认。",
    }


def _a_share_account_buyable(member: RecommendationUniverseMember) -> bool:
    return member.exchange in {"SSE", "SZSE"} and member.asset_type in {
        AssetType.STOCK.value,
        AssetType.ETF.value,
        "FUND",
    }


def _position_limit(grade: str, market_component: float) -> float:
    base = {
        "强候选": 0.18,
        "观察候选": 0.08,
        "弱观察": 0.03,
        "剔除": 0.0,
    }.get(grade, 0.0)
    if market_component < 8:
        base *= 0.5
    return base


def _core_logic(
    *,
    returns_5: float,
    returns_20: float,
    volume_ratio: float,
    latest_price: float,
    ma5: float,
    ma20: float,
) -> str:
    parts: list[str] = []
    if returns_20 > 0.05:
        parts.append("20日趋势偏强")
    elif returns_20 < -0.05:
        parts.append("20日趋势偏弱")
    else:
        parts.append("20日横盘震荡")
    if returns_5 > 0.025:
        parts.append("短线动量转强")
    elif returns_5 < -0.025:
        parts.append("短线动量转弱")
    if volume_ratio >= 1.4:
        parts.append("成交量放大确认")
    if latest_price >= ma5 >= ma20:
        parts.append("均线多头排列")
    return "，".join(parts) + "。"


def _grade(total: float) -> str:
    if total >= 85:
        return "强候选"
    if total >= 70:
        return "观察候选"
    if total >= 60:
        return "弱观察"
    return "剔除"


def _grade_class(grade: str) -> str:
    return {
        "强候选": "strong",
        "观察候选": "observe",
        "弱观察": "weak",
        "剔除": "reject",
    }.get(grade, "weak")


def _daily_returns(closes: list[float]) -> list[float]:
    return [
        closes[index] / closes[index - 1] - 1
        for index in range(1, len(closes))
        if closes[index - 1] > 0
    ]


def _return(closes: list[float], days: int) -> float:
    if len(closes) <= days or closes[-days - 1] <= 0:
        return 0.0
    return closes[-1] / closes[-days - 1] - 1.0


def _max_drawdown(closes: list[float]) -> float:
    peak = 0.0
    worst = 0.0
    for price in closes:
        peak = max(peak, price)
        if peak > 0:
            worst = min(worst, price / peak - 1.0)
    return abs(worst)


def _mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def _stdev(values: list[float]) -> float:
    if len(values) < 2:
        return 0.0
    avg = _mean(values)
    return math.sqrt(sum((value - avg) ** 2 for value in values) / (len(values) - 1))


def _safe_div(left: float, right: float) -> float:
    return left / right if right else 0.0


def _clip(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _money(value: float) -> str:
    if value >= 100_000_000:
        return f"{value / 100_000_000:.2f}亿"
    if value >= 10_000:
        return f"{value / 10_000:.0f}万"
    return f"{value:.0f}"


__all__ = [
    "CandidateInput",
    "DEFAULT_RECOMMENDATION_UNIVERSE",
    "RecommendationUniverseMember",
    "build_recommendation_report",
]
