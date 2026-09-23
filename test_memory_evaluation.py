from __future__ import annotations

from contextlib import closing
import sqlite3

import pytest

from app import AppError, MemoryStore, PendingProposalRecord, utc_now
from memory_action import ActionService
from memory_audit import AuditEventType, AuditMetrics, MemoryAuditStore
from memory_evaluation import EvaluationScenario, MemoryEvaluationRunner, PERFORMANCE_METRICS
from memory_proposal import SemanticProposalService, StaleProposalError
from memory_recovery import MemoryRecoveryService
from slot_registry import get_slot


def _candidate(value: str, *, operation: str = "set", attribute: str = "favorite_drink") -> dict:
    return {
        "operation": operation,
        "subject": "user",
        "attribute": attribute,
        "value": value,
        "confidence": 1.0,
        "reason": "explicit current fact",
        "valid_time": {"from": None, "to": None},
        "intent": "correction" if operation == "correct" else "current_fact",
    }


class EvaluationHarness:
    def __init__(self, tmp_path):
        tmp_path.mkdir(parents=True, exist_ok=True)
        self.core_path = tmp_path / "phase3f_core.db"
        self.audit_path = tmp_path / "phase3f_audit.db"
        self.store = MemoryStore(self.core_path)
        for user_id in ("user1", "user2"):
            for session_id in ("s1", "s2", "s3"):
                self.store.create_session(user_id, session_id)
        self.audit = MemoryAuditStore(self.audit_path)
        self.metrics = AuditMetrics()
        self.proposals = SemanticProposalService(
            store=self.store, audit_store=self.audit, metrics=self.metrics
        )
        self.actions = ActionService(proposals=self.proposals)
        self.recovery = MemoryRecoveryService(
            core_db=self.core_path,
            audit_db=self.audit_path,
            backup_dir=tmp_path / "phase3f_recovery",
        )

    def propose(self, value, *, user="user1", session="s1", operation="set", attribute="favorite_drink"):
        return self.proposals.create_proposal(
            user_id=user,
            session_id=session,
            source="phase3f_evaluation",
            source_text=f"explicit {attribute} assertion",
            candidate_operation=_candidate(value, operation=operation, attribute=attribute),
        )

    def confirm(self, proposal, *, user="user1", session="s1"):
        return self.proposals.confirm_proposal(
            user_id=user, session_id=session, proposal_id=proposal.proposal_id
        )

    def current(self, *, user="user1", session="s1", semantic_key="user.favorite_drink"):
        snapshot = self.store.get_typed_protocol_snapshot(user, session)
        matches = [item for item in snapshot["current"] if item["semantic_key"] == semantic_key]
        return None if not matches else matches[0]

    def set_value(self, value, *, user="user1", session="s1", operation="set", attribute="favorite_drink"):
        proposal = self.propose(value, user=user, session=session, operation=operation, attribute=attribute)
        self.confirm(proposal, user=user, session=session)
        return proposal

    def forget_current(self, *, user="user1", session="s1"):
        current = self.current(user=user, session=session)
        assert current is not None
        snapshot = self.store.get_typed_protocol_snapshot(user, session)
        slot = get_slot("user.favorite_drink")
        assert slot is not None
        record = PendingProposalRecord.semantic_existing_target(
            proposal_id="forget-" + str(snapshot["revision"]),
            user_id=user,
            session_id=session,
            base_revision=int(snapshot["revision"]),
            state_type="scalar",
            operation="DELETE_MEMORY",
            arguments={},
            target_memory_id=str(current["memory_id"]),
            destructive=True,
            created_at=utc_now(),
            slot_id=slot.slot_id,
            registry_version=slot.registry_version,
            semantic_key=slot.semantic_key,
            display_label=slot.display_label,
        )
        self.store.commit_semantic_proposal_turn(
            user, session, "explicit forget request", "待確認刪除。", record, int(snapshot["revision"])
        )
        self.store.confirm_proposal(
            user, session, record.proposal_id, allow_semantic_confirmation=True
        )


