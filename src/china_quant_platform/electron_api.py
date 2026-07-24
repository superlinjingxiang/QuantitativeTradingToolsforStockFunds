"""Local HTTP API used by the Electron desktop shell.

The API intentionally keeps all market data, strategy, backtest, and decision
logic inside Python. Electron is only a presentation layer.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import threading
import traceback
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, time, timedelta, timezone
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qs, urlparse

from china_quant_platform.data import BarsRequest, MarketDataProvider, SecuritySearchResult
from china_quant_platform.data.provider_factory import create_default_market_data_provider
from china_quant_platform.decision.hub import DecisionHub
from china_quant_platform.decision.models import DecisionReport, DecisionRequest
from china_quant_platform.domain import (
    AdjustmentMode,
    AssetType,
    Bar,
    BarInterval,
    DataHealth,
    DataHealthStatus,
    DataUnavailable,
    DomainError,
    Exchange,
    PortfolioStrategyEvidence,
    Quote,
    RecordQualityStatus,
    SecurityRef,
)
from china_quant_platform.manual_account import (
    evaluate_manual_account,
    manual_account_from_payload,
)
from china_quant_platform.market import build_market_overview
from china_quant_platform.strategies.etf_capacity_validation import (
    EtfCapacityAuditReport,
    assess_etf_capacity_scenario,
    audit_etf_rotation_capacity,
    classify_etf_trading_system,
)
from china_quant_platform.strategies.etf_rotation_lab import (
    common_trade_dates,
    fetch_etf_rotation_history,
)
from china_quant_platform.strategies.etf_rotation_validation import (
    EtfRotationAllocationSnapshot,
    EtfRotationBacktestConfig,
    EtfRotationValidationReport,
    build_current_etf_rotation_allocation,
    validate_etf_rotation_strategy,
)
from china_quant_platform.strategies.profit_validation import (
    ProfitValidationStatus,
    default_etf_validation_universe,
    run_profit_strategy_backtest,
)
from china_quant_platform.strategies.short_candidate_recommendation import (
    DEFAULT_RECOMMENDATION_UNIVERSE,
    CandidateInput,
    RecommendationUniverseMember,
    build_recommendation_report,
)
from china_quant_platform.ui.state import (
    AnalysisPanelState,
    BacktestPanelState,
    ChartOverlay,
    ChartPointState,
    ChartRangePreset,
    ChartSignalMarkerState,
    DecisionPanelState,
    MarketOverviewPanelState,
    SearchCandidateState,
    StrategyControlState,
    StrategyMode,
)
from china_quant_platform.ui.viewmodel import (
    _DEFAULT_MARKET_INDEX_IDS,
    _DEFAULT_MARKET_INDEX_NAMES,
    _analysis_report_from_profit_backtest,
    _fallback_security_from_query,
    _load_market_index_quote,
    _profit_strategy_config,
    _profitability_evidence_from_backtest,
    _range_start,
    _run_optimal_chart_backtest,
    build_demo_security_master,
)


@dataclass(slots=True)
class _ResolvedSecurity:
    security: SecurityRef
    candidates: tuple[SearchCandidateState, ...]


@dataclass(frozen=True, slots=True)
class _EtfRotationResearchCache:
    expires_at: datetime
    security_ids: tuple[str, ...]
    allocation: EtfRotationAllocationSnapshot
    validation: EtfRotationValidationReport
    capacity: EtfCapacityAuditReport


class ElectronBackendService:
    def __init__(
        self,
        env: Mapping[str, str] | None = None,
        *,
        provider: MarketDataProvider | None = None,
    ) -> None:
        self._env = dict(env or os.environ)
        self._provider = provider or create_default_market_data_provider(self._env)
        self._security_master = build_demo_security_master()
        self._rotation_cache_lock = threading.Lock()
        self._rotation_cache: _EtfRotationResearchCache | None = None
        self._rotation_retry_after: datetime | None = None
        self._rotation_last_error: str | None = None

    def health(self) -> dict[str, Any]:
        return {
            "ok": True,
            "service": "china_quant_platform.electron_api",
            "provider": self._provider.provider_id,
            "time": datetime.now(tz=UTC).isoformat(),
        }

    def market_overview(self) -> dict[str, Any]:
        now = datetime.now(tz=UTC)
        overview = self._market_overview(now)
        return {
            "ok": True,
            "marketOverview": overview.to_contract_dict(),
        }

    def search(self, query: str) -> dict[str, Any]:
        resolved = self._resolve_security(query, allow_online=True)
        return {
            "query": query,
            "selectedSecurityId": resolved.security.security_id,
            "candidates": [candidate.to_contract_dict() for candidate in resolved.candidates],
        }

    def quote(self, query: str) -> dict[str, Any]:
        """Fetch only the current quote without recomputing history or strategy."""

        stripped = query.strip()
        if not stripped:
            raise DataUnavailable("请输入需要刷新实时价格的标的。", retryable=False)
        now = datetime.now(tz=UTC)
        resolved = self._resolve_security(stripped, allow_online=False)
        quote = asyncio.run(self._provider.get_quote(resolved.security.security_id))
        quote_state = _quote_refresh_state(quote, now=now)
        issues = (
            ("交易时段内行情时间超过90秒，当前报价可能已延迟。",)
            if quote_state["status"] == "STALE"
            else ()
        )
        return {
            "ok": True,
            "selectedSecurity": resolved.security.to_contract_dict(),
            "quote": quote.to_contract_dict(),
            "latestChangePct": _quote_change_pct(quote),
            "quoteState": quote_state,
            "dataHealth": {
                "status": "STALE" if issues else "HEALTHY",
                "block_signal": bool(issues),
                "as_of": now.isoformat(),
                "issues": list(issues),
            },
        }

    def analyze(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        query = str(payload.get("query") or payload.get("securityId") or "").strip()
        if not query:
            return self._empty_state("请输入代码或名称后回车搜索。")

        now = datetime.now(tz=UTC)
        resolved = self._resolve_security(query, allow_online=True)
        security = resolved.security
        controls = _strategy_controls_from_payload(payload)
        config = _profit_strategy_config(
            controls.mode,
            controls.horizon,
            controls.max_trades_per_year,
        )
        interval = _interval_from_payload(payload.get("interval"))
        range_preset = _range_from_payload(payload.get("range"))
        adjustment = _adjustment_from_payload(payload.get("adjustment"))
        overlays = _overlays_from_payload(payload.get("overlays"))
        chart_backtest_active = bool(payload.get("chartBacktestActive"))
        manual_account = manual_account_from_payload(payload.get("accountContext"))

        visible_start = _range_start(now, range_preset)
        decision_start = now - timedelta(days=370 * 6)
        health_issues: list[str] = []
        chart_bars: tuple[Bar, ...] = ()
        decision_bars: tuple[Bar, ...] = ()
        market_regime_bars: tuple[Bar, ...] = ()
        quote: Quote | None = None

        try:
            chart_bars = tuple(
                asyncio.run(
                    self._provider.get_bars(
                        BarsRequest(
                            security_id=security.security_id,
                            interval=interval,
                            start_time=visible_start,
                            end_time=now,
                            adjustment=adjustment,
                        )
                    )
                )
            )
        except BaseException as error:  # noqa: BLE001 - serialized to data-health.
            health_issues.append(f"图表K线获取失败：{_short_error(error)}")

        try:
            decision_bars = tuple(
                asyncio.run(
                    self._provider.get_bars(
                        BarsRequest(
                            security_id=security.security_id,
                            interval=BarInterval.DAILY,
                            start_time=decision_start,
                            end_time=now,
                            adjustment=AdjustmentMode.FORWARD,
                        )
                    )
                )
            )
        except BaseException as error:  # noqa: BLE001
            health_issues.append(f"策略日线获取失败：{_short_error(error)}")
            decision_bars = chart_bars if interval is BarInterval.DAILY else ()

        requires_market_regime = (
            config.apply_a_share_market_regime_filter
            or config.apply_a_share_relative_strength_filter
        ) and (
            security.asset_type is AssetType.STOCK
            and security.exchange in {Exchange.SSE, Exchange.SZSE}
        )
        if requires_market_regime:
            try:
                market_regime_bars = tuple(
                    asyncio.run(
                        self._provider.get_bars(
                            BarsRequest(
                                security_id=config.market_regime_security_id,
                                interval=BarInterval.DAILY,
                                start_time=decision_start,
                                end_time=now,
                                adjustment=AdjustmentMode.FORWARD,
                            )
                        )
                    )
                )
            except BaseException as error:  # noqa: BLE001
                health_issues.append(f"A股市场环境数据获取失败：{_short_error(error)}")
            if len(market_regime_bars) <= config.market_regime_long_lookback:
                health_issues.append(
                    "A股市场环境历史不足，当前禁止新开A股仓位："
                    f"{len(market_regime_bars)}/{config.market_regime_long_lookback + 1} bars。"
                )
        market_regime_ready = (
            not requires_market_regime
            or len(market_regime_bars) > config.market_regime_long_lookback
        )

        portfolio_strategy_evidence: PortfolioStrategyEvidence | None = None
        if controls.mode is StrategyMode.SHORT_TERM:
            portfolio_strategy_evidence, portfolio_issue = self._etf_rotation_evidence(
                security_id=security.security_id,
                as_of=now,
                reference_capital=(
                    manual_account.planned_capital
                    if manual_account is not None and manual_account.planned_capital > 0
                    else 1_000_000.0
                ),
            )
            if portfolio_issue is not None:
                health_issues.append(portfolio_issue)

        try:
            quote = asyncio.run(self._provider.get_quote(security.security_id))
        except BaseException as error:  # noqa: BLE001
            health_issues.append(f"实时行情获取失败，使用最新K线兜底：{_short_error(error)}")
            quote = _quote_from_latest_bar(security.security_id, chart_bars or decision_bars, now)

        if quote is None:
            raise DataUnavailable("没有可用于展示或策略计算的行情数据。")

        points = tuple(ChartPointState.from_bar(bar) for bar in sorted(chart_bars, key=_bar_time))
        data_health = DataHealth(
            status=DataHealthStatus.HEALTHY if not health_issues else DataHealthStatus.DEGRADED,
            block_signal=(not decision_bars or not points or not market_regime_ready),
            as_of=now,
            issues=tuple(health_issues),
        )

        analysis = AnalysisPanelState()
        decision = DecisionPanelState()
        decision_report: DecisionReport | None = None
        backtest = BacktestPanelState(summary="行情已加载，策略样本不足或暂未计算。")
        chart_signals: tuple[ChartSignalMarkerState, ...] = ()
        if decision_bars:
            try:
                profit_backtest = run_profit_strategy_backtest(
                    security.security_id,
                    decision_bars,
                    config=config,
                    include_walk_forward=True,
                    market_regime_bars=market_regime_bars,
                )
                report = _analysis_report_from_profit_backtest(
                    security=security,
                    quote=quote,
                    data_health=data_health,
                    bars=decision_bars,
                    backtest=profit_backtest,
                    mode=controls.mode,
                    portfolio_strategy_evidence=portfolio_strategy_evidence,
                )
                request = DecisionRequest(
                    security_id=security.security_id,
                    as_of=report.as_of,
                    evidence_window=f"{profit_backtest.horizon.value}/{len(decision_bars)} bars",
                    min_backtest_trades=max(1, min(3, config.max_trades_per_year)),
                    max_backtest_drawdown=0.35,
                    max_brier_score=0.35,
                    require_simulation_evidence=True,
                )
                decision_report = DecisionHub().build_report(
                    request=request,
                    analysis_report=report,
                    profitability=_profitability_evidence_from_backtest(profit_backtest),
                    simulation=None,
                    out_of_sample_passed=profit_backtest.status is ProfitValidationStatus.PASS,
                    cost_stress_passed=profit_backtest.cost_stress_passed,
                )
                analysis = AnalysisPanelState.from_report(report)
                decision = DecisionPanelState.from_report(decision_report)
                backtest = BacktestPanelState.from_profit_result(profit_backtest)
            except BaseException as error:  # noqa: BLE001
                backtest = BacktestPanelState(summary=f"策略计算失败：{_short_error(error)}")
                data_health = data_health.model_copy(
                    update={
                        "status": DataHealthStatus.DEGRADED,
                        "block_signal": True,
                        "issues": (*data_health.issues, f"策略计算失败：{_short_error(error)}"),
                    }
                )

        if chart_backtest_active:
            chart_result = _run_optimal_chart_backtest(
                security_id=security.security_id,
                bars=(),
                fallback_points=points,
                horizon=controls.horizon,
                max_trades=controls.max_trades_per_year,
            )
            if chart_result is not None:
                chart_signals = chart_result.signals
                backtest = chart_result.panel

        account_assessment = evaluate_manual_account(
            account=manual_account,
            latest_price=quote.latest_price,
            final_signal=(
                decision_report.final_signal.value
                if decision_report is not None
                else analysis.operation.final_signal
            ),
            grade=analysis.operation.grade,
            target_position_limit=(
                decision_report.target_position_limit
                if decision_report is not None
                else analysis.operation.target_position_limit
            ),
            expected_drawdown=analysis.forecast.expected_drawdown,
            strategy_signal=analysis.operation.final_signal,
            strategy_target_position_limit=analysis.operation.target_position_limit,
            decision_readiness=(
                decision_report.execution_readiness.value if decision_report is not None else None
            ),
            capacity_status=(
                portfolio_strategy_evidence.capacity_status
                if portfolio_strategy_evidence is not None
                else None
            ),
            capacity_limit=(
                portfolio_strategy_evidence.capacity_max_supported_capital
                if portfolio_strategy_evidence is not None
                else None
            ),
            trading_system=(
                portfolio_strategy_evidence.trading_system
                if portfolio_strategy_evidence is not None
                else None
            ),
        )
        market_overview = self._market_overview(now)
        latest_change = _quote_change_pct(quote)
        return {
            "ok": True,
            "selectedSecurity": security.to_contract_dict(),
            "search": {
                "query": query,
                "candidates": [candidate.to_contract_dict() for candidate in resolved.candidates],
            },
            "strategyControls": controls.to_contract_dict(),
            "dataHealth": data_health.to_contract_dict(),
            "quote": quote.to_contract_dict(),
            "latestChangePct": latest_change,
            "chart": {
                "interval": interval.value,
                "range": range_preset.value,
                "adjustment": adjustment.value,
                "overlays": sorted(overlay.value for overlay in overlays),
                "chartBacktestActive": chart_backtest_active,
                "points": [point.to_contract_dict() for point in points],
                "signals": [signal.to_contract_dict() for signal in chart_signals],
            },
            "analysis": analysis.to_contract_dict(),
            "decision": decision.to_contract_dict(),
            "backtest": backtest.to_contract_dict(),
            "accountAssessment": account_assessment,
            "marketOverview": market_overview.to_contract_dict(),
        }

    def recommendations(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        now = datetime.now(tz=UTC)
        limit = _int_from_payload(payload.get("limit"), default=10, minimum=1, maximum=30)
        horizon_days = _int_from_payload(
            payload.get("horizonDays"),
            default=10,
            minimum=1,
            maximum=21,
        )
        include_cross_border_etf = bool(payload.get("includeUsLinked", True))
        members = tuple(
            member
            for member in DEFAULT_RECOMMENDATION_UNIVERSE
            if _recommendation_member_allowed(
                member,
                include_cross_border_etf=include_cross_border_etf,
            )
        )
        start_time = now - timedelta(days=460)
        candidates: list[CandidateInput] = []
        failures: list[dict[str, str]] = []

        for member in members:
            bars: tuple[Bar, ...] = ()
            quote: Quote | None = None
            try:
                bars = tuple(
                    asyncio.run(
                        self._provider.get_bars(
                            BarsRequest(
                                security_id=member.security_id,
                                interval=BarInterval.DAILY,
                                start_time=start_time,
                                end_time=now,
                                adjustment=AdjustmentMode.FORWARD,
                            )
                        )
                    )
                )
            except BaseException as error:  # noqa: BLE001 - returned as data quality evidence.
                failures.append(
                    {
                        "securityId": member.security_id,
                        "symbol": member.symbol,
                        "name": member.name,
                        "reason": f"K线获取失败：{_short_error(error)}",
                    }
                )
                continue
            try:
                quote = asyncio.run(self._provider.get_quote(member.security_id))
            except BaseException:
                quote = None
            candidates.append(CandidateInput(member=member, bars=bars, quote=quote))

        report = build_recommendation_report(
            candidates=tuple(candidates),
            failures=tuple(failures),
            as_of=now,
            limit=limit,
            horizon_days=horizon_days,
        )
        report["provider"] = self._provider.provider_id
        report["dataHealth"] = {
            "status": "HEALTHY" if not failures else "DEGRADED",
            "issues": [item["reason"] for item in failures[:5]],
            "block_signal": len(candidates) == 0,
            "as_of": now.isoformat(),
        }
        return report

    def _resolve_security(self, query: str, *, allow_online: bool) -> _ResolvedSecurity:
        stripped = query.strip()
        as_of = datetime.now(tz=UTC).date()
        results = self._security_master.search(
            stripped,
            as_of=as_of,
            limit=10,
            include_inactive=True,
        )
        candidates = [SearchCandidateState.from_search_result(result) for result in results]
        if allow_online:
            try:
                online = asyncio.run(self._provider.search_security(stripped))
            except BaseException:
                online = []
            for index, security in enumerate(online[:8]):
                self._security_master.upsert_security(security)
                candidate = SearchCandidateState.from_search_result(
                    SecuritySearchResult(
                        query=stripped,
                        security=security,
                        score=max(0.95 - index * 0.03, 0.75),
                        matched_fields=("provider",),
                    )
                )
                if not any(item.security_id == candidate.security_id for item in candidates):
                    candidates.insert(index, candidate)
        if not candidates:
            fallback = _fallback_security_from_query(stripped, as_of=as_of)
            if fallback is not None:
                self._security_master.upsert_security(fallback)
                candidates.append(
                    SearchCandidateState.from_search_result(
                        SecuritySearchResult(
                            query=stripped,
                            security=fallback,
                            score=0.72,
                            matched_fields=("code-fallback",),
                        )
                    )
                )
        if not candidates:
            raise DataUnavailable(f"未找到标的：{query}", retryable=True)
        selected_id = str(candidates[0].security_id)
        security = self._security_master.select_security(
            selected_id,
            selected_at=datetime.now(tz=UTC),
        )
        return _ResolvedSecurity(security=security, candidates=tuple(candidates))

    def _market_overview(self, now: datetime) -> MarketOverviewPanelState:
        try:
            quotes = tuple(
                asyncio.run(
                    _load_market_index_quote(
                        provider=self._provider,
                        security_id=security_id,
                        as_of=now,
                    )
                )
                for security_id in _DEFAULT_MARKET_INDEX_IDS
            )
            overview = build_market_overview(
                index_quotes=quotes,
                constituent_quotes=quotes,
                as_of=now,
                index_names=_DEFAULT_MARKET_INDEX_NAMES,
            )
            return MarketOverviewPanelState.from_overview(overview)
        except BaseException as error:  # noqa: BLE001
            return MarketOverviewPanelState.failed(_short_error(error))

    def _etf_rotation_evidence(
        self,
        *,
        security_id: str,
        as_of: datetime,
        reference_capital: float,
    ) -> tuple[PortfolioStrategyEvidence | None, str | None]:
        universe = default_etf_validation_universe()
        security_ids = tuple(member.security_id for member in universe)
        if security_id not in security_ids:
            return None, None
        try:
            cached, refresh_error = self._etf_rotation_research_cache(as_of=as_of)
        except BaseException as error:  # noqa: BLE001
            message = f"ETF组合研究证据获取失败：{_short_error(error)}"
            member = next(item for item in universe if item.security_id == security_id)
            return (
                PortfolioStrategyEvidence(
                    security_id=security_id,
                    strategy_id="strategy.etf_rotation_portfolio",
                    strategy_version="etf-rotation-v10",
                    validation_status="MISSING",
                    as_of_date=as_of.date(),
                    trading_system=classify_etf_trading_system(
                        security_id,
                        asset_bucket=member.asset_bucket,
                    ).value,
                    failures=(message,),
                    notes=("fixed_ten_etf_universe", "research_only_no_live_order_path"),
                ),
                message,
            )
        evidence = _portfolio_evidence_from_rotation_cache(
            cached,
            security_id=security_id,
            stale=refresh_error is not None,
            refresh_error=refresh_error,
            reference_capital=reference_capital,
        )
        issue = (
            f"ETF组合研究证据刷新失败，保留上次结果：{refresh_error}"
            if refresh_error is not None
            else None
        )
        return evidence, issue

    def _etf_rotation_research_cache(
        self,
        *,
        as_of: datetime,
    ) -> tuple[_EtfRotationResearchCache, str | None]:
        with self._rotation_cache_lock:
            cached = self._rotation_cache
            if cached is not None and as_of < cached.expires_at:
                return cached, None
            if (
                cached is not None
                and self._rotation_retry_after is not None
                and as_of < self._rotation_retry_after
            ):
                return cached, self._rotation_last_error
            try:
                universe = default_etf_validation_universe()
                security_ids = tuple(member.security_id for member in universe)
                bars_by_security, failures = asyncio.run(
                    fetch_etf_rotation_history(
                        self._provider,
                        universe=universe,
                        history_years=9,
                        as_of=as_of,
                    )
                )
                if failures:
                    raise DataUnavailable(
                        "固定十ETF取数不完整：" + "；".join(failures[:3]),
                        retryable=True,
                    )
                dates = common_trade_dates(
                    bars_by_security,
                    security_ids=security_ids,
                )
                config = EtfRotationBacktestConfig()
                minimum_dates = config.formation_lookback_bars + config.walk_forward_window_bars + 2
                if len(dates) < minimum_dates:
                    raise DataUnavailable(
                        f"固定十ETF共同历史不足：{len(dates)}/{minimum_dates}",
                        retryable=True,
                    )
                oos_start = dates[int(len(dates) * 0.75)]
                validation = validate_etf_rotation_strategy(
                    bars_by_security,
                    security_ids=security_ids,
                    config=config,
                    evaluation_start=oos_start,
                )
                allocation = build_current_etf_rotation_allocation(
                    bars_by_security,
                    security_ids=security_ids,
                    config=config,
                )
                trading_systems = {
                    member.security_id: classify_etf_trading_system(
                        member.security_id,
                        asset_bucket=member.asset_bucket,
                    )
                    for member in universe
                }
                capacity = audit_etf_rotation_capacity(
                    bars_by_security,
                    rebalances=validation.base.rebalances,
                    trading_system_by_security=trading_systems,
                )
                ttl_seconds = _positive_env_int(
                    self._env.get("CQP_ETF_ROTATION_CACHE_SECONDS"),
                    default=1800,
                )
                refreshed = _EtfRotationResearchCache(
                    expires_at=as_of + timedelta(seconds=ttl_seconds),
                    security_ids=security_ids,
                    allocation=allocation,
                    validation=validation,
                    capacity=capacity,
                )
                self._rotation_cache = refreshed
                self._rotation_retry_after = None
                self._rotation_last_error = None
                return refreshed, None
            except BaseException as error:  # noqa: BLE001
                self._rotation_retry_after = as_of + timedelta(seconds=30)
                self._rotation_last_error = _short_error(error)
                if cached is not None:
                    return cached, self._rotation_last_error
                raise

    @staticmethod
    def _empty_state(message: str) -> dict[str, Any]:
        return {
            "ok": True,
            "message": message,
            "chart": {"points": (), "signals": ()},
            "analysis": AnalysisPanelState().to_contract_dict(),
            "decision": DecisionPanelState().to_contract_dict(),
            "backtest": BacktestPanelState(summary=message).to_contract_dict(),
            "accountAssessment": evaluate_manual_account(
                account=None,
                latest_price=0.0,
                final_signal=None,
                grade=None,
                target_position_limit=None,
            ),
            "marketOverview": MarketOverviewPanelState.placeholder().to_contract_dict(),
        }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the local Electron backend API.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    service = ElectronBackendService()
    handler = _handler_for(service)
    server = ThreadingHTTPServer((args.host, args.port), handler)
    host, port = server.server_address[:2]
    host = str(host)
    print(f"CHINA_QUANT_BACKEND_READY http://{host}:{port}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        return 0
    finally:
        server.server_close()
    return 0


def _handler_for(service: ElectronBackendService) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        server_version = "ChinaQuantElectronApi/0.1"

        def do_OPTIONS(self) -> None:  # noqa: N802
            self._send_json({}, status=HTTPStatus.NO_CONTENT)

        def do_GET(self) -> None:  # noqa: N802
            parsed = urlparse(self.path)
            query = parse_qs(parsed.query)
            try:
                if parsed.path == "/api/health":
                    self._send_json(service.health())
                    return
                if parsed.path == "/api/search":
                    self._send_json(service.search(query.get("q", [""])[0]))
                    return
                if parsed.path == "/api/quote":
                    self._send_json(service.quote(query.get("q", [""])[0]))
                    return
                if parsed.path == "/api/market-overview":
                    self._send_json(service.market_overview())
                    return
                self._send_json({"ok": False, "error": "not found"}, status=HTTPStatus.NOT_FOUND)
            except BaseException as error:  # noqa: BLE001
                self._send_error(error)

        def do_POST(self) -> None:  # noqa: N802
            parsed = urlparse(self.path)
            try:
                payload = self._read_json()
                if parsed.path == "/api/analyze":
                    self._send_json(service.analyze(payload))
                    return
                if parsed.path == "/api/recommendations":
                    self._send_json(service.recommendations(payload))
                    return
                self._send_json({"ok": False, "error": "not found"}, status=HTTPStatus.NOT_FOUND)
            except BaseException as error:  # noqa: BLE001
                self._send_error(error)

        def log_message(self, format: str, *args: Any) -> None:
            sys.stderr.write(f"[electron-api] {format % args}\n")

        def _read_json(self) -> dict[str, Any]:
            length = int(self.headers.get("Content-Length", "0"))
            if length <= 0:
                return {}
            body = self.rfile.read(length).decode("utf-8")
            data = json.loads(body)
            if not isinstance(data, dict):
                raise ValueError("JSON body must be an object")
            return data

        def _send_error(self, error: BaseException) -> None:
            status = HTTPStatus.BAD_REQUEST
            if isinstance(error, DomainError) and not error.retryable:
                status = HTTPStatus.UNPROCESSABLE_ENTITY
            self._send_json(
                {
                    "ok": False,
                    "error": _short_error(error),
                    "trace": traceback.format_exc(limit=5),
                },
                status=status,
            )

        def _send_json(
            self,
            data: Mapping[str, Any],
            *,
            status: HTTPStatus = HTTPStatus.OK,
        ) -> None:
            payload = json.dumps(data, ensure_ascii=False).encode("utf-8")
            self.send_response(status.value)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(payload)))
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Headers", "content-type")
            self.send_header("Access-Control-Allow-Methods", "GET,POST,OPTIONS")
            self.end_headers()
            if status is not HTTPStatus.NO_CONTENT:
                self.wfile.write(payload)

    return Handler


def _strategy_controls_from_payload(payload: Mapping[str, Any]) -> StrategyControlState:
    mode = (
        StrategyMode.LONG_TERM
        if payload.get("strategyMode") == "long_term"
        else StrategyMode.SHORT_TERM
    )
    controls = StrategyControlState.for_mode(mode)
    max_trades = payload.get("maxTrades")
    if max_trades is not None:
        controls = controls.model_copy(
            update={"max_trades_per_year": max(1, min(int(max_trades), 60))}
        )
    return controls


def _recommendation_member_allowed(
    member: RecommendationUniverseMember,
    *,
    include_cross_border_etf: bool,
) -> bool:
    if member.exchange not in {"SSE", "SZSE"}:
        return False
    if member.bucket == "海外ETF" and not include_cross_border_etf:
        return False
    return True


def _int_from_payload(
    value: object,
    *,
    default: int,
    minimum: int,
    maximum: int,
) -> int:
    try:
        parsed = int(value) if isinstance(value, (int, float, str)) else default
    except (TypeError, ValueError):
        parsed = default
    return max(minimum, min(parsed, maximum))


def _interval_from_payload(value: object) -> BarInterval:
    text = str(value or BarInterval.DAILY.value)
    return BarInterval(text)


def _range_from_payload(value: object) -> ChartRangePreset:
    text = str(value or ChartRangePreset.ONE_MONTH.value)
    return ChartRangePreset(text)


def _adjustment_from_payload(value: object) -> AdjustmentMode:
    text = str(value or AdjustmentMode.NONE.value)
    return AdjustmentMode(text)


def _overlays_from_payload(value: object) -> frozenset[ChartOverlay]:
    if not isinstance(value, list):
        return frozenset({ChartOverlay.VOLUME})
    overlays: set[ChartOverlay] = set()
    for item in value:
        try:
            overlays.add(ChartOverlay(str(item)))
        except ValueError:
            continue
    return frozenset(overlays)


def _quote_from_latest_bar(security_id: str, bars: tuple[Bar, ...], now: datetime) -> Quote | None:
    if not bars:
        return None
    sorted_bars = tuple(sorted(bars, key=_bar_time))
    latest = sorted_bars[-1]
    previous = sorted_bars[-2] if len(sorted_bars) >= 2 else latest
    return Quote(
        security_id=security_id,
        latest_price=latest.close_price,
        previous_close=previous.close_price,
        open_price=latest.open_price,
        high_price=latest.high_price,
        low_price=latest.low_price,
        volume=latest.volume,
        amount=latest.amount,
        provider=f"{latest.provider}.bar_fallback",
        schema_version="electron-api.quote-fallback.v1",
        source_time=latest.source_time,
        observed_at=latest.observed_at,
        received_at=now,
        quality_status=RecordQualityStatus.DEGRADED,
    )


def _quote_change_pct(quote: Quote) -> float | None:
    if quote.previous_close <= 0:
        return None
    return quote.latest_price / quote.previous_close - 1.0


def _quote_refresh_state(quote: Quote, *, now: datetime) -> dict[str, Any]:
    china_tz = timezone(timedelta(hours=8), "Asia/Shanghai")
    local_now = now.astimezone(china_tz)
    local_time = local_now.time()
    weekday = local_now.weekday()
    market_open = weekday < 5 and (
        time(9, 15) <= local_time <= time(11, 35) or time(12, 55) <= local_time <= time(15, 5)
    )
    source_age_seconds = max(
        0,
        int((now - quote.source_time.astimezone(UTC)).total_seconds()),
    )
    if market_open:
        status = "LIVE" if source_age_seconds <= 90 else "STALE"
        label = "实时行情" if status == "LIVE" else "行情延迟"
    elif weekday < 5 and time(11, 35) < local_time < time(12, 55):
        status = "PAUSED"
        label = "午间休市价"
    else:
        status = "CLOSED"
        label = "最近收盘价"
    return {
        "status": status,
        "label": label,
        "sourceTime": quote.source_time.isoformat(),
        "receivedAt": quote.received_at.isoformat(),
        "sourceAgeSeconds": source_age_seconds,
        "pollIntervalSeconds": 3,
    }


def _portfolio_evidence_from_rotation_cache(
    cached: _EtfRotationResearchCache,
    *,
    security_id: str,
    stale: bool,
    refresh_error: str | None,
    reference_capital: float,
) -> PortfolioStrategyEvidence:
    allocation = cached.allocation
    validation = cached.validation
    ranked_security_ids = tuple(allocation.momentum_scores)
    rank = (
        ranked_security_ids.index(security_id) + 1 if security_id in ranked_security_ids else None
    )
    failures = (refresh_error,) if refresh_error else ()
    capacity = assess_etf_capacity_scenario(
        cached.capacity,
        portfolio_capital=reference_capital,
    )
    notes = tuple(
        dict.fromkeys(
            (
                *validation.notes,
                "fixed_ten_etf_universe",
                "signal_prior_close_execution_next_open",
                "research_only_no_live_order_path",
            )
        )
    )
    return PortfolioStrategyEvidence(
        security_id=security_id,
        strategy_id="strategy.etf_rotation_portfolio",
        strategy_version="etf-rotation-v10",
        validation_status=validation.status.value,
        as_of_date=allocation.as_of_date,
        signal_date=allocation.signal_date,
        execution_date=allocation.execution_date,
        selected_security_ids=allocation.selected_security_ids,
        current_security_selected=security_id in allocation.selected_security_ids,
        current_security_rank=rank,
        current_security_momentum=allocation.momentum_scores.get(security_id),
        target_position_fraction=allocation.target_position_fraction,
        current_security_target_fraction=allocation.target_weights.get(security_id, 0.0),
        bars_until_next_rebalance=allocation.bars_until_next_rebalance,
        base_total_return=validation.base.total_return,
        stress_total_return=validation.stress.total_return,
        excess_return=validation.base.excess_return,
        max_drawdown=validation.base.max_drawdown,
        sharpe_ratio=validation.base.sharpe_ratio,
        walk_forward_fold_count=len(validation.walk_forward_folds),
        required_walk_forward_fold_count=validation.config.minimum_walk_forward_folds,
        walk_forward_positive_ratio=validation.walk_forward_positive_ratio,
        walk_forward_excess_ratio=validation.walk_forward_excess_ratio,
        cumulative_turnover=validation.base.cumulative_turnover,
        average_rebalance_turnover=validation.base.average_rebalance_turnover,
        cumulative_transaction_cost=validation.base.cumulative_transaction_cost,
        trading_system=cached.capacity.trading_systems[security_id].value,
        capacity_status=capacity.status.value,
        capacity_model_version=cached.capacity.config.model_version,
        capacity_reference_capital=capacity.portfolio_capital,
        capacity_max_participation_rate=capacity.max_participation_rate,
        capacity_estimated_round_trip_cost_bps=capacity.max_modeled_round_trip_cost_bps,
        capacity_max_supported_capital=cached.capacity.maximum_supported_capital,
        capacity_observation_count=capacity.observation_count,
        capacity_missing_observation_count=capacity.missing_observation_count,
        stale=stale,
        failures=failures,
        notes=notes,
    )


def _positive_env_int(value: str | None, *, default: int) -> int:
    try:
        parsed = int(value) if value is not None else default
    except ValueError:
        parsed = default
    return max(1, parsed)


def _bar_time(bar: Bar) -> datetime:
    return bar.end_time


def _short_error(error: BaseException) -> str:
    if isinstance(error, DomainError):
        return error.engineering_message
    message = str(error).strip()
    return message or error.__class__.__name__


if __name__ == "__main__":
    raise SystemExit(main())
