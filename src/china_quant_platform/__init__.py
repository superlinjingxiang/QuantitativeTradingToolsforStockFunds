"""China stock and fund quant analysis platform."""

from china_quant_platform.app.runtime import RuntimeContext, bootstrap_runtime
from china_quant_platform.infrastructure.config import AppSettings
from china_quant_platform.infrastructure.logging import configure_logging

__version__ = "0.1.0"

__all__ = [
    "__version__",
    "AppSettings",
    "RuntimeContext",
    "bootstrap_runtime",
    "configure_logging",
]
