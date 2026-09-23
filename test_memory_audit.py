from __future__ import annotations

from pathlib import Path

import pytest

from app import MemoryStore
from memory_action import ActionService
from memory_audit import AuditEventType, AuditMetrics, MemoryAuditStore
from memory_proposal import SemanticProposalService


def candidate(value: str, *, attribute: str = "favorite_drink"):
    return {
        "operation": "set", "subject": "user", "attribute": attribute, "value": value,
        "confidence": 1.0, "reason": "explicit preference",
        "valid_time": {"from": None, "to": None},
    }


def setup(db_dir: Path):
    store = MemoryStore(db_dir / "memory-test.db")
    store.create_session("user1", "s1")
    store.create_session("user2", "s1")
    audit = MemoryAuditStore(db_dir / "audit-test.db")
    metrics = AuditMetrics()
    proposals = SemanticProposalService(store=store, audit_store=audit, metrics=metrics)
    return store, audit, metrics, proposals, ActionService(proposals=proposals)


def current(store: MemoryStore, user_id: str):
    snapshot = store.get_typed_protocol_snapshot(user_id, "s1")
    rows = [item for item in snapshot["current"] if item.get("semantic_key") == "user.favorite_drink"]
    return None if not rows else rows[0]["state"]["value"]


def propose(action: ActionService, value: str):
    return action.execute_task(
        user_id="user1", session_id="s1", task=f"我喜歡{value}",
        selected_tool="save_user_preference", candidate_change=candidate(value),
    )["proposal"]


def event_types(audit: MemoryAuditStore, user_id="user1"):
    return [event.event_type for event in audit.list_events(user_id=user_id)]


def test_a_proposal_creation_is_audited(tmp_path):
    store, audit, metrics, proposals, action = setup(tmp_path)
    proposal = propose(action, "紅茶")
    events = audit.list_events(user_id="user1")
    assert events[-1].event_type is AuditEventType.PROPOSAL_CREATED
    assert events[-1].entity_id == proposal["proposal_id"]
    assert current(store, "user1") is None
    assert metrics.snapshot()["counters"]["proposal_created"] == 1


def test_b_confirm_records_proposal_and_memory_commit(tmp_path):
    store, audit, metrics, proposals, action = setup(tmp_path)
    proposal = propose(action, "紅茶")
    proposals.confirm_proposal(user_id="user1", session_id="s1", proposal_id=proposal["proposal_id"])
    assert event_types(audit)[-2:] == [AuditEventType.PROPOSAL_CONFIRMED, AuditEventType.MEMORY_CREATED]
    assert current(store, "user1") == "紅茶"
    counters = metrics.snapshot()["counters"]
    assert counters["proposal_confirmed"] == counters["memory_write_success"] == 1


def test_c_reject_audit_and_no_mutation(tmp_path):
    store, audit, metrics, proposals, action = setup(tmp_path)
    proposal = propose(action, "紅茶")
    proposals.reject_proposal(user_id="user1", session_id="s1", proposal_id=proposal["proposal_id"])
    assert event_types(audit)[-1] is AuditEventType.PROPOSAL_REJECTED
    assert current(store, "user1") is None
    assert metrics.snapshot()["counters"]["proposal_rejected"] == 1


def test_d_validation_failure_is_audited_without_raw_secret(tmp_path):
    store, audit, metrics, proposals, action = setup(tmp_path)
    with pytest.raises(ValueError, match="candidate rejected"):
        action.execute_task(
            user_id="user1", session_id="s1", task="請記住我的 API key",
            selected_tool="save_user_preference", candidate_change=candidate("xxxxx", attribute="api_key"),
        )
    events = audit.list_events(user_id="user1")
    assert [event.event_type for event in events] == [AuditEventType.VALIDATION_FAILED, AuditEventType.MEMORY_REJECTED]
    serialized = repr(events)
    assert "xxxxx" not in serialized and "請記住" not in serialized
    assert current(store, "user1") is None
    assert metrics.snapshot()["counters"]["validation_failed"] == 1


def test_e_commit_failure_is_observable_and_memory_unchanged(tmp_path, monkeypatch):
    store, audit, metrics, proposals, action = setup(tmp_path)
    proposal = propose(action, "紅茶")
    monkeypatch.setattr(store, "confirm_proposal", lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("forced")))
    with pytest.raises(RuntimeError, match="forced"):
        proposals.confirm_proposal(user_id="user1", session_id="s1", proposal_id=proposal["proposal_id"])
    assert event_types(audit)[-1] is AuditEventType.MEMORY_REJECTED
    assert audit.list_events(user_id="user1")[-1].status == "COMMIT_FAILED"
    assert current(store, "user1") is None
    assert metrics.snapshot()["counters"]["memory_write_failure"] == 1


def test_f_audit_queries_are_user_isolated(tmp_path):
    store, audit, metrics, proposals, action = setup(tmp_path)
    propose(action, "紅茶")
    assert len(audit.list_events(user_id="user1")) == 1
    assert audit.list_events(user_id="user2") == []


def test_expiration_and_latency_metrics(tmp_path):
    store, audit, metrics, proposals, action = setup(tmp_path)
    proposal = propose(action, "紅茶")
    proposals.expire_proposal(user_id="user1", session_id="s1", proposal_id=proposal["proposal_id"])
    snapshot = metrics.snapshot()
    assert event_types(audit)[-1] is AuditEventType.PROPOSAL_EXPIRED
    assert snapshot["counters"]["proposal_expired"] == 1
    assert snapshot["latencies"]["validation_latency"]["count"] == 1
    assert set(snapshot["latencies"]) == {"extraction_latency", "validation_latency", "commit_latency"}


def test_manual_audit_trail(tmp_path):
    store, audit, metrics, proposals, action = setup(tmp_path)
    first = propose(action, "紅茶")
    proposals.confirm_proposal(user_id="user1", session_id="s1", proposal_id=first["proposal_id"])
    second = propose(action, "綠茶")
    proposals.reject_proposal(user_id="user1", session_id="s1", proposal_id=second["proposal_id"])
    events = audit.list_events(user_id="user1", session_id="s1")
    assert [event.event_type for event in events] == [
        AuditEventType.PROPOSAL_CREATED,
        AuditEventType.PROPOSAL_CONFIRMED,
        AuditEventType.MEMORY_CREATED,
        AuditEventType.PROPOSAL_CREATED,
        AuditEventType.PROPOSAL_REJECTED,
    ]
    assert all(event.user_id == "user1" and event.session_id == "s1" and event.timestamp for event in events)
    assert current(store, "user1") == "紅茶"
