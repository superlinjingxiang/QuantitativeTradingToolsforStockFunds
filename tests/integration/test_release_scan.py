"""Repository-level release security scan."""

from __future__ import annotations

from pathlib import Path

from china_quant_platform.release.audit import (
    iter_release_scan_paths,
    scan_for_embedded_credentials,
)


def test_release_scan_finds_no_embedded_credentials_in_release_files() -> None:
    root = Path.cwd()
    paths = iter_release_scan_paths(root)
    findings = scan_for_embedded_credentials(root, paths=paths)

    assert findings == ()
    assert root / "pyproject.toml" in paths
    assert all(".venv" not in path.parts for path in paths)
