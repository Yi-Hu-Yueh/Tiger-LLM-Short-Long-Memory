"""Isolated Phase-4E Human Review proposal persistence for ontology diagnostics.

This module persists only immutable Human Review proposals into dedicated
case-specific diagnostic databases.  It never touches the active Normal Chat
DB and does not Confirm, Correct, Cancel, or commit Current/History changes.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Mapping

import ontology_routing


PRODUCTION_ACTIVE = False
REVIEW_ENDPOINT = "/api/ontology-diagnostic/proposal/create"
REVIEW_STATUS_ENDPOINT = "/api/ontology-diagnostic/proposal/status"
REVIEW_CONFIRM_ENDPOINT = "/api/ontology-diagnostic/proposal/confirm"
USER_ID = "user1"
_ROOT = Path(__file__).resolve().parent / "data" / "ontology_diagnostic_review"
_SESSION_IDS: Mapping[str, str] = {
    "D1": "ontology-review-D1",
    "D2": "ontology-review-D2",
    "D3": "ontology-review-D3",
    "D4": "ontology-review-D4",
    "D6": "ontology-review-D6",
}
_DB_NAMES: Mapping[str, str] = {
    "D1": "d1_review.db",
    "D2": "d2_review.db",
    "D3": "d3_review.db",
    "D4": "d4_review.db",
    "D6": "d6_review.db",
}


class ReviewPersistenceError(ValueError):
    """Fail-closed error for isolated diagnostic proposal persistence."""


class OntologyReviewPersistenceService:
    """Persist previewed Human Review proposals into isolated diagnostic DBs."""

    def __init__(self, root: str | Path | None = None):
        self.root = Path(root) if root is not None else _ROOT

    def _db_path(self, case_id: str) -> Path:
        if case_id not in _DB_NAMES:
            raise ReviewPersistenceError("This diagnostic case has no Human Review persistence fixture")
        self.root.mkdir(parents=True, exist_ok=True)
        return self.root / _DB_NAMES[case_id]

    @staticmethod
    def _app_module():
        # Lazy import avoids a module cycle when app.py imports this helper.
        import app

        return app

    def _ensure_session(self, store, case_id: str) -> str:
        app = self._app_module()
        session_id = _SESSION_IDS[case_id]
        try:
            store.require_session(USER_ID, session_id)
        except app.AppError as exc:
            if exc.status != app.HTTPStatus.NOT_FOUND:
                raise
            store.create_session(USER_ID, session_id)
        return session_id

    def _ensure_fixture(self, store, case_id: str) -> None:
        """Create the server-owned synthetic Current state once per case DB."""
        app = self._app_module()
        fixtures = {
            "D2": (
                "memory_test_vehicle_color_001",
                "scalar",
                {"value": "黑色"},
                "vehicle.color",
                "車輛顏色",
                "vehicle:test-car-001",
            ),
            "D3": (
                "memory_test_group_count_001",
                "count",
                {"value": 4},
                "group.member_count",
                "群組人數",
                "group:test-book-club-001",
            ),
            "D4": (
                "memory_test_group_members_001",
                "set",
                {"items": ["小李"]},
                "group.members",
                "群組成員",
                "group:test-book-club-001",
            ),
            "D6": (
                "memory_test_group_members_remove_present_001",
                "set",
                {"items": ["小李", "小王"]},
                "group.members",
                "群組成員",
                "group:test-book-club-001",
            ),
        }
        fixture = fixtures.get(case_id)
        if fixture is None:
            return
        memory_id, state_type, state, slot_id, display_label, entity_id = fixture
        with app.closing(store._connect()) as conn:
            row = conn.execute(
                "SELECT state_type,state_json,semantic_key,display_label,slot_id,registry_version,entity_id "
                "FROM memories WHERE user_id=? AND memory_id=?",
                (USER_ID, memory_id),
            ).fetchone()
        if row is None:
            store.create_typed_memory(
                USER_ID,
                state_type,
                state,
                semantic_key=slot_id,
                display_label=display_label,
                memory_id=memory_id,
                slot_id=slot_id,
                registry_version=1,
                entity_id=entity_id,
            )
            return
        expected_state_json = app.canonical_typed_state_json(state_type, state)
        actual = (
            row["state_type"],
            row["state_json"],
            row["semantic_key"],
            row["display_label"],
            row["slot_id"],
            row["registry_version"],
            row["entity_id"],
        )
        expected = (
            state_type,
            expected_state_json,
            slot_id,
            display_label,
            slot_id,
            1,
            entity_id,
        )
        if actual != expected:
            raise ReviewPersistenceError("Synthetic authoritative fixture drifted")

    def create_proposal(
        self,
        *,
        case_id: str,
        question: str,
        route_plan: ontology_routing.OntologyRoutePlan,
    ) -> dict[str, object]:
        app = self._app_module()
        if route_plan.route != ontology_routing.OntologyRoute.HUMAN_REVIEW_ROUTE.value:
            raise ReviewPersistenceError("Only HUMAN_REVIEW_ROUTE may create a proposal")
        if not route_plan.proposal_required or route_plan.human_review_payload is None:
            raise ReviewPersistenceError("Human Review route is missing its canonical payload")
        if route_plan.commit_required or route_plan.commit_performed:
            raise ReviewPersistenceError("Human Review proposal creation cannot commit memory")

        db_path = self._db_path(case_id)
        store = app.MemoryStore(db_path)
        session_id = self._ensure_session(store, case_id)
        self._ensure_fixture(store, case_id)

        if store.get_pending_proposal(USER_ID, session_id) is not None:
            raise ReviewPersistenceError("This diagnostic case already has a pending isolated proposal")

        before = store.get_memory_snapshot(USER_ID)
        base_revision = int(before["revision"])
        payload = route_plan.human_review_payload
        arguments = ontology_routing.arguments_dict(payload.canonical_arguments)
        now = app.utc_now()

        if payload.operation in app.TYPED_CREATE_OPERATIONS:
            proposal = app.PendingProposalRecord.semantic_create(
                proposal_id=app.uuid.uuid4().hex,
                user_id=USER_ID,
                session_id=session_id,
                base_revision=base_revision,
                state_type=payload.state_type,
                operation=payload.operation,
                arguments=arguments,
                semantic_key=payload.semantic_key,
                display_label=payload.display_label,
                destructive=payload.destructive,
                created_at=now,
                slot_id=payload.slot_id,
                registry_version=payload.registry_version,
                entity_id=payload.entity_id,
            )
        else:
            proposal = app.PendingProposalRecord.semantic_existing_target(
                proposal_id=app.uuid.uuid4().hex,
                user_id=USER_ID,
                session_id=session_id,
                base_revision=base_revision,
                state_type=payload.state_type,
                operation=payload.operation,
                arguments=arguments,
                target_memory_id=payload.target_memory_id or "",
                destructive=payload.destructive,
                created_at=now,
                slot_id=payload.slot_id,
                registry_version=payload.registry_version,
                entity_id=payload.entity_id,
                semantic_key=payload.semantic_key,
                display_label=payload.display_label,
            )

        reply = app.EMPTY_PROPOSAL_REPLY_PREFIX + proposal.display_text
        store.commit_semantic_proposal_turn(
            USER_ID,
            session_id,
            question,
            reply,
            proposal,
            base_revision,
        )

        after = store.get_memory_snapshot(USER_ID)
        pending = store.get_pending_proposal(USER_ID, session_id)
        if pending is None:
            raise ReviewPersistenceError("Isolated proposal was not persisted")
        if before != after:
            raise ReviewPersistenceError("Proposal creation unexpectedly changed Current/History/revision")

        persisted_args = json.loads(str(pending["arguments_json"]))
        return {
            "isolated": True,
            "database": db_path.name,
            "user_id": USER_ID,
            "session_id": session_id,
            "proposal_id": pending["proposal_id"],
            "base_revision": pending["base_revision"],
            "memory_id": pending["memory_id"],
            "target_memory_id": pending["target_memory_id"],
            "purpose": pending["purpose"],
            "payload_version": pending["payload_version"],
            "destructive": pending["destructive"],
            "slot_id": pending["slot_id"],
            "registry_version": pending["registry_version"],
            "entity_id": pending["entity_id"],
            "semantic_key": pending["semantic_key"],
            "display_label": pending["display_label"],
            "state_type": pending["state_type"],
            "operation": pending["operation"],
            "canonical_arguments": persisted_args,
            "display_text": pending["display_text"],
            "current_changed": False,
            "history_changed": False,
            "revision_changed": False,
            "proposal_created": True,
            "commit_performed": False,
            "provider_calls_added": 0,
        }
    def proposal_status(self, *, case_id: str) -> dict[str, object]:
        """Return the one server-owned pending proposal for an isolated case DB."""
        if case_id not in _DB_NAMES:
            raise ReviewPersistenceError("This diagnostic case has no Human Review persistence fixture")
        db_path = self.root / _DB_NAMES[case_id]
        session_id = _SESSION_IDS[case_id]
        if not db_path.exists():
            return {
                "isolated": True,
                "database": db_path.name,
                "case_id": case_id,
                "user_id": USER_ID,
                "session_id": session_id,
                "pending": False,
                "proposal": None,
                "provider_calls_added": 0,
            }
        app = self._app_module()
        store = app.MemoryStore(db_path)
        try:
            store.require_session(USER_ID, session_id)
        except app.AppError as exc:
            if exc.status == app.HTTPStatus.NOT_FOUND:
                return {
                    "isolated": True,
                    "database": db_path.name,
                    "case_id": case_id,
                    "user_id": USER_ID,
                    "session_id": session_id,
                    "pending": False,
                    "proposal": None,
                    "provider_calls_added": 0,
                }
            raise
        pending = store.get_pending_proposal(USER_ID, session_id)
        snapshot = store.get_memory_snapshot(USER_ID)
        return {
            "isolated": True,
            "database": db_path.name,
            "case_id": case_id,
            "user_id": USER_ID,
            "session_id": session_id,
            "pending": pending is not None,
            "proposal": None if pending is None else {
                "proposal_id": pending["proposal_id"],
                "base_revision": pending["base_revision"],
                "memory_id": pending["memory_id"],
                "target_memory_id": pending["target_memory_id"],
                "purpose": pending["purpose"],
                "payload_version": pending["payload_version"],
                "destructive": pending["destructive"],
                "slot_id": pending["slot_id"],
                "registry_version": pending["registry_version"],
                "entity_id": pending["entity_id"],
                "semantic_key": pending["semantic_key"],
                "display_label": pending["display_label"],
                "state_type": pending["state_type"],
                "operation": pending["operation"],
                "canonical_arguments": json.loads(str(pending["arguments_json"])),
                "display_text": pending["display_text"],
            },
            "revision": snapshot["revision"],
            "current": snapshot["current"],
            "history": snapshot["history"],
            "provider_calls_added": 0,
        }

    def confirm_proposal(self, *, case_id: str) -> dict[str, object]:
        """Locally Confirm one persisted isolated semantic proposal with zero provider calls."""
        if case_id not in _DB_NAMES:
            raise ReviewPersistenceError("This diagnostic case has no Human Review persistence fixture")
        db_path = self.root / _DB_NAMES[case_id]
        if not db_path.exists():
            raise ReviewPersistenceError("No isolated diagnostic database exists for this case")
        app = self._app_module()
        store = app.MemoryStore(db_path)
        session_id = _SESSION_IDS[case_id]
        try:
            store.require_session(USER_ID, session_id)
        except app.AppError as exc:
            raise ReviewPersistenceError(str(exc)) from None
        pending = store.get_pending_proposal(USER_ID, session_id)
        if pending is None:
            raise ReviewPersistenceError("No pending isolated proposal exists for this case")
        if pending.get("purpose") != app.ProposalPurpose.SEMANTIC_CONFIRMATION.value:
            raise ReviewPersistenceError("Pending isolated proposal is not semantic confirmation")
        if pending.get("payload_version") != 1:
            raise ReviewPersistenceError("Pending isolated proposal payload version is unsupported")
        before = store.get_memory_snapshot(USER_ID)
        proposal_id = str(pending["proposal_id"])
        final_memory_id = (
            str(pending["memory_id"])
            if pending["operation"] in app.TYPED_CREATE_OPERATIONS
            else str(pending["target_memory_id"])
        )
        try:
            store.confirm_proposal(
                USER_ID,
                session_id,
                proposal_id,
                allow_semantic_confirmation=True,
            )
        except app.AppError as exc:
            raise ReviewPersistenceError(str(exc)) from None
        after = store.get_memory_snapshot(USER_ID)
        if store.get_pending_proposal(USER_ID, session_id) is not None:
            raise ReviewPersistenceError("Confirmed isolated proposal was not consumed")
        if int(after["revision"]) != int(before["revision"]) + 1:
            raise ReviewPersistenceError("Isolated Confirm did not advance revision exactly once")
        with app.closing(store._connect()) as conn:
            row = conn.execute(
                "SELECT memory_id,state_type,state_json,semantic_key,display_label,slot_id,"
                "registry_version,entity_id FROM memories WHERE user_id=? AND memory_id=?",
                (USER_ID, final_memory_id),
            ).fetchone()
        if row is None:
            raise ReviewPersistenceError("Confirmed isolated memory is missing")
        committed_state = app.validate_typed_state_json(row["state_type"], row["state_json"])
        expected_identity = (
            pending["state_type"],
            pending["semantic_key"],
            pending["display_label"],
            pending["slot_id"],
            pending["registry_version"],
            pending["entity_id"],
        )
        committed_identity = (
            row["state_type"],
            row["semantic_key"],
            row["display_label"],
            row["slot_id"],
            row["registry_version"],
            row["entity_id"],
        )
        if committed_identity != expected_identity:
            raise ReviewPersistenceError("Confirmed isolated memory identity differs from proposal")
        return {
            "isolated": True,
            "database": db_path.name,
            "case_id": case_id,
            "user_id": USER_ID,
            "session_id": session_id,
            "proposal_id": proposal_id,
            "proposal_consumed": True,
            "memory_id": final_memory_id,
            "target_memory_id": pending["target_memory_id"],
            "purpose": pending["purpose"],
            "payload_version": pending["payload_version"],
            "destructive": pending["destructive"],
            "slot_id": row["slot_id"],
            "registry_version": row["registry_version"],
            "entity_id": row["entity_id"],
            "semantic_key": row["semantic_key"],
            "display_label": row["display_label"],
            "state_type": row["state_type"],
            "operation": pending["operation"],
            "canonical_arguments": json.loads(str(pending["arguments_json"])),
            "committed_state": committed_state,
            "revision_before": before["revision"],
            "revision_after": after["revision"],
            "current_before": before["current"],
            "current_after": after["current"],
            "history_before": before["history"],
            "history_after": after["history"],
            "current_changed": before["current"] != after["current"],
            "history_changed": before["history"] != after["history"],
            "revision_changed": before["revision"] != after["revision"],
            "proposal_created": False,
            "commit_performed": True,
            "provider_calls_added": 0,
            "user_memory_changed": False,
        }

