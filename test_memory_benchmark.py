from __future__ import annotations

import json
import sys
import types
import unittest

try:
    import pytest  # noqa: F401
except ModuleNotFoundError:
    pytest_stub = types.ModuleType("pytest")

    class _Mark:
        def parametrize(self, *args, **kwargs):
            return lambda function: function

        def skipif(self, *args, **kwargs):
            return lambda function: function

    pytest_stub.mark = _Mark()
    sys.modules["pytest"] = pytest_stub

from memory_benchmark import (
    BonsaiProvider,
    MemoryBenchmarkRunner,
    MemoryModelProvider,
    ModelGeneration,
    load_validated_cases,
)
from test_memory_boundary import BOUNDARY_CASES
from test_state_transition import TRANSITION_CASES


class FixtureProvider(MemoryModelProvider):
    name = "mock"
    model = "validated-fixtures"
    status = "AVAILABLE"

    def __init__(self, cases):
        self._responses = {}
        for case in cases:
            output = {
                "intent": case.expected_fields.get("intent", "current_fact"),
                "operation": case.expected_fields["operation"],
                "subject": "user",
                "attribute": case.expected_fields.get("attribute"),
                "old_value": case.expected_fields.get("old_value"),
                "new_value": case.expected_fields.get("new_value"),
                "value": case.expected_fields.get("new_value", "fixture-value"),
                "confidence": 1.0,
                "reason": "validated fixture",
                "valid_time": {"from": None, "to": None},
            }
            if not case.expected_validator_accepted:
                output = {"operation": "ignore", "subject": None, "attribute": None,
                          "value": None, "confidence": 1.0, "reason": "safe rejection",
                          "valid_time": {"from": None, "to": None}}
            self._responses[case.text] = output

    def generate(self, prompt):
        text = json.loads(prompt)["user_text"]
        return ModelGeneration(
            raw_output=json.dumps(self._responses[text], ensure_ascii=False),
            latency_seconds=0.01,
            token_usage={"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
        )


def _cases():
    return load_validated_cases(BOUNDARY_CASES, TRANSITION_CASES)


class MemoryBenchmarkTests(unittest.TestCase):
    def test_existing_validated_dataset_loads_without_fixture_changes(self):
        cases = _cases()
        self.assertEqual(len(cases), 70)
        self.assertEqual(
            {case.category for case in cases}, {"extraction", "transition", "safety"}
        )
        self.assertEqual(len({case.case_id for case in cases}), len(cases))
        self.assertEqual(len(BOUNDARY_CASES), 50)
        self.assertEqual(len(TRANSITION_CASES), 20)

    def test_mock_provider_runs_all_benchmark_categories(self):
        cases = _cases()
        runner = MemoryBenchmarkRunner(cases=cases, providers=[FixtureProvider(cases)])
        report = runner.run_all()
        result = report["benchmark"]["mock:validated-fixtures"]
        self.assertEqual(sum(section["total_cases"] for section in result.values()), 70)
        self.assertTrue(all(section["status"] == "COMPLETED" for section in result.values()))
        self.assertEqual(result["safety"]["safety_accuracy"], 1.0)
        self.assertEqual(report["recommendation"]["decision"], "NO_MODEL_REPLACEMENT")

    def test_unavailable_bonsai_is_reported_without_generation(self):
        cases = _cases()
        provider = BonsaiProvider(available=False)
        report = MemoryBenchmarkRunner(cases=cases, providers=[provider]).run_all()
        key = f"bonsai:{provider.model}"
        self.assertEqual(report["models"][key]["status"], "NOT_AVAILABLE")
        self.assertTrue(
            all(
                section["status"] == "NOT_AVAILABLE"
                for section in report["benchmark"][key].values()
            )
        )

    def test_report_generation_is_deterministic(self):
        cases = _cases()
        runner = MemoryBenchmarkRunner(cases=cases, providers=[FixtureProvider(cases)])
        first = runner.run_all()
        second = runner.generate_report()
        self.assertEqual(first, second)
        self.assertEqual(runner.render_report(first), runner.render_report(second))


if __name__ == "__main__":
    unittest.main()
