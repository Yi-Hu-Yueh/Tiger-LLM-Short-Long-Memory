"""Phase 3B-R facade over the canonical semantic-confirmation proposal store.

This module does not introduce another persisted proposal representation.  It
uses ``app.PendingProposalRecord`` and ``app.MemoryStore`` as the sole payload
and transaction authorities.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import StrEnum
import json
import time
import uuid
from typing import Any, Mapping

from app import MemoryStore, PendingProposalRecord, ProposalPurpose, utc_now
from memory_audit import AuditEventType, AuditMetrics, MemoryAuditStore
from memory_validator import CandidateOperation, MemoryOperationValidator, WRITE_OPERATIONS
from slot_registry import TypedFamily, get_slot


class ProposalStatus(StrEnum):
    PENDING_REVIEW = "PENDING_REVIEW"
    CONFIRMED = "CONFIRMED"
    REJECTED = "REJECTED"
    CANCELLED = "CANCELLED"
    EXPIRED = "EXPIRED"


class StaleProposalError(ValueError):
    """Raised after a stale proposal is deterministically rejected."""


@dataclass(frozen=True, slots=True)
class SemanticProposal:
    proposal_id: str
    user_id: str
    session_id: str
    source: str
    candidate_operation: str
    attribute: str
    old_value: Any
    new_value: Any
    status: ProposalStatus
    created_at: str
    confirmed_at: str | None
    base_revision: int
    purpose: str
    destructive: bool
    payload_version: int
    memory_id: str
    target_memory_id: str | None
    slot_id: str
    registry_version: int
    semantic_key: str
    display_label: str


_ATTRIBUTE_SLOTS = {
    "office_city": "user.office.location",
    "favorite_drink": "user.favorite_drink",
    "birth_month": "user.birth_month",
    "desk_floor": "desk.floor",
    "phone_model": "device.phone.model",
    "pet_name": "pet.name",
    "city": "person.residence.location",
}


class SemanticProposalService:
    """Validate candidates and delegate persistence/commit to the canonical store."""

    def __init__(
        self,
        *,
        store: MemoryStore,
        validator: MemoryOperationValidator | None = None,
        audit_store: MemoryAuditStore | None = None,
        metrics: AuditMetrics | None = None,
    ):
        self.store = store
        self.validator = validator or MemoryOperationValidator()
        self.audit_store = audit_store
        self.metrics = metrics or AuditMetrics()
        self._views: dict[str, SemanticProposal] = {}

    def create_proposal(
        self,
        *,
        user_id: str,
        session_id: str,
        source: str,
        source_text: str,
        candidate_operation: Mapping[str, Any],
    ) -> SemanticProposal:
        self.store.require_session(user_id, session_id)
        validation_started = time.perf_counter()
        validation = self.validator.validate(source_text, candidate_operation)
        self.metrics.observe_latency("validation_latency", time.perf_counter() - validation_started)
        if not validation.accepted or validation.candidate is None:
            reasons = ",".join(validation.reasons) or "validator_rejected"
            self.metrics.increment("validation_failed")
            self._audit(
                user_id=user_id,
                session_id=session_id,
                event_type=AuditEventType.VALIDATION_FAILED,
                source=source,
                status="REJECTED",
                entity_id="candidate",
                details={"reason_code": validation.reasons[0] if validation.reasons else "validator_rejected"},
            )
            self._audit(
                user_id=user_id,
                session_id=session_id,
                event_type=AuditEventType.MEMORY_REJECTED,
                source=source,
                status="VALIDATION_FAILED",
                entity_id="candidate",
                details={"reason_code": validation.reasons[0] if validation.reasons else "validator_rejected"},
            )
            raise ValueError(f"candidate rejected: {reasons}")
        candidate = validation.candidate
        if candidate.operation not in WRITE_OPERATIONS:
            raise ValueError("candidate does not describe a changed write")
        if candidate.operation == CandidateOperation.FORGET:
            raise ValueError("Phase 3B-R preference workflow does not admit deletion")
        if candidate.attribute not in _ATTRIBUTE_SLOTS:
            raise ValueError("candidate attribute has no exact canonical slot")
        slot_id = _ATTRIBUTE_SLOTS[candidate.attribute]
        slot = get_slot(slot_id)
        if slot is None or slot.typed_family is not TypedFamily.SCALAR:
            raise ValueError("candidate slot is not an admitted scalar")

        snapshot = self.store.get_typed_protocol_snapshot(user_id, session_id)
        current = [item for item in snapshot["current"] if item.get("semantic_key") == slot_id]
        if len(current) > 1:
            raise ValueError("multiple active memories exist for one canonical slot")
        old_value = None
        target_memory_id = None
        if current:
            state = current[0].get("state")
            if not isinstance(state, Mapping) or not isinstance(state.get("value"), str):
                raise ValueError("current scalar state is invalid")
            old_value = state["value"]
            target_memory_id = str(current[0]["memory_id"])
        if candidate.value == old_value:
            raise ValueError("candidate is a deterministic no-op")

        proposal_id = uuid.uuid4().hex
        created_at = utc_now()
        arguments = {"value": candidate.value}
        if target_memory_id is None:
            record = PendingProposalRecord.semantic_create(
                proposal_id=proposal_id,
                user_id=user_id,
                session_id=session_id,
                base_revision=int(snapshot["revision"]),
                state_type="scalar",
                operation="CREATE_SCALAR",
                arguments=arguments,
                semantic_key=slot.semantic_key,
                display_label=slot.display_label,
                destructive=False,
                created_at=created_at,
                slot_id=slot.slot_id,
                registry_version=slot.registry_version,
            )
        else:
            record = PendingProposalRecord.semantic_existing_target(
                proposal_id=proposal_id,
                user_id=user_id,
                session_id=session_id,
                base_revision=int(snapshot["revision"]),
                state_type="scalar",
                operation="SET_VALUE",
                arguments=arguments,
                target_memory_id=target_memory_id,
                destructive=False,
                created_at=created_at,
                slot_id=slot.slot_id,
                registry_version=slot.registry_version,
                semantic_key=slot.semantic_key,
                display_label=slot.display_label,
            )
        self.store.commit_semantic_proposal_turn(
            user_id,
            session_id,
            source_text,
            "已建立待確認的記憶變更提案。",
            record,
            int(snapshot["revision"]),
        )
        view = SemanticProposal(
            proposal_id=record.proposal_id,
            user_id=user_id,
            session_id=session_id,
            source=source,
            candidate_operation=record.operation or "",
            attribute=candidate.attribute or "",
            old_value=old_value,
            new_value=candidate.value,
            status=ProposalStatus.PENDING_REVIEW,
            created_at=record.created_at,
            confirmed_at=None,
            base_revision=record.base_revision,
            purpose=ProposalPurpose.SEMANTIC_CONFIRMATION.value,
            destructive=bool(record.destructive),
            payload_version=int(record.payload_version or 0),
            memory_id=str(record.memory_id),
            target_memory_id=record.target_memory_id,
            slot_id=slot.slot_id,
            registry_version=slot.registry_version,
            semantic_key=slot.semantic_key,
            display_label=slot.display_label,
        )
        self._views[proposal_id] = view
        self.metrics.increment("proposal_created")
        self._audit(
            user_id=user_id,
            session_id=session_id,
            event_type=AuditEventType.PROPOSAL_CREATED,
            source=source,
            status="PENDING_REVIEW",
            entity_id=proposal_id,
            details={"operation": view.candidate_operation, "slot_id": view.slot_id},
        )
        return view

    def confirm_proposal(
        self, *, user_id: str, session_id: str, proposal_id: str
    ) -> SemanticProposal:
        known = self._views.get(proposal_id)
        if known is not None:
            self._require_scope(known, user_id, session_id)
            if known.status is ProposalStatus.CONFIRMED:
                return known
            if known.status is not ProposalStatus.PENDING_REVIEW:
                raise ValueError("proposal is no longer pending")
        pending = self.store.get_pending_proposal(user_id, session_id)
        if pending is None or pending["proposal_id"] != proposal_id:
            raise ValueError("pending proposal not found")
        base_revision = int(pending["base_revision"])
        current_revision = int(self.store.get_memory_snapshot(user_id)["revision"])
        if current_revision != base_revision:
            if known is None:
                known = self._view_from_pending(pending, source="persisted")
            self.store.cancel_proposal(user_id, session_id, proposal_id)
            self._views[proposal_id] = replace(known, status=ProposalStatus.REJECTED)
            raise StaleProposalError("proposal base revision is stale")
        commit_started = time.perf_counter()
        try:
            self.store.confirm_proposal(
                user_id,
                session_id,
                proposal_id,
                allow_semantic_confirmation=True,
            )
        except Exception as exc:
            self.metrics.increment("memory_write_failure")
            self.metrics.observe_latency("commit_latency", time.perf_counter() - commit_started)
            self._audit(
                user_id=user_id,
                session_id=session_id,
                event_type=AuditEventType.MEMORY_REJECTED,
                source="proposal_confirm",
                status="COMMIT_FAILED",
                entity_id=proposal_id,
                details={"error_type": type(exc).__name__},
            )
            raise
        self.metrics.observe_latency("commit_latency", time.perf_counter() - commit_started)
        if known is None:
            known = self._view_from_pending(pending, source="persisted")
        resolved = replace(known, status=ProposalStatus.CONFIRMED, confirmed_at=utc_now())
        self._views[proposal_id] = resolved
        self.metrics.increment("proposal_confirmed")
        self.metrics.increment("memory_write_success")
        self._audit(
            user_id=user_id,
            session_id=session_id,
            event_type=AuditEventType.PROPOSAL_CONFIRMED,
            source="explicit_confirm",
            status="CONFIRMED",
            entity_id=proposal_id,
            details={"operation": resolved.candidate_operation, "slot_id": resolved.slot_id},
        )
        self._audit(
            user_id=user_id,
            session_id=session_id,
            event_type=(
                AuditEventType.MEMORY_CREATED
                if resolved.candidate_operation == "CREATE_SCALAR"
                else AuditEventType.MEMORY_UPDATED
            ),
            source="proposal_confirm",
            status="COMMITTED",
            entity_id=resolved.memory_id,
            details={"operation": resolved.candidate_operation, "slot_id": resolved.slot_id},
        )
        return resolved

    def reject_proposal(
        self, *, user_id: str, session_id: str, proposal_id: str
    ) -> SemanticProposal:
        return self._close_without_commit(
            user_id=user_id,
            session_id=session_id,
            proposal_id=proposal_id,
            status=ProposalStatus.REJECTED,
        )

    def cancel_proposal(
        self, *, user_id: str, session_id: str, proposal_id: str
    ) -> SemanticProposal:
        return self._close_without_commit(
            user_id=user_id,
            session_id=session_id,
            proposal_id=proposal_id,
            status=ProposalStatus.CANCELLED,
        )

    def expire_proposal(
        self, *, user_id: str, session_id: str, proposal_id: str
    ) -> SemanticProposal:
        return self._close_without_commit(
            user_id=user_id,
            session_id=session_id,
            proposal_id=proposal_id,
            status=ProposalStatus.EXPIRED,
        )

    def get_pending_proposals(
        self, *, user_id: str, session_id: str
    ) -> list[SemanticProposal]:
        pending = self.store.get_pending_proposal(user_id, session_id)
        if pending is None:
            return []
        proposal_id = str(pending["proposal_id"])
        view = self._views.get(proposal_id)
        if view is None:
            view = self._view_from_pending(pending, source="persisted")
            self._views[proposal_id] = view
        return [view]

    def _close_without_commit(
        self,
        *,
        user_id: str,
        session_id: str,
        proposal_id: str,
        status: ProposalStatus,
    ) -> SemanticProposal:
        known = self._views.get(proposal_id)
        if known is not None:
            self._require_scope(known, user_id, session_id)
            if known.status is status:
                return known
            if known.status is not ProposalStatus.PENDING_REVIEW:
                raise ValueError("proposal is no longer pending")
        pending = self.store.get_pending_proposal(user_id, session_id)
        if pending is None or pending["proposal_id"] != proposal_id:
            raise ValueError("pending proposal not found")
        self.store.cancel_proposal(user_id, session_id, proposal_id)
        if known is None:
            known = self._view_from_pending(pending, source="persisted")
        resolved = replace(known, status=status)
        self._views[proposal_id] = resolved
        if status is ProposalStatus.EXPIRED:
            self.metrics.increment("proposal_expired")
            event_type = AuditEventType.PROPOSAL_EXPIRED
        else:
            self.metrics.increment("proposal_rejected")
            event_type = AuditEventType.PROPOSAL_REJECTED
        self._audit(
            user_id=user_id,
            session_id=session_id,
            event_type=event_type,
            source="proposal_lifecycle",
            status=status.value,
            entity_id=proposal_id,
            details={"operation": resolved.candidate_operation, "slot_id": resolved.slot_id},
        )
        return resolved

    def _audit(
        self,
        *,
        user_id: str,
        session_id: str,
        event_type: AuditEventType,
        source: str,
        status: str,
        entity_id: str,
        details: Mapping[str, Any],
    ) -> None:
        if self.audit_store is None:
            return
        self.audit_store.record(
            user_id=user_id,
            session_id=session_id,
            event_type=event_type,
            source=source,
            status=status,
            entity_id=entity_id,
            details=details,
        )

    @staticmethod
    def _require_scope(proposal: SemanticProposal, user_id: str, session_id: str) -> None:
        if proposal.user_id != user_id or proposal.session_id != session_id:
            raise ValueError("proposal scope mismatch")

    def _view_from_pending(
        self, pending: Mapping[str, Any], *, source: str
    ) -> SemanticProposal:
        arguments = json.loads(str(pending["arguments_json"]))
        target_memory_id = pending.get("target_memory_id")
        attribute = next(
            (key for key, value in _ATTRIBUTE_SLOTS.items() if value == pending.get("slot_id")),
            str(pending.get("semantic_key") or ""),
        )
        old_value = None
        if target_memory_id is not None:
            snapshot = self.store.get_typed_protocol_snapshot(
                str(pending["user_id"]), str(pending["session_id"])
            )
            target = next(
                (item for item in snapshot["current"] if item["memory_id"] == target_memory_id),
                None,
            )
            if target is not None and isinstance(target.get("state"), Mapping):
                old_value = target["state"].get("value")
        return SemanticProposal(
            proposal_id=str(pending["proposal_id"]),
            user_id=str(pending["user_id"]),
            session_id=str(pending["session_id"]),
            source=source,
            candidate_operation=str(pending["operation"]),
            attribute=attribute,
            old_value=old_value,
            new_value=arguments.get("value"),
            status=ProposalStatus.PENDING_REVIEW,
            created_at=str(pending["created_at"]),
            confirmed_at=None,
            base_revision=int(pending["base_revision"]),
            purpose=str(pending["purpose"]),
            destructive=bool(pending["destructive"]),
            payload_version=int(pending["payload_version"]),
            memory_id=str(pending["memory_id"]),
            target_memory_id=None if target_memory_id is None else str(target_memory_id),
            slot_id=str(pending["slot_id"]),
            registry_version=int(pending["registry_version"]),
            semantic_key=str(pending["semantic_key"]),
            display_label=str(pending["display_label"]),
        )
