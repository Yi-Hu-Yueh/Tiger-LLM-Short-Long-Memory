from __future__ import annotations

import hashlib

from app import MemoryStore
from memory_action import ActionService
from memory_audit import AuditMetrics, MemoryAuditStore
from memory_proposal import SemanticProposalService
from memory_recovery import MemoryRecoveryService
from memory_release import (
    GOVERNANCE_FILES,
    OPERATIONS_CHECKS,
    REGRESSION_GROUPS,
    SECURITY_CHECKS,
    ReleaseValidator,
)


def _hash(path):
    return hashlib.sha256(path.read_bytes()).hexdigest().upper()


def _validator(project_root, *, governance=None, regression=None, security=None, operations=None):
    hashes = governance or {name: _hash(project_root / name) for name in GOVERNANCE_FILES}
    return ReleaseValidator(
        project_root=project_root,
        expected_governance_hashes=hashes,
        regression_results=regression or {name: True for name in REGRESSION_GROUPS},
        security_results=security or {name: True for name in SECURITY_CHECKS},
        operations_results=operations or {name: True for name in OPERATIONS_CHECKS},
    )


def test_full_validation_passes(project_root):
    report = _validator(project_root).run_full_validation()
    assert report["release_status"] == "PASS"
    assert report["blockers"] == []
    assert report["regression"]["passed"] is True
    assert report["security"]["passed"] is True
    assert report["governance"]["passed"] is True
    assert report["operations"]["passed"] is True


def test_governance_hash_violation_fails_release(project_root):
    hashes = {name: _hash(project_root / name) for name in GOVERNANCE_FILES}
    hashes["MEMORY_SEMANTIC_CONTRACTS.md"] = "0" * 64
    report = _validator(project_root, governance=hashes).run_full_validation()
    assert report["release_status"] == "FAIL"
    assert "governance:MEMORY_SEMANTIC_CONTRACTS.md" in report["blockers"]


def test_security_regression_fails_release(project_root):
    security = {name: True for name in SECURITY_CHECKS}
    security["proposal_confirmation_required"] = False
    report = _validator(project_root, security=security).run_full_validation()
    assert report["release_status"] == "FAIL"
    assert report["blockers"] == ["security:proposal_confirmation_required"]


def test_recovery_regression_fails_release(project_root):
    regression = {name: True for name in REGRESSION_GROUPS}
    regression["recovery"] = False
    operations = {name: True for name in OPERATIONS_CHECKS}
    operations["recovery_readiness"] = False
    report = _validator(
        project_root, regression=regression, operations=operations
    ).run_full_validation()
    assert report["release_status"] == "FAIL"
    assert "regression:recovery" in report["blockers"]
    assert "operations:recovery_readiness" in report["blockers"]


def test_release_report_is_deterministic(project_root):
    validator = _validator(project_root)
    first = validator.run_full_validation()
    second = validator.run_full_validation()
    assert first == second
    assert validator.render_report(first) == validator.render_report(second)


def test_manual_release_candidate_flow(project_root, tmp_path):
    core_path = tmp_path / "phase5a_core.db"
    audit_path = tmp_path / "phase5a_audit.db"
    store = MemoryStore(core_path)
    store.create_session("user1", "s1")
    audit = MemoryAuditStore(audit_path)
    proposals = SemanticProposalService(
        store=store, audit_store=audit, metrics=AuditMetrics()
    )
    actions = ActionService(proposals=proposals)
    recovery = MemoryRecoveryService(
        core_db=core_path, audit_db=audit_path, backup_dir=tmp_path / "recovery"
    )

    def candidate(value):
        return {
            "operation": "set", "subject": "user", "attribute": "favorite_drink",
            "value": value, "confidence": 1.0, "reason": "explicit current fact",
            "valid_time": {"from": None, "to": None}, "intent": "current_fact",
        }

    green = proposals.create_proposal(
        user_id="user1", session_id="s1", source="phase5a_manual",
        source_text="我喜歡綠茶", candidate_operation=candidate("綠茶"),
    )
    proposals.confirm_proposal(user_id="user1", session_id="s1", proposal_id=green.proposal_id)
    red = proposals.create_proposal(
        user_id="user1", session_id="s1", source="phase5a_manual",
        source_text="改喜歡紅茶", candidate_operation=candidate("紅茶"),
    )
    proposals.confirm_proposal(user_id="user1", session_id="s1", proposal_id=red.proposal_id)
    answer = actions.execute_task(
        user_id="user1", session_id="s1", task="推薦飲料", selected_tool="recommend_drink"
    )
    point = recovery.create_backup()
    temporary = proposals.create_proposal(
        user_id="user1", session_id="s1", source="phase5a_manual",
        source_text="改喜歡咖啡", candidate_operation=candidate("咖啡"),
    )
    proposals.confirm_proposal(
        user_id="user1", session_id="s1", proposal_id=temporary.proposal_id
    )
    recovery.restore_backup(point.recovery_id)

    current = store.get_typed_protocol_snapshot("user1", "s1")["current"]
    integrity = recovery.verify_integrity()["valid"]
    events = audit.list_events(user_id="user1")
    report = _validator(project_root).run_full_validation()
    assert answer["tool_result"]["value"] == "紅茶"
    assert len(current) == 1 and current[0]["state"] == {"value": "紅茶"}
    assert events and integrity is True
    assert report["release_status"] == "PASS"


def pytest_generate_tests(metafunc):
    if "project_root" in metafunc.fixturenames:
        metafunc.parametrize("project_root", [__import__("pathlib").Path(__file__).resolve().parent])
