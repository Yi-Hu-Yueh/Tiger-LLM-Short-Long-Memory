"""Phase 3F deterministic production-readiness evaluation orchestration.

The runner is deliberately policy-neutral: scenarios exercise the existing
Memory Core, proposal, audit, and recovery services and return a boolean
outcome.  It records results without creating a second mutation path.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
import time
from typing import Any, Callable, Mapping, Sequence

from memory_audit import AuditMetrics


EVALUATION_CATEGORIES = ("correctness", "safety", "reliability")
PERFORMANCE_METRICS = (
    "extraction_latency",
    "validation_latency",
    "commit_latency",
    "context_retrieval_latency",
    "decision_latency",
)


@dataclass(frozen=True, slots=True)
class EvaluationScenario:
    name: str
    category: str
    execute: Callable[[], bool]
    measured_as: str | None = None

    def __post_init__(self) -> None:
        if not self.name:
            raise ValueError("scenario name is required")
        if self.category not in EVALUATION_CATEGORIES:
            raise ValueError("unsupported evaluation category")
        if self.measured_as is not None and self.measured_as not in PERFORMANCE_METRICS:
            raise ValueError("unsupported performance metric")


class MemoryEvaluationRunner:
    """Execute deterministic pass/fail scenarios and collect observations."""

    def __init__(self, *, metrics: AuditMetrics | None = None):
        self.metrics = metrics or AuditMetrics()
        self._local_latencies = {
            name: {"count": 0, "total_seconds": 0.0, "max_seconds": 0.0}
            for name in ("context_retrieval_latency", "decision_latency")
        }

    def run(self, scenarios: Sequence[EvaluationScenario]) -> dict[str, Any]:
        summary = {
            category: {"passed": 0, "failed": 0}
            for category in EVALUATION_CATEGORIES
        }
        results: list[dict[str, str]] = []
        names: set[str] = set()
        for scenario in scenarios:
            if scenario.name in names:
                raise ValueError("scenario names must be unique")
            names.add(scenario.name)
            started = time.perf_counter()
            error_type = ""
            try:
                passed = scenario.execute() is True
            except Exception as exc:  # Evaluation failures are report data.
                passed = False
                error_type = type(exc).__name__
            elapsed = time.perf_counter() - started
            if scenario.measured_as is not None:
                self._observe(scenario.measured_as, elapsed)
            key = "passed" if passed else "failed"
            summary[scenario.category][key] += 1
            result = {
                "name": scenario.name,
                "category": scenario.category,
                "result": "PASS" if passed else "FAIL",
            }
            if error_type:
                result["error_type"] = error_type
            results.append(result)

        performance = self._performance_snapshot()
        overall = (
            "PASS"
            if all(summary[category]["failed"] == 0 for category in EVALUATION_CATEGORIES)
            else "FAIL"
        )
        return {
            "correctness": summary["correctness"],
            "safety": summary["safety"],
            "reliability": summary["reliability"],
            "performance": {"metrics": performance},
            "scenarios": results,
            "overall": overall,
        }

    @staticmethod
    def render_report(report: Mapping[str, Any]) -> str:
        return json.dumps(report, ensure_ascii=False, sort_keys=True, separators=(",", ":"))

    def _observe(self, name: str, seconds: float) -> None:
        if name in ("extraction_latency", "validation_latency", "commit_latency"):
            self.metrics.observe_latency(name, seconds)
            return
        metric = self._local_latencies[name]
        metric["count"] += 1
        metric["total_seconds"] += seconds
        metric["max_seconds"] = max(metric["max_seconds"], seconds)

    def _performance_snapshot(self) -> dict[str, dict[str, float | int]]:
        audit_latencies = self.metrics.snapshot()["latencies"]
        source = {**audit_latencies, **self._local_latencies}
        result: dict[str, dict[str, float | int]] = {}
        for name in PERFORMANCE_METRICS:
            metric = source[name]
            count = int(metric["count"])
            total = float(metric["total_seconds"])
            result[name] = {
                "count": count,
                "total_seconds": round(total, 6),
                "average_seconds": round(total / count, 6) if count else 0.0,
                "max_seconds": round(float(metric["max_seconds"]), 6),
            }
        return result
