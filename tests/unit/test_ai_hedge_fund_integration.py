"""Optional ai-hedge-fund research entry tests."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from china_quant_platform.ai_hedge_fund import main as ai_hedge_fund_main
from china_quant_platform.integrations.ai_hedge_fund import (
    AI_HEDGE_FUND_REPO_ENV,
    AiHedgeFundIntegrationError,
    AiHedgeFundRequest,
    build_ai_hedge_fund_command,
    find_missing_ai_hedge_fund_environment,
    resolve_ai_hedge_fund_repo,
    run_ai_hedge_fund_cli,
)


def make_fake_ai_hedge_fund_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "ai-hedge-fund"
    src = repo / "src"
    src.mkdir(parents=True)
    (src / "main.py").write_text(
        "import json, sys\nprint(json.dumps({'argv': sys.argv[1:]}, ensure_ascii=False))\n",
        encoding="utf-8",
    )
    return repo


def test_build_ai_hedge_fund_command_keeps_external_agent_isolated(tmp_path: Path) -> None:
    repo = make_fake_ai_hedge_fund_repo(tmp_path)
    request = AiHedgeFundRequest(
        tickers=("AAPL", "MSFT"),
        start_date="2026-01-01",
        end_date="2026-02-01",
        analysts=("technical_analyst", "valuation_analyst"),
        model="gpt-4.1",
        initial_cash=50_000,
    )

    command = build_ai_hedge_fund_command(
        repo,
        request,
        python_executable="python-test",
    )

    assert command[:4] == (
        "python-test",
        str(repo / "src" / "main.py"),
        "--ticker",
        "AAPL,MSFT",
    )
    assert "--analysts" in command
    assert "technical_analyst,valuation_analyst" in command
    assert "--model" in command
    assert "gpt-4.1" in command
    assert "--start-date" in command
    assert "--end-date" in command


def test_resolve_ai_hedge_fund_repo_accepts_env_path(tmp_path: Path) -> None:
    repo = make_fake_ai_hedge_fund_repo(tmp_path)

    assert resolve_ai_hedge_fund_repo(env={AI_HEDGE_FUND_REPO_ENV: str(repo)}) == repo


def test_resolve_ai_hedge_fund_repo_rejects_missing_checkout(tmp_path: Path) -> None:
    missing = tmp_path / "missing"

    try:
        resolve_ai_hedge_fund_repo(missing)
    except AiHedgeFundIntegrationError as exc:
        assert "expected" in str(exc)
    else:
        raise AssertionError("expected invalid repo to fail")


def test_environment_preflight_requires_data_and_llm_keys() -> None:
    request = AiHedgeFundRequest(tickers=("AAPL",))

    missing = find_missing_ai_hedge_fund_environment(request, env={})

    assert "FINANCIAL_DATASETS_API_KEY" in missing
    assert any(item.startswith("one of OPENAI_API_KEY") for item in missing)


def test_environment_preflight_ollama_only_requires_financial_data_key() -> None:
    request = AiHedgeFundRequest(tickers=("AAPL",), use_ollama=True)

    missing = find_missing_ai_hedge_fund_environment(request, env={})

    assert missing == ("FINANCIAL_DATASETS_API_KEY",)


def test_run_ai_hedge_fund_cli_uses_subprocess_without_core_strategy_import(
    tmp_path: Path,
) -> None:
    repo = make_fake_ai_hedge_fund_repo(tmp_path)
    request = AiHedgeFundRequest(tickers=("AAPL",), analysts=("technical_analyst",))

    result = run_ai_hedge_fund_cli(
        repo,
        request,
        python_executable=sys.executable,
        timeout_seconds=5,
        skip_environment_check=True,
    )

    assert result.ok is True
    assert "--ticker" in result.stdout
    assert "AAPL" in result.stdout
    assert "technical_analyst" in result.stdout


def test_run_ai_hedge_fund_cli_reads_external_repo_dotenv(tmp_path: Path) -> None:
    repo = make_fake_ai_hedge_fund_repo(tmp_path)
    (repo / ".env").write_text(
        "FINANCIAL_DATASETS_API_KEY=fake-financial-key\nOPENAI_API_KEY=fake-openai-key\n",
        encoding="utf-8",
    )
    request = AiHedgeFundRequest(tickers=("AAPL",), analysts=("technical_analyst",))

    result = run_ai_hedge_fund_cli(
        repo,
        request,
        python_executable=sys.executable,
        timeout_seconds=5,
    )

    assert result.ok is True
    assert result.missing_environment == ()
    assert "AAPL" in result.stdout


def test_ai_hedge_fund_module_dry_run_prints_command(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    repo = make_fake_ai_hedge_fund_repo(tmp_path)

    exit_code = ai_hedge_fund_main(
        [
            "--repo",
            str(repo),
            "--ticker",
            "AAPL",
            "--dry-run",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "AI Hedge Fund 独立研究入口 dry-run" in captured.out
    assert "profit_validation" in captured.out
    assert str(repo / "src" / "main.py") in captured.out
