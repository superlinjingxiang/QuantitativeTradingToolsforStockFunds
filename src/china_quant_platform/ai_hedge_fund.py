"""Standalone command entry for the optional ai-hedge-fund research agent."""

from __future__ import annotations

import argparse
import shlex
import sys
from collections.abc import Sequence
from pathlib import Path

from china_quant_platform.integrations.ai_hedge_fund import (
    DEFAULT_ANALYSTS,
    AiHedgeFundIntegrationError,
    AiHedgeFundRequest,
    build_ai_hedge_fund_command,
    normalize_csv_items,
    resolve_ai_hedge_fund_repo,
    run_ai_hedge_fund_cli,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="china-quant-ai-hedge-fund",
        description=(
            "Run the external virattt/ai-hedge-fund agent through an isolated "
            "research-only entry point."
        ),
    )
    parser.add_argument(
        "--repo",
        type=Path,
        default=None,
        help=(
            "Path to a local ai-hedge-fund checkout. "
            "Alternatively set CHINA_QUANT_AI_HEDGE_FUND_PATH."
        ),
    )
    parser.add_argument(
        "--python",
        dest="python_executable",
        default=sys.executable,
        help="Python executable that has ai-hedge-fund dependencies installed.",
    )
    parser.add_argument(
        "--ticker",
        "--tickers",
        dest="tickers",
        required=True,
        help="Comma-separated US ticker symbols supported by ai-hedge-fund, e.g. AAPL,MSFT,NVDA.",
    )
    parser.add_argument("--start-date", help="Start date passed to ai-hedge-fund, YYYY-MM-DD.")
    parser.add_argument("--end-date", help="End date passed to ai-hedge-fund, YYYY-MM-DD.")
    parser.add_argument(
        "--analysts",
        default=",".join(DEFAULT_ANALYSTS),
        help=(
            "Comma-separated ai-hedge-fund analyst keys. "
            "Defaults to a compact technical/fundamental/valuation set."
        ),
    )
    parser.add_argument(
        "--analysts-all",
        action="store_true",
        help="Use all ai-hedge-fund analysts instead of --analysts.",
    )
    parser.add_argument(
        "--model", default="gpt-4.1", help="LLM model name passed to ai-hedge-fund."
    )
    parser.add_argument("--ollama", action="store_true", help="Use ai-hedge-fund's Ollama mode.")
    parser.add_argument(
        "--show-reasoning", action="store_true", help="Ask ai-hedge-fund to show agent reasoning."
    )
    parser.add_argument("--initial-cash", type=float, default=100_000.0)
    parser.add_argument("--margin-requirement", type=float, default=0.0)
    parser.add_argument(
        "--timeout-seconds",
        type=int,
        default=600,
        help="Maximum external process runtime.",
    )
    parser.add_argument(
        "--skip-api-key-check",
        action="store_true",
        help="Run without local FINANCIAL_DATASETS/LLM key preflight checks.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Only print the external command; do not run the agent.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        repo_path = resolve_ai_hedge_fund_repo(args.repo)
        request = AiHedgeFundRequest(
            tickers=normalize_csv_items(args.tickers),
            start_date=args.start_date,
            end_date=args.end_date,
            analysts=normalize_csv_items(args.analysts),
            use_all_analysts=args.analysts_all,
            model=args.model,
            use_ollama=args.ollama,
            show_reasoning=args.show_reasoning,
            initial_cash=args.initial_cash,
            margin_requirement=args.margin_requirement,
        )
    except (AiHedgeFundIntegrationError, ValueError) as exc:
        print(f"ai-hedge-fund入口配置错误：{exc}", file=sys.stderr)
        return 2

    command = build_ai_hedge_fund_command(
        repo_path,
        request,
        python_executable=args.python_executable,
    )
    if args.dry_run:
        print("AI Hedge Fund 独立研究入口 dry-run")
        print(f"repo={repo_path}")
        print("command=" + shlex.join(command))
        print("说明：该入口不会替换 china_quant_platform.strategies.profit_validation。")
        return 0

    result = run_ai_hedge_fund_cli(
        repo_path,
        request,
        python_executable=args.python_executable,
        timeout_seconds=args.timeout_seconds,
        skip_environment_check=args.skip_api_key_check,
    )
    if result.stdout:
        print(result.stdout, end="")
    if result.stderr:
        print(result.stderr, end="" if result.stderr.endswith("\n") else "\n", file=sys.stderr)
    return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
