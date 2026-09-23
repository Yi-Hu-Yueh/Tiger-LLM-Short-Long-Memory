"""Phase 4B-R bounded soak orchestration for the approved two-user scope."""

from __future__ import annotations

from dataclasses import dataclass
import gc
import json
import threading
import time
from typing import Any, Callable, Mapping, Sequence
import warnings


LATENCY_NAMES = ("read", "write", "proposal", "confirm")
INTEGRITY_NAMES = (
    "corruption_count",
    "isolation_failures",
    "stale_conflicts",
    "rollback_count",
)


@dataclass(frozen=True, slots=True)
class SoakOutcome:
    passed: bool
    label: str

    def __post_init__(self) -> None:
        if type(self.passed) is not bool or not self.label:
            raise ValueError("invalid soak outcome")


@dataclass(frozen=True, slots=True)
class SoakScenario:
    name: str
    execute: Callable[["SoakMetrics"], SoakOutcome | bool]

    def __post_init__(self) -> None:
        if not self.name:
            raise ValueError("scenario name is required")


class SoakMetrics:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._total = 0
        self._success = 0
        self._failure = 0
        self._latencies = {
            name: {"count": 0, "total_seconds": 0.0, "max_seconds": 0.0}
            for name in LATENCY_NAMES
        }
        self._integrity = {name: 0 for name in INTEGRITY_NAMES}

    def measure(self, name: str, operation: Callable[[], Any], *, expected_failure: bool = False) -> Any:
        if name not in LATENCY_NAMES:
            raise ValueError("unknown latency category")
        started = time.perf_counter()
        try:
            result = operation()
        except Exception:
            self._record(name, time.perf_counter() - started, success=False)
            raise
        self._record(name, time.perf_counter() - started, success=not expected_failure)
        return result

    def expected_failure(self, name: str, operation: Callable[[], Any]) -> BaseException | None:
        try:
            self.measure(name, operation)
        except Exception as exc:
            return exc
        return None

    def increment_integrity(self, name: str, amount: int = 1) -> None:
        if name not in self._integrity or isinstance(amount, bool) or amount < 0:
            raise ValueError("invalid integrity metric")
        with self._lock:
            self._integrity[name] += amount

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            latencies: dict[str, dict[str, float | int]] = {}
            for name in LATENCY_NAMES:
                item = self._latencies[name]
                count = int(item["count"])
                total = float(item["total_seconds"])
                latencies[name] = {
                    "count": count,
                    "total_seconds": round(total, 6),
                    "average_seconds": round(total / count, 6) if count else 0.0,
                    "max_seconds": round(float(item["max_seconds"]), 6),
                }
            return {
                "operations": {
                    "total": self._total,
                    "successful": self._success,
                    "failed": self._failure,
                },
                "latency": latencies,
                "integrity": dict(self._integrity),
            }

    def _record(self, name: str, elapsed: float, *, success: bool) -> None:
        with self._lock:
            self._total += 1
            self._success += int(success)
            self._failure += int(not success)
            item = self._latencies[name]
            item["count"] += 1
            item["total_seconds"] += elapsed
            item["max_seconds"] = max(item["max_seconds"], elapsed)


class MemorySoakRunner:
    """Execute bounded scenarios and report operations, latency, integrity, and cleanup."""

    def run(self, scenarios: Sequence[SoakScenario]) -> dict[str, Any]:
        metrics = SoakMetrics()
        names: set[str] = set()
        results: list[dict[str, str]] = []
        warning_count = 0
        threads_before = threading.active_count()
        with warnings.catch_warnings(record=True) as captured:
            warnings.simplefilter("always", ResourceWarning)
            for scenario in scenarios:
                if scenario.name in names:
                    raise ValueError("scenario names must be unique")
                names.add(scenario.name)
                error_type = ""
                try:
                    raw = scenario.execute(metrics)
                    outcome = raw if isinstance(raw, SoakOutcome) else SoakOutcome(raw, scenario.name)
                except Exception as exc:
                    outcome = SoakOutcome(False, scenario.name)
                    error_type = type(exc).__name__
                result = {
                    "name": scenario.name,
                    "result": "PASS" if outcome.passed else "FAIL",
                    "label": outcome.label,
                }
                if error_type:
                    result["error_type"] = error_type
                results.append(result)
                gc.collect()
            warning_count = sum(issubclass(item.category, ResourceWarning) for item in captured)
        threads_after = threading.active_count()
        snapshot = metrics.snapshot()
        cleanup = threads_after == threads_before
        overall = (
            "PASS"
            if all(item["result"] == "PASS" for item in results)
            and warning_count == 0
            and cleanup
            and snapshot["integrity"]["corruption_count"] == 0
            and snapshot["integrity"]["isolation_failures"] == 0
            else "FAIL"
        )
        return {
            **snapshot,
            "resource": {
                "resource_warning_count": warning_count,
                "threads_before": threads_before,
                "threads_after": threads_after,
                "cleanup_status": "PASS" if cleanup else "FAIL",
            },
            "scenarios": results,
            "overall": overall,
        }

    @staticmethod
    def render_report(report: Mapping[str, Any]) -> str:
        return json.dumps(report, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
