from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import json
import os
import sys
import tempfile
from typing import Any

import pytest

from memory_answer import AnswerResult
from memory_extractor import MockMemoryExtractor
from memory_multi_turn import MultiTurnMemoryService


def candidate(operation, attribute=None, value=None, *, subject="user", intent="current_fact"):
    return {
        "operation": operation,
        "subject": subject,
        "attribute": attribute,
        "value": value,
        "old_value": None,
        "new_value": value,
        "confidence": 0.95,
        "intent": intent,
        "reason": "stress fixture",
        "valid_time": {"from": None, "to": None},
    }


class MockStressAnswerGenerator:
    def answer(self, user_message: str, memory_context: dict[str, Any]) -> AnswerResult:
        if "住哪" in user_message and "city" in memory_context:
            text = f"你目前住在{memory_context['city']}。"
        elif "活動" in user_message and "city" in memory_context:
            text = f"可以在{memory_context['city']}附近安排活動。"
        elif "飲料" in user_message and "favorite_drink" in memory_context:
            text = f"可以考慮{memory_context['favorite_drink']}。"
        elif "飲料" in user_message:
            text = "可以考慮茶飲或氣泡水。"
        else:
            text = "已處理。"
        return AnswerResult(text, 0.0, 0, {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0})


MOCK_RESPONSES = {
    "我住台北": candidate("set", "city", "台北"),
    "我住新竹": candidate("replace", "city", "新竹"),
    "我住高雄": candidate("replace", "city", "高雄"),
    "我搬到新竹": candidate("replace", "city", "新竹"),
    "我搬到台中": candidate("replace", "city", "台中"),
    "我搬到台南": candidate("replace", "city", "台南"),
    "我喜歡茶": candidate("set", "favorite_drink", "茶"),
    "我改喝咖啡": candidate("replace", "favorite_drink", "咖啡"),
    "更正，我不喝咖啡": candidate("forget", "favorite_drink", None, intent="forget_command"),
    "更正，我住新竹": {**candidate("correct", "city", "新竹", intent="correction"), "valid_time": {"from": "2026-09-01T00:00:00+00:00", "to": None}},
    "更正，我住台中": {**candidate("correct", "city", "台中", intent="correction"), "valid_time": {"from": "2026-09-02T00:00:00+00:00", "to": None}},
    "我喜歡咖啡": candidate("set", "favorite_drink", "咖啡"),
    "忘記我的飲料偏好": candidate("forget", "favorite_drink", None, intent="forget_command"),
    "我喜歡綠茶": candidate("set", "favorite_drink", "綠茶"),
    "我現在住哪？": candidate("query", None, None, subject=None, intent="query"),
    "我住哪?": candidate("query", None, None, subject=None, intent="query"),
    "推薦飲料": candidate("query", None, None, subject=None, intent="query"),
    "推薦附近活動": candidate("query", None, None, subject=None, intent="query"),
    "只是聊天": candidate("ignore", None, None, subject=None, intent="ignore"),
}


@dataclass(frozen=True)
class StressScenario:
    case_id: str
    turns: tuple[tuple[str, str, str], ...]
    final_user_id: str
    expected_context: dict[str, Any]
    expected_history: tuple[Any, ...]
    one_current_attributes: tuple[str, ...]
    critical: bool = False


def _long_turns() -> tuple[tuple[str, str, str], ...]:
    turns = []
    for index in range(1, 51):
        message = "只是聊天"
        if index == 1:
            message = "我住台北"
        elif index == 10:
            message = "我喜歡茶"
        elif index == 20:
            message = "我搬到新竹"
        elif index == 30:
            message = "我改喝咖啡"
        elif index == 40:
            message = "更正，我不喝咖啡"
        elif index == 50:
            message = "我現在住哪？"
        turns.append(("user1", "long", message))
    return tuple(turns)


def _user_isolation_turns() -> tuple[tuple[str, str, str], ...]:
    turns = []
    for index in range(50):
        turns.append(("userA", "ua", "我住台北" if index == 0 else "只是聊天"))
        turns.append(("userB", "ub", "我搬到新竹" if index == 0 else "只是聊天"))
    return tuple(turns)


