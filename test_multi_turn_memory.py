from __future__ import annotations

from dataclasses import dataclass
import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Any

import pytest

from memory_answer import AnswerResult
from memory_extractor import MockMemoryExtractor
from memory_multi_turn import MultiTurnMemoryService


def candidate(operation, attribute=None, value=None, *, subject="user", confidence=0.95):
    return {
        "operation": operation,
        "subject": subject,
        "attribute": attribute,
        "value": value,
        "old_value": None,
        "new_value": value,
        "confidence": confidence,
        "intent": "current_fact",
        "reason": "multi-turn fixture",
        "valid_time": {"from": None, "to": None},
    }


MOCK_RESPONSES = {
    "我喜歡喝無糖綠茶": candidate("set", "favorite_drink", "無糖綠茶"),
    "推薦飲料": candidate("query", None, None, subject=None),
    "我住台北": candidate("set", "city", "台北"),
    "我搬到新竹": candidate("replace", "city", "新竹"),
    "推薦附近活動": candidate("query", None, None, subject=None),
    "我住新竹": candidate("set", "city", "新竹"),
    "更正，我現在住台中": {
        **candidate("correct", "city", "台中"),
        "intent": "correction",
        "valid_time": {"from": "2026-09-01T00:00:00+00:00", "to": None},
    },
    "我住哪裡?": candidate("query", None, None, subject=None),
    "我喜歡咖啡": candidate("set", "favorite_drink", "咖啡"),
    "忘記我的飲料偏好": {
        **candidate("forget", "favorite_drink", None),
        "intent": "forget_command",
    },
    "我不喝咖啡": candidate("ignore", None, None, subject=None),
    "我住哪?": candidate("query", None, None, subject=None),
}


class MockAnswerGenerator:
    def answer(self, user_message: str, memory_context: dict[str, Any]) -> AnswerResult:
        if "favorite_drink" in memory_context and "飲料" in user_message:
            text = f"可以考慮{memory_context['favorite_drink']}。"
        elif "city" in memory_context and "活動" in user_message:
            text = f"可以在{memory_context['city']}附近散步或看展。"
        elif "city" in memory_context and "住哪" in user_message:
            text = f"你目前住在{memory_context['city']}。"
        elif "飲料" in user_message:
            text = "可以考慮茶飲或氣泡水。"
        else:
            text = "目前沒有相關記憶。"
        return AnswerResult(text, 0.0, 0, {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0})


@dataclass(frozen=True)
class ConversationCase:
    case_id: str
    turns: tuple[tuple[str, str, str], ...]
    final_user_id: str
    expected_contains: tuple[str, ...]
    forbidden_contains: tuple[str, ...] = ()
    expected_context: dict[str, Any] | None = None
    expected_history: tuple[Any, ...] = ()
    critical: bool = False


CONVERSATION_CASES = (
    ConversationCase(
        "A_preference_persistence",
        (("user1", "s1", "我喜歡喝無糖綠茶"), ("user1", "s1", "推薦飲料")),
        "user1",
        ("無糖綠茶",),
        critical=False,
    ),
    ConversationCase(
        "B_location_replacement",
        (("user1", "s1", "我住台北"), ("user1", "s1", "我搬到新竹"), ("user1", "s1", "推薦附近活動")),
        "user1",
        ("新竹",),
        ("台北",),
        {"city": "新竹"},
        ("台北", "新竹"),
        True,
    ),
    ConversationCase(
        "C_correction_lifecycle",
        (("user1", "s1", "我住新竹"), ("user1", "s1", "更正，我現在住台中"), ("user1", "s1", "我住哪裡?")),
        "user1",
        ("台中",),
        ("新竹",),
        {"city": "台中"},
        ("新竹", "台中"),
        True,
    ),
    ConversationCase(
        "D_forget_preference",
        (("user1", "s1", "我喜歡咖啡"), ("user1", "s1", "忘記我的飲料偏好"), ("user1", "s1", "推薦飲料")),
        "user1",
        (),
        ("熱咖啡", "冰咖啡", "拿鐵", "美式"),
        {},
        ("咖啡",),
        True,
    ),
    ConversationCase(
        "E_negative_preference",
        (("user1", "s1", "我不喝咖啡"), ("user1", "s1", "推薦飲料")),
        "user1",
        (),
        ("熱咖啡", "冰咖啡", "拿鐵", "美式"),
        {},
        (),
        False,
    ),
    ConversationCase(
        "F_session_isolation",
        (("userA", "s1", "我住台北"), ("userB", "s2", "我住哪?")),
        "userB",
        (),
        ("台北",),
        {},
        (),
        True,
    ),
    ConversationCase(
        "G_preference_second_session",
        (("user1", "s1", "我喜歡喝無糖綠茶"), ("user1", "s2", "推薦飲料")),
        "user1",
        ("無糖綠茶",),
    ),
    ConversationCase(
        "H_location_query_second_session",
        (("user1", "s1", "我住台北"), ("user1", "s2", "我住哪裡?")),
        "user1",
        ("台北",),
    ),
    ConversationCase(
        "I_replace_second_session",
        (("user1", "s1", "我住台北"), ("user1", "s2", "我搬到新竹"), ("user1", "s3", "我住哪裡?")),
        "user1",
        ("新竹",),
        ("台北",),
        {"city": "新竹"},
        ("台北", "新竹"),
        True,
    ),
    ConversationCase(
        "J_forget_cross_session",
        (("user1", "s1", "我喜歡咖啡"), ("user1", "s2", "忘記我的飲料偏好"), ("user1", "s3", "推薦飲料")),
        "user1",
        (),
        ("熱咖啡", "冰咖啡", "拿鐵", "美式"),
        {},
        ("咖啡",),
        True,
    ),
)


