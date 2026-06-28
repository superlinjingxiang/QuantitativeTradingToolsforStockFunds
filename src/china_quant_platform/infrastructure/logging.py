"""Logging helpers for application startup and tests."""

from __future__ import annotations

import logging


def configure_logging(level: str | int = "INFO") -> logging.Logger:
    """Configure the package logger without installing duplicate handlers."""

    logger = logging.getLogger("china_quant_platform")
    logger.setLevel(level)
    logger.propagate = True
    return logger
