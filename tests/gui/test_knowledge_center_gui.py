"""Knowledge center GUI tests."""

from __future__ import annotations

from typing import Any

from PySide6 import QtCore, QtWidgets

from china_quant_platform.knowledge import FORBIDDEN_PROMISE_TERMS
from china_quant_platform.ui import ApplicationViewModel, MainWindow


def test_view_model_initializes_knowledge_topics_and_contextual_help() -> None:
    view_model = ApplicationViewModel()

    assert len(view_model.state.knowledge.topics) >= 7
    help_text = view_model.contextual_help("ETF")

    assert help_text is not None
    assert "国际理论" in help_text
    assert "中国市场规则" in help_text
    assert all(term not in help_text for term in FORBIDDEN_PROMISE_TERMS)

    view_model.search_knowledge("净值")

    assert view_model.state.knowledge.query == "净值"
    assert view_model.state.knowledge.selected_topic_id == "fund_nav"


def test_main_window_renders_and_filters_knowledge_center(qtbot: Any) -> None:
    view_model = ApplicationViewModel()
    window = MainWindow(view_model)
    qtbot.addWidget(window)

    search = window.findChild(QtWidgets.QLineEdit, "knowledgeSearch")
    topics = window.findChild(QtWidgets.QListWidget, "knowledgeTopics")
    detail = window.findChild(QtWidgets.QTextBrowser, "knowledgeDetail")
    assert search is not None
    assert topics is not None
    assert detail is not None
    assert topics.count() >= 7

    qtbot.keyClicks(search, "max_drawdown")

    assert topics.count() == 1
    assert "最大回撤" in topics.item(0).text()
    topics.itemActivated.emit(topics.item(0))

    assert "国际理论" in detail.toPlainText()
    assert "中国市场规则" in detail.toPlainText()
    assert "保证收益" not in detail.toPlainText()
    assert topics.item(0).data(QtCore.Qt.ItemDataRole.UserRole) == "max_drawdown"
