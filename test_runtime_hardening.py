from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import sqlite3
import threading

import pytest

from app import AppError, MemoryStore
from memory_action import ActionService
from memory_audit import AuditEventType, AuditMetrics, MemoryAuditStore
from memory_proposal import SemanticProposalService, StaleProposalError
from memory_recovery import MemoryRecoveryService
from memory_runtime_hardening import HardeningOutcome, HardeningScenario, RuntimeHardeningRunner


def _candidate(value: str, *, operation="set", attribute="favorite_drink"):
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


class HardeningHarness:
    def __init__(self, path):
        path.mkdir(parents=True, exist_ok=True)
        self.store = MemoryStore(path / "phase4a_core.db")
        for user in ("user1", "user2"):
            for session in ("s1", "s2", "s3"):
                self.store.create_session(user, session)
        self.audit = MemoryAuditStore(path / "phase4a_audit.db")
        self.metrics = AuditMetrics()
        self.proposals = SemanticProposalService(
            store=self.store, audit_store=self.audit, metrics=self.metrics
        )
        self.actions = ActionService(proposals=self.proposals)
        self.recovery = MemoryRecoveryService(
            core_db=path / "phase4a_core.db",
            audit_db=path / "phase4a_audit.db",
            backup_dir=path / "recovery",
        )

    def propose(self, value, *, session="s1", operation="set", attribute="favorite_drink"):
        return self.proposals.create_proposal(
            user_id="user1",
            session_id=session,
            source="phase4a_hardening",
            source_text=f"explicit {attribute} assertion",
            candidate_operation=_candidate(value, operation=operation, attribute=attribute),
        )

    def confirm(self, proposal, *, session="s1"):
        return self.proposals.confirm_proposal(
            user_id="user1", session_id=session, proposal_id=proposal.proposal_id
        )

    def set_value(self, value, *, session="s1", operation="set", attribute="favorite_drink"):
        proposal = self.propose(value, session=session, operation=operation, attribute=attribute)
        self.confirm(proposal, session=session)
        return proposal

    def current(self, *, session="s1", key="user.favorite_drink"):
        snapshot = self.store.get_typed_protocol_snapshot("user1", session)
        matches = [item for item in snapshot["current"] if item["semantic_key"] == key]
        return None if not matches else matches[0]


def _hardening_scenarios(base_path):
    def concurrent_reads():
        h = HardeningHarness(base_path / "reads")
        h.set_value("綠茶")
        expected = h.store.get_typed_protocol_snapshot("user1", "s1")

        def read_many(_):
            return [h.store.get_typed_protocol_snapshot("user1", "s1") for _ in range(20)]

        with ThreadPoolExecutor(max_workers=8) as pool:
            batches = list(pool.map(read_many, range(8)))
        passed = all(item == expected for batch in batches for item in batch)
        return HardeningOutcome(passed, operations=160)

    def concurrent_proposals():
        h = HardeningHarness(base_path / "proposals")
        h.set_value("高雄", session="s3", attribute="city")
        barrier = threading.Barrier(2)

        def propose(session, value):
            barrier.wait()
            return h.propose(value, session=session, attribute="city")

        with ThreadPoolExecutor(max_workers=2) as pool:
            first_future = pool.submit(propose, "s1", "台北")
            second_future = pool.submit(propose, "s2", "台中")
            first, second = first_future.result(), second_future.result()
        h.confirm(first, session="s1")
        stale_rejected = False
        try:
            h.confirm(second, session="s2")
        except (StaleProposalError, ValueError, AppError):
            stale_rejected = True
        current = h.current(session="s1", key="person.residence.location")
        return HardeningOutcome(
            stale_rejected and current is not None and current["state"] == {"value": "台北"},
            operations=4,
        )

    def concurrent_confirms():
        h = HardeningHarness(base_path / "confirms")
        proposal = h.propose("紅茶")
        revision_before = h.store.get_memory_snapshot("user1")["revision"]
        barrier = threading.Barrier(2)

        def confirm_once(_):
            barrier.wait()
            try:
                h.confirm(proposal)
                return "confirmed"
            except (ValueError, AppError, sqlite3.DatabaseError):
                return "safe_rejection"

        with ThreadPoolExecutor(max_workers=2) as pool:
            outcomes = list(pool.map(confirm_once, range(2)))
        revision_after = h.store.get_memory_snapshot("user1")["revision"]
        confirmed_events = [
            event for event in h.audit.list_events(user_id="user1")
            if event.event_type is AuditEventType.PROPOSAL_CONFIRMED
        ]
        passed = (
            outcomes.count("confirmed") >= 1
            and revision_after == revision_before + 1
            and len(confirmed_events) == 1
            and h.current()["state"] == {"value": "紅茶"}
        )
        return HardeningOutcome(passed, operations=2)

    def resource_cleanup():
        h = HardeningHarness(base_path / "resources")
        for _ in range(30):
            h.store.get_typed_protocol_snapshot("user1", "s1")
            h.audit.list_events(user_id="user1")
        valid = h.recovery.verify_integrity()["valid"]
        return HardeningOutcome(valid, operations=60)

    def long_run_100():
        h = HardeningHarness(base_path / "long")
        confirmed = 0
        for index in range(20):
            operation = "correct" if index and index % 3 == 0 else "set"
            proposal = h.propose(f"飲料{index}", operation=operation)
            if index % 5 == 4:
                h.proposals.reject_proposal(
                    user_id="user1", session_id="s1", proposal_id=proposal.proposal_id
                )
            else:
                h.confirm(proposal)
                confirmed += 1
            h.store.get_typed_protocol_snapshot("user1", "s1")
            h.store.get_history("user1")
            h.audit.list_events(user_id="user1")
        snapshot = h.store.get_typed_protocol_snapshot("user1", "s1")
        current = [item for item in snapshot["current"] if item["semantic_key"] == "user.favorite_drink"]
        audit_events = h.audit.list_events(user_id="user1")
        passed = (
            len(current) == 1
            and current[0]["state"] == {"value": "飲料18"}
            and snapshot["revision"] == confirmed
            and len(snapshot["history"]) == 10
            and len({event.audit_id for event in audit_events}) == len(audit_events)
            and h.recovery.verify_integrity()["valid"]
        )
        return HardeningOutcome(passed, operations=100)

    def failure_injection():
        h = HardeningHarness(base_path / "failures")
        h.set_value("綠茶")
        before = h.store.get_typed_protocol_snapshot("user1", "s1")

        commit_proposal = h.propose("紅茶")
        original_confirm = h.store.confirm_proposal
        h.store.confirm_proposal = lambda *args, **kwargs: (_ for _ in ()).throw(
            sqlite3.OperationalError("simulated_commit_failure")
        )
        try:
            with pytest.raises(sqlite3.OperationalError):
                h.confirm(commit_proposal)
        finally:
            h.store.confirm_proposal = original_confirm
        commit_safe = h.store.get_typed_protocol_snapshot("user1", "s1")["current"] == before["current"]
        h.proposals.cancel_proposal(
            user_id="user1", session_id="s1", proposal_id=commit_proposal.proposal_id
        )

        original_create = h.store.commit_semantic_proposal_turn
        h.store.commit_semantic_proposal_turn = lambda *args, **kwargs: (_ for _ in ()).throw(
            sqlite3.OperationalError("simulated_proposal_failure")
        )
        try:
            with pytest.raises(sqlite3.OperationalError):
                h.propose("烏龍茶")
        finally:
            h.store.commit_semantic_proposal_turn = original_create
        proposal_safe = h.store.get_pending_proposal("user1", "s1") is None

        audit_proposal = h.propose("紅茶")
        original_audit = h.audit.record
        h.audit.record = lambda **kwargs: (_ for _ in ()).throw(sqlite3.OperationalError("simulated_audit_failure"))
        audit_failed = False
        try:
            h.confirm(audit_proposal)
        except sqlite3.OperationalError:
            audit_failed = True
        finally:
            h.audit.record = original_audit
        audit_safe = h.current()["state"] == {"value": "紅茶"} and h.recovery.verify_integrity()["valid"]
        failure_audited = any(
            event.event_type is AuditEventType.MEMORY_REJECTED
            and event.status == "COMMIT_FAILED"
            for event in h.audit.list_events(user_id="user1")
        )
        return HardeningOutcome(
            commit_safe and proposal_safe and audit_failed and audit_safe and failure_audited,
            operations=3,
        )

    return [
        HardeningScenario("concurrent_reads", "concurrency", concurrent_reads),
        HardeningScenario("concurrent_proposals", "concurrency", concurrent_proposals),
        HardeningScenario("concurrent_confirms", "concurrency", concurrent_confirms),
        HardeningScenario("resource_cleanup", "resource_safety", resource_cleanup),
        HardeningScenario("long_run_100", "long_run", long_run_100),
        HardeningScenario("failure_injection", "failure_isolation", failure_injection),
    ]


