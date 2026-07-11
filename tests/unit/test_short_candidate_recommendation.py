from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta

from china_quant_platform.data.fake_provider import DeterministicFakeMarketDataProvider
from china_quant_platform.domain import AdjustmentMode, Bar, BarInterval, RecordQualityStatus
from china_quant_platform.electron_api import ElectronBackendService
from china_quant_platform.strategies.short_candidate_recommendation import (
    DEFAULT_RECOMMENDATION_UNIVERSE,
    CandidateInput,
    RecommendationUniverseMember,
    build_recommendation_report,
)


def test_short_candidate_report_scores_liquid_uptrend_candidate() -> None:
    member = RecommendationUniverseMember(
        security_id="SSE:600000",
        symbol="600000",
        name="样本银行",
        asset_type="STOCK",
        bucket="金融",
        exchange="SSE",
    )
    bars = _bars("SSE:600000", count=90, start_price=10.0, daily_step=0.08, amount=250_000_000)

    report = build_recommendation_report(
        candidates=(CandidateInput(member=member, bars=bars),),
        failures=(),
        as_of=datetime(2026, 7, 10, tzinfo=UTC),
        limit=5,
        horizon_days=10,
    )

    assert report["ok"] is True
    assert report["evaluatedCount"] == 1
    assert report["candidates"]
    candidate = report["candidates"][0]
    assert candidate["grade"] in {"强候选", "观察候选"}
    assert candidate["totalScore"] >= 70
    assert candidate["tradingSystem"]["label"] == "T+1"
    assert candidate["tradingSystem"]["isT0"] is False
    assert "买入触发" not in candidate["buyTrigger"]
    assert candidate["maxPosition"] in {"8%", "18%"}
    assert "新闻/解禁/减持/财务异常数据未接入" in "\n".join(candidate["riskNotes"])


def test_short_candidate_report_rejects_insufficient_history() -> None:
    member = RecommendationUniverseMember(
        security_id="SZSE:300000",
        symbol="300000",
        name="样本科技",
        asset_type="STOCK",
        bucket="科技",
        exchange="SZSE",
    )

    report = build_recommendation_report(
        candidates=(CandidateInput(member=member, bars=_bars("SZSE:300000", count=12)),),
        failures=(),
        as_of=datetime(2026, 7, 10, tzinfo=UTC),
        limit=5,
        horizon_days=10,
    )

    assert report["candidates"] == []
    assert report["rejected"][0]["grade"] == "剔除"
    assert any("样本不足" in note for note in report["rejected"][0]["riskNotes"])


def test_short_candidate_report_keeps_failures_visible() -> None:
    report = build_recommendation_report(
        candidates=(),
        failures=(
            {
                "securityId": "NASDAQ:QQQ",
                "symbol": "QQQ",
                "name": "纳指100ETF",
                "reason": "K线获取失败：timeout",
            },
        ),
        as_of=datetime(2026, 7, 10, tzinfo=UTC),
        limit=5,
        horizon_days=10,
    )

    assert report["failedCount"] == 1
    assert report["failures"][0]["symbol"] == "QQQ"
    assert report["summary"]["candidateCount"] == 0


def test_default_recommendation_universe_is_a_share_account_buyable() -> None:
    assert all(member.exchange in {"SSE", "SZSE"} for member in DEFAULT_RECOMMENDATION_UNIVERSE)
    symbols = {member.symbol for member in DEFAULT_RECOMMENDATION_UNIVERSE}
    assert "QQQ" not in symbols
    assert "SPY" not in symbols
    assert {"513300", "159941", "513100", "513500"}.issubset(symbols)


def test_electron_recommendations_api_returns_report_with_failures() -> None:
    service = ElectronBackendService(env={})
    service._provider = DeterministicFakeMarketDataProvider()  # noqa: SLF001 - direct service smoke.

    report = service.recommendations({"limit": 5, "horizonDays": 10, "includeUsLinked": False})

    assert report["ok"] is True
    assert "candidates" in report
    assert report["evaluatedCount"] >= 1
    assert report["failedCount"] >= 1
    assert report["dataHealth"]["status"] == "DEGRADED"


def test_short_candidate_report_marks_cross_border_etf_as_t0_and_sorts_descending() -> None:
    weak_stock = RecommendationUniverseMember(
        security_id="SSE:600001",
        symbol="600001",
        name="样本股票",
        asset_type="STOCK",
        bucket="消费",
        exchange="SSE",
    )
    strong_etf = RecommendationUniverseMember(
        security_id="SSE:513300",
        symbol="513300",
        name="纳斯达克ETF华夏",
        asset_type="ETF",
        bucket="海外ETF",
        exchange="SSE",
        linked_theme="NASDAQ",
    )

    report = build_recommendation_report(
        candidates=(
            CandidateInput(
                member=weak_stock,
                bars=_bars("SSE:600001", count=90, start_price=10.0, daily_step=0.01),
            ),
            CandidateInput(
                member=strong_etf,
                bars=_bars(
                    "SSE:513300",
                    count=90,
                    start_price=2.0,
                    daily_step=0.03,
                    amount=300_000_000,
                ),
            ),
        ),
        failures=(),
        as_of=datetime(2026, 7, 10, tzinfo=UTC),
        limit=5,
        horizon_days=10,
    )

    scores = [candidate["totalScore"] for candidate in report["candidates"]]
    assert scores == sorted(scores, reverse=True)
    etf = next(candidate for candidate in report["candidates"] if candidate["symbol"] == "513300")
    assert etf["tradingSystem"]["label"] == "T+0"
    assert etf["tradingSystem"]["isT0"] is True
    assert etf["buyableMarket"] == "A股账户可买"


def _bars(
    security_id: str,
    *,
    count: int,
    start_price: float = 10.0,
    daily_step: float = 0.01,
    amount: float = 80_000_000,
) -> tuple[Bar, ...]:
    rows: list[Bar] = []
    current = date(2026, 1, 1)
    price = start_price
    while len(rows) < count:
        if current.weekday() >= 5:
            current += timedelta(days=1)
            continue
        session_start = datetime.combine(current, time(9, 30), tzinfo=UTC)
        session_end = datetime.combine(current, time(15, 0), tzinfo=UTC)
        open_price = price
        close_price = price + daily_step
        high_price = max(open_price, close_price) + 0.05
        low_price = min(open_price, close_price) - 0.05
        rows.append(
            Bar(
                security_id=security_id,
                interval=BarInterval.DAILY,
                start_time=session_start,
                end_time=session_end,
                trade_date=current,
                open_price=open_price,
                high_price=high_price,
                low_price=low_price,
                close_price=close_price,
                volume=amount / close_price,
                amount=amount,
                adjustment=AdjustmentMode.NONE,
                provider="unit-test",
                schema_version="unit-test.v1",
                source_time=session_end,
                observed_at=session_end,
                received_at=session_end,
                quality_status=RecordQualityStatus.OK,
            )
        )
        price = close_price
        current += timedelta(days=1)
    return tuple(rows)
