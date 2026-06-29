"""Structured MVP release audit and credential scanning."""

from __future__ import annotations

import argparse
import json
import re
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import Literal

from china_quant_platform import __version__
from china_quant_platform.domain.base import DomainModel

ACCEPTANCE_IDS = tuple(f"AC-{index:02d}" for index in range(1, 13))
NFR_IDS = tuple(f"NFR-{index:02d}" for index in range(1, 9))
DEFINITION_OF_DONE_IDS = (
    "DoD-implementation",
    "DoD-verification",
    "DoD-traceability",
    "DoD-delivery",
)

_EXCLUDED_SCAN_DIRS = frozenset(
    {
        ".git",
        ".mypy_cache",
        ".pytest-cache",
        ".pytest_cache",
        ".pytest-tmp",
        ".ruff_cache",
        ".uv-bootstrap",
        ".uv-cache",
        ".venv",
        "__pycache__",
        "build",
        "data",
        "dist",
        "logs",
        "reports",
    }
)
_TEXT_SUFFIXES = frozenset(
    {
        "",
        ".cfg",
        ".css",
        ".example",
        ".gitignore",
        ".ini",
        ".json",
        ".md",
        ".py",
        ".spec",
        ".toml",
        ".txt",
        ".yaml",
        ".yml",
    }
)
_SECRET_PATTERNS = (
    (
        "private_key",
        re.compile(r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----"),
    ),
    (
        "aws_access_key",
        re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    ),
    (
        "assigned_secret",
        re.compile(
            r"(?i)\b(api[_-]?key|secret|access[_-]?token|auth[_-]?token|password)\b\s*=\s*"
            r"[\"']?([A-Za-z0-9_\-]{16,})[\"']?"
        ),
    ),
)


class ReleaseCommand(DomainModel):
    name: str
    command: tuple[str, ...]
    purpose: str
    produces: str | None = None
    windows_only: bool = False

    @property
    def shell_text(self) -> str:
        return " ".join(self.command)


class ReleaseGate(DomainModel):
    gate_id: str
    description: str
    evidence: str
    status: Literal["pass", "manual-review"] = "pass"


class ReleaseMigrationStep(DomainModel):
    step_id: str
    description: str
    idempotent: bool
    rollback: str


class CredentialPolicy(DomainModel):
    allowed_sources: tuple[str, ...]
    forbidden_locations: tuple[str, ...]
    redaction_fields: tuple[str, ...]
    scan_pattern_ids: tuple[str, ...]


class CredentialFinding(DomainModel):
    path: str
    pattern_id: str
    redacted_match: str


class ReleaseAuditReport(DomainModel):
    version: str
    package_name: str
    manifest_path: str
    windows_package_command: ReleaseCommand
    smoke_test_commands: tuple[ReleaseCommand, ...]
    migration_steps: tuple[ReleaseMigrationStep, ...]
    credential_policy: CredentialPolicy
    recovery_checks: tuple[ReleaseGate, ...]
    observability_checks: tuple[ReleaseGate, ...]
    acceptance_gates: tuple[ReleaseGate, ...]
    nfr_gates: tuple[ReleaseGate, ...]
    definition_of_done_gates: tuple[ReleaseGate, ...]

    @property
    def acceptance_ids(self) -> tuple[str, ...]:
        return tuple(gate.gate_id for gate in self.acceptance_gates)

    @property
    def nfr_ids(self) -> tuple[str, ...]:
        return tuple(gate.gate_id for gate in self.nfr_gates)

    @property
    def definition_of_done_ids(self) -> tuple[str, ...]:
        return tuple(gate.gate_id for gate in self.definition_of_done_gates)


class ReleaseAuditResult(DomainModel):
    passed: bool
    failures: tuple[str, ...] = ()


def build_release_audit_report(version: str = __version__) -> ReleaseAuditReport:
    """Build the static MVP release checklist used by docs, CI, and tests."""

    return ReleaseAuditReport(
        version=version,
        package_name=f"china-quant-platform-{version}-windows",
        manifest_path="MANIFEST.sha256",
        windows_package_command=ReleaseCommand(
            name="windows-pyinstaller-package",
            command=(
                "uv",
                "run",
                "pyinstaller",
                "packaging/china_quant_platform.spec",
                "--noconfirm",
                "--clean",
            ),
            purpose="Build the Windows one-folder desktop package from the pinned environment.",
            produces="dist/china-quant-platform",
            windows_only=True,
        ),
        smoke_test_commands=(
            ReleaseCommand(
                name="dependency-lock",
                command=("uv", "lock"),
                purpose="Verify the dependency lock can be resolved.",
            ),
            ReleaseCommand(
                name="dependency-sync",
                command=("uv", "sync", "--all-extras", "--dev"),
                purpose="Install the pinned runtime and development tools.",
            ),
            ReleaseCommand(
                name="format-check",
                command=("uv", "run", "ruff", "format", "--check", "."),
                purpose="Verify formatting.",
            ),
            ReleaseCommand(
                name="lint",
                command=("uv", "run", "ruff", "check", "."),
                purpose="Verify lint rules.",
            ),
            ReleaseCommand(
                name="type-check",
                command=("uv", "run", "mypy", "src", "tests"),
                purpose="Verify static types.",
            ),
            ReleaseCommand(
                name="tests",
                command=("uv", "run", "pytest"),
                purpose="Run unit, integration, regression, and GUI tests.",
            ),
            ReleaseCommand(
                name="version-smoke",
                command=("uv", "run", "python", "-m", "china_quant_platform", "--version"),
                purpose="Verify the installed module entry point.",
            ),
            ReleaseCommand(
                name="release-audit",
                command=("uv", "run", "python", "-m", "china_quant_platform.release.audit"),
                purpose="Verify release gate coverage and embedded credential scan.",
            ),
            ReleaseCommand(
                name="packager-smoke",
                command=("uv", "run", "pyinstaller", "--version"),
                purpose="Verify the Windows packager is installed before building artifacts.",
            ),
        ),
        migration_steps=(
            ReleaseMigrationStep(
                step_id="runtime-directories",
                description="Create data, logs, and reports directories via bootstrap_runtime.",
                idempotent=True,
                rollback="Directories contain generated state only and can be recreated.",
            ),
            ReleaseMigrationStep(
                step_id="manifest-refresh",
                description="Refresh MANIFEST.sha256 after release files change.",
                idempotent=True,
                rollback="Regenerate from the Git-tracked release file list.",
            ),
            ReleaseMigrationStep(
                step_id="simulation-state",
                description="Persist and restore SimulationAccountState JSON snapshots.",
                idempotent=True,
                rollback="Keep the previous snapshot until the new checksum verifies.",
            ),
        ),
        credential_policy=CredentialPolicy(
            allowed_sources=(
                "environment variables with CQP_ prefix",
                "operating system credential store",
                "local ignored .env file",
            ),
            forbidden_locations=(
                "source code",
                "tests",
                "docs",
                "logs",
                "reports",
                "release package",
                "MANIFEST.sha256",
            ),
            redaction_fields=("api_key", "secret", "token", "password"),
            scan_pattern_ids=tuple(pattern_id for pattern_id, _pattern in _SECRET_PATTERNS),
        ),
        recovery_checks=(
            ReleaseGate(
                gate_id="recovery-runtime-paths",
                description="Runtime bootstrap can recreate data/log/report directories.",
                evidence="tests/unit/test_runtime.py",
            ),
            ReleaseGate(
                gate_id="recovery-simulation-account",
                description="Simulation account state is exportable and restorable.",
                evidence="tests/unit/test_simulation_broker.py",
            ),
            ReleaseGate(
                gate_id="recovery-task-cancel",
                description="Qt tasks can be cancelled without blocking the main thread.",
                evidence="tests/gui/test_app_shell.py",
            ),
        ),
        observability_checks=(
            ReleaseGate(
                gate_id="observability-data-health",
                description="Data health states expose stale/invalid causes to the UI.",
                evidence="tests/unit/test_data_quality.py; tests/gui/test_app_shell.py",
            ),
            ReleaseGate(
                gate_id="observability-audit-report",
                description="Analysis and backtest reports retain model, rule, and snapshot ids.",
                evidence="tests/unit/test_analysis_report_builder.py; tests/regression",
            ),
            ReleaseGate(
                gate_id="observability-release-audit",
                description="Release audit CLI emits machine-readable JSON.",
                evidence="tests/unit/test_release_audit.py",
            ),
        ),
        acceptance_gates=_build_acceptance_gates(),
        nfr_gates=_build_nfr_gates(),
        definition_of_done_gates=_build_definition_of_done_gates(),
    )


def validate_release_audit(report: ReleaseAuditReport) -> ReleaseAuditResult:
    failures: list[str] = []
    _require_ids("acceptance", ACCEPTANCE_IDS, report.acceptance_ids, failures)
    _require_ids("nfr", NFR_IDS, report.nfr_ids, failures)
    _require_ids(
        "definition of done",
        DEFINITION_OF_DONE_IDS,
        report.definition_of_done_ids,
        failures,
    )
    if "pyinstaller" not in report.windows_package_command.command:
        failures.append("Windows package command must use pyinstaller")
    if "packaging/china_quant_platform.spec" not in report.windows_package_command.command:
        failures.append(
            "Windows package command must reference packaging/china_quant_platform.spec"
        )
    smoke_names = {command.name for command in report.smoke_test_commands}
    for required in {
        "dependency-sync",
        "format-check",
        "lint",
        "type-check",
        "tests",
        "version-smoke",
        "release-audit",
        "packager-smoke",
    }:
        if required not in smoke_names:
            failures.append(f"missing smoke command: {required}")
    if not report.migration_steps:
        failures.append("release audit requires migration steps")
    if not report.recovery_checks:
        failures.append("release audit requires recovery checks")
    if not report.observability_checks:
        failures.append("release audit requires observability checks")
    if "source code" not in report.credential_policy.forbidden_locations:
        failures.append("credential policy must forbid secrets in source code")
    return ReleaseAuditResult(passed=not failures, failures=tuple(failures))


def iter_release_scan_paths(root: Path) -> tuple[Path, ...]:
    resolved_root = root.resolve()
    paths: list[Path] = []
    for path in resolved_root.rglob("*"):
        if not path.is_file():
            continue
        relative_parts = path.relative_to(resolved_root).parts
        if any(part in _EXCLUDED_SCAN_DIRS for part in relative_parts):
            continue
        if path.suffix.lower() not in _TEXT_SUFFIXES:
            continue
        paths.append(path)
    return tuple(sorted(paths))


def scan_for_embedded_credentials(
    root: Path,
    *,
    paths: Iterable[Path] | None = None,
) -> tuple[CredentialFinding, ...]:
    resolved_root = root.resolve()
    scan_paths = tuple(paths) if paths is not None else iter_release_scan_paths(resolved_root)
    findings: list[CredentialFinding] = []
    for path in scan_paths:
        resolved_path = path if path.is_absolute() else resolved_root / path
        try:
            text = resolved_path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            text = resolved_path.read_text(encoding="utf-8", errors="ignore")
        for pattern_id, pattern in _SECRET_PATTERNS:
            for match in pattern.finditer(text):
                findings.append(
                    CredentialFinding(
                        path=_relative_path(resolved_root, resolved_path),
                        pattern_id=pattern_id,
                        redacted_match=_redact(match.group(0)),
                    )
                )
    return tuple(findings)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m china_quant_platform.release.audit",
        description="Validate release gate coverage and scan for embedded credentials.",
    )
    parser.add_argument("--json", action="store_true", help="Emit machine-readable audit JSON.")
    parser.add_argument(
        "--root",
        type=Path,
        default=Path.cwd(),
        help="Repository root to scan. Defaults to the current working directory.",
    )
    args = parser.parse_args(argv)

    report = build_release_audit_report()
    result = validate_release_audit(report)
    findings = scan_for_embedded_credentials(args.root)
    if findings:
        result = ReleaseAuditResult(
            passed=False,
            failures=(*result.failures, f"embedded credential findings: {len(findings)}"),
        )

    if args.json:
        print(
            json.dumps(
                {
                    "report": report.to_contract_dict(),
                    "result": result.to_contract_dict(),
                    "credential_findings": [finding.to_contract_dict() for finding in findings],
                },
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
        )
    elif result.passed:
        print("RELEASE_AUDIT_OK")
    else:
        for failure in result.failures:
            print(f"RELEASE_AUDIT_FAIL {failure}")
    return 0 if result.passed else 1


def _build_acceptance_gates() -> tuple[ReleaseGate, ...]:
    evidence_by_id = {
        "AC-01": "tests/unit/test_security_master.py; tests/gui/test_app_shell.py",
        "AC-02": "tests/gui/test_chart_workspace.py; tests/gui/test_analysis_panel.py",
        "AC-03": "tests/gui/test_chart_workspace.py",
        "AC-04": "tests/gui/test_analysis_panel.py",
        "AC-05": "tests/unit/test_forecasting_engine.py; tests/unit/test_knowledge_center.py",
        "AC-06": "tests/integration/test_data_quality_signal_gate.py",
        "AC-07": "tests/unit/test_backtest_engine.py",
        "AC-08": "tests/unit/test_market_rules.py; tests/unit/test_portfolio_risk.py",
        "AC-09": "tests/regression/test_backtest_report_regression.py",
        "AC-10": "tests/unit/test_analysis_report_builder.py",
        "AC-11": "tests/unit/test_fund_analysis.py; tests/unit/test_market_rules.py",
        "AC-12": (
            "tests/unit/test_etf_rotation_strategy.py; tests/unit/test_a_share_trend_strategy.py"
        ),
    }
    return tuple(
        ReleaseGate(
            gate_id=gate_id,
            description=f"{gate_id} is covered by release evidence.",
            evidence=evidence_by_id[gate_id],
        )
        for gate_id in ACCEPTANCE_IDS
    )


def _build_nfr_gates() -> tuple[ReleaseGate, ...]:
    evidence_by_id = {
        "NFR-01": "tests/unit/test_security_master.py",
        "NFR-02": "tests/gui/test_chart_workspace.py",
        "NFR-03": "tests/gui/test_app_shell.py",
        "NFR-04": "tests/integration/test_market_data_gateway.py",
        "NFR-05": "tests/unit/test_backtest_engine.py",
        "NFR-06": "tests/unit/test_rate_limit.py; tests/gui/test_app_shell.py",
        "NFR-07": "tests/unit/test_runtime.py; tests/unit/test_simulation_broker.py",
        "NFR-08": "tests/regression/test_backtest_report_regression.py; MANIFEST.sha256",
    }
    return tuple(
        ReleaseGate(
            gate_id=gate_id,
            description=f"{gate_id} is covered by release evidence.",
            evidence=evidence_by_id[gate_id],
        )
        for gate_id in NFR_IDS
    )


def _build_definition_of_done_gates() -> tuple[ReleaseGate, ...]:
    evidence_by_id = {
        "DoD-implementation": "TASKS.md; docs/TRACEABILITY.md",
        "DoD-verification": "uv run ruff/mypy/pytest/version commands",
        "DoD-traceability": "docs/DECISIONS.md; spec/requirements.yaml; active ExecPlan",
        "DoD-delivery": "MANIFEST.sha256; docs/release/RELEASE_CHECKLIST.md",
    }
    return tuple(
        ReleaseGate(
            gate_id=gate_id,
            description=f"{gate_id} is covered by release evidence.",
            evidence=evidence_by_id[gate_id],
        )
        for gate_id in DEFINITION_OF_DONE_IDS
    )


def _require_ids(
    label: str,
    expected: tuple[str, ...],
    actual: tuple[str, ...],
    failures: list[str],
) -> None:
    missing = tuple(item for item in expected if item not in actual)
    extra = tuple(item for item in actual if item not in expected)
    if missing:
        failures.append(f"missing {label} gates: {', '.join(missing)}")
    if extra:
        failures.append(f"unknown {label} gates: {', '.join(extra)}")


def _relative_path(root: Path, path: Path) -> str:
    try:
        return path.resolve().relative_to(root).as_posix()
    except ValueError:
        return path.as_posix()


def _redact(value: str) -> str:
    if len(value) <= 8:
        return "***"
    return f"{value[:4]}...{value[-4:]}"


if __name__ == "__main__":
    raise SystemExit(main())
