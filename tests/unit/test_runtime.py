"""Runtime bootstrap behavior tests."""

from __future__ import annotations

import logging
from pathlib import Path

from china_quant_platform import AppSettings, bootstrap_runtime, configure_logging


def test_bootstrap_runtime_is_side_effect_free_by_default(tmp_path: Path) -> None:
    settings = AppSettings(
        data_dir=tmp_path / "data",
        logs_dir=tmp_path / "logs",
        reports_dir=tmp_path / "reports",
    )

    context = bootstrap_runtime(
        settings=settings,
        project_root=tmp_path,
        create_dirs=False,
        configure_logs=False,
    )

    assert context.project_root == tmp_path.resolve()
    assert context.data_dir == tmp_path / "data"
    assert context.logs_dir == tmp_path / "logs"
    assert context.reports_dir == tmp_path / "reports"
    assert not context.data_dir.exists()
    assert not context.logs_dir.exists()
    assert not context.reports_dir.exists()


def test_bootstrap_runtime_can_create_runtime_directories(tmp_path: Path) -> None:
    settings = AppSettings(
        data_dir=tmp_path / "data",
        logs_dir=tmp_path / "logs",
        reports_dir=tmp_path / "reports",
    )

    context = bootstrap_runtime(
        settings=settings,
        project_root=tmp_path,
        create_dirs=True,
        configure_logs=False,
    )

    assert context.data_dir.is_dir()
    assert context.logs_dir.is_dir()
    assert context.reports_dir.is_dir()


def test_configure_logging_is_idempotent() -> None:
    logger = configure_logging(logging.DEBUG)
    handlers = list(logger.handlers)

    assert configure_logging("INFO") is logger
    assert list(logger.handlers) == handlers
