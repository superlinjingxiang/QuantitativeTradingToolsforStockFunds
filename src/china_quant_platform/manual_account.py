"""Manual account input assessment for the desktop research UI."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

_BUY_SIGNALS = {"BUY_CANDIDATE", "ADD_CANDIDATE", "HOLD"}
_REDUCE_SIGNALS = {"SELL", "REDUCE"}


@dataclass(frozen=True, slots=True)
class ManualAccountInput:
    planned_capital: float = 0.0
    available_cash: float | None = None
    holding_quantity: int = 0
    average_cost: float = 0.0
    risk_profile: str = "standard"


def manual_account_from_payload(payload: object) -> ManualAccountInput | None:
    """Parse the Electron account context payload."""

    if not isinstance(payload, dict) or not payload:
        return None
    return ManualAccountInput(
        planned_capital=_float(payload.get("plannedCapital")),
        available_cash=_optional_float(payload.get("availableCash")),
        holding_quantity=max(0, int(_float(payload.get("holdingQuantity")))),
        average_cost=_float(payload.get("averageCost")),
        risk_profile=_risk_profile(payload.get("riskProfile")),
    )


def evaluate_manual_account(
    *,
    account: ManualAccountInput | None,
    latest_price: float,
    final_signal: str | None,
    grade: str | None,
    target_position_limit: object,
    expected_drawdown: object = None,
) -> dict[str, Any]:
    """Translate the current strategy output into account-position advice.

    This function must not run an independent trading strategy. It only uses
    the existing strategy signal and target position limit, then converts that
    into user-specific amount/share suggestions.
    """

    if account is None:
        return {
            "connected": False,
            "summary": "尚未录入账户数据。点击“账户输入”填写计划资金、成本价和持仓数量。",
            "accountAdvice": "未录入",
            "suggestedAmount": "--",
            "suggestedQuantity": "--",
            "reason": "账户数据仅用于研究建议，不会读取券商账户或执行下单。",
            "disclaimer": "研究建议，不构成真实交易指令。",
        }

    price = max(0.0, latest_price)
    quantity = max(0, account.holding_quantity)
    market_value = price * quantity
    cost_value = account.average_cost * quantity
    unrealized_pnl = market_value - cost_value
    unrealized_return = unrealized_pnl / cost_value if cost_value > 0 else 0.0
    planned_capital = max(0.0, account.planned_capital)
    estimated_cash = (
        account.available_cash
        if account.available_cash is not None
        else max(0.0, planned_capital - market_value)
    )
    net_asset = max(planned_capital, market_value + max(0.0, estimated_cash))
    current_weight = market_value / net_asset if net_asset > 0 else 0.0
    strategy_target_weight = _parse_percent(target_position_limit)
    signal = str(final_signal or "").upper()
    grade_text = str(grade or "N").upper()

    blockers: list[str] = []
    if planned_capital <= 0:
        blockers.append("计划总资金未填写或为0，无法计算仓位比例。")
    if price <= 0:
        blockers.append("最新价格不可用，无法折算建议金额和份额。")
    if account.average_cost <= 0 and quantity > 0:
        blockers.append("已有持仓但成本价未填写，盈亏只能部分估算。")

    advice = "观察"
    reason = "策略证据不足，暂不建议新增仓位。"
    suggested_amount = 0.0

    if blockers:
        advice = "补全账户数据"
        reason = " ".join(blockers)
    elif quantity == 0:
        if signal in _BUY_SIGNALS and strategy_target_weight > 0:
            max_position_value = net_asset * strategy_target_weight
            suggested_amount = min(max_position_value, max(0.0, estimated_cash))
            advice = "可小仓试买" if suggested_amount > 0 else "观察"
            reason = (
                f"当前空仓，直接按当前策略{_signal_label(signal)}和仓位上限"
                f"{_pct(strategy_target_weight)}折算可买金额；等级{grade_text}仅作证据强弱展示。"
            )
        else:
            advice = "暂不新开仓"
            reason = (
                f"当前空仓；当前策略为{_signal_label(signal)}，仓位上限"
                f"{_pct(strategy_target_weight)}，因此不建议新增仓位。"
            )
    else:
        target_value = net_asset * strategy_target_weight
        if signal in _REDUCE_SIGNALS or strategy_target_weight <= 0:
            suggested_amount = max(0.0, market_value - target_value)
            advice = "建议减仓"
            reason = (
                f"当前策略为{_signal_label(signal)}且仓位上限{_pct(strategy_target_weight)}，"
                f"账户模块只按该策略目标降低已有仓位；当前仓位约{_pct(current_weight)}。"
            )
        elif current_weight > strategy_target_weight + 0.01:
            suggested_amount = market_value - target_value
            advice = "建议减仓"
            reason = (
                f"当前仓位约{_pct(current_weight)}，高于当前策略仓位上限"
                f"{_pct(strategy_target_weight)}。"
            )
        elif signal in _BUY_SIGNALS and current_weight < strategy_target_weight - 0.01:
            suggested_amount = min(target_value - market_value, max(0.0, estimated_cash))
            advice = "可加仓" if suggested_amount > 0 else "持有"
            reason = (
                f"当前仓位约{_pct(current_weight)}，低于当前策略仓位上限"
                f"{_pct(strategy_target_weight)}；策略为{_signal_label(signal)}。"
            )
        else:
            advice = "持有观察"
            reason = (
                f"当前仓位约{_pct(current_weight)}，与当前策略仓位上限"
                f"{_pct(strategy_target_weight)}基本匹配；"
                f"策略为{_signal_label(signal)}。"
            )

    signed_amount = _signed_amount(advice, suggested_amount)
    suggested_quantity = int(suggested_amount // price) if price > 0 and suggested_amount > 0 else 0
    return {
        "connected": True,
        "plannedCapital": _money(planned_capital),
        "availableCash": _money(max(0.0, estimated_cash)),
        "holdingQuantity": quantity,
        "averageCost": _price(account.average_cost),
        "latestPrice": _price(price),
        "marketValue": _money(market_value),
        "costValue": _money(cost_value),
        "unrealizedPnl": _signed_money(unrealized_pnl),
        "unrealizedReturn": _pct(unrealized_return),
        "currentWeight": _pct(current_weight),
        "targetWeight": _pct(strategy_target_weight),
        "accountAdvice": advice,
        "suggestedAmount": signed_amount,
        "suggestedQuantity": f"{suggested_quantity} 股/份" if suggested_quantity else "--",
        "reason": reason,
        "riskProfile": _risk_profile_label(account.risk_profile),
        "summary": (
            f"{advice}：当前市值{_money(market_value)}，浮动盈亏{_signed_money(unrealized_pnl)}"
            f"（{_pct(unrealized_return)}），仓位{_pct(current_weight)}。"
        ),
        "disclaimer": (
            "账户建议由当前策略仓位上限折算而来，不构成真实交易指令；不会读取券商账户或执行下单。"
        ),
    }


def _float(value: object) -> float:
    try:
        if value is None or value == "":
            return 0.0
        if isinstance(value, (int, float, str)):
            return float(value)
        return 0.0
    except (TypeError, ValueError):
        return 0.0


def _optional_float(value: object) -> float | None:
    if value is None or value == "":
        return None
    parsed = _float(value)
    return max(0.0, parsed)


def _risk_profile(value: object) -> str:
    text = str(value or "standard").strip().lower()
    return text if text in {"conservative", "standard", "aggressive"} else "standard"


def _risk_profile_label(value: str) -> str:
    return {
        "conservative": "保守",
        "standard": "标准",
        "aggressive": "激进",
    }.get(value, "标准")


def _parse_percent(value: object) -> float:
    if value is None:
        return 0.0
    text = str(value).strip()
    try:
        parsed = float(text[:-1] if text.endswith("%") else text)
    except ValueError:
        return 0.0
    return max(0.0, parsed / 100 if parsed > 1 else parsed)


def _signal_label(value: str) -> str:
    return {
        "BUY_CANDIDATE": "买入候选",
        "ADD_CANDIDATE": "加仓候选",
        "SELL": "卖出",
        "REDUCE": "减仓",
        "HOLD": "持有",
        "WATCH": "观察",
        "ABSTAIN": "暂不交易",
    }.get(value, value or "--")


def _signed_amount(advice: str, value: float) -> str:
    if value <= 0:
        return "--"
    prefix = "建议减仓约" if "减仓" in advice or "止损" in advice else "可操作约"
    return f"{prefix}{_money(value)}"


def _money(value: float) -> str:
    return f"{value:,.2f} 元"


def _signed_money(value: float) -> str:
    sign = "+" if value >= 0 else "-"
    return f"{sign}{abs(value):,.2f} 元"


def _price(value: float) -> str:
    return f"{value:.3f}"


def _pct(value: float) -> str:
    return f"{value * 100:.1f}%"
