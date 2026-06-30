"""Research-grade decision helpers for the live desktop workflow."""

from __future__ import annotations

import math
from collections.abc import Sequence
from datetime import timedelta

from china_quant_platform.decision.hub import DecisionHub
from china_quant_platform.decision.models import (
    DecisionReport,
    DecisionRequest,
    ProfitabilityEvidence,
)
from china_quant_platform.domain import (
    AbstainReason,
    AnalysisReport,
    AssetType,
    Bar,
    DataHealth,
    DirectionProbabilities,
    FinalSignal,
    Quote,
    SecurityRef,
)
from china_quant_platform.domain.identifiers import NonEmptyString

RESEARCH_RULE_VERSION = "rules-cn-research-v1"
RESEARCH_DATA_SNAPSHOT_ID = "live-bars-research"
RESEARCH_MODEL_VERSION = "research.bar_momentum.v1"


def build_research_decision_from_market_data(
    *,
    security: SecurityRef,
    bars: Sequence[Bar],
    quote: Quote,
    data_health: DataHealth,
) -> DecisionReport:
    """Build a deterministic research decision from live bars and quote data."""

    sorted_bars = tuple(sorted(bars, key=lambda item: item.end_time))
    analysis = build_research_analysis_report(
        security=security,
        bars=sorted_bars,
        quote=quote,
        data_health=data_health,
    )
    profitability = build_bar_profitability_evidence(
        security=security,
        bars=sorted_bars,
        strategy_id=analysis.strategy_id,
        strategy_version=analysis.strategy_version,
    )
    request = DecisionRequest(
        security_id=security.security_id,
        as_of=analysis.as_of,
        evidence_window=f"{len(sorted_bars)} bars",
        min_backtest_trades=5,
        max_backtest_drawdown=0.30,
        max_brier_score=0.30,
        require_simulation_evidence=True,
    )
    return DecisionHub().build_report(
        request=request,
        analysis_report=analysis,
        profitability=profitability,
        simulation=None,
        out_of_sample_passed=profitability is not None and profitability.trade_count >= 5,
        cost_stress_passed=profitability is not None and profitability.cost_drag is not None,
    )


def build_research_analysis_report(
    *,
    security: SecurityRef,
    bars: Sequence[Bar],
    quote: Quote,
    data_health: DataHealth,
) -> AnalysisReport:
    sorted_bars = tuple(sorted(bars, key=lambda item: item.end_time))
    as_of = quote.source_time
    strategy_id = _strategy_id(security.asset_type)
    strategy_name = _strategy_version(security.asset_type)
    if len(sorted_bars) < 25:
        return AnalysisReport(
            security_id=security.security_id,
            as_of=as_of,
            data_health=data_health,
            strategy_id=strategy_id,
            strategy_version=strategy_name,
            horizon=5,
            market_regime="UNKNOWN",
            direction_probabilities=DirectionProbabilities(up=0.25, flat=0.50, down=0.25),
            raw_signal="ABSTAIN",
            final_signal=FinalSignal.ABSTAIN,
            valid_until=as_of + timedelta(days=1),
            positive_drivers=("样本不足，暂不提取正向交易证据。",),
            negative_drivers=(f"历史K线不足：{len(sorted_bars)}/25。",),
            model_version=RESEARCH_MODEL_VERSION,
            rule_version=RESEARCH_RULE_VERSION,
            data_snapshot_id=RESEARCH_DATA_SNAPSHOT_ID,
            expected_return_quantiles={},
            expected_drawdown=None,
            grade="N",
            target_position_limit=0.0,
            exit_or_invalidation_conditions=("补足历史样本后重新评估。",),
            abstain_reason=AbstainReason.INSUFFICIENT_HISTORY,
        )

    closes = tuple(bar.close_price for bar in sorted_bars)
    score = _current_score(closes)
    probabilities = _probabilities(score)
    samples = _forward_returns(closes, horizon=5)
    quantiles = _return_quantiles(samples)
    drawdowns = _drawdowns(closes[-60:])
    expected_drawdown = min(drawdowns) if drawdowns else None
    final_signal = _analysis_signal(score, data_health)
    abstain_reason = AbstainReason.DATA if data_health.block_signal else None
    raw_signal = "ABSTAIN" if final_signal is FinalSignal.ABSTAIN else _raw_signal(score)
    target_position = _target_position_limit(score, data_health)
    drivers = _drivers(closes, score)
    return AnalysisReport(
        security_id=security.security_id,
        as_of=as_of,
        data_health=data_health,
        strategy_id=strategy_id,
        strategy_version=strategy_name,
        horizon=5,
        market_regime=_market_regime(score),
        direction_probabilities=probabilities,
        raw_signal=raw_signal,
        final_signal=final_signal,
        valid_until=as_of + timedelta(days=1),
        positive_drivers=drivers[0],
        negative_drivers=drivers[1],
        model_version=RESEARCH_MODEL_VERSION,
        rule_version=RESEARCH_RULE_VERSION,
        data_snapshot_id=RESEARCH_DATA_SNAPSHOT_ID,
        expected_return_quantiles=quantiles,
        expected_drawdown=expected_drawdown,
        grade=_grade(score, final_signal),
        target_position_limit=target_position,
        exit_or_invalidation_conditions=_invalidation_conditions(score),
        abstain_reason=abstain_reason,
    )


