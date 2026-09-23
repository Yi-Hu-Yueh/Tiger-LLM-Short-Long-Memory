"""Phase 5A deterministic release-candidate evidence validation."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

from app import PRODUCT_MODE, PRODUCTION_AUTO_COMMIT_ENABLED
from memory_validator import INJECTION_MARKERS, SENSITIVE_ATTRIBUTES
from slot_registry import PRODUCTION_ACTIVE


GOVERNANCE_FILES = (
    "MEMORY_CONSISTENCY_SPEC.md",
    "MEMORY_SEMANTIC_CONTRACTS.md",
    "MEMORY_ACCEPTANCE_SUITE.md",
)
REGRESSION_GROUPS = ("memory_core", "proposal", "audit", "recovery", "security", "operations")
SECURITY_CHECKS = (
    "user_isolation",
    "sensitive_data_rejection",
    "fail_closed",
    "proposal_confirmation_required",
)
OPERATIONS_CHECKS = (
    "startup_validation",
    "shutdown_cleanup",
    "recovery_readiness",
    "observability_available",
)


class ReleaseValidator:
    """Combine independently produced release evidence without changing runtime state."""

    def __init__(
        self,
        *,
        project_root: str | Path,
        expected_governance_hashes: Mapping[str, str],
        regression_results: Mapping[str, bool],
        security_results: Mapping[str, bool],
        operations_results: Mapping[str, bool],
    ):
        self.project_root = Path(project_root).resolve()
        self.expected_governance_hashes = self._expected_hashes(expected_governance_hashes)
        self.regression_results = self._checks(regression_results, REGRESSION_GROUPS)
        self.security_results = self._checks(security_results, SECURITY_CHECKS)
        self.operations_results = self._checks(operations_results, OPERATIONS_CHECKS)

    def validate_regression(self) -> dict[str, Any]:
        failed = [name for name in REGRESSION_GROUPS if not self.regression_results[name]]
        return {
            "passed": not failed,
            "checks": dict(self.regression_results),
            "failed_groups": failed,
        }

    def validate_governance(self) -> dict[str, Any]:
        documents: dict[str, dict[str, Any]] = {}
        for name in GOVERNANCE_FILES:
            path = self.project_root / name
            actual = self._sha256(path) if path.is_file() else None
            expected = self.expected_governance_hashes[name]
            documents[name] = {
                "actual_sha256": actual,
                "expected_sha256": expected,
                "match": actual == expected,
            }
        validator_not_weakened = {
            "sensitive_attributes": {"password", "api_key", "secret"} <= set(SENSITIVE_ATTRIBUTES),
            "prompt_injection_markers": {"忽略所有規則", "bypass"} <= set(INJECTION_MARKERS),
        }
        direct_model_write_disabled = (
            PRODUCT_MODE == "HUMAN_REVIEWED_MEMORY_ASSISTANT"
            and PRODUCTION_AUTO_COMMIT_ENABLED is False
            and PRODUCTION_ACTIVE is False
        )
        passed = (
            all(item["match"] for item in documents.values())
            and all(validator_not_weakened.values())
            and direct_model_write_disabled
        )
        return {
            "passed": passed,
            "documents": documents,
            "validator_not_weakened": validator_not_weakened,
            "direct_model_write_disabled": direct_model_write_disabled,
        }

    def run_full_validation(self) -> dict[str, Any]:
        regression = self.validate_regression()
        governance = self.validate_governance()
        security = self._section(self.security_results)
        operations = self._section(self.operations_results)
        return self.generate_release_report(
            regression=regression,
            governance=governance,
            security=security,
            operations=operations,
        )

    def generate_release_report(
        self,
        *,
        regression: Mapping[str, Any] | None = None,
        governance: Mapping[str, Any] | None = None,
        security: Mapping[str, Any] | None = None,
        operations: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        regression_result = dict(regression or self.validate_regression())
        governance_result = dict(governance or self.validate_governance())
        security_result = dict(security or self._section(self.security_results))
        operations_result = dict(operations or self._section(self.operations_results))
        blockers: list[str] = []
        blockers.extend(
            f"regression:{name}" for name in regression_result.get("failed_groups", ())
        )
        blockers.extend(
            f"governance:{name}"
            for name, item in governance_result.get("documents", {}).items()
            if not item.get("match", False)
        )
        if not governance_result.get("direct_model_write_disabled", False):
            blockers.append("governance:direct_model_write_path")
        for name, passed in governance_result.get("validator_not_weakened", {}).items():
            if not passed:
                blockers.append(f"governance:{name}")
        blockers.extend(
            f"security:{name}"
            for name, passed in security_result.get("checks", {}).items()
            if not passed
        )
        blockers.extend(
            f"operations:{name}"
            for name, passed in operations_result.get("checks", {}).items()
            if not passed
        )
        blockers = sorted(set(blockers))
        passed = all(
            section.get("passed", False)
            for section in (regression_result, governance_result, security_result, operations_result)
        ) and not blockers
        return {
            "release_status": "PASS" if passed else "FAIL",
            "regression": regression_result,
            "security": security_result,
            "governance": governance_result,
            "operations": operations_result,
            "blockers": blockers,
        }

    @staticmethod
    def render_report(report: Mapping[str, Any]) -> str:
        return json.dumps(report, ensure_ascii=False, sort_keys=True, separators=(",", ":"))

    @staticmethod
    def _sha256(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for block in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(block)
        return digest.hexdigest().upper()

    @staticmethod
    def _expected_hashes(source: Mapping[str, str]) -> dict[str, str]:
        if set(source) != set(GOVERNANCE_FILES):
            raise ValueError("exact governance hash evidence is required")
        result: dict[str, str] = {}
        for name in GOVERNANCE_FILES:
            value = source[name]
            if not isinstance(value, str) or len(value) != 64:
                raise ValueError("invalid governance hash evidence")
            result[name] = value.upper()
        return result

    @staticmethod
    def _checks(source: Mapping[str, bool], required: tuple[str, ...]) -> dict[str, bool]:
        if set(source) != set(required) or any(type(value) is not bool for value in source.values()):
            raise ValueError("exact boolean release evidence is required")
        return {name: source[name] for name in required}

    @staticmethod
    def _section(checks: Mapping[str, bool]) -> dict[str, Any]:
        failed = [name for name, passed in checks.items() if not passed]
        return {"passed": not failed, "checks": dict(checks), "failed_checks": failed}
