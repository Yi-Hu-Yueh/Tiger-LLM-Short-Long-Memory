from __future__ import annotations

from pathlib import Path

import pytest

from app import MemoryStore
from memory_action import ActionService
from memory_proposal import ProposalStatus, SemanticProposalService, StaleProposalError


def candidate(value: str):
    return {
        "operation": "set",
        "subject": "user",
        "attribute": "favorite_drink",
        "value": value,
        "confidence": 1.0,
        "reason": "explicit preference",
        "valid_time": {"from": None, "to": None},
    }


def setup(db_path: Path):
    store = MemoryStore(db_path)
    for user_id in ("user1", "user2"):
        for session_id in ("s1", "s2", "s3"):
            store.create_session(user_id, session_id)
    proposals = SemanticProposalService(store=store)
    return store, proposals, ActionService(proposals=proposals)


def current(store: MemoryStore, user_id: str, session_id: str = "s1"):
    snapshot = store.get_typed_protocol_snapshot(user_id, session_id)
    records = [item for item in snapshot["current"] if item.get("semantic_key") == "user.favorite_drink"]
    return None if not records else records[0]["state"]["value"]


def propose(action: ActionService, value: str, *, session_id: str = "s1"):
    return action.execute_task(
        user_id="user1",
        session_id=session_id,
        task=f"我喜歡{value}",
        selected_tool="save_user_preference",
        candidate_change=candidate(value),
    )["proposal"]


def establish(store, proposals, action, value="咖啡"):
    proposal = propose(action, value)
    proposals.confirm_proposal(
        user_id="user1", session_id="s1", proposal_id=proposal["proposal_id"]
    )
    assert current(store, "user1") == value


def test_a_create_is_pending_and_current_unchanged(tmp_path):
    store, proposals, action = setup(tmp_path / "life-a.db")
    proposal = propose(action, "茶")
    assert proposal["status"] is ProposalStatus.PENDING_REVIEW
    assert current(store, "user1") is None


def test_b_confirm_updates_once(tmp_path):
    store, proposals, action = setup(tmp_path / "life-b.db")
    proposal = propose(action, "茶")
    before = store.get_memory_snapshot("user1")["revision"]
    proposals.confirm_proposal(user_id="user1", session_id="s1", proposal_id=proposal["proposal_id"])
    assert current(store, "user1") == "茶"
    assert store.get_memory_snapshot("user1")["revision"] == before + 1


def test_c_reject_is_terminal_and_does_not_mutate(tmp_path):
    store, proposals, action = setup(tmp_path / "life-c.db")
    proposal = propose(action, "茶")
    rejected = proposals.reject_proposal(user_id="user1", session_id="s1", proposal_id=proposal["proposal_id"])
    assert rejected.status is ProposalStatus.REJECTED
    assert current(store, "user1") is None
    with pytest.raises(ValueError, match="no longer pending"):
        proposals.confirm_proposal(user_id="user1", session_id="s1", proposal_id=proposal["proposal_id"])


def test_d_cancel_is_terminal_and_does_not_mutate(tmp_path):
    store, proposals, action = setup(tmp_path / "life-d.db")
    proposal = propose(action, "茶")
    cancelled = proposals.cancel_proposal(user_id="user1", session_id="s1", proposal_id=proposal["proposal_id"])
    assert cancelled.status is ProposalStatus.CANCELLED
    assert current(store, "user1") is None
    with pytest.raises(ValueError, match="no longer pending"):
        proposals.reject_proposal(user_id="user1", session_id="s1", proposal_id=proposal["proposal_id"])


def test_e_expired_proposal_cannot_confirm(tmp_path):
    store, proposals, action = setup(tmp_path / "life-e.db")
    proposal = propose(action, "茶")
    expired = proposals.expire_proposal(user_id="user1", session_id="s1", proposal_id=proposal["proposal_id"])
    assert expired.status is ProposalStatus.EXPIRED
    assert current(store, "user1") is None
    with pytest.raises(ValueError, match="no longer pending"):
        proposals.confirm_proposal(user_id="user1", session_id="s1", proposal_id=proposal["proposal_id"])


def test_f_duplicate_confirm_is_idempotent(tmp_path):
    store, proposals, action = setup(tmp_path / "life-f.db")
    proposal = propose(action, "茶")
    first = proposals.confirm_proposal(user_id="user1", session_id="s1", proposal_id=proposal["proposal_id"])
    revision = store.get_memory_snapshot("user1")["revision"]
    second = proposals.confirm_proposal(user_id="user1", session_id="s1", proposal_id=proposal["proposal_id"])
    assert first == second
    assert store.get_memory_snapshot("user1")["revision"] == revision


def test_g_stale_proposal_is_rejected_without_overwrite(tmp_path):
    store, proposals, action = setup(tmp_path / "life-g.db")
    establish(store, proposals, action, "咖啡")
    stale = propose(action, "茶", session_id="s1")
    winner = propose(action, "果汁", session_id="s2")
    proposals.confirm_proposal(user_id="user1", session_id="s2", proposal_id=winner["proposal_id"])
    assert current(store, "user1") == "果汁"
    with pytest.raises(StaleProposalError):
        proposals.confirm_proposal(user_id="user1", session_id="s1", proposal_id=stale["proposal_id"])
    assert current(store, "user1") == "果汁"
    assert proposals.get_pending_proposals(user_id="user1", session_id="s1") == []


def test_h_conflicting_proposals_only_valid_confirm_commits(tmp_path):
    store, proposals, action = setup(tmp_path / "life-h.db")
    establish(store, proposals, action, "咖啡")
    proposal_a = propose(action, "新竹茶", session_id="s1")
    proposal_b = propose(action, "台中茶", session_id="s2")
    assert len(proposals.get_pending_proposals(user_id="user1", session_id="s1")) == 1
    assert len(proposals.get_pending_proposals(user_id="user1", session_id="s2")) == 1
    proposals.confirm_proposal(user_id="user1", session_id="s1", proposal_id=proposal_a["proposal_id"])
    with pytest.raises(StaleProposalError):
        proposals.confirm_proposal(user_id="user1", session_id="s2", proposal_id=proposal_b["proposal_id"])
    assert current(store, "user1") == "新竹茶"


def test_i_user_isolation(tmp_path):
    store, proposals, action = setup(tmp_path / "life-i.db")
    proposal = propose(action, "茶")
    with pytest.raises(ValueError, match="scope mismatch"):
        proposals.confirm_proposal(user_id="user2", session_id="s1", proposal_id=proposal["proposal_id"])
    assert current(store, "user1") is None
    assert current(store, "user2") is None


def test_manual_lifecycle_scenario(tmp_path):
    store, proposals, action = setup(tmp_path / "life-manual.db")
    first = propose(action, "茶")
    proposals.confirm_proposal(user_id="user1", session_id="s1", proposal_id=first["proposal_id"])
    assert current(store, "user1") == "茶"
    second = propose(action, "咖啡")
    proposals.reject_proposal(user_id="user1", session_id="s1", proposal_id=second["proposal_id"])
    assert current(store, "user1") == "茶"
    stale = propose(action, "紅茶", session_id="s1")
    winner = propose(action, "烏龍茶", session_id="s2")
    proposals.confirm_proposal(user_id="user1", session_id="s2", proposal_id=winner["proposal_id"])
    with pytest.raises(StaleProposalError):
        proposals.confirm_proposal(user_id="user1", session_id="s1", proposal_id=stale["proposal_id"])
    assert current(store, "user1") == "烏龍茶"
