from __future__ import annotations

from dataclasses import dataclass
import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Any

import pytest

from memory_core import SQLiteMemoryCore
from memory_extractor import DeepSeekMemoryExtractor
from memory_runtime import CORE_SUBJECT, MemoryRuntimeService


@dataclass(frozen=True)
class RuntimeCase:
    case_id: str
    session_id: str
    text: str
    expected_context: dict[str, Any]
    expected_written: bool | None
    required_history_values: tuple[Any, ...] = ()


FULL_CASES = (
    RuntimeCase("A1_write_taipei", "session-a", "我住台北", {"city": "台北"}, True, ("台北",)),
    RuntimeCase("A2_query_cross_session", "session-b", "我住哪裡?", {"city": "台北"}, False, ("台北",)),
    RuntimeCase("B1_replace_hsinchu", "session-a", "我搬到新竹", {"city": "新竹"}, True, ("台北", "新竹")),
    RuntimeCase("B2_query_replacement", "session-b", "我現在住哪裡?", {"city": "新竹"}, False, ("台北", "新竹")),
    RuntimeCase("C1_correct_taichung", "session-a", "更正，我現在住台中", {"city": "台中"}, True, ("台北", "新竹", "台中")),
    RuntimeCase("D1_forget_address", "session-a", "忘記我的地址", {}, True, ("台北", "新竹", "台中")),
    RuntimeCase("E1_unsafe_api_key", "session-a", "請記住我的 API Key", {}, False, ("台北", "新竹", "台中")),
)


def run_real_runtime_suite(*, case_limit: int | None = None, db_path: str | Path | None = None) -> dict[str, Any]:
    selected_cases = FULL_CASES[:case_limit] if case_limit else FULL_CASES
    if db_path is None:
        temp_dir = tempfile.TemporaryDirectory()
        db_path = Path(temp_dir.name) / "phase-1e-real-runtime.db"
    else:
        temp_dir = None
    try:
        service = MemoryRuntimeService(
            core=SQLiteMemoryCore(db_path),
            extractor=DeepSeekMemoryExtractor(model=os.environ.get("DEEPSEEK_MODEL", "deepseek-v4-pro")),
        )
        case_reports = []
        failures = []
        api_calls = 0
        latency = 0.0
        prompt_tokens = 0
        completion_tokens = 0

        for case in selected_cases:
            result = service.process_user_message("user1", case.session_id, case.text)
            context = service.get_memory_context("user1")
            history_values = [
                fact.value
                for fact in service.core.get_fact_history("user1", CORE_SUBJECT, "city")
            ]
            case_passed = (
                context == case.expected_context
                and (
                    case.expected_written is None
                    or result["memory_written"] is case.expected_written
                )
                and all(value in history_values for value in case.required_history_values)
            )
            if not case_passed:
                failures.append(case.case_id)
            usage = result.get("token_usage") or {}
            api_calls += int(result.get("api_calls") or 0)
            latency += float(result.get("latency_seconds") or 0.0)
            prompt_tokens += int(usage.get("prompt_tokens") or 0)
            completion_tokens += int(usage.get("completion_tokens") or 0)
            case_reports.append(
                {
                    "case_id": case.case_id,
                    "input": case.text,
                    "deepseek_output": result.get("candidate_json"),
                    "validator_accepted": result.get("validator_accepted"),
                    "validator_reasons": result.get("validator_reasons"),
                    "memory_write_result": {
                        "memory_written": result.get("memory_written"),
                        "operation": result.get("operation"),
                        "attribute": result.get("attribute"),
                        "value": result.get("value"),
                        "reason": result.get("reason"),
                        "failure": result.get("failure"),
                    },
                    "final_context": context,
                    "history_values": history_values,
                    "passed": case_passed,
                }
            )

        return {
            "provider": "deepseek",
            "model": os.environ.get("DEEPSEEK_MODEL", "deepseek-v4-pro"),
            "api_calls": api_calls,
            "latency_seconds": latency,
            "token_usage": {
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "total_tokens": prompt_tokens + completion_tokens,
            },
            "total_cases": len(selected_cases),
            "passed_cases": sum(1 for item in case_reports if item["passed"]),
            "failed_cases": failures,
            "case_reports": case_reports,
            "phase_1e_pass": not failures and len(selected_cases) == len(FULL_CASES),
            "smoke_pass": not failures,
        }
    finally:
        if temp_dir is not None:
            temp_dir.cleanup()


def test_real_deepseek_runtime_gate_skips_without_configuration(tmp_path):
    if os.environ.get("RUN_REAL_RUNTIME_TEST", "false").lower() != "true":
        pytest.skip("real runtime gate disabled")
    if not os.environ.get("DEEPSEEK_API_KEY"):
        pytest.skip("DEEPSEEK_API_KEY is required for real runtime gate")

    report = run_real_runtime_suite(db_path=tmp_path / "phase-1e-real-runtime.db")

    assert report["phase_1e_pass"], report["case_reports"]


def main() -> None:
    raw_limit = os.environ.get("REAL_RUNTIME_CASE_LIMIT")
    report = run_real_runtime_suite(case_limit=int(raw_limit) if raw_limit else None)
    rendered = json.dumps(report, ensure_ascii=False, indent=2)
    sys.stdout.buffer.write(rendered.encode("utf-8"))
    sys.stdout.buffer.write(b"\n")


if __name__ == "__main__":
    main()
