"""Machine-readable specification smoke tests."""

from __future__ import annotations

import json
from pathlib import Path

import yaml
from jsonschema.validators import Draft202012Validator

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def test_json_contracts_are_valid_draft_2020_12_schemas() -> None:
    contract_dir = PROJECT_ROOT / "spec" / "contracts"

    for schema_path in sorted(contract_dir.glob("*.schema.json")):
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        Draft202012Validator.check_schema(schema)


def test_analysis_report_references_existing_data_health_schema() -> None:
    contract_dir = PROJECT_ROOT / "spec" / "contracts"
    analysis_schema = json.loads(
        (contract_dir / "analysis_report.schema.json").read_text(encoding="utf-8")
    )

    assert analysis_schema["properties"]["data_health"]["$ref"] == "data-health.schema.json"
    assert (contract_dir / "data-health.schema.json").is_file()


def test_requirements_yaml_is_parseable() -> None:
    requirements_path = PROJECT_ROOT / "spec" / "requirements.yaml"
    requirements = yaml.safe_load(requirements_path.read_text(encoding="utf-8"))

    assert isinstance(requirements, dict)
    assert requirements["project"] == "china_quant_platform"
    assert requirements["version"] == "1.0"