def build_bar_profitability_evidence(
    *,
    security: SecurityRef,
    bars: Sequence[Bar],
    strategy_id: str,
    strategy_version: str,
    horizon: int = 5,
    lookback: int = 20,
    round_trip_cost_bps: float = 12.0,
) -> ProfitabilityEvidence | None:
    sorted_bars = tuple(sorted(bars, key=lambda item: item.end_time))
    closes = tuple(bar.close_price for bar in sorted_bars)
    if len(closes) < lookback + horizon + 5:
        return None

    trade_returns: list[float] = []
    predicted_probabilities: list[float] = []
    outcomes: list[int] = []
    for index in range(lookback, len(closes) - horizon):
        trailing = closes[: index + 1]
        score = _current_score(trailing)
        if score <= 0.25:
            continue
        raw_return = closes[index + horizon] / closes[index] - 1.0
        net_return = raw_return - round_trip_cost_bps / 10_000.0
        trade_returns.append(net_return)
        predicted_probabilities.append(max(0.51, min(0.75, 0.52 + score * 0.18)))
        outcomes.append(1 if net_return > 0 else 0)

    if not trade_returns:
        return ProfitabilityEvidence(
            source="bar_walk_forward",
            strategy_id=strategy_id,
            strategy_version=strategy_version,
            total_return=0.0,
            annualized_return=0.0,
            max_drawdown=0.0,
            benchmark_total_return=closes[-1] / closes[lookback] - 1.0,
            excess_return=-(closes[-1] / closes[lookback] - 1.0),
            trade_count=0,
            turnover=0.0,
            cost_drag=0.0,
            calibration_sample_count=0,
            brier_score=None,
            checksum=_bar_checksum(sorted_bars),
            notes=("未出现足够强的历史买入候选样本。",),
        )

    equity_curve = _equity_curve(trade_returns)
    total_return = equity_curve[-1] - 1.0
    max_drawdown = min(_drawdowns(equity_curve))
    benchmark_total_return = closes[-1] / closes[lookback] - 1.0
    exposure_days = max(len(trade_returns) * horizon, 1)
    annualized_return = (1.0 + total_return) ** (252.0 / exposure_days) - 1.0
    brier_score = _brier_score(predicted_probabilities, outcomes)
    cost_drag = len(trade_returns) * round_trip_cost_bps / 10_000.0
    return ProfitabilityEvidence(
        source="bar_walk_forward",
        strategy_id=strategy_id,
        strategy_version=strategy_version,
        total_return=total_return,
        annualized_return=annualized_return,
        max_drawdown=max_drawdown,
        benchmark_total_return=benchmark_total_return,
        excess_return=total_return - benchmark_total_return,
        trade_count=len(trade_returns),
        turnover=float(len(trade_returns)),
        cost_drag=cost_drag,
        calibration_sample_count=len(outcomes),
        brier_score=brier_score,
        checksum=_bar_checksum(sorted_bars),
        notes=("基于历史K线的滚动研究样本，已扣除简化往返成本。",),
    )


def _strategy_id(asset_type: AssetType) -> str:
    if asset_type in {AssetType.ETF, AssetType.LOF}:
        return "strategy.etf_bar_momentum_decision"
    if asset_type is AssetType.MUTUAL_FUND:
        return "strategy.fund_bar_momentum_decision"
    return "strategy.a_share_bar_momentum_decision"


def _strategy_version(asset_type: AssetType) -> str:
    if asset_type in {AssetType.ETF, AssetType.LOF}:
        return "etf-research-v1"
    if asset_type is AssetType.MUTUAL_FUND:
        return "fund-research-v1"
    return "a-share-research-v1"


def _current_score(closes: Sequence[float]) -> float:
    if len(closes) < 21:
        return 0.0
    ret20 = closes[-1] / closes[-21] - 1.0
    ma5 = sum(closes[-5:]) / 5
    ma20 = sum(closes[-20:]) / 20
    spread = ma5 / ma20 - 1.0 if ma20 > 0 else 0.0
    recent_returns = _period_returns(closes[-21:])
    volatility = _std(recent_returns) * math.sqrt(252.0)
    momentum_score = _clamp(ret20 / 0.12)
    trend_score = _clamp(spread / 0.05)
    risk_penalty = min(volatility / 0.60, 1.0) * 0.25
    return _clamp(0.55 * momentum_score + 0.35 * trend_score - risk_penalty)


def _probabilities(score: float) -> DirectionProbabilities:
    up = min(max(0.34 + score * 0.25, 0.05), 0.85)
    down = min(max(0.33 - score * 0.20, 0.05), 0.85)
    flat = max(0.05, 1.0 - up - down)
    total = up + flat + down
    up /= total
    flat /= total
    down = max(0.0, 1.0 - up - flat)
    return DirectionProbabilities(up=up, flat=flat, down=down)