def _build_scenarios(base_path, metrics: AuditMetrics):
    def harness(name):
        instance = EvaluationHarness(base_path / name)
        instance.metrics = metrics
        instance.proposals.metrics = metrics
        return instance

    def create_memory():
        h = harness("create")
        h.set_value("無糖綠茶")
        return h.current()["state"] == {"value": "無糖綠茶"}

    def update_memory():
        h = harness("update")
        h.set_value("無糖綠茶")
        h.set_value("紅茶")
        history = h.store.get_typed_protocol_snapshot("user1", "s1")["history"]
        return h.current()["state"] == {"value": "紅茶"} and any(
            item["state"] == {"value": "無糖綠茶"} for item in history
        )

    def correction():
        h = harness("correction")
        h.set_value("紅茶")
        h.set_value("烏龍茶", operation="correct")
        return h.current()["state"] == {"value": "烏龍茶"}

    def forget():
        h = harness("forget")
        h.set_value("烏龍茶")
        before_revision = h.store.get_memory_snapshot("user1")["revision"]
        h.forget_current()
        after = h.store.get_typed_protocol_snapshot("user1", "s1")
        return h.current() is None and after["history"] == [] and after["revision"] == before_revision + 1

    def proposal_confirm_idempotent():
        h = harness("confirm")
        proposal = h.propose("茶")
        before = h.store.get_memory_snapshot("user1")["revision"]
        h.confirm(proposal)
        h.confirm(proposal)
        after = h.store.get_memory_snapshot("user1")["revision"]
        return after == before + 1 and h.current()["state"] == {"value": "茶"}

    def rejection_and_sensitive_block():
        h = harness("safety")
        h.set_value("茶")
        proposal = h.propose("咖啡")
        before = h.current()["state"]
        h.proposals.reject_proposal(user_id="user1", session_id="s1", proposal_id=proposal.proposal_id)
        rejected_unchanged = h.current()["state"] == before
        try:
            h.proposals.create_proposal(
                user_id="user1",
                session_id="s1",
                source="phase3f_evaluation",
                source_text="請記住我的 API Key",
                candidate_operation=_candidate("secret", attribute="api_key"),
            )
        except ValueError:
            return rejected_unchanged and h.current()["state"] == before
        return False

    def stale_concurrent_update():
        h = harness("stale")
        h.set_value("高雄", session="s3", attribute="city")
        first = h.propose("台北", session="s1", attribute="city")
        second = h.propose("台中", session="s2", attribute="city")
        h.confirm(second, session="s2")
        try:
            h.confirm(first, session="s1")
        except (StaleProposalError, ValueError, AppError):
            city = h.current(session="s2", semantic_key="person.residence.location")
            return city is not None and city["state"] == {"value": "台中"}
        return False

    def recovery_and_rollback():
        h = harness("recovery")
        h.set_value("茶")
        point = h.recovery.create_backup()
        before = h.current()["state"]
        proposal = h.propose("失敗值")
        original = h.store.confirm_proposal
        h.store.confirm_proposal = lambda *args, **kwargs: (_ for _ in ()).throw(sqlite3.OperationalError("simulated"))
        try:
            with pytest.raises(sqlite3.OperationalError):
                h.confirm(proposal)
        finally:
            h.store.confirm_proposal = original
        rollback_ok = h.current()["state"] == before
        h.proposals.cancel_proposal(user_id="user1", session_id="s1", proposal_id=proposal.proposal_id)
        h.set_value("暫時值")
        h.recovery.restore_backup(point.recovery_id)
        return rollback_ok and h.current()["state"] == before and h.recovery.verify_integrity()["valid"]

    def user_isolation():
        h = harness("isolation")
        h.set_value("茶", user="user1", session="s1")
        h.set_value("咖啡", user="user2", session="s1")
        user1 = h.current(user="user1", session="s1")["state"]
        user2 = h.current(user="user2", session="s1")["state"]
        return user1 != user2 and user2 == {"value": "咖啡"}

    def long_conversation():
        h = harness("long")
        values = [f"偏好{i}" for i in range(12)]
        start_revision = h.store.get_memory_snapshot("user1")["revision"]
        for value in values:
            h.set_value(value, session="s3")
        snapshot = h.store.get_typed_protocol_snapshot("user1", "s3")
        active = [item for item in snapshot["current"] if item["semantic_key"] == "user.favorite_drink"]
        return (
            len(active) == 1
            and active[0]["state"] == {"value": values[-1]}
            and snapshot["revision"] == start_revision + len(values)
            and len(snapshot["history"]) == 10
        )

    return [
        EvaluationScenario("create_memory", "correctness", create_memory),
        EvaluationScenario("update_memory", "correctness", update_memory),
        EvaluationScenario("correction", "correctness", correction),
        EvaluationScenario("forget", "correctness", forget),
        EvaluationScenario("proposal_confirm", "reliability", proposal_confirm_idempotent, "commit_latency"),
        EvaluationScenario("proposal_reject_and_sensitive", "safety", rejection_and_sensitive_block),
        EvaluationScenario("stale_concurrent_update", "reliability", stale_concurrent_update),
        EvaluationScenario("recovery_restore_and_rollback", "reliability", recovery_and_rollback),
        EvaluationScenario("user_isolation", "safety", user_isolation, "context_retrieval_latency"),
        EvaluationScenario("long_conversation", "reliability", long_conversation, "decision_latency"),
    ]


