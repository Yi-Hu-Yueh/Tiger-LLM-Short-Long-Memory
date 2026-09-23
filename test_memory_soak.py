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
from memory_soak import MemorySoakRunner, SoakOutcome, SoakScenario


def _candidate(value, *, operation="set"):
    return {
        "operation": operation,
        "subject": "user",
        "attribute": "favorite_drink",
        "value": value,
        "confidence": 1.0,
        "reason": "explicit current fact",
        "valid_time": {"from": None, "to": None},
        "intent": "correction" if operation == "correct" else "current_fact",
    }


class SoakHarness:
    def __init__(self, path):
        path.mkdir(parents=True, exist_ok=True)
        self.core_path = path / "phase4br_core.db"
        self.audit_path = path / "phase4br_audit.db"
        self.store = MemoryStore(self.core_path)
        for user in ("user1", "user2"):
            for session in ("s1", "s2", "s3"):
                self.store.create_session(user, session)
        self.audit = MemoryAuditStore(self.audit_path)
        self.proposals = SemanticProposalService(
            store=self.store, audit_store=self.audit, metrics=AuditMetrics()
        )
        self.actions = ActionService(proposals=self.proposals)
        self.recovery = MemoryRecoveryService(
            core_db=self.core_path,
            audit_db=self.audit_path,
            backup_dir=path / "recovery",
        )

    def propose(self, user, value, *, session="s1", operation="set"):
        return self.proposals.create_proposal(
            user_id=user,
            session_id=session,
            source="phase4br_soak",
            source_text="explicit favorite drink assertion",
            candidate_operation=_candidate(value, operation=operation),
        )

    def confirm(self, user, proposal, *, session="s1"):
        return self.proposals.confirm_proposal(
            user_id=user, session_id=session, proposal_id=proposal.proposal_id
        )

    def current(self, user, *, session="s1"):
        snapshot = self.store.get_typed_protocol_snapshot(user, session)
        matches = [item for item in snapshot["current"] if item["semantic_key"] == "user.favorite_drink"]
        return None if not matches else matches[0]