def _analysis_signal(score: float, data_health: DataHealth) -> FinalSignal:
    if data_health.block_signal:
        return FinalSignal.ABSTAIN
    if score >= 0.30:
        return FinalSignal.BUY_CANDIDATE
    if score <= -0.35:
        return FinalSignal.SELL
    return FinalSignal.WATCH


def _raw_signal(score: float) -> str:
    if score >= 0.30:
        return "BUY_BIAS"
    if score <= -0.35:
        return "SELL_BIAS"
    return "WATCH"


def _target_position_limit(score: float, data_health: DataHealth) -> float:
    if data_health.block_signal or score < 0.30:
        return 0.0
    return min(max(0.02 + score * 0.06, 0.02), 0.08)


def _drivers(closes: Sequence[float], score: float) -> tuple[tuple[str, ...], tuple[str, ...]]:
    ret20 = closes[-1] / closes[-21] - 1.0
    ma5 = sum(closes[-5:]) / 5
    ma20 = sum(closes[-20:]) / 20
    recent_returns = _period_returns(closes[-21:])
    volatility = _std(recent_returns) * math.sqrt(252.0)
    positive = [
        f"20日动量={ret20:.2%}：衡量当前趋势是否有延续基础。",
        f"5/20日均线差={ma5 / ma20 - 1.0:.2%}：衡量短期价格相对中期趋势。",
    ]
    negative = [
        f"年化波动={volatility:.2%}：波动越高，建议仓位越受限。",
        "研究级信号尚需完整样本外、模拟盘和风险复核。",
    ]
    if score < 0:
        positive = ["暂无足够强的正向趋势证据。"]
        negative.insert(0, f"综合趋势得分={score:.2f}：当前不支持买入候选。")
    return tuple(positive), tuple(negative)


def _market_regime(score: float) -> str:
    if score >= 0.45:
        return "TREND_UP_RESEARCH"
    if score <= -0.45:
        return "TREND_DOWN_RESEARCH"
    return "RANGE_OR_MIXED_RESEARCH"


def _grade(score: float, final_signal: FinalSignal) -> str:
    if final_signal is FinalSignal.ABSTAIN:
        return "N"
    if score >= 0.55:
        return "B"
    if score >= 0.30:
        return "C"
    return "N"


def _invalidation_conditions(score: float) -> tuple[str, ...]:
    if score >= 0.30:
        return (
            "20日动量转负或5日均线跌破20日均线。",
            "波动率快速上升、数据延迟或模拟盘偏差超限。",
        )
    return ("趋势得分重新转强且证据门槛通过后再评估。",)


def _forward_returns(closes: Sequence[float], *, horizon: int) -> tuple[float, ...]:
    if len(closes) <= horizon:
        return ()
    return tuple(
        closes[index + horizon] / closes[index] - 1.0 for index in range(len(closes) - horizon)
    )


def _return_quantiles(samples: Sequence[float]) -> dict[str, float]:
    if not samples:
        return {}
    sorted_samples = tuple(sorted(samples))
    return {
        "p05": _quantile(sorted_samples, 0.05),
        "p50": _quantile(sorted_samples, 0.50),
        "p95": _quantile(sorted_samples, 0.95),
    }


def _quantile(sorted_samples: Sequence[float], probability: float) -> float:
    if len(sorted_samples) == 1:
        return sorted_samples[0]
    position = probability * (len(sorted_samples) - 1)
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return sorted_samples[lower]
    weight = position - lower
    return sorted_samples[lower] * (1.0 - weight) + sorted_samples[upper] * weight


def _period_returns(values: Sequence[float]) -> tuple[float, ...]:
    return tuple(
        current / previous - 1.0
        for previous, current in zip(values, values[1:], strict=False)
        if previous > 0
    )


def _std(values: Sequence[float]) -> float:
    if not values:
        return 0.0
    mean = sum(values) / len(values)
    return math.sqrt(sum((value - mean) ** 2 for value in values) / len(values))


def _drawdowns(values: Sequence[float]) -> tuple[float, ...]:
    peak = values[0] if values else 1.0
    drawdowns: list[float] = []
    for value in values:
        peak = max(peak, value)
        drawdowns.append(value / peak - 1.0 if peak else 0.0)
    return tuple(drawdowns)


def _equity_curve(returns: Sequence[float]) -> tuple[float, ...]:
    equity = 1.0
    curve = [equity]
    for value in returns:
        equity *= 1.0 + value
        curve.append(equity)
    return tuple(curve)


def _brier_score(probabilities: Sequence[float], outcomes: Sequence[int]) -> float:
    if not probabilities:
        return 0.0
    return sum(
        (probability - outcome) ** 2
        for probability, outcome in zip(probabilities, outcomes, strict=True)
    ) / len(probabilities)


def _bar_checksum(bars: Sequence[Bar]) -> NonEmptyString:
    return f"bars:{len(bars)}:{bars[0].trade_date.isoformat()}:{bars[-1].trade_date.isoformat()}"


def _clamp(value: float) -> float:
    return max(-1.0, min(value, 1.0))
