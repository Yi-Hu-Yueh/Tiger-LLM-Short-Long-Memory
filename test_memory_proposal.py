from __future__ import annotations

from pathlib import Path

import pytest

from app import MemoryStore
from memory_action import ActionService
from memory_proposal import ProposalStatus, SemanticProposalService


def candidate(value: str, *, attribute: str = "favorite_drink"):
    return {
        "operation": "set",
        "subject": "user",
        "attribute": attribute,
        "value": value,
        "confidence": 1.0,
        "reason": "explicit user preference",
        "valid_time": {"from": None, "to": None},
    }


def setup_service(db_path: Path):
    store = MemoryStore(db_path)
    store.create_session("user1", "s1")
    store.create_session("user2", "s1")
    proposals = SemanticProposalService(store=store)
    return store, proposals, ActionService(proposals=proposals)


def current_value(store: MemoryStore, user_id: str, session_id: str):
    snapshot = store.get_typed_protocol_snapshot(user_id, session_id)
    records = [item for item in snapshot["current"] if item.get("semantic_key") == "user.favorite_drink"]
    return None if not records else records[0]["state"]["value"]


def test_candidate_creates_pending_proposal_without_current_mutation(tmp_path):
    store, proposals, action = setup_service(tmp_path / "proposal-a.db")
    result = action.execute_task(
        user_id="user1", session_id="s1", task="我開始喜歡紅茶",
        selected_tool="save_user_preference", candidate_change=candidate("紅茶"),
    )
    assert result["review_status"] == "HUMAN_REVIEW_REQUIRED"
    assert result["memory_updated"] is False
    assert current_value(store, "user1", "s1") is None
    pending = proposals.get_pending_proposals(user_id="user1", session_id="s1")
    assert len(pending) == 1
    assert pending[0].status is ProposalStatus.PENDING_REVIEW


def test_confirm_commits_exact_proposal(tmp_path):
    store, proposals, action = setup_service(tmp_path / "proposal-b.db")
    result = action.execute_task(
        user_id="user1", session_id="s1", task="我開始喜歡紅茶",
        selected_tool="save_user_preference", candidate_change=candidate("紅茶"),
    )
    proposal_id = result["proposal"]["proposal_id"]
    confirmed = proposals.confirm_proposal(user_id="user1", session_id="s1", proposal_id=proposal_id)
    assert confirmed.status is ProposalStatus.CONFIRMED
    assert current_value(store, "user1", "s1") == "紅茶"
    assert proposals.get_pending_proposals(user_id="user1", session_id="s1") == []


def test_reject_keeps_current_unchanged(tmp_path):
    store, proposals, action = setup_service(tmp_path / "proposal-c.db")
    first = action.execute_task(
        user_id="user1", session_id="s1", task="我喜歡綠茶",
        selected_tool="save_user_preference", candidate_change=candidate("綠茶"),
    )
    proposals.confirm_proposal(user_id="user1", session_id="s1", proposal_id=first["proposal"]["proposal_id"])
    second = action.execute_task(
        user_id="user1", session_id="s1", task="我開始喜歡紅茶",
        selected_tool="save_user_preference", candidate_change=candidate("紅茶"),
    )
    rejected = proposals.reject_proposal(user_id="user1", session_id="s1", proposal_id=second["proposal"]["proposal_id"])
    assert rejected.status is ProposalStatus.REJECTED
    assert current_value(store, "user1", "s1") == "綠茶"


def test_sensitive_write_fails_closed_without_proposal(tmp_path):
    store, proposals, action = setup_service(tmp_path / "proposal-d.db")
    with pytest.raises(ValueError, match="candidate rejected"):
        action.execute_task(
            user_id="user1", session_id="s1", task="請記住我的 API key",
            selected_tool="save_user_preference", candidate_change=candidate("xxxxx", attribute="api_key"),
        )
    assert current_value(store, "user1", "s1") is None
    assert proposals.get_pending_proposals(user_id="user1", session_id="s1") == []


def test_duplicate_confirm_is_idempotent(tmp_path):
    store, proposals, action = setup_service(tmp_path / "proposal-e.db")
    result = action.execute_task(
        user_id="user1", session_id="s1", task="我開始喜歡紅茶",
        selected_tool="save_user_preference", candidate_change=candidate("紅茶"),
    )
    proposal_id = result["proposal"]["proposal_id"]
    first = proposals.confirm_proposal(user_id="user1", session_id="s1", proposal_id=proposal_id)
    revision = store.get_memory_snapshot("user1")["revision"]
    second = proposals.confirm_proposal(user_id="user1", session_id="s1", proposal_id=proposal_id)
    assert first == second
    assert store.get_memory_snapshot("user1")["revision"] == revision
    assert current_value(store, "user1", "s1") == "紅茶"


def test_proposal_user_isolation(tmp_path):
    store, proposals, action = setup_service(tmp_path / "proposal-f.db")
    result = action.execute_task(
        user_id="user1", session_id="s1", task="我開始喜歡紅茶",
        selected_tool="save_user_preference", candidate_change=candidate("紅茶"),
    )
    proposal_id = result["proposal"]["proposal_id"]
    with pytest.raises(ValueError, match="scope mismatch"):
        proposals.confirm_proposal(user_id="user2", session_id="s1", proposal_id=proposal_id)
    assert current_value(store, "user1", "s1") is None
    assert current_value(store, "user2", "s1") is None


def test_failed_tool_creates_no_proposal_and_preserves_current(tmp_path):
    store, proposals, action = setup_service(tmp_path / "proposal-tool-failure.db")
    result = action.execute_task(
        user_id="user1", session_id="s1", task="我開始喜歡紅茶",
        selected_tool="save_user_preference", candidate_change=candidate("紅茶"), fail_tool=True,
    )
    assert result["tool_result"]["success"] is False
    assert result["proposal"] is None
    assert current_value(store, "user1", "s1") is None
    assert proposals.get_pending_proposals(user_id="user1", session_id="s1") == []


def test_manual_runtime_flow(tmp_path):
    store, proposals, action = setup_service(tmp_path / "proposal-manual.db")
    first = action.execute_task(
        user_id="user1", session_id="s1", task="我開始喜歡紅茶",
        selected_tool="save_user_preference", candidate_change=candidate("紅茶"),
    )
    assert current_value(store, "user1", "s1") is None
    proposals.confirm_proposal(user_id="user1", session_id="s1", proposal_id=first["proposal"]["proposal_id"])
    assert current_value(store, "user1", "s1") == "紅茶"
    second = action.execute_task(
        user_id="user1", session_id="s1", task="我改喜歡烏龍茶",
        selected_tool="save_user_preference", candidate_change=candidate("烏龍茶"),
    )
    proposals.reject_proposal(user_id="user1", session_id="s1", proposal_id=second["proposal"]["proposal_id"])
    assert current_value(store, "user1", "s1") == "紅茶"
