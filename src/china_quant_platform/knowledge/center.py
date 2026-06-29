"""Curated help topics with explicit theory and China-rule context."""

from __future__ import annotations

from pydantic import Field, model_validator

from china_quant_platform.domain.base import DomainModel
from china_quant_platform.domain.identifiers import NonEmptyString

FORBIDDEN_PROMISE_TERMS = (
    "保证收益",
    "稳赚",
    "必涨",
    "无风险收益",
    "确定盈利",
)


class HelpTopic(DomainModel):
    topic_id: NonEmptyString
    title: NonEmptyString
    summary: NonEmptyString
    theory_context: NonEmptyString
    china_rule_context: NonEmptyString
    body: NonEmptyString
    related_terms: tuple[NonEmptyString, ...] = ()
    warnings: tuple[NonEmptyString, ...] = Field(
        default=("任何解释都不构成收益承诺，必须结合数据、规则和风险约束。",)
    )

    @model_validator(mode="after")
    def enforce_help_safety(self) -> HelpTopic:
        combined = " ".join(
            (
                self.title,
                self.summary,
                self.theory_context,
                self.china_rule_context,
                self.body,
                " ".join(self.related_terms),
                " ".join(self.warnings),
            )
        )
        forbidden = [term for term in FORBIDDEN_PROMISE_TERMS if term in combined]
        if forbidden:
            raise ValueError(f"help topic contains forbidden promise terms: {forbidden}")
        if "国际理论" not in self.theory_context:
            raise ValueError("theory_context must explicitly mention 国际理论")
        if "中国市场规则" not in self.china_rule_context:
            raise ValueError("china_rule_context must explicitly mention 中国市场规则")
        return self

    @property
    def searchable_text(self) -> str:
        return " ".join(
            (
                self.topic_id,
                self.title,
                self.summary,
                self.theory_context,
                self.china_rule_context,
                self.body,
                " ".join(self.related_terms),
            )
        ).lower()


class KnowledgeCenter:
    def __init__(self, topics: tuple[HelpTopic, ...] = ()) -> None:
        self._topics = topics or DEFAULT_KNOWLEDGE_TOPICS
        self._by_id = {topic.topic_id: topic for topic in self._topics}
        if len(self._by_id) != len(self._topics):
            raise ValueError("knowledge topic ids must be unique")

    def list_topics(self) -> tuple[HelpTopic, ...]:
        return tuple(sorted(self._topics, key=lambda topic: topic.topic_id))

    def get_topic(self, topic_id: str) -> HelpTopic:
        try:
            return self._by_id[topic_id]
        except KeyError as exc:
            raise KeyError(f"unknown knowledge topic: {topic_id}") from exc

    def search(self, query: str) -> tuple[HelpTopic, ...]:
        normalized = query.strip().lower()
        if not normalized:
            return self.list_topics()
        matches = (
            (topic, _match_score(topic, normalized))
            for topic in self.list_topics()
            if normalized in topic.searchable_text
        )
        return tuple(
            topic
            for topic, _score in sorted(
                matches,
                key=lambda item: (-item[1], item[0].topic_id),
            )
        )

    def contextual_help(self, term: str) -> HelpTopic | None:
        matches = self.search(term)
        return matches[0] if matches else None