def _scenarios(base_path):
    def single_user_1000(metrics):
        h = SoakHarness(base_path / "single")
        expected = None
        confirmed = 0
        for index in range(200):
            operation = "correct" if index and index % 7 == 0 else "set"
            proposal = metrics.measure(
                "proposal", lambda i=index, op=operation: h.propose("user1", f"偏好{i}", operation=op)
            )
            if index % 10 == 8:
                metrics.measure(
                    "write",
                    lambda p=proposal: h.proposals.reject_proposal(
                        user_id="user1", session_id="s1", proposal_id=p.proposal_id
                    ),
                )
            elif index % 10 == 9:
                metrics.measure(
                    "write",
                    lambda p=proposal: h.proposals.cancel_proposal(
                        user_id="user1", session_id="s1", proposal_id=p.proposal_id
                    ),
                )
            else:
                metrics.measure("confirm", lambda p=proposal: h.confirm("user1", p))
                expected = f"偏好{index}"
                confirmed += 1
            metrics.measure("read", lambda: h.store.get_typed_protocol_snapshot("user1", "s1"))
            metrics.measure("read", lambda: h.store.get_history("user1"))
            metrics.measure("read", lambda: h.audit.list_events(user_id="user1"))
        snapshot = h.store.get_typed_protocol_snapshot("user1", "s1")
        current = h.current("user1")
        valid = h.recovery.verify_integrity()["valid"]
        passed = (
            current is not None
            and current["state"] == {"value": expected}
            and snapshot["revision"] == confirmed
            and len(snapshot["history"]) == 10
            and valid
        )
        if not passed:
            metrics.increment_integrity("corruption_count")
        return SoakOutcome(passed, "single_user_1000")

    def two_user_500_each(metrics):
        h = SoakHarness(base_path / "two_user")
        expected = {}
        confirmed = {"user1": 0, "user2": 0}
        for user in ("user1", "user2"):
            for index in range(100):
                proposal = metrics.measure(
                    "proposal", lambda u=user, i=index: h.propose(u, f"{u}-偏好{i}")
                )
                if index % 5 == 4:
                    metrics.measure(
                        "write",
                        lambda u=user, p=proposal: h.proposals.reject_proposal(
                            user_id=u, session_id="s1", proposal_id=p.proposal_id
                        ),
                    )
                else:
                    metrics.measure("confirm", lambda u=user, p=proposal: h.confirm(u, p))
                    expected[user] = f"{user}-偏好{index}"
                    confirmed[user] += 1
                metrics.measure("read", lambda u=user: h.store.get_typed_protocol_snapshot(u, "s1"))
                metrics.measure("read", lambda u=user: h.store.get_history(u))
                metrics.measure("read", lambda u=user: h.audit.list_events(user_id=u))
        first = h.current("user1")
        second = h.current("user2")
        first_audit = h.audit.list_events(user_id="user1")
        second_audit = h.audit.list_events(user_id="user2")
        isolated = (
            first is not None and second is not None
            and first["state"] == {"value": expected["user1"]}
            and second["state"] == {"value": expected["user2"]}
            and first["memory_id"] != second["memory_id"]
            and all(event.user_id == "user1" for event in first_audit)
            and all(event.user_id == "user2" for event in second_audit)
            and h.store.get_memory_snapshot("user1")["revision"] == confirmed["user1"]
            and h.store.get_memory_snapshot("user2")["revision"] == confirmed["user2"]
            and h.recovery.verify_integrity()["valid"]
        )
        if not isolated:
            metrics.increment_integrity("isolation_failures")
        return SoakOutcome(isolated, "two_user_500_each")

    def concurrent_lifecycle(metrics):
        h = SoakHarness(base_path / "concurrent")
        initial = metrics.measure("proposal", lambda: h.propose("user1", "基準"))
        metrics.measure("confirm", lambda: h.confirm("user1", initial))
        barrier = threading.Barrier(2)

        def create(session, value):
            barrier.wait()
            return metrics.measure("proposal", lambda: h.propose("user1", value, session=session))

        with ThreadPoolExecutor(max_workers=2) as pool:
            first_future = pool.submit(create, "s1", "紅茶")
            second_future = pool.submit(create, "s2", "烏龍茶")
            first, second = first_future.result(), second_future.result()
        metrics.measure("confirm", lambda: h.confirm("user1", first, session="s1"))
        stale = metrics.expected_failure(
            "confirm", lambda: h.confirm("user1", second, session="s2")
        )
        if isinstance(stale, (StaleProposalError, ValueError, AppError)):
            metrics.increment_integrity("stale_conflicts")

        duplicate = metrics.measure("proposal", lambda: h.propose("user1", "綠茶", session="s3"))
        revision_before = h.store.get_memory_snapshot("user1")["revision"]
        barrier2 = threading.Barrier(2)

        def confirm_duplicate(_):
            barrier2.wait()
            def attempt():
                try:
                    h.confirm("user1", duplicate, session="s3")
                    return "ok"
                except (ValueError, AppError, sqlite3.DatabaseError):
                    return "safe"
            return metrics.measure("confirm", attempt)

        with ThreadPoolExecutor(max_workers=2) as pool:
            outcomes = list(pool.map(confirm_duplicate, range(2)))
        revision_after = h.store.get_memory_snapshot("user1")["revision"]
        confirmed_events = [
            event for event in h.audit.list_events(user_id="user1")
            if event.event_type is AuditEventType.PROPOSAL_CONFIRMED
            and event.entity_id == duplicate.proposal_id
        ]
        passed = (
            stale is not None
            and revision_after == revision_before + 1
            and len(confirmed_events) == 1
            and outcomes.count("ok") >= 1
            and h.current("user1")["state"] == {"value": "綠茶"}
            and h.recovery.verify_integrity()["valid"]
        )
        if not passed:
            metrics.increment_integrity("corruption_count")
        return SoakOutcome(passed, "concurrent_proposal_lifecycle")

    def failure_injection(metrics):
        h = SoakHarness(base_path / "failures")
        initial = metrics.measure("proposal", lambda: h.propose("user1", "綠茶"))
        metrics.measure("confirm", lambda: h.confirm("user1", initial))
        baseline = h.store.get_typed_protocol_snapshot("user1", "s1")

        commit_candidate = metrics.measure("proposal", lambda: h.propose("user1", "紅茶"))
        original_confirm = h.store.confirm_proposal
        h.store.confirm_proposal = lambda *args, **kwargs: (_ for _ in ()).throw(
            sqlite3.OperationalError("injected_commit_failure")
        )
        try:
            commit_error = metrics.expected_failure("confirm", lambda: h.confirm("user1", commit_candidate))
        finally:
            h.store.confirm_proposal = original_confirm
        commit_safe = h.store.get_typed_protocol_snapshot("user1", "s1")["current"] == baseline["current"]
        if commit_error is not None and commit_safe:
            metrics.increment_integrity("rollback_count")
        metrics.measure(
            "write",
            lambda: h.proposals.cancel_proposal(
                user_id="user1", session_id="s1", proposal_id=commit_candidate.proposal_id
            ),
        )

        original_proposal = h.store.commit_semantic_proposal_turn
        h.store.commit_semantic_proposal_turn = lambda *args, **kwargs: (_ for _ in ()).throw(
            sqlite3.OperationalError("injected_proposal_failure")
        )
        try:
            proposal_error = metrics.expected_failure("proposal", lambda: h.propose("user1", "咖啡"))
        finally:
            h.store.commit_semantic_proposal_turn = original_proposal
        proposal_safe = h.store.get_pending_proposal("user1", "s1") is None
        if proposal_error is not None and proposal_safe:
            metrics.increment_integrity("rollback_count")

        audit_candidate = metrics.measure("proposal", lambda: h.propose("user1", "紅茶"))
        original_audit = h.audit.record
        h.audit.record = lambda **kwargs: (_ for _ in ()).throw(
            sqlite3.OperationalError("injected_audit_failure")
        )
        try:
            audit_error = metrics.expected_failure("confirm", lambda: h.confirm("user1", audit_candidate))
        finally:
            h.audit.record = original_audit
        audit_safe = (
            audit_error is not None
            and h.current("user1")["state"] == {"value": "紅茶"}
            and h.recovery.verify_integrity()["valid"]
        )
        failure_audited = any(
            event.event_type is AuditEventType.MEMORY_REJECTED
            and event.status == "COMMIT_FAILED"
            for event in h.audit.list_events(user_id="user1")
        )
        passed = commit_safe and proposal_safe and audit_safe and failure_audited
        if not passed:
            metrics.increment_integrity("corruption_count")
        return SoakOutcome(passed, "failure_injection")

    return [
        SoakScenario("single_user_1000", single_user_1000),
        SoakScenario("two_user_500_each", two_user_500_each),
        SoakScenario("concurrent_lifecycle", concurrent_lifecycle),
        SoakScenario("failure_injection", failure_injection),
    ]