def test_phase_3f_evaluation_report(tmp_path):
    metrics = AuditMetrics()
    runner = MemoryEvaluationRunner(metrics=metrics)
    report = runner.run(_build_scenarios(tmp_path, metrics))

    assert report["correctness"] == {"passed": 4, "failed": 0}
    assert report["safety"] == {"passed": 2, "failed": 0}
    assert report["reliability"] == {"passed": 4, "failed": 0}
    assert report["overall"] == "PASS"
    assert len(report["scenarios"]) == 10
    assert set(report["performance"]["metrics"]) == set(PERFORMANCE_METRICS)
    assert report["performance"]["metrics"]["validation_latency"]["count"] > 0
    assert report["performance"]["metrics"]["commit_latency"]["count"] > 0
    assert runner.render_report(report) == runner.render_report(report)


def test_manual_acceptance(tmp_path):
    h = EvaluationHarness(tmp_path)
    h.set_value("無糖綠茶")
    proposal = h.propose("紅茶")
    assert h.current()["state"] == {"value": "無糖綠茶"}
    h.confirm(proposal)

    decision = h.actions.execute_task(
        user_id="user1", session_id="s1", task="推薦飲料", selected_tool="recommend_drink"
    )
    assert decision["tool_result"]["value"] == "紅茶"
    point = h.recovery.create_backup()

    h.set_value("暫時偏好")
    h.recovery.restore_backup(point.recovery_id)
    assert h.current()["state"] == {"value": "紅茶"}
    event_types = {event.event_type for event in h.audit.list_events(user_id="user1")}
    assert AuditEventType.PROPOSAL_CONFIRMED in event_types
    assert AuditEventType.MEMORY_UPDATED in event_types
    assert h.recovery.verify_integrity()["valid"] is True


def test_evaluator_reports_failure_without_mutating_services(tmp_path):
    h = EvaluationHarness(tmp_path)
    runner = MemoryEvaluationRunner(metrics=h.metrics)
    report = runner.run([EvaluationScenario("expected_failure", "safety", lambda: False)])
    assert report["safety"] == {"passed": 0, "failed": 1}
    assert report["overall"] == "FAIL"
    assert h.store.get_memory_snapshot("user1")["current"] == []
