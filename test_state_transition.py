from __future__ import annotations

from dataclasses import dataclass
import json
import os
import sys
from typing import Any

import pytest

from memory_extractor import DeepSeekMemoryExtractor
from memory_validator import MemoryOperationValidator


@dataclass(frozen=True)
class TransitionCase:
    case_id: str
    current_context: dict[str, Any]
    text: str
    expected_intent: str
    expected_operation: str
    expected_attribute: str | None
    expected_old_value: Any
    expected_new_value: Any
    expected_validator_accepted: bool
    critical: bool = False


TRANSITION_CASES = (
    TransitionCase("A1", {"city": "台北"}, "我搬到新竹", "current_fact", "replace", "city", "台北", "新竹", True, True),
    TransitionCase("A2", {"city": "新竹"}, "我現在住台中", "current_fact", "replace", "city", "新竹", "台中", True, True),
    TransitionCase("A3", {"city": "台中"}, "我仍然住台中", "current_fact", "no_op", "city", "台中", "台中", True, True),
    TransitionCase("A4", {}, "我住台北", "current_fact", "set", "city", None, "台北", True),
    TransitionCase("A5", {"city": "台北"}, "我現在是新竹人", "current_fact", "replace", "city", "台北", "新竹", True),
    TransitionCase("A6", {"favorite_drink": "咖啡"}, "我現在改喝茶", "current_fact", "replace", "favorite_drink", "咖啡", "茶", True),
    TransitionCase("A7", {"office_city": "台北"}, "我的辦公室改到新竹", "current_fact", "replace", "office_city", "台北", "新竹", True),
    TransitionCase("A8", {"phone_model": "Pixel"}, "我的手機改成iPhone", "current_fact", "replace", "phone_model", "Pixel", "iPhone", True),
    TransitionCase("A9", {"pet_name": "Mochi"}, "我的寵物現在叫Cookie", "current_fact", "replace", "pet_name", "Mochi", "Cookie", True),
    TransitionCase("A10", {"desk_floor": "2樓"}, "我的桌子現在在3樓", "current_fact", "replace", "desk_floor", "2樓", "3樓", True),
    TransitionCase("A11", {"city": "台南"}, "我還是住台南", "current_fact", "no_op", "city", "台南", "台南", True),
    TransitionCase("A12", {"favorite_drink": "茶"}, "我仍然喝茶", "current_fact", "no_op", "favorite_drink", "茶", "茶", True),
    TransitionCase("A13", {"office_city": "新竹"}, "辦公室還是在新竹", "current_fact", "no_op", "office_city", "新竹", "新竹", True),
    TransitionCase("A14", {"city": "台北"}, "我改為住桃園", "current_fact", "replace", "city", "台北", "桃園", True),
    TransitionCase("A15", {"city": "桃園"}, "我改成住台南", "current_fact", "replace", "city", "桃園", "台南", True),
    TransitionCase("B1", {"city": "台中"}, "更正，我現在住台南", "correction", "correct", "city", "台中", "台南", True, True),
    TransitionCase("B2", {"phone_model": "Pixel"}, "更正，我的手機是iPhone", "correction", "correct", "phone_model", "Pixel", "iPhone", True),
    TransitionCase("C1", {"city": "台北"}, "我可能搬去高雄", "future_plan", "ignore", None, None, None, True, True),
    TransitionCase("D1", {"city": "台北"}, "我在台北和新竹兩邊跑", "ignore", "ignore", None, None, None, True),
    TransitionCase("E1", {"city": "台北"}, "我以前住高雄", "historical_fact", "set", "city", "台北", "高雄", False, True),
)


