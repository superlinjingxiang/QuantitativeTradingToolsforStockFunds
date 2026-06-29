"""Release audit, packaging, and credential safety tests."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from china_quant_platform.release.audit import (
    ACCEPTANCE_IDS,
    DEFINITION_OF_DONE_IDS,
    NFR_IDS,
    build_release_audit_report,
    iter_release_scan_paths,
    scan_for_embedded_credentials,
    validate_release_audit,
)


def test_release_audit_covers_all_acceptance_nfr_and_done_gates() -> None:
    report = build_release_audit_report()
    result = validate_release_audit(report)

    assert result.passed is True
    assert report.acceptance_ids == ACCEPTANCE_IDS
    assert report.nfr_ids == NFR_IDS
    assert report.definition_of_done_ids == DEFINITION_OF_DONE_IDS
    assert "pyinstaller" in report.windows_package_command.command
    assert "packaging/china_quant_platform.spec" in report.windows_package_command.command
    assert any(command.name == "release-audit" for command in report.smoke_test_commands)
    assert any(command.name == "packager-smoke" for command in report.smoke_test_commands)


def test_release_audit_rejects_missing_required_gate() -> None:
    report = build_release_audit_report()
    broken = report.model_copy(update={"acceptance_gates": report.acceptance_gates[1:]})

    result = validate_release_audit(broken)

    assert result.passed is False
    assert any("AC-01" in failure for failure in result.failures)


def test_credential_scan_detects_embedded_secret_and_allows_blank_example(
    tmp_path: Path,
) -> None:
    secret_file = tmp_path / "bad_settings.py"
    fake_key = "AKIA" + "ABCDEFGHIJKLMNOP"
    secret_file.write_text(f'API_KEY = "{fake_key}"\n', encoding="utf-8")
    example_file = tmp_path / ".env.example"
    example_file.write_text("CQP_DATA_PROVIDER_API_KEY=\n", encoding="utf-8")

    findings = scan_for_embedded_credentials(
        tmp_path,
        paths=(secret_file, example_file),
    )

    assert len(findings) >= 1
    assert findings[0].path == "bad_settings.py"
    assert any(finding.pattern_id == "aws_access_key" for finding in findings)


def test_release_scan_excludes_runtime_and_cache_directories(tmp_path: Path) -> None:
    source_file = tmp_path / "pyproject.toml"
    source_file.write_text("[project]\nname='demo'\n", encoding="utf-8")
    ignored_file = tmp_path / ".venv" / "secret.py"
    ignored_file.parent.mkdir()
    ignored_file.write_text("CQP_DATA_PROVIDER_API_KEY=\n", encoding="utf-8")

    paths = iter_release_scan_paths(tmp_path)

    assert source_file in paths
    assert ignored_file not in paths


def test_release_audit_cli_json_smoke() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "china_quant_platform.release.audit", "--json"],
        check=True,
        capture_output=True,
        text=True,
    )
    payload = json.loads(result.stdout)

    assert payload["result"]["passed"] is True
    assert payload["credential_findings"] == []
