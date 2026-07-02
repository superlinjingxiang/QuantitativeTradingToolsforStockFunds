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
import traceback
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qs, urlparse

from china_quant_platform.data import BarsRequest, SecuritySearchResult
from china_quant_platform.data.provider_factory import create_default_market_data_provider
from china_quant_platform.decision.hub import DecisionHub
from china_quant_platform.decision.models import DecisionRequest
from china_quant_platform.domain import (
    AdjustmentMode,
    Bar,
    BarInterval,
    DataHealth,
    DataHealthStatus,
    DataUnavailable,
    DomainError,
    Quote,
    RecordQualityStatus,
    SecurityRef,
)
from china_quant_platform.market import build_market_overview
from china_quant_platform.strategies.profit_validation import (
    ProfitValidationStatus,
    run_profit_strategy_backtest,
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


class ElectronBackendService:
    def __init__(self, env: Mapping[str, str] | None = None) -> None:
        self._env = dict(env or os.environ)
        self._provider = create_default_market_data_provider(self._env)
        self._security_master = build_demo_security_master()

    def health(self) -> dict[str, Any]:
        return {
            "ok": True,
            "service": "china_quant_platform.electron_api",
            "provider": self._provider.provider_id,
            "time": datetime.now(tz=UTC).isoformat(),
        }

    def search(self, query: str) -> dict[str, Any]:
        resolved = self._resolve_security(query, allow_online=True)
        return {
            "query": query,
            "selectedSecurityId": resolved.security.security_id,
            "candidates": [candidate.to_contract_dict() for candidate in resolved.candidates],
        }

    def analyze(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        query = str(payload.get("query") or payload.get("securityId") or "").strip()
        if not query:
            return self._empty_state("请输入代码或名称后回车搜索。")

        now = datetime.now(tz=UTC)
        resolved = self._resolve_security(query, allow_online=True)
        security = resolved.security
        controls = _strategy_controls_from_payload(payload)
        interval = _interval_from_payload(payload.get("interval"))
        range_preset = _range_from_payload(payload.get("range"))
        adjustment = _adjustment_from_payload(payload.get("adjustment"))
        overlays = _overlays_from_payload(payload.get("overlays"))
        chart_backtest_active = bool(payload.get("chartBacktestActive"))

        visible_start = _range_start(now, range_preset)
        decision_start = now - timedelta(days=370 * 6)
        health_issues: list[str] = []
        chart_bars: tuple[Bar, ...] = ()
        decision_bars: tuple[Bar, ...] = ()
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
                            adjustment=AdjustmentMode.NONE,
                        )
                    )
                )
            )
        except BaseException as error:  # noqa: BLE001
            health_issues.append(f"策略日线获取失败：{_short_error(error)}")
            decision_bars = chart_bars if interval is BarInterval.DAILY else ()

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
            block_signal=not decision_bars or not points,
            as_of=now,
            issues=tuple(health_issues),
        )

        analysis = AnalysisPanelState()
        decision = DecisionPanelState()
        backtest = BacktestPanelState(summary="行情已加载，策略样本不足或暂未计算。")
        chart_signals: tuple[ChartSignalMarkerState, ...] = ()
        if decision_bars:
            try:
                config = _profit_strategy_config(
                    controls.mode,
                    controls.horizon,
                    controls.max_trades_per_year,
                )
                profit_backtest = run_profit_strategy_backtest(
                    security.security_id,
                    decision_bars,
                    config=config,
                    include_walk_forward=True,
                )
                report = _analysis_report_from_profit_backtest(
                    security=security,
                    quote=quote,
                    data_health=data_health,
                    bars=decision_bars,
                    backtest=profit_backtest,
                    mode=controls.mode,
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
                    cost_stress_passed=profit_backtest.cost_drag is not None,
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
            "marketOverview": market_overview.to_contract_dict(),
        }

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

    @staticmethod
    def _empty_state(message: str) -> dict[str, Any]:
        return {
            "ok": True,
            "message": message,
            "chart": {"points": (), "signals": ()},
            "analysis": AnalysisPanelState().to_contract_dict(),
            "decision": DecisionPanelState().to_contract_dict(),
            "backtest": BacktestPanelState(summary=message).to_contract_dict(),
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


def _bar_time(bar: Bar) -> datetime:
    return bar.end_time


def _short_error(error: BaseException) -> str:
    if isinstance(error, DomainError):
        return error.engineering_message
    message = str(error).strip()
    return message or error.__class__.__name__


if __name__ == "__main__":
    raise SystemExit(main())
