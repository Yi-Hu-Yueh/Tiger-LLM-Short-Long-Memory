from __future__ import annotations

from pathlib import Path
import sqlite3

import pytest

from app import MemoryStore
from memory_action import ActionService
from memory_audit import AuditEventType, AuditMetrics, MemoryAuditStore
from memory_proposal import SemanticProposalService
from memory_recovery import MemoryRecoveryService


def candidate(value: str):
    return {
        "operation": "set", "subject": "user", "attribute": "favorite_drink", "value": value,
        "confidence": 1.0, "reason": "explicit preference",
        "valid_time": {"from": None, "to": None},
    }


def setup(root: Path):
    core_path = root / "recovery-test-core.db"
    audit_path = root / "recovery-test-audit.db"
    store = MemoryStore(core_path)
    store.create_session("user1", "s1")
    store.create_session("user2", "s1")
    audit = MemoryAuditStore(audit_path)
    metrics = AuditMetrics()
    proposals = SemanticProposalService(store=store, audit_store=audit, metrics=metrics)
    action = ActionService(proposals=proposals)
    recovery = MemoryRecoveryService(core_db=core_path, audit_db=audit_path, backup_dir=root / "recovery-points")
    return store, audit, proposals, action, recovery


def propose(action: ActionService, value: str, *, user_id="user1"):
    return action.execute_task(
        user_id=user_id, session_id="s1", task=f"我喜歡{value}",
        selected_tool="save_user_preference", candidate_change=candidate(value),
    )["proposal"]


def confirm(proposals: SemanticProposalService, proposal, *, user_id="user1"):
    return proposals.confirm_proposal(user_id=user_id, session_id="s1", proposal_id=proposal["proposal_id"])


def current(store: MemoryStore, user_id="user1"):
    snapshot = store.get_typed_protocol_snapshot(user_id, "s1")
    rows = [item for item in snapshot["current"] if item.get("semantic_key") == "user.favorite_drink"]
    return None if not rows else rows[0]["state"]["value"]


def establish(proposals, action, value="茶", *, user_id="user1"):
    proposal = propose(action, value, user_id=user_id)
    confirm(proposals, proposal, user_id=user_id)


def test_a_backup_creates_recovery_point(tmp_path):
    store, audit, proposals, action, recovery = setup(tmp_path)
    establish(proposals, action)
    point = recovery.create_backup()
    assert point in recovery.list_recovery_points()
    assert recovery.verify_integrity(point.recovery_id)["valid"]
    assert point.revisions == (("user1", 1), ("user2", 0))


def test_b_restore_recovers_damaged_current(tmp_path):
    store, audit, proposals, action, recovery = setup(tmp_path)
    establish(proposals, action, "茶")
    point = recovery.create_backup()
    with sqlite3.connect(store.path) as conn:
        conn.execute("DELETE FROM memories WHERE user_id='user1'")
        conn.commit()
    assert current(store) is None
    recovery.restore_backup(point.recovery_id)
    assert current(store) == "茶"
    assert recovery.verify_integrity()["valid"]


def test_c_failed_commit_is_audited_and_recoverable(tmp_path, monkeypatch):
    store, audit, proposals, action, recovery = setup(tmp_path)
    proposal = propose(action, "茶")
    monkeypatch.setattr(store, "confirm_proposal", lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("forced")))
    with pytest.raises(RuntimeError, match="forced"):
        confirm(proposals, proposal)
    assert current(store) is None
    assert audit.list_events(user_id="user1")[-1].event_type is AuditEventType.MEMORY_REJECTED
    point = recovery.create_backup()
    assert recovery.verify_integrity(point.recovery_id)["valid"]


def test_d_corrupted_backup_is_rejected_without_restore(tmp_path):
    store, audit, proposals, action, recovery = setup(tmp_path)
    establish(proposals, action, "茶")
    point = recovery.create_backup()
    core_backup = (tmp_path / "recovery-points" / point.core_backup)
    with core_backup.open("ab") as handle:
        handle.write(b"corrupt")
    assert not recovery.verify_integrity(point.recovery_id)["valid"]
    with pytest.raises(ValueError, match="integrity check failed"):
        recovery.restore_backup(point.recovery_id)
    assert current(store) == "茶"


def test_e_pending_proposal_survives_restore(tmp_path):
    store, audit, proposals, action, recovery = setup(tmp_path)
    proposal = propose(action, "茶")
    point = recovery.create_backup()
    proposals.reject_proposal(user_id="user1", session_id="s1", proposal_id=proposal["proposal_id"])
    assert store.get_pending_proposal("user1", "s1") is None
    recovery.restore_backup(point.recovery_id)
    restored = store.get_pending_proposal("user1", "s1")
    assert restored is not None and restored["proposal_id"] == proposal["proposal_id"]
    assert current(store) is None


def test_f_audit_ordering_survives_restore(tmp_path):
    store, audit, proposals, action, recovery = setup(tmp_path)
    establish(proposals, action, "茶")
    point = recovery.create_backup()
    before = [event.audit_id for event in audit.list_events(user_id="user1")]
    second = propose(action, "咖啡")
    proposals.reject_proposal(user_id="user1", session_id="s1", proposal_id=second["proposal_id"])
    recovery.restore_backup(point.recovery_id)
    after = [event.audit_id for event in audit.list_events(user_id="user1")]
    assert after == before
    assert recovery.verify_integrity()["audit_sequence"] == point.audit_sequence


def test_g_user_isolation_survives_restore(tmp_path):
    store, audit, proposals, action, recovery = setup(tmp_path)
    establish(proposals, action, "茶", user_id="user1")
    establish(proposals, action, "咖啡", user_id="user2")
    point = recovery.create_backup()
    recovery.restore_backup(point.recovery_id)
    assert current(store, "user1") == "茶"
    assert current(store, "user2") == "咖啡"
    assert all(event.user_id == "user1" for event in audit.list_events(user_id="user1"))
    assert all(event.user_id == "user2" for event in audit.list_events(user_id="user2"))


def test_manual_recovery_drill(tmp_path):
    store, audit, proposals, action, recovery = setup(tmp_path)
    establish(proposals, action, "茶")
    point = recovery.create_backup()
    audit_before = len(audit.list_events(user_id="user1"))
    with sqlite3.connect(store.path) as conn:
        conn.execute("DELETE FROM memories WHERE user_id='user1'")
        conn.commit()
    recovery.restore_backup(point.recovery_id)
    assert current(store) == "茶"
    assert len(audit.list_events(user_id="user1")) == audit_before
    assert recovery.verify_integrity()["valid"]
