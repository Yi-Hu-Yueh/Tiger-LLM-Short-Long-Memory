from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys
import tempfile
from typing import Any, Mapping

try:
    import pytest
except ModuleNotFoundError:  # Direct real-gate execution does not require pytest.
    pytest = None

from memory_core import MemoryOperation, SQLiteMemoryCore
from memory_decision import DecisionResult, DecisionService, DeepSeekDecisionGenerator
from memory_extractor import MockMemoryExtractor
from memory_runtime import MemoryRuntimeService


@dataclass(frozen=True)
class DecisionCase:
    case_id: str
    setup: str
    task: str
    expected_memory_used: tuple[str, ...]
    expected_contains: tuple[str, ...] = ()
    forbidden_contains: tuple[str, ...] = ()
    critical: bool = False


DECISION_CASES = (
    DecisionCase("A1_preference_affects", "tea", "推薦飲料", ("favorite_drink",), ("無糖綠茶",), critical=True),
    DecisionCase("C1_irrelevant_city_ignored", "city", "解釋 Python list", (), ("Python",), ("台中",), critical=True),
    DecisionCase("E1_history_isolation", "city_history", "推薦附近活動", ("city",), ("台中",), ("台北",), critical=True),
    DecisionCase("D1_no_memory", "none", "推薦飲料", (), (), ("無糖綠茶", "咖啡")),
    DecisionCase("F1_forgotten_preference", "forgotten_coffee", "推薦飲料", (), (), ("咖啡",)),
    DecisionCase("B1_location_affects", "city", "推薦附近活動", ("city",), ("台中",), ("台北",)),
    DecisionCase("A2_preference_personalized", "tea", "選一種適合我的飲料", ("favorite_drink",), ("無糖綠茶",)),
    DecisionCase("C2_irrelevant_preference_ignored", "tea", "解釋 Python dictionary", (), ("Python",), ("無糖綠茶",)),
    DecisionCase("D2_no_location_memory", "none", "推薦附近活動", (), (), ("台北", "台中", "新竹")),
    DecisionCase("E2_current_city_only", "city_history", "我目前適合去哪裡散步", ("city",), ("台中",), ("台北",), critical=True),
)


class MockDecisionGenerator:
    def generate(self, task: str, memory_context: Mapping[str, Any]) -> DecisionResult:
        if "飲料" in task and "favorite_drink" in memory_context:
            text = f"選擇{memory_context['favorite_drink']}。"
            used = ("favorite_drink",)
        elif ("活動" in task or "散步" in task) and "city" in memory_context:
            text = f"選擇{memory_context['city']}的在地活動。"
            used = ("city",)
        elif "Python" in task:
            text = "提供 Python 概念與範例。"
            used = ()
        else:
            text = "提供不依賴個人記憶的一般建議。"
            used = ()
        return DecisionResult(text, "依目前可用資訊決定。", used, 1.0, dict(memory_context))


def build_runtime(db_path: Path) -> MemoryRuntimeService:
    return MemoryRuntimeService(core=SQLiteMemoryCore(db_path), extractor=MockMemoryExtractor({}))


def setup_memory(runtime: MemoryRuntimeService, setup: str) -> dict[str, Any]:
    if setup == "none":
        return {}
    if setup in {"tea", "forgotten_coffee"}:
        value = "無糖綠茶" if setup == "tea" else "咖啡"
        runtime.core.append_or_replace_fact(
            event_id=f"decision-{setup}-set",
            user_id="user1",
            session_id="setup",
            subject="profile",
            attribute="favorite_drink",
            value=value,
            operation=MemoryOperation.SET,
        )
        if setup == "forgotten_coffee":
            runtime.core.forget_fact(
                event_id="decision-coffee-forget",
                user_id="user1",
                session_id="setup",
                subject="profile",
                attribute="favorite_drink",
            )
    elif setup == "city":
        runtime.core.append_or_replace_fact(
            event_id="decision-city",
            user_id="user1",
            session_id="setup",
            subject="profile",
            attribute="city",
            value="台中",
            operation=MemoryOperation.SET,
        )
    elif setup == "city_history":
        runtime.core.append_or_replace_fact(
            event_id="decision-city-taipei",
            user_id="user1",
            session_id="setup",
            subject="profile",
            attribute="city",
            value="台北",
            valid_from=datetime(2026, 9, 1, tzinfo=timezone.utc),
            system_time=datetime(2026, 9, 1, tzinfo=timezone.utc),
            operation=MemoryOperation.SET,
        )
        runtime.core.append_or_replace_fact(
            event_id="decision-city-taichung",
            user_id="user1",
            session_id="setup",
            subject="profile",
            attribute="city",
            value="台中",
            valid_from=datetime(2026, 9, 20, tzinfo=timezone.utc),
            system_time=datetime(2026, 9, 20, tzinfo=timezone.utc),
            operation=MemoryOperation.REPLACE,
        )
    else:
        raise AssertionError(f"unknown setup: {setup}")
    return runtime.get_memory_context("user1")


def evaluate(case: DecisionCase, result: Mapping[str, Any]) -> bool:
    combined = f"{result['decision']} {result['reason']}"
    return (
        tuple(result["memory_used"]) == case.expected_memory_used
        and all(item in combined for item in case.expected_contains)
        and not any(item in combined for item in case.forbidden_contains)
    )


