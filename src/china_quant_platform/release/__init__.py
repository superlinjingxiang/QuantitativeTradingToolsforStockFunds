"""Release packaging, recovery, security, and audit helpers."""

from __future__ import annotations

__all__ = [
    "ACCEPTANCE_IDS",
    "DEFINITION_OF_DONE_IDS",
    "NFR_IDS",
    "CredentialFinding",
    "CredentialPolicy",
    "ReleaseAuditReport",
    "ReleaseAuditResult",
    "ReleaseCommand",
    "ReleaseGate",
    "ReleaseMigrationStep",
    "build_release_audit_report",
    "iter_release_scan_paths",
    "scan_for_embedded_credentials",
    "validate_release_audit",
]


def __getattr__(name: str) -> object:
    if name not in __all__:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    from china_quant_platform.release import audit

    return getattr(audit, name)