def run_real_transition_gate(*, case_limit: int | None = None) -> dict[str, Any]:
    extractor = DeepSeekMemoryExtractor(model=os.environ.get("DEEPSEEK_MODEL", "deepseek-v4-pro"))
    validator = MemoryOperationValidator()
    selected = TRANSITION_CASES[:case_limit] if case_limit else TRANSITION_CASES
    reports = []
    api_calls = 0
    latency = 0.0
    parse_failures = 0
    retry_count = 0
    prompt_tokens = 0
    completion_tokens = 0
    for case in selected:
        output = None
        accepted = False
        reasons = ()
        error = None
        try:
            output = extractor.extract_with_context(case.text, case.current_context)
            metadata = extractor.last_metadata
            validation = validator.validate(case.text, output)
            accepted = validation.accepted
            reasons = validation.reasons
            api_calls += int(metadata.get("request_count") or 0)
            latency += float(metadata.get("latency_seconds") or 0.0)
            parse_failures += int(metadata.get("parse_failures") or 0)
            retry_count += int(metadata.get("retry_count") or 0)
            usage = metadata.get("usage") or {}
            prompt_tokens += int(usage.get("prompt_tokens") or 0)
            completion_tokens += int(usage.get("completion_tokens") or 0)
        except Exception as exc:
            error = type(exc).__name__ + ": " + str(exc)

        extraction_passed = (
            error is None
            and output is not None
            and _transition_matches_expected(case, output)
        )
        safety_passed = (
            error is None
            and (
                accepted is case.expected_validator_accepted
                or (
                    case.expected_validator_accepted is False
                    and output is not None
                    and output.get("operation") == "ignore"
                    and accepted is True
                )
            )
        )
        reports.append(
            {
                "case_id": case.case_id,
                "critical": case.critical,
                "input": case.text,
                "current_context": case.current_context,
                "deepseek_output": output,
                "validator_accepted": accepted,
                "validator_reasons": reasons,
                "extraction_passed": extraction_passed,
                "safety_passed": safety_passed,
                "passed": extraction_passed and safety_passed,
                "error": error,
            }
        )
    extraction_passed = sum(1 for item in reports if item["extraction_passed"])
    safety_passed = sum(1 for item in reports if item["safety_passed"])
    critical = [item for item in reports if item["critical"]]
    critical_passed = sum(1 for item in critical if item["passed"])
    return {
        "provider": "deepseek",
        "model": os.environ.get("DEEPSEEK_MODEL", "deepseek-v4-pro"),
        "api_calls": api_calls,
        "latency_seconds": latency,
        "parse_failures": parse_failures,
        "retry_count": retry_count,
        "token_usage": {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": prompt_tokens + completion_tokens,
        },
        "total_cases": len(reports),
        "extraction_passed_cases": extraction_passed,
        "safety_passed_cases": safety_passed,
        "critical_cases": len(critical),
        "critical_passed": critical_passed,
        "extraction_accuracy": extraction_passed / len(reports) if reports else 0.0,
        "safety_accuracy": safety_passed / len(reports) if reports else 0.0,
        "failed_cases": [item for item in reports if not item["passed"]],
        "phase_1e_r_pass": (
            len(reports) == len(TRANSITION_CASES)
            and extraction_passed / len(reports) >= 0.95
            and critical_passed == len(critical)
        )
        if reports
        else False,
    }


def _transition_matches_expected(case: TransitionCase, output: dict[str, Any]) -> bool:
    if case.expected_intent == "historical_fact":
        return output.get("intent") == "historical_fact" and output.get("operation") != "replace"
    return (
        output.get("intent") == case.expected_intent
        and output.get("operation") == case.expected_operation
        and output.get("attribute") == case.expected_attribute
        and output.get("old_value") == case.expected_old_value
        and output.get("new_value") == case.expected_new_value
    )


def test_real_transition_gate_skips_without_configuration():
    if os.environ.get("RUN_REAL_TRANSITION_TEST", "false").lower() != "true":
        pytest.skip("real transition gate disabled")
    if not os.environ.get("DEEPSEEK_API_KEY"):
        pytest.skip("DEEPSEEK_API_KEY is required for real transition gate")

    report = run_real_transition_gate()

    assert report["phase_1e_r_pass"], report["failed_cases"]


def main() -> None:
    raw_limit = os.environ.get("REAL_TRANSITION_CASE_LIMIT")
    report = run_real_transition_gate(case_limit=int(raw_limit) if raw_limit else None)
    rendered = json.dumps(report, ensure_ascii=False, indent=2)
    sys.stdout.buffer.write(rendered.encode("utf-8"))
    sys.stdout.buffer.write(b"\n")


if __name__ == "__main__":
    main()
