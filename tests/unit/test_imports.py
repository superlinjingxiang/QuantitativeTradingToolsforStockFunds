"""Foundation import and command smoke tests."""

from __future__ import annotations

import subprocess
import sys

from pytest import MonkeyPatch

import china_quant_platform
from china_quant_platform.__main__ import _is_packaged_app_without_args


def test_package_exposes_public_foundation_api() -> None:
    assert china_quant_platform.__version__ == "0.1.0"
    assert china_quant_platform.AppSettings is not None
    assert china_quant_platform.RuntimeContext is not None
    assert china_quant_platform.bootstrap_runtime is not None
    assert china_quant_platform.configure_logging is not None


def test_module_version_command() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "china_quant_platform", "--version"],
        check=True,
        capture_output=True,
        text=True,
    )

    assert result.stdout.strip() == china_quant_platform.__version__


def test_packaged_exe_without_args_defaults_to_gui(monkeypatch: MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "argv", ["china-quant-platform.exe"])

    assert _is_packaged_app_without_args(None) is True
    assert _is_packaged_app_without_args(()) is True
    assert _is_packaged_app_without_args(("--version",)) is False
