from __future__ import annotations

from pathlib import Path
import sqlite3

import pytest

from app import MemoryStore, SCHEMA_VERSION
from memory_audit import AuditMetrics, MemoryAuditStore
from memory_operations import MemoryOperationsManager, OperationsStartupError
from memory_proposal import SemanticProposalService


def _candidate(value):
    return {
        "operation": "set",
        "subject": "user",
        "attribute": "favorite_drink",
        "value": value,
        "confidence": 1.0,
        "reason": "explicit current fact",
        "valid_time": {"from": None, "to": None},
        "intent": "current_fact",
    }


def _prepared(tmp_path, *, marker="test"):
    core = tmp_path / "operations_core.db"
    audit = tmp_path / "operations_audit.db"
    MemoryStore(core)
    MemoryAuditStore(audit)
    environment_marker = tmp_path / ".memory-environment"
    environment_marker.write_text(marker, encoding="utf-8")
    manager = MemoryOperationsManager(
        core_db=core,
        audit_db=audit,
        environment="test",
        environment_marker=environment_marker,
    )
    return manager, core, audit, environment_marker


def test_valid_startup_and_user_scope(tmp_path):
    manager, _, _, _ = _prepared(tmp_path)
    runtime = manager.initialize_runtime()
    report = manager.generate_startup_report()
    assert runtime.store.get_memory_snapshot("user1")["current"] == []
    assert report["startup_ready"] is True
    assert report["runtime_state"] == "RUNNING"
    assert report["storage"]["schema_version"] == SCHEMA_VERSION
    assert report["storage"]["user_scope_valid"] is True
    assert report["storage"]["proposal_storage_available"] is True
    assert report["storage"]["audit_storage_available"] is True


def test_missing_database_fails_closed_without_creation(tmp_path):
    marker = tmp_path / ".memory-environment"
    marker.write_text("test", encoding="utf-8")
    core = tmp_path / "missing_core.db"
    audit = tmp_path / "missing_audit.db"
    manager = MemoryOperationsManager(
        core_db=core, audit_db=audit, environment="test", environment_marker=marker
    )
    with pytest.raises(OperationsStartupError):
        manager.initialize_runtime()
    assert not core.exists() and not audit.exists()
    assert manager.generate_startup_report()["startup_ready"] is False


def test_corrupted_sqlite_fails_closed(tmp_path):
    manager, core, _, _ = _prepared(tmp_path)
    core.write_bytes(b"not-a-sqlite-database")
    with pytest.raises(OperationsStartupError):
        manager.initialize_runtime()
    assert manager.generate_startup_report()["storage"]["valid"] is False


def test_unsupported_schema_and_corrupted_metadata_block_startup(tmp_path):
    manager, core, _, _ = _prepared(tmp_path)
    with sqlite3.connect(core) as conn:
        conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION + 1}")
    with pytest.raises(OperationsStartupError):
        manager.initialize_runtime()
    assert "schema_version_unsupported" in manager.validate_storage()["reasons"]

    with sqlite3.connect(core) as conn:
        conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
        conn.execute("DROP TABLE pending_memory_proposals")
    with pytest.raises(OperationsStartupError):
        manager.initialize_runtime()
    assert "core_schema_incomplete" in manager.validate_storage()["reasons"]


def test_shutdown_cleanup_is_idempotent(tmp_path):
    manager, _, _, _ = _prepared(tmp_path)
    manager.initialize_runtime()
    first = manager.shutdown_runtime()
    second = manager.shutdown_runtime()
    assert first == second == {
        "status": "STOPPED",
        "transactions_clear": True,
        "audit_flushed": True,
        "cleanup": True,
    }
    assert manager.generate_startup_report()["runtime_state"] == "STOPPED"


def test_environment_mismatch_and_protected_name_block_start(tmp_path):
    manager, _, _, marker = _prepared(tmp_path, marker="development")
    with pytest.raises(OperationsStartupError):
        manager.initialize_runtime()
    assert "environment_marker_mismatch" in manager.validate_environment()["reasons"]

    protected = tmp_path / "memory.db"
    safe_audit = tmp_path / "audit_for_protected_name.db"
    marker.write_text("test", encoding="utf-8")
    blocked = MemoryOperationsManager(
        core_db=protected,
        audit_db=safe_audit,
        environment="test",
        environment_marker=marker,
    )
    assert "protected_database_in_nonproduction" in blocked.validate_environment()["reasons"]


def test_manual_lifecycle_restart_preserves_memory_and_audit(tmp_path):
    manager, core, audit_path, marker = _prepared(tmp_path)
    runtime = manager.initialize_runtime()
    runtime.store.create_session("user1", "s1")
    metrics = AuditMetrics()
    proposals = SemanticProposalService(
        store=runtime.store, audit_store=runtime.audit, metrics=metrics
    )
    proposal = proposals.create_proposal(
        user_id="user1", session_id="s1", source="phase4e_manual",
        source_text="我喜歡紅茶", candidate_operation=_candidate("紅茶"),
    )
    proposals.confirm_proposal(
        user_id="user1", session_id="s1", proposal_id=proposal.proposal_id
    )
    report = manager.generate_startup_report()
    assert report["startup_ready"] is True
    assert manager.shutdown_runtime()["cleanup"] is True

    restarted = MemoryOperationsManager(
        core_db=core, audit_db=audit_path, environment="test", environment_marker=marker
    )
    handles = restarted.initialize_runtime()
    snapshot = handles.store.get_typed_protocol_snapshot("user1", "s1")
    assert len(snapshot["current"]) == 1
    assert snapshot["current"][0]["state"] == {"value": "紅茶"}
    assert handles.audit.list_events(user_id="user1")
    assert restarted.generate_startup_report()["startup_ready"] is True
    assert restarted.shutdown_runtime()["cleanup"] is True