def test_phase_4br_soak(tmp_path):
    runner = MemorySoakRunner()
    report = runner.run(_scenarios(tmp_path))
    assert [item["result"] for item in report["scenarios"]] == ["PASS"] * 4
    assert report["operations"] == {"total": 2017, "successful": 2013, "failed": 4}
    assert report["integrity"]["corruption_count"] == 0
    assert report["integrity"]["isolation_failures"] == 0
    assert report["integrity"]["stale_conflicts"] == 1
    assert report["integrity"]["rollback_count"] == 2
    assert report["resource"]["resource_warning_count"] == 0
    assert report["resource"]["cleanup_status"] == "PASS"
    assert report["overall"] == "PASS"
    assert runner.render_report(report) == runner.render_report(report)


def test_manual_approved_scope_runtime(tmp_path):
    h = SoakHarness(tmp_path)
    first = h.propose("user1", "綠茶")
    h.confirm("user1", first)
    second = h.propose("user1", "紅茶")
    h.confirm("user1", second)
    user1_result = h.actions.execute_task(
        user_id="user1", session_id="s1", task="推薦飲料", selected_tool="recommend_drink"
    )
    user2_result = h.actions.execute_task(
        user_id="user2", session_id="s1", task="推薦飲料", selected_tool="recommend_drink"
    )
    assert h.current("user1")["state"] == {"value": "紅茶"}
    assert h.current("user2") is None
    assert user1_result["tool_result"]["value"] == "紅茶"
    assert user2_result["tool_result"]["value"] == "一般飲料建議"
    assert all(event.user_id == "user1" for event in h.audit.list_events(user_id="user1"))
    assert h.audit.list_events(user_id="user2") == []


def test_soak_runner_reports_failure():
    report = MemorySoakRunner().run([SoakScenario("failed", lambda metrics: False)])
    assert report["overall"] == "FAIL"
    assert report["scenarios"][0]["result"] == "FAIL"
