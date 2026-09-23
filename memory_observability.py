"""Phase 4C deterministic aggregation, health, alerting, and reporting."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from enum import StrEnum
import json
from typing import Any, Mapping

from memory_audit import AuditMetrics, COUNTER_NAMES


OPERATION_METRICS = tuple(COUNTER_NAMES)
RELIABILITY_METRICS = (
    "rollback_count",
    "stale_conflict_count",
    "corruption_count",
    "isolation_failure_count",
)
PERFORMANCE_METRICS = (
    "extraction_latency",
    "validation_latency",
    "commit_latency",
    "context_latency",
    "decision_latency",
)


class HealthState(StrEnum):
    HEALTHY = "HEALTHY"
    WARNING = "WARNING"
    CRITICAL = "CRITICAL"


@dataclass(frozen=True, slots=True)
class ObservabilityThresholds:
    failure_ratio_warning: float = 0.10
    rollback_warning: int = 3
    rollback_critical: int = 10
    extraction_latency: float = 5.0
    validation_latency: float = 0.10
    commit_latency: float = 0.50
    context_latency: float = 0.10
    decision_latency: float = 5.0

    def __post_init__(self) -> None:
        if not 0.0 <= self.failure_ratio_warning <= 1.0:
            raise ValueError("failure ratio threshold must be from zero through one")
        if self.rollback_warning < 0 or self.rollback_critical < self.rollback_warning:
            raise ValueError("rollback thresholds are invalid")
        for name in PERFORMANCE_METRICS:
            if getattr(self, name) < 0:
                raise ValueError("latency threshold must be non-negative")


class ObservabilityService:
    """Read existing metrics and evaluate them without changing runtime state."""

    def __init__(
        self,
        *,
        audit_metrics: AuditMetrics,
        reliability: Mapping[str, int] | None = None,
        performance: Mapping[str, Mapping[str, float | int]] | None = None,
        thresholds: ObservabilityThresholds | None = None,
    ):
        self.audit_metrics = audit_metrics
        self.reliability = self._reliability(reliability or {})
        self.performance = self._supplemental_performance(performance or {})
        self.thresholds = thresholds or ObservabilityThresholds()

    def collect_metrics(self) -> dict[str, Any]:
        source = self.audit_metrics.snapshot()
        operations = {
            name: int(source["counters"].get(name, 0))
            for name in OPERATION_METRICS
        }
        performance: dict[str, dict[str, float | int]] = {}
        aliases = {
            "extraction_latency": "extraction_latency",
            "validation_latency": "validation_latency",
            "commit_latency": "commit_latency",
        }
        for target, source_name in aliases.items():
            performance[target] = self._normalize_latency(source["latencies"][source_name])
        performance["context_latency"] = deepcopy(self.performance["context_latency"])
        performance["decision_latency"] = deepcopy(self.performance["decision_latency"])
        return {
            "memory_operations": operations,
            "reliability": dict(self.reliability),
            "performance": performance,
        }

    def evaluate_health(self, metrics: Mapping[str, Any] | None = None) -> HealthState:
        snapshot = self._validated_snapshot(metrics or self.collect_metrics())
        reliability = snapshot["reliability"]
        if reliability["corruption_count"] > 0 or reliability["isolation_failure_count"] > 0:
            return HealthState.CRITICAL
        if reliability["rollback_count"] >= self.thresholds.rollback_critical:
            return HealthState.CRITICAL
        if self._failure_ratio(snapshot) > self.thresholds.failure_ratio_warning:
            return HealthState.WARNING
        if reliability["rollback_count"] > self.thresholds.rollback_warning:
            return HealthState.WARNING
        if self._high_latency_names(snapshot):
            return HealthState.WARNING
        return HealthState.HEALTHY

    def evaluate_alerts(self, metrics: Mapping[str, Any] | None = None) -> list[dict[str, Any]]:
        snapshot = self._validated_snapshot(metrics or self.collect_metrics())
        reliability = snapshot["reliability"]
        alerts: list[dict[str, Any]] = []
        if reliability["corruption_count"] > 0:
            alerts.append({
                "alert": "MEMORY_CORRUPTION",
                "severity": "CRITICAL",
                "value": reliability["corruption_count"],
            })
        if reliability["isolation_failure_count"] > 0:
            alerts.append({
                "alert": "USER_ISOLATION_FAILURE",
                "severity": "CRITICAL",
                "value": reliability["isolation_failure_count"],
            })
        if reliability["rollback_count"] >= self.thresholds.rollback_critical:
            alerts.append({
                "alert": "REPEATED_ROLLBACK_FAILURE",
                "severity": "CRITICAL",
                "value": reliability["rollback_count"],
            })
        ratio = self._failure_ratio(snapshot)
        if ratio > self.thresholds.failure_ratio_warning:
            alerts.append({
                "alert": "HIGH_FAILURE_RATE",
                "severity": "WARNING",
                "value": round(ratio, 6),
            })
        high_latency = self._high_latency_names(snapshot)
        if high_latency:
            alerts.append({
                "alert": "HIGH_LATENCY",
                "severity": "WARNING",
                "metrics": high_latency,
            })
        return alerts

    def generate_report(self) -> dict[str, Any]:
        metrics = self.collect_metrics()
        return {
            "metrics": metrics,
            "health": self.evaluate_health(metrics).value,
            "alerts": self.evaluate_alerts(metrics),
        }

    @staticmethod
    def render_report(report: Mapping[str, Any]) -> str:
        return json.dumps(report, ensure_ascii=False, sort_keys=True, separators=(",", ":"))

    @staticmethod
    def _reliability(source: Mapping[str, int]) -> dict[str, int]:
        unknown = set(source) - set(RELIABILITY_METRICS)
        if unknown:
            raise ValueError("unknown reliability metric")
        result: dict[str, int] = {}
        for name in RELIABILITY_METRICS:
            value = source.get(name, 0)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError("reliability metrics must be non-negative integers")
            result[name] = value
        return result

    @classmethod
    def _supplemental_performance(
        cls, source: Mapping[str, Mapping[str, float | int]]
    ) -> dict[str, dict[str, float | int]]:
        allowed = {"context_latency", "decision_latency"}
        if set(source) - allowed:
            raise ValueError("unknown supplemental performance metric")
        return {
            name: cls._normalize_latency(source.get(name, {}))
            for name in sorted(allowed)
        }

    @staticmethod
    def _normalize_latency(source: Mapping[str, float | int]) -> dict[str, float | int]:
        count = source.get("count", 0)
        total = source.get("total_seconds", 0.0)
        maximum = source.get("max_seconds", 0.0)
        if (
            isinstance(count, bool) or not isinstance(count, int) or count < 0
            or isinstance(total, bool) or not isinstance(total, (int, float)) or total < 0
            or isinstance(maximum, bool) or not isinstance(maximum, (int, float)) or maximum < 0
        ):
            raise ValueError("invalid latency metric")
        total_float = float(total)
        return {
            "count": count,
            "total_seconds": round(total_float, 6),
            "average_seconds": round(total_float / count, 6) if count else 0.0,
            "max_seconds": round(float(maximum), 6),
        }

    @staticmethod
    def _validated_snapshot(metrics: Mapping[str, Any]) -> Mapping[str, Any]:
        if set(metrics) != {"memory_operations", "reliability", "performance"}:
            raise ValueError("invalid observability snapshot")
        return metrics

    @staticmethod
    def _failure_ratio(metrics: Mapping[str, Any]) -> float:
        operations = metrics["memory_operations"]
        success = operations["memory_write_success"]
        failures = operations["memory_write_failure"] + operations["validation_failed"]
        total = success + failures
        return failures / total if total else 0.0

    def _high_latency_names(self, metrics: Mapping[str, Any]) -> list[str]:
        return [
            name
            for name in PERFORMANCE_METRICS
            if metrics["performance"][name]["average_seconds"] > getattr(self.thresholds, name)
        ]