def run_decision_gate(*, case_limit: int | None = None, real: bool = True) -> dict[str, Any]:
    selected = DECISION_CASES[:case_limit] if case_limit else DECISION_CASES
    generator = DeepSeekDecisionGenerator(model=os.environ.get("DEEPSEEK_MODEL", "deepseek-v4-pro")) if real else MockDecisionGenerator()
    reports = []
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temp_dir:
        for case in selected:
            runtime = build_runtime(Path(temp_dir) / f"{case.case_id}.db")
            context = setup_memory(runtime, case.setup)
            result = DecisionService(runtime=runtime, generator=generator).decide("user1", case.task)
            reports.append({
                "case_id": case.case_id,
                "critical": case.critical,
                "task": case.task,
                "memory_context": context,
                "llm_output": result["raw_output"],
                "decision": result["decision"],
                "reason": result["reason"],
                "memory_used": result["memory_used"],
                "latency_seconds": result["latency_seconds"],
                "token_usage": result["token_usage"],
                "passed": evaluate(case, result),
            })
    critical = [item for item in reports if item["critical"]]
    return {
        "provider": "deepseek" if real else "mock",
        "model": os.environ.get("DEEPSEEK_MODEL", "deepseek-v4-pro") if real else "mock",
        "api_calls": sum(1 for item in reports if real),
        "latency_seconds": sum(float(item["latency_seconds"]) for item in reports),
        "token_usage": {
            key: sum(int(item["token_usage"].get(key) or 0) for item in reports)
            for key in ("prompt_tokens", "completion_tokens", "total_tokens")
        },
        "total_cases": len(reports),
        "passed_cases": sum(1 for item in reports if item["passed"]),
        "critical_cases": len(critical),
        "critical_passed": sum(1 for item in critical if item["passed"]),
        "failed_cases": [item for item in reports if not item["passed"]],
        "phase_3a_pass": len(reports) == len(DECISION_CASES)
        and all(item["passed"] for item in reports)
        and all(item["passed"] for item in critical),
        "smoke_pass": all(item["passed"] for item in reports),
    }


def run_manual_runtime_test() -> dict[str, Any]:
    responses = {
        "我喜歡無糖綠茶": {
            "operation": "set", "subject": "user", "attribute": "favorite_drink",
            "value": "無糖綠茶", "old_value": None, "new_value": "無糖綠茶",
            "confidence": 1.0, "intent": "current_fact", "reason": "manual setup",
            "valid_time": {"from": None, "to": None},
        },
        "忘記我的飲料偏好": {
            "operation": "forget", "subject": "user", "attribute": "favorite_drink",
            "value": None, "old_value": "無糖綠茶", "new_value": None,
            "confidence": 1.0, "intent": "forget_command", "reason": "manual forget",
            "valid_time": {"from": None, "to": None},
        },
    }
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temp_dir:
        runtime = MemoryRuntimeService(
            core=SQLiteMemoryCore(Path(temp_dir) / "manual-decision.db"),
            extractor=MockMemoryExtractor(responses),
        )
        service = DecisionService(
            runtime=runtime,
            generator=DeepSeekDecisionGenerator(model=os.environ.get("DEEPSEEK_MODEL", "deepseek-v4-pro")),
        )
        stored = runtime.process_user_message("user1", "manual", "我喜歡無糖綠茶")
        before = service.decide("user1", "推薦飲料")
        forgotten = runtime.process_user_message("user1", "manual", "忘記我的飲料偏好")
        after = service.decide("user1", "推薦飲料")
    before_text = f"{before['decision']} {before['reason']}"
    after_text = f"{after['decision']} {after['reason']}"
    passed = (
        stored["memory_written"]
        and "無糖綠茶" in before_text
        and before["memory_used"] == ["favorite_drink"]
        and forgotten["memory_written"]
        and after["memory_used"] == []
        and "無糖綠茶" not in after_text
    )
    return {
        "api_calls": before["api_calls"] + after["api_calls"],
        "latency_seconds": before["latency_seconds"] + after["latency_seconds"],
        "token_usage": {
            key: int(before["token_usage"].get(key) or 0) + int(after["token_usage"].get(key) or 0)
            for key in ("prompt_tokens", "completion_tokens", "total_tokens")
        },
        "before_forget": {"context": before["memory_context"], "decision": before["decision"], "memory_used": before["memory_used"]},
        "after_forget": {"context": after["memory_context"], "decision": after["decision"], "memory_used": after["memory_used"]},
        "passed": passed,
    }


def test_mock_decision_gate_passes_without_provider():
    report = run_decision_gate(real=False)
    assert report["phase_3a_pass"], report["failed_cases"]


def test_real_decision_gate_skips_without_configuration():
    assert pytest is not None
    if os.environ.get("RUN_REAL_DECISION_TEST", "false").lower() != "true":
        pytest.skip("real decision gate disabled")
    if not os.environ.get("DEEPSEEK_API_KEY"):
        pytest.skip("DEEPSEEK_API_KEY is required for real decision gate")
    report = run_decision_gate(real=True)
    assert report["phase_3a_pass"], report["failed_cases"]


def main() -> None:
    mode = os.environ.get("DECISION_GATE_MODE", "full")
    if mode == "manual":
        report = run_manual_runtime_test()
    else:
        raw_limit = os.environ.get("REAL_DECISION_CASE_LIMIT")
        report = run_decision_gate(case_limit=int(raw_limit) if raw_limit else None, real=True)
    sys.stdout.buffer.write(json.dumps(report, ensure_ascii=False, indent=2).encode("utf-8"))
    sys.stdout.buffer.write(b"\n")


if __name__ == "__main__":
    main()