def test_phase_4a_runtime_hardening(tmp_path):
    runner = RuntimeHardeningRunner()
    report = runner.run(_hardening_scenarios(tmp_path))
    assert report["concurrency"] == {"passed": 3, "failed": 0}
    assert report["resource_safety"] == {"passed": 1, "failed": 0}
    assert report["long_run"] == {"passed": 1, "failed": 0}
    assert report["failure_isolation"] == {"passed": 1, "failed": 0}
    assert report["resources"]["operation_count"] == 329
    assert report["resources"]["thread_delta"] == 0
    assert report["overall"] == "PASS"
    assert runner.render_report(report) == runner.render_report(report)


def test_manual_runtime_acceptance(tmp_path):
    h = HardeningHarness(tmp_path)
    h.set_value("綠茶")
    proposal = h.propose("紅茶")
    h.confirm(proposal)
    first_query = h.actions.execute_task(
        user_id="user1", session_id="s1", task="推薦飲料", selected_tool="recommend_drink"
    )
    before_failure = h.store.get_typed_protocol_snapshot("user1", "s1")

    failed = h.propose("咖啡")
    original = h.store.confirm_proposal
    h.store.confirm_proposal = lambda *args, **kwargs: (_ for _ in ()).throw(
        sqlite3.OperationalError("manual_simulated_failure")
    )
    try:
        with pytest.raises(sqlite3.OperationalError):
            h.confirm(failed)
    finally:
        h.store.confirm_proposal = original
    second_query = h.actions.execute_task(
        user_id="user1", session_id="s1", task="再次推薦飲料", selected_tool="recommend_drink"
    )
    assert first_query["tool_result"]["value"] == "紅茶"
    assert second_query["tool_result"]["value"] == "紅茶"
    assert h.store.get_typed_protocol_snapshot("user1", "s1")["current"] == before_failure["current"]
    assert h.audit.list_events(user_id="user1")
    assert h.recovery.verify_integrity()["valid"]


def test_runner_reports_scenario_exception():
    runner = RuntimeHardeningRunner()

    def broken():
        raise RuntimeError("expected")

    report = runner.run([HardeningScenario("broken", "failure_isolation", broken)])
    assert report["failure_isolation"] == {"passed": 0, "failed": 1}
    assert report["resources"]["scenario_exceptions"] == 1
    assert report["overall"] == "FAIL"