def run_multi_turn_gate(*, case_limit: int | None = None, real: bool = True) -> dict[str, Any]:
    selected = CONVERSATION_CASES[:case_limit] if case_limit else CONVERSATION_CASES
    reports = []
    api_calls = 0
    latency = 0.0
    prompt_tokens = 0
    completion_tokens = 0
    with tempfile.TemporaryDirectory() as temp_dir:
        for case in selected:
            db_path = Path(temp_dir) / f"{case.case_id}.db"
            service = (
                MultiTurnMemoryService(db_path=db_path)
                if real
                else MultiTurnMemoryService(
                    db_path=db_path,
                    extractor=MockMemoryExtractor(MOCK_RESPONSES),
                    answer_generator=MockAnswerGenerator(),
                )
            )
            turn_reports = []
            final_turn = None
            for user_id, session_id, message in case.turns:
                final_turn = service.run_turn(user_id=user_id, session_id=session_id, message=message)
                extraction = final_turn.extraction_result
                usage = extraction.get("token_usage") or {}
                api_calls += int(extraction.get("api_calls") or 0) + final_turn.answer_api_calls
                latency += float(extraction.get("latency_seconds") or 0.0) + final_turn.answer_latency_seconds
                prompt_tokens += int(usage.get("prompt_tokens") or 0) + int(final_turn.answer_token_usage.get("prompt_tokens") or 0)
                completion_tokens += int(usage.get("completion_tokens") or 0) + int(final_turn.answer_token_usage.get("completion_tokens") or 0)
                turn_reports.append(
                    {
                        "message": message,
                        "extraction_result": extraction,
                        "memory_context": final_turn.memory_context,
                        "assistant_response": final_turn.assistant_response,
                    }
                )
            assert final_turn is not None
            final_context = service.runtime.get_memory_context(case.final_user_id)
            history_values = service.get_history_values(case.final_user_id, "city") + service.get_history_values(case.final_user_id, "favorite_drink")
            passed = (
                all(item in final_turn.assistant_response for item in case.expected_contains)
                and not any(item in final_turn.assistant_response for item in case.forbidden_contains)
                and (case.expected_context is None or final_context == case.expected_context)
                and all(value in history_values for value in case.expected_history)
            )
            reports.append(
                {
                    "case_id": case.case_id,
                    "critical": case.critical,
                    "turns": turn_reports,
                    "final_context": final_context,
                    "history_values": history_values,
                    "passed": passed,
                }
            )
    critical = [item for item in reports if item["critical"]]
    critical_passed = sum(1 for item in critical if item["passed"])
    return {
        "provider": "deepseek" if real else "mock",
        "model": os.environ.get("DEEPSEEK_MODEL", "deepseek-v4-pro") if real else "mock",
        "api_calls": api_calls,
        "latency_seconds": latency,
        "token_usage": {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": prompt_tokens + completion_tokens,
        },
        "total_conversations": len(reports),
        "passed_conversations": sum(1 for item in reports if item["passed"]),
        "critical_conversations": len(critical),
        "critical_passed": critical_passed,
        "failed_cases": [item for item in reports if not item["passed"]],
        "phase_2b_pass": len(reports) == len(CONVERSATION_CASES)
        and all(item["passed"] for item in reports)
        and critical_passed == len(critical),
        "smoke_pass": all(item["passed"] for item in reports),
    }


def test_mock_multi_turn_gate_passes_without_real_provider():
    report = run_multi_turn_gate(real=False)

    assert report["phase_2b_pass"], report["failed_cases"]


def test_real_multi_turn_gate_skips_without_configuration():
    if os.environ.get("RUN_REAL_MULTI_TURN_TEST", "false").lower() != "true":
        pytest.skip("real multi-turn gate disabled")
    if not os.environ.get("DEEPSEEK_API_KEY"):
        pytest.skip("DEEPSEEK_API_KEY is required for real multi-turn gate")

    report = run_multi_turn_gate(real=True)

    assert report["phase_2b_pass"], report["failed_cases"]


def main() -> None:
    raw_limit = os.environ.get("REAL_MULTI_TURN_CASE_LIMIT")
    report = run_multi_turn_gate(case_limit=int(raw_limit) if raw_limit else None, real=True)
    rendered = json.dumps(report, ensure_ascii=False, indent=2)
    sys.stdout.buffer.write(rendered.encode("utf-8"))
    sys.stdout.buffer.write(b"\n")


if __name__ == "__main__":
    main()
