"""Optional third-party integrations.

These adapters are deliberately kept outside the core strategy package so that
research tools cannot replace validated platform strategies by accident.
"""

from china_quant_platform.integrations.ai_hedge_fund import (
    AI_HEDGE_FUND_REPO_ENV,
    AiHedgeFundIntegrationError,
    AiHedgeFundRequest,
    AiHedgeFundRunResult,
    build_ai_hedge_fund_command,
    find_missing_ai_hedge_fund_environment,
    resolve_ai_hedge_fund_repo,
    run_ai_hedge_fund_cli,
)

__all__ = [
    "AI_HEDGE_FUND_REPO_ENV",
    "AiHedgeFundIntegrationError",
    "AiHedgeFundRequest",
    "AiHedgeFundRunResult",
    "build_ai_hedge_fund_command",
    "find_missing_ai_hedge_fund_environment",
    "resolve_ai_hedge_fund_repo",
    "run_ai_hedge_fund_cli",
]