DEFAULT_KNOWLEDGE_TOPICS = (
    HelpTopic(
        topic_id="kline_ohlc",
        title="K线 / OHLC",
        summary="K线记录一个时间区间内的开盘、最高、最低和收盘价格。",
        theory_context="国际理论：K线和技术指标属于价格行为特征，可作为统计输入。",
        china_rule_context="中国市场规则：分钟、日线和复权口径必须与交易时段、停牌和公司行为一致。",
        body=(
            "K线本身不是独立买入理由；它需要和样本外验证、成本、流动性、"
            "数据质量以及风险预算一起使用。"
        ),
        related_terms=("OHLC", "复权", "停牌", "公司行为"),
    ),
    HelpTopic(
        topic_id="t_plus_turnover",
        title="T+ / 回转交易",
        summary="T+表示交易或确认的时间约束，不同资产含义不同。",
        theory_context="国际理论：成交时序影响回测可实现性，不能把不可得价格用于当前决策。",
        china_rule_context="中国市场规则：A股通常受T+1可卖约束，ETF和基金按产品规则确认。",
        body=(
            "系统按资产类型和生效规则计算可卖数量、确认日期和成交资格；"
            "不得用一个固定T+规则套用所有证券。"
        ),
        related_terms=("T+1", "回转交易", "可卖数量", "确认日期"),
    ),
    HelpTopic(
        topic_id="etf",
        title="ETF",
        summary="ETF是交易所交易基金，兼具基金组合和交易所价格特征。",
        theory_context="国际理论：ETF可用于资产配置、分散化和相对强弱比较。",
        china_rule_context="中国市场规则：场内ETF使用交易所价格，回转资格、费用和流动性按产品规则。",
        body=("ETF轮动基准仍是研究状态，最终操作需要数据质量、规则、风险和组合门禁。"),
        related_terms=("场内基金", "轮动", "流动性", "折溢价"),
    ),
    HelpTopic(
        topic_id="fund_nav",
        title="基金净值",
        summary="场外基金分析使用正式披露净值，盘中估算只可作为参考信息。",
        theory_context="国际理论：净值序列可用于收益、波动、回撤和同类比较。",
        china_rule_context="中国市场规则：场外基金申赎按正式净值和确认规则处理，估算净值不得替代。",
        body=("正式净值和估算净值在模型中使用不同类型，估算净值不能进入正式回测或确认路径。"),
        related_terms=("正式净值", "估算净值", "申购", "赎回"),
    ),
    HelpTopic(
        topic_id="max_drawdown",
        title="最大回撤",
        summary="最大回撤表示净值从历史峰值到后续谷值的最大跌幅。",
        theory_context="国际理论：回撤用于衡量路径风险和尾部亏损压力。",
        china_rule_context="中国市场规则：回撤控制仍需结合涨跌停、停牌、流动性和可卖数量。",
        body=("较低回撤不表示未来不会亏损；它只是历史或模拟路径上的风险摘要。"),
        related_terms=("回撤", "风险预算", "尾部风险", "净值"),
    ),
    HelpTopic(
        topic_id="positive_expectancy",
        title="期望值",
        summary="正期望值表示扣除成本后的长期平均结果为正。",
        theory_context="国际理论：期望值需要由收益概率、盈亏幅度和成本共同决定。",
        china_rule_context="中国市场规则：交易成本、滑点、涨跌停和成交限制会改变期望值。",
        body=("正期望值不表示每笔交易盈利；样本不足或成本上升时系统应降低置信度或ABSTAIN。"),
        related_terms=("正期望值", "成本", "胜率", "盈亏比"),
    ),
    HelpTopic(
        topic_id="probability_calibration",
        title="概率校准",
        summary="概率校准检查模型概率和长期实际频率是否一致。",
        theory_context="国际理论：Brier、LogLoss和ECE可用于评估概率质量。",
        china_rule_context="中国市场规则：校准结果必须在中国市场数据和当前规则语境下验证。",
        body=("未经校准的分数不能当作概率；低置信度、漂移或分布外输入会触发不交易。"),
        related_terms=("Brier", "LogLoss", "ECE", "ABSTAIN"),
    ),
)


def _match_score(topic: HelpTopic, normalized_query: str) -> int:
    title = topic.title.lower()
    related_terms = tuple(term.lower() for term in topic.related_terms)
    if normalized_query == title:
        return 100
    if normalized_query in title:
        return 90
    if any(normalized_query == term for term in related_terms):
        return 80
    if any(normalized_query in term for term in related_terms):
        return 70
    if normalized_query in topic.summary.lower():
        return 60
    if normalized_query in topic.theory_context.lower():
        return 50
    if normalized_query in topic.china_rule_context.lower():
        return 40
    return 10
