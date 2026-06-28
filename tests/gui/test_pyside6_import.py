"""GUI dependency smoke tests."""

from __future__ import annotations

from PySide6 import QtCore


def test_pyside6_qtcore_imports() -> None:
    assert QtCore.qVersion()
