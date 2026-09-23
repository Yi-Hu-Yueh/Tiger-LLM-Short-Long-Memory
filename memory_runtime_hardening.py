"""Phase 4A production-like runtime hardening evaluation runner.

This module only orchestrates validation scenarios.  It does not introduce a
memory mutation, proposal, audit, validation, or recovery path.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
import threading
import time
import tracemalloc
from typing import Any, Callable, Mapping, Sequence


HARDENING_CATEGORIES = (
    "concurrency",
    "resource_safety",
    "long_run",
    "failure_isolation",
)


@dataclass(frozen=True, slots=True)
class HardeningOutcome:
    passed: bool
    operations: int = 0

    def __post_init__(self) -> None:
        if type(self.passed) is not bool:
            raise ValueError("passed must be boolean")
        if isinstance(self.operations, bool) or not isinstance(self.operations, int) or self.operations < 0:
            raise ValueError("operations must be a non-negative integer")


@dataclass(frozen=True, slots=True)
class HardeningScenario:
    name: str
    category: str
    execute: Callable[[], HardeningOutcome | bool]

    def __post_init__(self) -> None:
        if not self.name:
            raise ValueError("scenario name is required")
        if self.category not in HARDENING_CATEGORIES:
            raise ValueError("unsupported hardening category")


class RuntimeHardeningRunner:
    """Run bounded hardening scenarios and emit a stable report schema."""

    def run(self, scenarios: Sequence[HardeningScenario]) -> dict[str, Any]:
        categories = {
            category: {"passed": 0, "failed": 0}
            for category in HARDENING_CATEGORIES
        }
        results: list[dict[str, str | int]] = []
        names: set[str] = set()
        exceptions = 0
        operations = 0
        threads_before = threading.active_count()
        started = time.perf_counter()
        tracemalloc.start()
        try:
            for scenario in scenarios:
                if scenario.name in names:
                    raise ValueError("scenario names must be unique")
                names.add(scenario.name)
                error_type = ""
                try:
                    raw = scenario.execute()
                    outcome = raw if isinstance(raw, HardeningOutcome) else HardeningOutcome(raw)
                except Exception as exc:  # A scenario exception is evaluation evidence.
                    outcome = HardeningOutcome(False)
                    error_type = type(exc).__name__
                    exceptions += 1
                operations += outcome.operations
                key = "passed" if outcome.passed else "failed"
                categories[scenario.category][key] += 1
                result: dict[str, str | int] = {
                    "name": scenario.name,
                    "category": scenario.category,
                    "result": "PASS" if outcome.passed else "FAIL",
                    "operations": outcome.operations,
                }
                if error_type:
                    result["error_type"] = error_type
                results.append(result)
            _, peak_bytes = tracemalloc.get_traced_memory()
        finally:
            tracemalloc.stop()
        elapsed = time.perf_counter() - started
        threads_after = threading.active_count()
        overall = (
            "PASS"
            if all(categories[name]["failed"] == 0 for name in HARDENING_CATEGORIES)
            else "FAIL"
        )
        return {
            **categories,
            "resources": {
                "scenario_count": len(scenarios),
                "operation_count": operations,
                "scenario_exceptions": exceptions,
                "elapsed_seconds": round(elapsed, 6),
                "peak_traced_bytes": peak_bytes,
                "threads_before": threads_before,
                "threads_after": threads_after,
                "thread_delta": threads_after - threads_before,
            },
            "scenarios": results,
            "overall": overall,
        }

    @staticmethod
    def render_report(report: Mapping[str, Any]) -> str:
        return json.dumps(report, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
