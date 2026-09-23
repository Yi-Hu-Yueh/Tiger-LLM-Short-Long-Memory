from __future__ import annotations

from dataclasses import dataclass
import json
import os
import sqlite3
import sys
import tempfile
from pathlib import Path
from typing import Any

import pytest

from memory_multi_turn import MultiTurnMemoryService


@dataclass(frozen=True)
class RealStressScenario:
    case_id: str
    turns: tuple[tuple[str, str, str], ...]
    final_user_id: str
    expected_context: dict[str, Any]
    expected_history: tuple[Any, ...]
    forbidden_answer_terms: tuple[str, ...] = ()
    required_answer_terms: tuple[str, ...] = ()
    critical: bool = False


REAL_STRESS_SCENARIOS = (
    RealStressScenario(
        "A_repeated_replacement",
        (
            ("user1", "stress-a", "我住台北"),
            ("user1", "stress-a", "我搬到新竹"),
            ("user1", "stress-a", "我搬到台中"),
            ("user1", "stress-a", "我搬到台南"),
            ("user1", "stress-a", "我住哪?"),
        ),
        "user1",
        {"city": "台南"},
        ("台北", "新竹", "台中", "台南"),
        forbidden_answer_terms=("台北", "新竹", "台中"),
        required_answer_terms=("台南",),
        critical=True,
    ),
    RealStressScenario(
        "B_correction_chain",
        (
            ("user1", "stress-b", "我住新竹"),
            ("user1", "stress-b", "更正，我現在住台中"),
            ("user1", "stress-b", "我住哪?"),
        ),
        "user1",
        {"city": "台中"},
        ("新竹", "台中"),
        forbidden_answer_terms=("新竹",),
        required_answer_terms=("台中",),
        critical=True,
    ),
    RealStressScenario(
        "C_forget_and_rebuild",
        (
            ("user1", "stress-c", "我喜歡咖啡"),
            ("user1", "stress-c", "忘記我的飲料偏好"),
            ("user1", "stress-c", "我喜歡無糖綠茶"),
            ("user1", "stress-c", "推薦飲料"),
        ),
        "user1",
        {"favorite_drink": "無糖綠茶"},
        ("咖啡", "無糖綠茶"),
        forbidden_answer_terms=("咖啡",),
        required_answer_terms=("無糖綠茶",),
        critical=True,
    ),
    RealStressScenario(
        "D_user_isolation",
        (
            ("userA", "stress-d-a", "我住台北"),
            ("userB", "stress-d-b", "我住哪?"),
        ),
        "userB",
        {},
        (),
        forbidden_answer_terms=("台北",),
        critical=True,
    ),
    RealStressScenario(
        "E_conflict_handling",
        (
            ("user1", "stress-e", "我住台北"),
            ("user1", "stress-e", "我住高雄"),
            ("user1", "stress-e", "我住哪?"),
        ),
        "user1",
        {"city": "高雄"},
        ("台北", "高雄"),
        forbidden_answer_terms=("台北",),
        required_answer_terms=("高雄",),
    ),
)


def run_real_stress_smoke() -> dict[str, Any]:
    reports = []
    api_calls = 0
    latency = 0.0
    prompt_tokens = 0
    completion_tokens = 0
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temp_dir:
        for scenario in REAL_STRESS_SCENARIOS:
            db_path = Path(temp_dir) / f"{scenario.case_id}.db"
            service = MultiTurnMemoryService(db_path=db_path)
            turn_reports = []
            final_answer = ""
            for user_id, session_id, message in scenario.turns:
                turn = service.run_turn(user_id=user_id, session_id=session_id, message=message)
                final_answer = turn.assistant_response
                extraction = turn.extraction_result
                extraction_usage = extraction.get("token_usage") or {}
                api_calls += int(extraction.get("api_calls") or 0) + turn.answer_api_calls
                latency += float(extraction.get("latency_seconds") or 0.0) + turn.answer_latency_seconds
                prompt_tokens += int(extraction_usage.get("prompt_tokens") or 0) + int(
                    turn.answer_token_usage.get("prompt_tokens") or 0
                )
                completion_tokens += int(extraction_usage.get("completion_tokens") or 0) + int(
                    turn.answer_token_usage.get("completion_tokens") or 0
                )
                turn_reports.append(
                    {
                        "input": message,
                        "deepseek_output": extraction.get("candidate_json"),
                        "extracted_operation": extraction.get("operation"),
                        "validator_accepted": extraction.get("validator_accepted"),
                        "validator_reasons": extraction.get("validator_reasons"),
                        "memory_write_result": {
                            "memory_written": extraction.get("memory_written"),
                            "reason": extraction.get("reason"),
                            "failure": extraction.get("failure"),
                        },
                        "context": turn.memory_context,
                        "answer": turn.assistant_response,
                    }
                )
            final_context = service.runtime.get_memory_context(scenario.final_user_id)
            history_values = []
            for attribute in ("city", "favorite_drink"):
                history_values.extend(service.get_history_values(scenario.final_user_id, attribute))
            current_counts = {
                "city": _active_current_count(db_path, scenario.final_user_id, "city"),
                "favorite_drink": _active_current_count(db_path, scenario.final_user_id, "favorite_drink"),
            }
            passed = (
                final_context == scenario.expected_context
                and all(value in history_values for value in scenario.expected_history)
                and all(count <= 1 for count in current_counts.values())
                and all(term in final_answer for term in scenario.required_answer_terms)
                and not any(term in final_answer for term in scenario.forbidden_answer_terms)
            )
            reports.append(
                {
                    "case_id": scenario.case_id,
                    "critical": scenario.critical,
                    "turns": turn_reports,
                    "final_context": final_context,
                    "history_values": history_values,
                    "current_counts": current_counts,
                    "final_answer": final_answer,
                    "passed": passed,
                }
            )
    critical = [item for item in reports if item["critical"]]
    critical_passed = sum(1 for item in critical if item["passed"])
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
        "total_scenarios": len(reports),
        "passed_scenarios": sum(1 for item in reports if item["passed"]),
        "critical_scenarios": len(critical),
        "critical_passed": critical_passed,
        "failed_cases": [item for item in reports if not item["passed"]],
        "phase_2c_b_pass": all(item["passed"] for item in reports) and critical_passed == len(critical),
    }


def _active_current_count(db_path: Path, user_id: str, attribute: str) -> int:
    with sqlite3.connect(db_path) as conn:
        return int(
            conn.execute(
                """
                SELECT COUNT(*)
                FROM structured_facts
                WHERE user_id = ?
                  AND subject = 'profile'
                  AND attribute = ?
                  AND valid_to IS NULL
                  AND system_to IS NULL
                """,
                (user_id, attribute),
            ).fetchone()[0]
        )


def test_real_deepseek_stress_smoke_skips_without_configuration():
    if os.environ.get("RUN_REAL_STRESS_SMOKE_TEST", "false").lower() != "true":
        pytest.skip("real stress smoke gate disabled")
    if not os.environ.get("DEEPSEEK_API_KEY"):
        pytest.skip("DEEPSEEK_API_KEY is required for real stress smoke gate")

    report = run_real_stress_smoke()

    assert report["phase_2c_b_pass"], report["failed_cases"]


def main() -> None:
    rendered = json.dumps(run_real_stress_smoke(), ensure_ascii=False, indent=2)
    sys.stdout.buffer.write(rendered.encode("utf-8"))
    sys.stdout.buffer.write(b"\n")


if __name__ == "__main__":
    main()
