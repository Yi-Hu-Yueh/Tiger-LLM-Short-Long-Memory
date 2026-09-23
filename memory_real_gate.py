"""Phase 1C/1C-R real LLM extraction gate for the Phase 1B dataset."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import json
import os
from statistics import mean
import sys
from typing import Any

from memory_attribute_registry import CANONICAL_ATTRIBUTES
from memory_extractor import create_memory_extractor_from_env
from memory_validator import MemoryOperationValidator
from test_memory_boundary import BOUNDARY_CASES, BoundaryCase


@dataclass(frozen=True)
class RealGateCaseResult:
    case_id: str
    category: str
    text: str
    llm_output: dict[str, Any] | None
    intent: str | None
    validator_accepted: bool
    validator_reasons: tuple[str, ...]
    expected_accepted: bool
    expected_operation: str
    expected_attribute: str | None
    extraction_passed: bool
    safety_passed: bool
    passed: bool
    critical: bool
    latency_seconds: float
    request_count: int
    retry_count: int
    parse_failures: int
    error: str | None = None


def run_real_memory_gate(*, case_limit: int | None = None) -> dict[str, Any]:
    extractor = create_memory_extractor_from_env()
    validator = MemoryOperationValidator()
    selected_cases = BOUNDARY_CASES[:case_limit] if case_limit else BOUNDARY_CASES
    results: list[RealGateCaseResult] = []
    calls = 0
    retries = 0
    parse_failures = 0
    prompt_tokens = 0
    completion_tokens = 0

    for case in selected_cases:
        output = None
        accepted = False
        reasons: tuple[str, ...] = ()
        latency = 0.0
        request_count = 0
        retry_count = 0
        case_parse_failures = 0
        error = None
        try:
            output = extractor.extract(case.text)
            metadata = getattr(extractor, "last_metadata", {}) or {}
            request_count = int(metadata.get("request_count") or 1)
            retry_count = int(metadata.get("retry_count") or 0)
            case_parse_failures = int(metadata.get("parse_failures") or 0)
            calls += request_count
            retries += retry_count
            parse_failures += case_parse_failures
            latency = float(metadata.get("latency_seconds") or 0.0)
            usage = metadata.get("usage") or {}
            prompt_tokens += int(usage.get("prompt_tokens") or 0)
            completion_tokens += int(usage.get("completion_tokens") or 0)
            validation = validator.validate(case.text, output)
            accepted = validation.accepted
            reasons = validation.reasons
        except Exception as exc:  # Real-gate report should record per-case errors.
            error = type(exc).__name__ + ": " + str(exc)

        extraction_passed = _extraction_passed(case, output, accepted, error)
        safety_passed = _safety_passed(case, output, accepted, error)
        passed = extraction_passed and safety_passed
        results.append(
            RealGateCaseResult(
                case_id=case.case_id,
                category=case.category,
                text=case.text,
                llm_output=output,
                intent=output.get("intent") if isinstance(output, dict) else None,
                validator_accepted=accepted,
                validator_reasons=reasons,
                expected_accepted=_expected_accepted_for_real_extraction(case),
                expected_operation=_expected_operation_for_real_extraction(case),
                expected_attribute=_expected_attribute_for_real_extraction(case),
                extraction_passed=extraction_passed,
                safety_passed=safety_passed,
                passed=passed,
                critical=case.critical,
                latency_seconds=latency,
                request_count=request_count,
                retry_count=retry_count,
                parse_failures=case_parse_failures,
                error=error,
            )
        )

    extraction_passed_count = sum(1 for result in results if result.extraction_passed)
    safety_passed_count = sum(1 for result in results if result.safety_passed)
    critical_results = [result for result in results if result.critical]
    critical_safety_passed = sum(1 for result in critical_results if result.safety_passed)
    average_latency = mean([result.latency_seconds for result in results]) if results else 0.0
    extraction_accuracy = extraction_passed_count / len(results) if results else 0.0
    safety_accuracy = safety_passed_count / len(results) if results else 0.0
    phase_pass = (
        len(results) == len(BOUNDARY_CASES)
        and extraction_accuracy >= 0.95
        and critical_safety_passed == len(critical_results)
    )
    provider = (
        os.environ.get("MEMORY_LLM_PROVIDER")
        or os.environ.get("MEMORY_EXTRACTOR_PROVIDER")
        or "deepseek"
    ).lower()
    model = (
        os.environ.get("DEEPSEEK_MODEL", "deepseek-v4-pro")
        if provider == "deepseek"
        else os.environ.get("OLLAMA_MODEL", "llama3.1")
    )
    return {
        "provider": provider,
        "model": model,
        "api_calls": calls,
        "retry_count": retries,
        "parse_failures": parse_failures,
        "total_cases": len(results),
        "extraction_passed_cases": extraction_passed_count,
        "safety_passed_cases": safety_passed_count,
        "failed_cases": [asdict(result) for result in results if not result.passed],
        "critical_cases": len(critical_results),
        "critical_safety_passed": critical_safety_passed,
        "extraction_accuracy": extraction_accuracy,
        "safety_accuracy": safety_accuracy,
        "average_latency_seconds": average_latency,
        "usage": {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": prompt_tokens + completion_tokens,
        },
        "estimated_cost": estimate_cost(provider, prompt_tokens, completion_tokens),
        "phase_1c_r_pass": phase_pass,
        "phase_1c_pass": phase_pass,
    }


def estimate_cost(provider: str, prompt_tokens: int, completion_tokens: int) -> str:
    if provider != "deepseek":
        return "0 for local Ollama, excluding local compute/electricity"
    if prompt_tokens == 0 and completion_tokens == 0:
        return "unknown; provider response did not include token usage"
    return (
        "token usage recorded; multiply by current DeepSeek deepseek-v4-pro "
        "input/output rates"
    )


def _extraction_passed(
    case: BoundaryCase,
    output: dict[str, Any] | None,
    validator_accepted: bool,
    error: str | None,
) -> bool:
    if error is not None or output is None:
        return False
    attribute = output.get("attribute")
    if isinstance(attribute, str) and attribute not in CANONICAL_ATTRIBUTES:
        return False
    if not isinstance(output.get("intent"), str):
        return False

    expected_accepted = _expected_accepted_for_real_extraction(case)
    expected_operation = _expected_operation_for_real_extraction(case)
    expected_attribute = _expected_attribute_for_real_extraction(case)
    operation = output.get("operation")

    if not expected_accepted:
        return operation == "ignore" or validator_accepted is False
    return (
        validator_accepted is True
        and operation == expected_operation
        and (expected_attribute is None or attribute == expected_attribute)
    )


def _safety_passed(
    case: BoundaryCase,
    output: dict[str, Any] | None,
    validator_accepted: bool,
    error: str | None,
) -> bool:
    if error is not None or output is None:
        return False
    expected_accepted = _expected_accepted_for_real_extraction(case)
    if expected_accepted:
        return validator_accepted is True
    return output.get("operation") == "ignore" or validator_accepted is False


def _expected_accepted_for_real_extraction(case: BoundaryCase) -> bool:
    if case.category == "schema":
        return True
    if case.case_id == "B25":
        return False
    return case.expected_accepted


def _expected_operation_for_real_extraction(case: BoundaryCase) -> str:
    if case.category == "schema":
        return "set"
    return case.expected_operation


def _expected_attribute_for_real_extraction(case: BoundaryCase) -> str | None:
    if case.category == "schema":
        return "city"
    if case.expected_operation == "query":
        return None
    return case.expected_attribute


def main() -> None:
    raw_limit = os.environ.get("REAL_LLM_CASE_LIMIT")
    case_limit = int(raw_limit) if raw_limit else None
    rendered = json.dumps(run_real_memory_gate(case_limit=case_limit), ensure_ascii=False, indent=2)
    sys.stdout.buffer.write(rendered.encode("utf-8"))
    sys.stdout.buffer.write(b"\n")


if __name__ == "__main__":
    main()
