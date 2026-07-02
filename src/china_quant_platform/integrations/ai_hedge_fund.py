"""Adapter for the external virattt/ai-hedge-fund research agent.

The integration is intentionally process-based and optional. The external
project has a large dependency surface and requires its own API keys, so the
core China Quant strategy engine remains independent.
"""

from __future__ import annotations

import os
import subprocess
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path

AI_HEDGE_FUND_REPO_ENV = "CHINA_QUANT_AI_HEDGE_FUND_PATH"
DEFAULT_ANALYSTS = (
    "technical_analyst",
    "fundamentals_analyst",
    "valuation_analyst",
)
LLM_API_KEY_ENV_NAMES = (
    "OPENAI_API_KEY",
    "ANTHROPIC_API_KEY",
    "DEEPSEEK_API_KEY",
    "GROQ_API_KEY",
    "GOOGLE_API_KEY",
    "XAI_API_KEY",
    "MOONSHOT_API_KEY",
    "GIGACHAT_API_KEY",
    "OPENROUTER_API_KEY",
    "AZURE_OPENAI_API_KEY",
)


class AiHedgeFundIntegrationError(RuntimeError):
    """Raised when the optional ai-hedge-fund integration cannot run."""


@dataclass(frozen=True, slots=True)
class AiHedgeFundRequest:
    """CLI request for the external ai-hedge-fund agent."""

    tickers: tuple[str, ...]
    start_date: str | None = None
    end_date: str | None = None
    analysts: tuple[str, ...] = DEFAULT_ANALYSTS
    use_all_analysts: bool = False
    model: str = "gpt-4.1"
    use_ollama: bool = False
    show_reasoning: bool = False
    initial_cash: float = 100_000.0
    margin_requirement: float = 0.0

    def __post_init__(self) -> None:
        tickers = normalize_csv_items(self.tickers)
        if not tickers:
            raise ValueError("ai-hedge-fund request requires at least one ticker")
        object.__setattr__(self, "tickers", tickers)
        object.__setattr__(self, "analysts", normalize_csv_items(self.analysts))
        if self.initial_cash <= 0:
            raise ValueError("initial_cash must be positive")
        if not 0 <= self.margin_requirement <= 1:
            raise ValueError("margin_requirement must be between 0 and 1")


@dataclass(frozen=True, slots=True)
class AiHedgeFundRunResult:
    """Captured subprocess result from the external agent."""

    command: tuple[str, ...]
    repo_path: Path
    returncode: int
    stdout: str
    stderr: str
    missing_environment: tuple[str, ...] = field(default_factory=tuple)

    @property
    def ok(self) -> bool:
        return self.returncode == 0


def resolve_ai_hedge_fund_repo(
    explicit_repo: str | Path | None = None,
    *,
    env: Mapping[str, str] | None = None,
) -> Path:
    """Resolve and validate an external ai-hedge-fund checkout."""

    values = os.environ if env is None else env
    raw_path = (
        str(explicit_repo) if explicit_repo is not None else values.get(AI_HEDGE_FUND_REPO_ENV)
    )
    if not raw_path:
        raise AiHedgeFundIntegrationError(
            f"missing ai-hedge-fund repository path; pass --repo or set {AI_HEDGE_FUND_REPO_ENV}"
        )

    repo_path = Path(raw_path).expanduser().resolve()
    main_file = repo_path / "src" / "main.py"
    if not main_file.exists():
        raise AiHedgeFundIntegrationError(f"invalid ai-hedge-fund repository: expected {main_file}")
    return repo_path


def normalize_csv_items(items: str | Sequence[str]) -> tuple[str, ...]:
    """Normalize comma-separated CLI values into a stable tuple."""

    raw_items = (items,) if isinstance(items, str) else tuple(items)
    normalized: list[str] = []
    for item in raw_items:
        normalized.extend(part.strip() for part in item.split(",") if part.strip())
    return tuple(dict.fromkeys(normalized))


def build_ai_hedge_fund_command(
    repo_path: Path,
    request: AiHedgeFundRequest,
    *,
    python_executable: str | Path | None = None,
) -> tuple[str, ...]:
    """Build the external process command without executing it."""

    executable = str(python_executable or sys.executable)
    command: list[str] = [
        executable,
        str(repo_path / "src" / "main.py"),
        "--ticker",
        ",".join(request.tickers),
        "--initial-cash",
        f"{request.initial_cash:.2f}",
        "--margin-requirement",
        f"{request.margin_requirement:.6f}",
    ]
    if request.start_date is not None:
        command.extend(["--start-date", request.start_date])
    if request.end_date is not None:
        command.extend(["--end-date", request.end_date])
    if request.use_all_analysts:
        command.append("--analysts-all")
    elif request.analysts:
        command.extend(["--analysts", ",".join(request.analysts)])
    if request.use_ollama:
        command.append("--ollama")
    if request.model:
        command.extend(["--model", request.model])
    if request.show_reasoning:
        command.append("--show-reasoning")
    return tuple(command)


def find_missing_ai_hedge_fund_environment(
    request: AiHedgeFundRequest,
    *,
    env: Mapping[str, str] | None = None,
) -> tuple[str, ...]:
    """Return required environment values that are currently missing."""

    values = os.environ if env is None else env
    missing: list[str] = []
    if not values.get("FINANCIAL_DATASETS_API_KEY"):
        missing.append("FINANCIAL_DATASETS_API_KEY")
    if not request.use_ollama and not any(values.get(name) for name in LLM_API_KEY_ENV_NAMES):
        missing.append("one of " + "/".join(LLM_API_KEY_ENV_NAMES))
    return tuple(missing)


def run_ai_hedge_fund_cli(
    repo_path: str | Path,
    request: AiHedgeFundRequest,
    *,
    python_executable: str | Path | None = None,
    timeout_seconds: int = 600,
    env: Mapping[str, str] | None = None,
    skip_environment_check: bool = False,
) -> AiHedgeFundRunResult:
    """Run the external ai-hedge-fund CLI and capture its output."""

    resolved_repo = resolve_ai_hedge_fund_repo(repo_path, env=env)
    process_env = _merged_env(resolved_repo, env=env)
    command = build_ai_hedge_fund_command(
        resolved_repo,
        request,
        python_executable=python_executable,
    )
    missing = (
        ()
        if skip_environment_check
        else find_missing_ai_hedge_fund_environment(request, env=process_env)
    )
    if missing:
        return AiHedgeFundRunResult(
            command=command,
            repo_path=resolved_repo,
            returncode=2,
            stdout="",
            stderr="Missing required ai-hedge-fund environment: " + ", ".join(missing),
            missing_environment=missing,
        )

    completed = subprocess.run(
        command,
        cwd=resolved_repo,
        env=process_env,
        text=True,
        capture_output=True,
        timeout=timeout_seconds,
        check=False,
    )
    return AiHedgeFundRunResult(
        command=command,
        repo_path=resolved_repo,
        returncode=completed.returncode,
        stdout=completed.stdout,
        stderr=completed.stderr,
    )


def _merged_env(repo_path: Path, *, env: Mapping[str, str] | None = None) -> dict[str, str]:
    process_env = os.environ.copy()
    process_env.update(_read_dotenv(repo_path / ".env"))
    if env is not None:
        process_env.update(env)
    return process_env


def _read_dotenv(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key:
            values[key] = value
    return values
