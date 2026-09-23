from __future__ import annotations

from memory_audit import AuditEventType, AuditMetrics, MemoryAuditStore
from memory_observability import HealthState, ObservabilityService, ObservabilityThresholds
from memory_proposal import SemanticProposalService
from app import MemoryStore


def _metrics(*, successes=0, failures=0, validation_failures=0, latency=None):
    metrics = AuditMetrics()
    for _ in range(successes):
        metrics.increment("memory_write_success")
    for _ in range(failures):
        metrics.increment("memory_write_failure")
    for _ in range(validation_failures):
        metrics.increment("validation_failed")
    if latency is not None:
        name, value = latency
        metrics.observe_latency(name, value)
    return metrics


def test_healthy_system():
    service = ObservabilityService(audit_metrics=_metrics(successes=10))
    assert service.evaluate_health() is HealthState.HEALTHY
    assert service.evaluate_alerts() == []


def test_high_latency_is_warning():
    metrics = _metrics(successes=10, latency=("commit_latency", 0.75))
    service = ObservabilityService(audit_metrics=metrics)
    assert service.evaluate_health() is HealthState.WARNING
    assert service.evaluate_alerts() == [
        {"alert": "HIGH_LATENCY", "severity": "WARNING", "metrics": ["commit_latency"]}
    ]


def test_memory_corruption_is_critical():
    service = ObservabilityService(
        audit_metrics=_metrics(successes=1), reliability={"corruption_count": 1}
    )
    assert service.evaluate_health() is HealthState.CRITICAL
    assert service.evaluate_alerts()[0]["alert"] == "MEMORY_CORRUPTION"


def test_isolation_failure_is_critical():
    service = ObservabilityService(
        audit_metrics=_metrics(successes=1), reliability={"isolation_failure_count": 1}
    )
    assert service.evaluate_health() is HealthState.CRITICAL
    assert service.evaluate_alerts()[0]["alert"] == "USER_ISOLATION_FAILURE"


def test_high_failure_rate_is_warning():
    service = ObservabilityService(audit_metrics=_metrics(successes=7, failures=3))
    assert service.evaluate_health() is HealthState.WARNING
    assert service.evaluate_alerts() == [
        {"alert": "HIGH_FAILURE_RATE", "severity": "WARNING", "value": 0.3}
    ]


def test_report_generation_is_reproducible():
    metrics = _metrics(successes=2)
    metrics.increment("proposal_created")
    metrics.increment("proposal_confirmed")
    service = ObservabilityService(
        audit_metrics=metrics,
        performance={
            "context_latency": {"count": 2, "total_seconds": 0.02, "max_seconds": 0.015},
            "decision_latency": {"count": 1, "total_seconds": 0.2, "max_seconds": 0.2},
        },
    )
    first = service.generate_report()
    second = service.generate_report()
    assert first == second
    assert service.render_report(first) == service.render_report(second)
    assert first["health"] == "HEALTHY"


def test_manual_runtime_observability(tmp_path):
    store = MemoryStore(tmp_path / "phase4c_core.db")
    store.create_session("user1", "s1")
    audit = MemoryAuditStore(tmp_path / "phase4c_audit.db")
    metrics = AuditMetrics()
    proposals = SemanticProposalService(store=store, audit_store=audit, metrics=metrics)
    candidate = {
        "operation": "set",
        "subject": "user",
        "attribute": "favorite_drink",
        "value": "綠茶",
        "confidence": 1.0,
        "reason": "explicit current fact",
        "valid_time": {"from": None, "to": None},
        "intent": "current_fact",
    }
    proposal = proposals.create_proposal(
        user_id="user1",
        session_id="s1",
        source="phase4c_manual",
        source_text="我喜歡綠茶",
        candidate_operation=candidate,
    )
    proposals.confirm_proposal(user_id="user1", session_id="s1", proposal_id=proposal.proposal_id)

    report = ObservabilityService(audit_metrics=metrics).generate_report()
    events = audit.list_events(user_id="user1")
    assert report["health"] == "HEALTHY"
    assert report["metrics"]["memory_operations"]["memory_write_success"] == 1
    assert report["metrics"]["memory_operations"]["proposal_created"] == 1
    assert report["metrics"]["memory_operations"]["proposal_confirmed"] == 1
    assert sum(event.event_type is AuditEventType.PROPOSAL_CREATED for event in events) == 1
    assert sum(event.event_type is AuditEventType.PROPOSAL_CONFIRMED for event in events) == 1
    assert report["alerts"] == []


def test_repeated_rollbacks_become_critical():
    service = ObservabilityService(
        audit_metrics=_metrics(),
        reliability={"rollback_count": 10},
        thresholds=ObservabilityThresholds(rollback_warning=3, rollback_critical=10),
    )
    assert service.evaluate_health() is HealthState.CRITICAL
    assert service.evaluate_alerts()[0]["alert"] == "REPEATED_ROLLBACK_FAILURE"
