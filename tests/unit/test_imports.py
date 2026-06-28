"""Foundation import and command smoke tests."""

from __future__ import annotations

import subprocess
import sys

import china_quant_platform


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