STRESS_SCENARIOS = (
    StressScenario("A_long_conversation", _long_turns(), "user1", {"city": "新竹"}, ("台北", "新竹", "茶", "咖啡"), ("city",), False),
    StressScenario("B_repeated_replacement", (("user1", "s", "我住台北"), ("user1", "s", "我搬到新竹"), ("user1", "s", "我搬到台中"), ("user1", "s", "我搬到台南")), "user1", {"city": "台南"}, ("台北", "新竹", "台中", "台南"), ("city",), True),
    StressScenario("C_conflicting_statements", (("user1", "s", "我住台北"), ("user1", "s", "我住新竹"), ("user1", "s", "我住高雄")), "user1", {"city": "高雄"}, ("台北", "新竹", "高雄"), ("city",), True),
    StressScenario("D_correction_chain", (("user1", "s", "我住台北"), ("user1", "s", "更正，我住新竹"), ("user1", "s", "更正，我住台中")), "user1", {"city": "台中"}, ("台北", "新竹", "台中"), ("city",), False),
    StressScenario("E_forget_rebuild", (("user1", "s", "我喜歡咖啡"), ("user1", "s", "忘記我的飲料偏好"), ("user1", "s", "我喜歡綠茶")), "user1", {"favorite_drink": "綠茶"}, ("咖啡", "綠茶"), ("favorite_drink",), True),
    StressScenario("F_user_isolation", _user_isolation_turns(), "userB", {"city": "新竹"}, ("新竹",), ("city",), True),
    StressScenario("G_duplicate_event", tuple(("user1", "s", "我住台北") for _ in range(10)), "user1", {"city": "台北"}, ("台北",), ("city",), True),
    StressScenario("H_rebuild_after_many_chats", (("user1", "s", "我住台北"),) + tuple(("user1", "s", "只是聊天") for _ in range(20)) + (("user1", "s", "我搬到新竹"),), "user1", {"city": "新竹"}, ("台北", "新竹"), ("city",), False),
    StressScenario("I_forget_only", (("user1", "s", "我喜歡咖啡"), ("user1", "s", "忘記我的飲料偏好")), "user1", {}, ("咖啡",), ("favorite_drink",), True),
    StressScenario("J_conflict_then_query", (("user1", "s", "我住台北"), ("user1", "s", "我住新竹"), ("user1", "s", "我住哪?")), "user1", {"city": "新竹"}, ("台北", "新竹"), ("city",), False),
)


def run_stress_gate(*, case_limit: int | None = None, real: bool = True) -> dict[str, Any]:
    selected = STRESS_SCENARIOS[:case_limit] if case_limit else STRESS_SCENARIOS
    reports = []
    api_calls = 0
    latency = 0.0
    prompt_tokens = 0
    completion_tokens = 0
    with tempfile.TemporaryDirectory() as temp_dir:
        for scenario in selected:
            service = (
                MultiTurnMemoryService(db_path=Path(temp_dir) / f"{scenario.case_id}.db")
                if real
                else MultiTurnMemoryService(
                    db_path=Path(temp_dir) / f"{scenario.case_id}.db",
                    extractor=MockMemoryExtractor(MOCK_RESPONSES),
                    answer_generator=MockStressAnswerGenerator(),
                )
            )
            for user_id, session_id, message in scenario.turns:
                turn = service.run_turn(user_id=user_id, session_id=session_id, message=message)
                extraction = turn.extraction_result
                usage = extraction.get("token_usage") or {}
                api_calls += int(extraction.get("api_calls") or 0) + turn.answer_api_calls
                latency += float(extraction.get("latency_seconds") or 0.0) + turn.answer_latency_seconds
                prompt_tokens += int(usage.get("prompt_tokens") or 0) + int(turn.answer_token_usage.get("prompt_tokens") or 0)
                completion_tokens += int(usage.get("completion_tokens") or 0) + int(turn.answer_token_usage.get("completion_tokens") or 0)
            context = service.runtime.get_memory_context(scenario.final_user_id)
            histories = []
            for attribute in ("city", "favorite_drink"):
                histories.extend(service.get_history_values(scenario.final_user_id, attribute))
            one_current_ok = all(attribute not in context or list(context).count(attribute) == 1 for attribute in scenario.one_current_attributes)
            passed = context == scenario.expected_context and one_current_ok and all(value in histories for value in scenario.expected_history)
            reports.append({"case_id": scenario.case_id, "critical": scenario.critical, "final_context": context, "history_values": histories, "passed": passed})
    critical = [item for item in reports if item["critical"]]
    critical_passed = sum(1 for item in critical if item["passed"])
    return {
        "provider": "deepseek" if real else "mock",
        "model": os.environ.get("DEEPSEEK_MODEL", "deepseek-v4-pro") if real else "mock",
        "api_calls": api_calls,
        "latency_seconds": latency,
        "token_usage": {"prompt_tokens": prompt_tokens, "completion_tokens": completion_tokens, "total_tokens": prompt_tokens + completion_tokens},
        "total_scenarios": len(reports),
        "passed_scenarios": sum(1 for item in reports if item["passed"]),
        "critical_scenarios": len(critical),
        "critical_passed": critical_passed,
        "failed_cases": [item for item in reports if not item["passed"]],
        "phase_2c_pass": len(reports) == len(STRESS_SCENARIOS) and all(item["passed"] for item in reports) and critical_passed == len(critical),
        "smoke_pass": all(item["passed"] for item in reports),
    }


def test_mock_stress_gate_passes_without_real_provider():
    report = run_stress_gate(real=False)
    assert report["phase_2c_pass"], report["failed_cases"]


def test_real_stress_gate_skips_without_configuration():
    if os.environ.get("RUN_REAL_STRESS_TEST", "false").lower() != "true":
        pytest.skip("real stress gate disabled")
    if not os.environ.get("DEEPSEEK_API_KEY"):
        pytest.skip("DEEPSEEK_API_KEY is required for real stress gate")
    report = run_stress_gate(real=True)
    assert report["phase_2c_pass"], report["failed_cases"]


def main() -> None:
    raw_limit = os.environ.get("REAL_STRESS_CASE_LIMIT")
    report = run_stress_gate(case_limit=int(raw_limit) if raw_limit else None, real=True)
    rendered = json.dumps(report, ensure_ascii=False, indent=2)
    sys.stdout.buffer.write(rendered.encode("utf-8"))
    sys.stdout.buffer.write(b"\n")


if __name__ == "__main__":
    main()
