"""Dormant deterministic routing-plan preview for the ontology pipeline.

Phase 4D maps already validated application-owned compiler, authoritative
precondition, and Risk Engine facts into an immutable route plan.  It performs
no provider call, proposal persistence, commit, revision change, or database
access.  Production routing remains disabled.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

import ontology_compiler
import ontology_preconditions
import risk_engine


PRODUCTION_ACTIVE = False
SEMANTIC_CONFIRMATION_PURPOSE = "SEMANTIC_CONFIRMATION"
SEMANTIC_PROPOSAL_PAYLOAD_VERSION = 1


class OntologyRoute(str, Enum):
    NON_WRITE = "NON_WRITE"
    HUMAN_REVIEW_ROUTE = "HUMAN_REVIEW_ROUTE"
    AUTO_COMMIT_ROUTE = "AUTO_COMMIT_ROUTE"
    FAIL_CLOSED = "FAIL_CLOSED"


class RoutingReason(str, Enum):
    HUMAN_REVIEW_REQUIRED = "HUMAN_REVIEW_REQUIRED"
    AUTO_COMMIT_ALLOWED = "AUTO_COMMIT_ALLOWED"
    DETERMINISTIC_NON_WRITE = "DETERMINISTIC_NON_WRITE"
    UPSTREAM_FAIL_CLOSED = "UPSTREAM_FAIL_CLOSED"
    CONTRADICTORY_UPSTREAM_FACTS = "CONTRADICTORY_UPSTREAM_FACTS"
    RISK_SLOT_MISMATCH = "RISK_SLOT_MISMATCH"
    RISK_OPERATION_MISMATCH = "RISK_OPERATION_MISMATCH"
    OPERATION_UNRESOLVED = "OPERATION_UNRESOLVED"
    PRECONDITION_NOT_READY = "PRECONDITION_NOT_READY"
    WRITE_NOT_CHANGED = "WRITE_NOT_CHANGED"
    ATOMIC_COMMIT_UNAVAILABLE = "ATOMIC_COMMIT_UNAVAILABLE"
    DESTRUCTIVE_AUTO_FORBIDDEN = "DESTRUCTIVE_AUTO_FORBIDDEN"
    AUTO_POLICY_NOT_ENABLED = "AUTO_POLICY_NOT_ENABLED"
    AUTO_RISK_HAS_FAILED_CONDITIONS = "AUTO_RISK_HAS_FAILED_CONDITIONS"


FrozenValue = object
FrozenArguments = tuple[tuple[str, FrozenValue], ...]


def _freeze(value: object) -> object:
    if isinstance(value, dict):
        return tuple((str(key), _freeze(item)) for key, item in value.items())
    if isinstance(value, (list, tuple)):
        return tuple(_freeze(item) for item in value)
    return value


def _thaw(value: object) -> object:
    if isinstance(value, tuple):
        if all(
            isinstance(item, tuple)
            and len(item) == 2
            and isinstance(item[0], str)
            for item in value
        ):
            return {item[0]: _thaw(item[1]) for item in value}
        return [_thaw(item) for item in value]
    return value


def _freeze_arguments(arguments: dict[str, object]) -> FrozenArguments:
    return tuple((key, _freeze(value)) for key, value in arguments.items())


def arguments_dict(arguments: FrozenArguments) -> dict[str, object]:
    """Return a display-only mutable copy of immutable route arguments."""
    return {key: _thaw(value) for key, value in arguments}


@dataclass(frozen=True, slots=True)
class HumanReviewPayloadPreview:
    """Canonical proposal facts only; this is not a persisted POLICY-19 proposal."""

    purpose: str
    payload_version: int
    destructive: bool
    slot_id: str
    registry_version: int
    entity_id: str | None
    target_memory_id: str | None
    semantic_key: str
    display_label: str
    state_type: str
    operation: str
    canonical_arguments: FrozenArguments
    proposal_id: None = None
    base_revision: None = None
    memory_id: None = None


@dataclass(frozen=True, slots=True)
class OntologyRoutePlan:
    """Immutable deterministic plan.  It never performs the described route."""

    route: str
    executable: bool
    write_required: bool
    proposal_required: bool
    commit_required: bool
    slot_id: str | None
    registry_version: int | None
    entity_id: str | None
    target_memory_id: str | None
    semantic_key: str | None
    display_label: str | None
    typed_family: str | None
    resolved_operation: str | None
    canonical_arguments: FrozenArguments
    destructive: bool
    precondition_outcome: str
    risk_decision: str
    reason_codes: tuple[str, ...]
    human_review_payload: HumanReviewPayloadPreview | None
    routing_performed: bool = False
    persistence_performed: bool = False
    proposal_created: bool = False
    commit_performed: bool = False


def _combined_reasons(
    risk: risk_engine.RiskDecision,
    precondition: ontology_preconditions.OntologyPreconditionResult,
    *extra: RoutingReason,
) -> tuple[str, ...]:
    values: list[str] = []
    for value in (
        *risk.reason_codes,
        *precondition.reason_codes,
        *(reason.value for reason in extra),
    ):
        if value and value not in values:
            values.append(value)
    return tuple(values)


def _base_plan(
    *,
    route: OntologyRoute,
    candidate: ontology_compiler.OntologyActionCandidate,
    precondition: ontology_preconditions.OntologyPreconditionResult,
    risk: risk_engine.RiskDecision,
    reason_codes: tuple[str, ...],
    executable: bool = False,
    write_required: bool = False,
    proposal_required: bool = False,
    commit_required: bool = False,
    arguments: FrozenArguments = (),
    payload: HumanReviewPayloadPreview | None = None,
) -> OntologyRoutePlan:
    return OntologyRoutePlan(
        route=route.value,
        executable=executable,
        write_required=write_required,
        proposal_required=proposal_required,
        commit_required=commit_required,
        slot_id=candidate.slot_id,
        registry_version=candidate.registry_version,
        entity_id=candidate.entity_id,
        target_memory_id=precondition.target_memory_id,
        semantic_key=candidate.semantic_key,
        display_label=candidate.display_label,
        typed_family=candidate.typed_family,
        resolved_operation=precondition.resolved_operation,
        canonical_arguments=arguments,
        destructive=precondition.destructive or candidate.destructive,
        precondition_outcome=precondition.outcome,
        risk_decision=risk.decision,
        reason_codes=reason_codes,
        human_review_payload=payload,
    )


def _fail_closed(
    candidate: ontology_compiler.OntologyActionCandidate,
    precondition: ontology_preconditions.OntologyPreconditionResult,
    risk: risk_engine.RiskDecision,
    *reasons: RoutingReason,
) -> OntologyRoutePlan:
    return _base_plan(
        route=OntologyRoute.FAIL_CLOSED,
        candidate=candidate,
        precondition=precondition,
        risk=risk,
        reason_codes=_combined_reasons(risk, precondition, *reasons),
    )


def _validate_identity_alignment(
    candidate: ontology_compiler.OntologyActionCandidate,
    precondition: ontology_preconditions.OntologyPreconditionResult,
    risk: risk_engine.RiskDecision,
) -> RoutingReason | None:
    if risk.evaluated_slot_id != candidate.slot_id:
        return RoutingReason.RISK_SLOT_MISMATCH
    if (
        risk.evaluated_operation is not None
        and precondition.resolved_operation is not None
        and risk.evaluated_operation != precondition.resolved_operation
    ):
        return RoutingReason.RISK_OPERATION_MISMATCH
    return None


def _resolved_arguments(
    candidate: ontology_compiler.OntologyActionCandidate,
    precondition: ontology_preconditions.OntologyPreconditionResult,
) -> FrozenArguments:
    operation = precondition.resolved_operation
    if not operation:
        return ()
    return _freeze_arguments(
        ontology_preconditions.canonical_arguments_for_operation(candidate, operation)
    )


def _human_review_payload(
    candidate: ontology_compiler.OntologyActionCandidate,
    precondition: ontology_preconditions.OntologyPreconditionResult,
    arguments: FrozenArguments,
) -> HumanReviewPayloadPreview:
    if (
        candidate.slot_id is None
        or candidate.registry_version is None
        or candidate.semantic_key is None
        or candidate.display_label is None
        or candidate.typed_family is None
        or precondition.resolved_operation is None
    ):
        raise ValueError("Human Review payload requires complete canonical identity")
    return HumanReviewPayloadPreview(
        purpose=SEMANTIC_CONFIRMATION_PURPOSE,
        payload_version=SEMANTIC_PROPOSAL_PAYLOAD_VERSION,
        destructive=precondition.destructive or candidate.destructive,
        slot_id=candidate.slot_id,
        registry_version=candidate.registry_version,
        entity_id=candidate.entity_id,
        target_memory_id=precondition.target_memory_id,
        semantic_key=candidate.semantic_key,
        display_label=candidate.display_label,
        state_type=candidate.typed_family,
        operation=precondition.resolved_operation,
        canonical_arguments=arguments,
    )


def plan_route(
    candidate: ontology_compiler.OntologyActionCandidate,
    precondition: ontology_preconditions.OntologyPreconditionResult,
    risk: risk_engine.RiskDecision,
) -> OntologyRoutePlan:
    """Build a pure route preview from already-authoritative application facts."""
    if not isinstance(candidate, ontology_compiler.OntologyActionCandidate):
        raise TypeError("candidate must be OntologyActionCandidate")
    if not isinstance(precondition, ontology_preconditions.OntologyPreconditionResult):
        raise TypeError("precondition must be OntologyPreconditionResult")
    if not isinstance(risk, risk_engine.RiskDecision):
        raise TypeError("risk must be RiskDecision")

    mismatch = _validate_identity_alignment(candidate, precondition, risk)
    if mismatch is not None:
        return _fail_closed(candidate, precondition, risk, mismatch)

    if risk.decision == risk_engine.RiskResult.NON_WRITE_OR_FAIL_CLOSED.value:
        if precondition.outcome == "FAIL_CLOSED":
            return _fail_closed(
                candidate, precondition, risk, RoutingReason.UPSTREAM_FAIL_CLOSED
            )
        if precondition.outcome in {"NON_WRITE", "NOOP", "TARGET_NOT_FOUND"}:
            return _base_plan(
                route=OntologyRoute.NON_WRITE,
                candidate=candidate,
                precondition=precondition,
                risk=risk,
                reason_codes=_combined_reasons(
                    risk, precondition, RoutingReason.DETERMINISTIC_NON_WRITE
                ),
            )
        return _fail_closed(
            candidate, precondition, risk, RoutingReason.CONTRADICTORY_UPSTREAM_FACTS
        )

    if risk.decision not in {
        risk_engine.RiskResult.HUMAN_REVIEW_REQUIRED.value,
        risk_engine.RiskResult.AUTO_COMMIT_ALLOWED.value,
    }:
        return _fail_closed(
            candidate, precondition, risk, RoutingReason.CONTRADICTORY_UPSTREAM_FACTS
        )

    if not candidate.executable:
        return _fail_closed(
            candidate, precondition, risk, RoutingReason.CONTRADICTORY_UPSTREAM_FACTS
        )
    if not precondition.ready:
        return _fail_closed(
            candidate, precondition, risk, RoutingReason.PRECONDITION_NOT_READY
        )
    if not precondition.changed:
        return _fail_closed(
            candidate, precondition, risk, RoutingReason.WRITE_NOT_CHANGED
        )
    if not precondition.resolved_operation:
        return _fail_closed(
            candidate, precondition, risk, RoutingReason.OPERATION_UNRESOLVED
        )
    if risk.evaluated_operation != precondition.resolved_operation:
        return _fail_closed(
            candidate, precondition, risk, RoutingReason.RISK_OPERATION_MISMATCH
        )
    if not precondition.atomic_commit_available:
        return _fail_closed(
            candidate, precondition, risk, RoutingReason.ATOMIC_COMMIT_UNAVAILABLE
        )

    arguments = _resolved_arguments(candidate, precondition)

    if risk.decision == risk_engine.RiskResult.HUMAN_REVIEW_REQUIRED.value:
        payload = _human_review_payload(candidate, precondition, arguments)
        return _base_plan(
            route=OntologyRoute.HUMAN_REVIEW_ROUTE,
            candidate=candidate,
            precondition=precondition,
            risk=risk,
            reason_codes=_combined_reasons(
                risk, precondition, RoutingReason.HUMAN_REVIEW_REQUIRED
            ),
            executable=True,
            write_required=True,
            proposal_required=True,
            commit_required=False,
            arguments=arguments,
            payload=payload,
        )

    # AUTO_COMMIT_ALLOWED is only a future route-plan capability.  It is valid
    # only when the upstream deterministic Risk Engine explicitly proves the
    # production policy and all low-risk conditions.  No commit occurs here.
    if precondition.outcome != "EXECUTABLE":
        return _fail_closed(
            candidate, precondition, risk, RoutingReason.CONTRADICTORY_UPSTREAM_FACTS
        )
    if candidate.destructive or precondition.destructive or risk.destructive:
        return _fail_closed(
            candidate, precondition, risk, RoutingReason.DESTRUCTIVE_AUTO_FORBIDDEN
        )
    if not risk.registry_auto_commit_allowed:
        return _fail_closed(
            candidate, precondition, risk, RoutingReason.AUTO_POLICY_NOT_ENABLED
        )
    if risk.failed_conditions:
        return _fail_closed(
            candidate,
            precondition,
            risk,
            RoutingReason.AUTO_RISK_HAS_FAILED_CONDITIONS,
        )

    return _base_plan(
        route=OntologyRoute.AUTO_COMMIT_ROUTE,
        candidate=candidate,
        precondition=precondition,
        risk=risk,
        reason_codes=_combined_reasons(
            risk, precondition, RoutingReason.AUTO_COMMIT_ALLOWED
        ),
        executable=True,
        write_required=True,
        proposal_required=False,
        commit_required=True,
        arguments=arguments,
    )


def human_review_payload_preview(
    payload: HumanReviewPayloadPreview | None,
) -> dict[str, object] | None:
    if payload is None:
        return None
    return {
        "purpose": payload.purpose,
        "payload_version": payload.payload_version,
        "destructive": payload.destructive,
        "slot_id": payload.slot_id,
        "registry_version": payload.registry_version,
        "entity_id": payload.entity_id,
        "target_memory_id": payload.target_memory_id,
        "semantic_key": payload.semantic_key,
        "display_label": payload.display_label,
        "state_type": payload.state_type,
        "operation": payload.operation,
        "canonical_arguments": arguments_dict(payload.canonical_arguments),
        "proposal_id": None,
        "base_revision": None,
        "memory_id": None,
        "proposal_created": False,
    }


def routing_preview(plan: OntologyRoutePlan) -> dict[str, object]:
    """Serialize a route plan while making all absent side effects explicit."""
    if not isinstance(plan, OntologyRoutePlan):
        raise TypeError("plan must be OntologyRoutePlan")
    return {
        "preview_only": True,
        "route": plan.route,
        "executable": plan.executable,
        "write_required": plan.write_required,
        "proposal_required": plan.proposal_required,
        "commit_required": plan.commit_required,
        "slot_id": plan.slot_id,
        "registry_version": plan.registry_version,
        "entity_id": plan.entity_id,
        "target_memory_id": plan.target_memory_id,
        "semantic_key": plan.semantic_key,
        "display_label": plan.display_label,
        "typed_family": plan.typed_family,
        "resolved_operation": plan.resolved_operation,
        "canonical_arguments": arguments_dict(plan.canonical_arguments),
        "destructive": plan.destructive,
        "precondition_outcome": plan.precondition_outcome,
        "risk_decision": plan.risk_decision,
        "reason_codes": list(plan.reason_codes),
        "routing_performed": False,
        "persistence_performed": False,
        "proposal_created": False,
        "commit_performed": False,
    }
