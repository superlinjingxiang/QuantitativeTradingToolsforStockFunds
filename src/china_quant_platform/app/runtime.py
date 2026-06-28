"""Runtime bootstrap helpers for the desktop application foundation."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from china_quant_platform.infrastructure.config import AppSettings
from china_quant_platform.infrastructure.logging import configure_logging


@dataclass(frozen=True, slots=True)
class RuntimeContext:
    """Resolved runtime paths and settings for application startup."""

    settings: AppSettings
    project_root: Path
    data_dir: Path
    logs_dir: Path
    reports_dir: Path


def _resolve_path(project_root: Path, path: Path) -> Path:
    if path.is_absolute():
        return path
    return project_root / path


def bootstrap_runtime(
    settings: AppSettings | None = None,
    *,
    project_root: Path | None = None,
    create_dirs: bool = False,
    configure_logs: bool = True,
) -> RuntimeContext:
    """Resolve runtime configuration without starting GUI or data providers."""

    resolved_settings = settings or AppSettings()
    resolved_root = (project_root or Path.cwd()).resolve()
    context = RuntimeContext(
        settings=resolved_settings,
        project_root=resolved_root,
        data_dir=_resolve_path(resolved_root, resolved_settings.data_dir),
        logs_dir=_resolve_path(resolved_root, resolved_settings.logs_dir),
        reports_dir=_resolve_path(resolved_root, resolved_settings.reports_dir),
    )

    if create_dirs:
        for directory in (context.data_dir, context.logs_dir, context.reports_dir):
            directory.mkdir(parents=True, exist_ok=True)

    if configure_logs:
        configure_logging(resolved_settings.log_level)

    return context
