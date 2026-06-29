"""Knowledge center content and safety tests."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from china_quant_platform.knowledge import (
    DEFAULT_KNOWLEDGE_TOPICS,
    FORBIDDEN_PROMISE_TERMS,
    HelpTopic,
    KnowledgeCenter,
)


def test_default_topics_cover_required_terms_and_distinguish_theory_rules() -> None:
    required_ids = {
        "kline_ohlc",
        "t_plus_turnover",
        "etf",
        "fund_nav",
        "max_drawdown",
        "positive_expectancy",
        "probability_calibration",
    }

    assert {topic.topic_id for topic in DEFAULT_KNOWLEDGE_TOPICS} == required_ids
    for topic in DEFAULT_KNOWLEDGE_TOPICS:
        combined_text = " ".join(
            (
                topic.title,
                topic.summary,
                topic.theory_context,
                topic.china_rule_context,
                topic.body,
                " ".join(topic.related_terms),
                " ".join(topic.warnings),
            )
        )
        assert "国际理论" in topic.theory_context
        assert "中国市场规则" in topic.china_rule_context
        assert all(term not in combined_text for term in FORBIDDEN_PROMISE_TERMS)


def test_search_and_contextual_help_find_terms() -> None:
    center = KnowledgeCenter()

    assert center.search("概率校准")[0].topic_id == "probability_calibration"
    assert center.search("T+1")[0].topic_id == "t_plus_turnover"
    help_topic = center.contextual_help("回撤")

    assert help_topic is not None
    assert help_topic.topic_id == "max_drawdown"


def test_help_topic_rejects_promise_terms_and_missing_context() -> None:
    with pytest.raises(ValidationError, match="forbidden promise"):
        HelpTopic(
            topic_id="unsafe",
            title="收益说明",
            summary="保证收益",
            theory_context="国际理论：概率用于表达不确定性。",
            china_rule_context="中国市场规则：交易规则影响可实现性。",
            body="测试条目。",
        )

    with pytest.raises(ValidationError, match="国际理论"):
        HelpTopic(
            topic_id="missing_theory",
            title="缺少理论上下文",
            summary="测试摘要。",
            theory_context="概率用于表达不确定性。",
            china_rule_context="中国市场规则：交易规则影响可实现性。",
            body="测试条目。",
        )

    with pytest.raises(ValidationError, match="中国市场规则"):
        HelpTopic(
            topic_id="missing_china_rules",
            title="缺少中国规则上下文",
            summary="测试摘要。",
            theory_context="国际理论：概率用于表达不确定性。",
            china_rule_context="交易规则影响可实现性。",
            body="测试条目。",
        )
